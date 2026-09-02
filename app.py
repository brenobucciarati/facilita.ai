from flask import Flask, render_template, request, jsonify, redirect, session, url_for, flash, send_file
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from models import db, Admin, Evento, MatriculaCadastrada, FuncaoBloqueada, Inscricao, MatriculaBloqueada, Time, TimeJogador, LogAcesso, gerar_codigo_unico, Destaque, NotaAtualizacao, Jogador
from config import Config
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from functools import wraps
from sqlalchemy.exc import OperationalError
from sqlalchemy import text
import openpyxl
import os
import time
import logging
import shutil

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)

# Configurações específicas para PostgreSQL
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgresql://'):
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_size': 10,
        'pool_recycle': 600,
        'pool_pre_ping': True,
        'max_overflow': 20,
        'connect_args': {
            'sslmode': 'require',
            'connect_timeout': 5,
        }
    }

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'admin_login'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ============ MIGRAÇÃO AUTOMÁTICA ============
def run_migrations():
    """Executa migrações automaticamente na inicialização"""
    try:
        is_postgres = app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgresql://')
        
        with app.app_context():
            print("🔄 Verificando migrações pendentes...")
            
            # 1. Criar tabelas novas (se não existirem)
            db.create_all()
            print("✅ Tabelas verificadas")
            
            if is_postgres:
                # Migrações para PostgreSQL
                migrations = [
                    ("inscricao", "jogador_id", "INTEGER"),
                    ("evento", "vagas_mensalistas", "INTEGER DEFAULT 0"),
                    ("evento", "vagas_diaristas", "INTEGER DEFAULT 0"),
                    ("evento", "vagas_visitantes", "INTEGER DEFAULT 0"),
                    ("evento", "usar_prioridades", "BOOLEAN DEFAULT FALSE"),
                ]
                
                for tabela, coluna, tipo in migrations:
                    try:
                        db.session.execute(text(f"ALTER TABLE {tabela} ADD COLUMN IF NOT EXISTS {coluna} {tipo}"))
                        print(f"✅ {tabela}.{coluna} adicionado")
                    except Exception as e:
                        print(f"⚠️ {tabela}.{coluna}: {e}")
                
                db.session.commit()
                print("✅ Migrações PostgreSQL concluídas!")
            
            else:
                # Migrações para SQLite
                migrations = [
                    ("inscricao", "jogador_id", "INTEGER"),
                    ("evento", "vagas_mensalistas", "INTEGER DEFAULT 0"),
                    ("evento", "vagas_diaristas", "INTEGER DEFAULT 0"),
                    ("evento", "vagas_visitantes", "INTEGER DEFAULT 0"),
                    ("evento", "usar_prioridades", "BOOLEAN DEFAULT 0"),
                ]
                
                for tabela, coluna, tipo in migrations:
                    try:
                        result = db.session.execute(text(f"PRAGMA table_info({tabela})")).fetchall()
                        colunas_existentes = [row[1] for row in result]
                        
                        if coluna not in colunas_existentes:
                            db.session.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}"))
                            print(f"✅ {tabela}.{coluna} adicionado")
                        else:
                            print(f"⏭️ {tabela}.{coluna} já existe")
                    except Exception as e:
                        print(f"⚠️ {tabela}.{coluna}: {e}")
                
                db.session.commit()
                print("✅ Migrações SQLite concluídas!")
    
    except Exception as e:
        print(f"❌ Erro na migração: {e}")

# ============ EXECUTAR MIGRAÇÕES ============
with app.app_context():
    run_migrations()

# ============ DECORATOR DE RETRY ============
def retry_on_db_error(max_retries=3):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return f(*args, **kwargs)
                except OperationalError as e:
                    if 'SSL error' in str(e) and attempt < max_retries - 1:
                        logger.warning(f"⚠️ Tentativa {attempt + 1} falhou, tentando novamente...")
                        db.session.rollback()
                        time.sleep(2 ** attempt)
                        continue
                    raise
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ============ DECORATOR ADMIN MASTER ============
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('❌ Acesso restrito ao administrador!', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def registrar_log(acao, descricao='', evento_id=None):
    try:
        log = LogAcesso(
            user_id=current_user.id if current_user.is_authenticated else None,
            evento_id=evento_id,
            acao=acao,
            descricao=descricao,
            ip=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')[:300]
        )
        db.session.add(log)
        db.session.commit()
    except:
        pass

@login_manager.user_loader
def load_user(user_id):
    try:
        return Admin.query.get(int(user_id))
    except OperationalError as e:
        if 'SSL error' in str(e):
            logger.warning("⚠️ SSL Error no load_user, tentando reconectar...")
            db.session.rollback()
            return Admin.query.get(int(user_id))
        raise

@app.teardown_appcontext
def shutdown_session(exception=None):
    """Garantir que a sessão seja fechada ao final da requisição"""
    db.session.remove()

# ============ CRIAÇÃO DO ADMIN ============
with app.app_context():
    if not Admin.query.first():
        admin = Admin(
            username='admin',
            password=generate_password_hash('admin123'),
            nome='Administrador',
            role='admin'
        )
        db.session.add(admin)
        db.session.commit()
        logger.info("✅ Admin master criado")

# ============ ROTAS ============

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        admin = Admin.query.filter_by(username=request.form['username'], ativo=True).first()
        if admin and check_password_hash(admin.password, request.form['password']):
            login_user(admin)
            admin.ultimo_acesso = datetime.utcnow()
            db.session.commit()
            registrar_log('login', f'Login de {admin.username}')
            flash('✅ Login realizado!', 'success')
            return redirect(url_for('dashboard'))
        flash('❌ Usuário ou senha inválidos', 'danger')
    return render_template('admin/login.html')

@app.route('/admin/logout')
@login_required
def admin_logout():
    logout_user()
    return redirect(url_for('admin_login'))

@app.route('/')
def index():
    return redirect(url_for('admin_login'))

@app.route('/admin/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        eventos = Evento.query.filter_by(excluido=False).order_by(Evento.created_at.desc()).all()
    else:
        eventos = Evento.query.filter_by(criado_por=current_user.id, excluido=False).order_by(Evento.created_at.desc()).all()
    
    total_cadastrados = MatriculaCadastrada.query.filter(
        MatriculaCadastrada.evento_id.is_(None),
        MatriculaCadastrada.criado_por == current_user.id
    ).count()
    
    destaque = Destaque.query.filter_by(ativo=True).order_by(Destaque.ordem).first()
    notas_atualizacao = NotaAtualizacao.query.filter_by(ativo=True).order_by(NotaAtualizacao.ordem).all()
    
    # ✅ NOVO: Total de jogadores
    total_jogadores = Jogador.query.filter_by(criado_por=current_user.id).count()
    
    return render_template('admin/dashboard.html', 
                          eventos=eventos, 
                          total_cadastrados=total_cadastrados,
                          destaque=destaque,
                          notas_atualizacao=notas_atualizacao,
                          total_jogadores=total_jogadores)  # ✅ ADICIONADO

@app.route('/admin/usuarios')
@login_required
@admin_required
def admin_usuarios():
    usuarios = Admin.query.order_by(Admin.created_at.desc()).all()
    destaques = Destaque.query.order_by(Destaque.ordem).all()
    notas = NotaAtualizacao.query.order_by(NotaAtualizacao.ordem).all()
    
    destaques_dict = [d.to_dict() for d in destaques]
    notas_dict = [n.to_dict() for n in notas]
    
    return render_template('admin/usuarios.html', 
                          usuarios=usuarios,
                          destaques=destaques_dict,
                          notas=notas_dict)

@app.route('/admin/usuarios/criar', methods=['POST'])
@login_required
@admin_required
def admin_criar_usuario():
    username = request.form['username'].strip()
    password = request.form['password']
    nome = request.form['nome'].strip()
    role = request.form.get('role', 'operador')
    
    if Admin.query.filter_by(username=username).first():
        flash('❌ Usuário já existe!', 'danger')
        return redirect(url_for('admin_usuarios'))
    
    user = Admin(username=username, password=generate_password_hash(password), nome=nome, role=role)
    db.session.add(user)
    db.session.commit()
    registrar_log('criar_usuario', f'Criou usuário {username}')
    flash(f'✅ Usuário {username} criado!', 'success')
    return redirect(url_for('admin_usuarios'))

# ============ GERENCIAR DESTAQUES ============
@app.route('/admin/destaques')
@login_required
@admin_required
def admin_destaques():
    destaques = Destaque.query.order_by(Destaque.ordem).all()
    destaques_dict = [d.to_dict() for d in destaques]
    return render_template('admin/destaques.html', destaques=destaques_dict)

@app.route('/admin/destaques/criar', methods=['POST'])
@login_required
@admin_required
def admin_criar_destaque():
    try:
        destaque = Destaque(
            imagem_url=request.form.get('imagem_url', ''),
            titulo=request.form['titulo'],
            descricao=request.form['descricao'],
            link=request.form.get('link', ''),
            ativo=request.form.get('ativo') == 'on',
            ordem=int(request.form.get('ordem', 0)),
            criado_por=current_user.id
        )
        db.session.add(destaque)
        db.session.commit()
        registrar_log('criar_destaque', f'Criou destaque: {destaque.titulo}')
        flash('✅ Destaque criado com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Erro ao criar destaque: {str(e)}', 'danger')
    return redirect(url_for('admin_destaques'))

@app.route('/admin/destaques/<int:destaque_id>/editar', methods=['POST'])
@login_required
@admin_required
def admin_editar_destaque(destaque_id):
    destaque = Destaque.query.get_or_404(destaque_id)
    try:
        destaque.imagem_url = request.form.get('imagem_url', '')
        destaque.titulo = request.form['titulo']
        destaque.descricao = request.form['descricao']
        destaque.link = request.form.get('link', '')
        destaque.ativo = request.form.get('ativo') == 'on'
        destaque.ordem = int(request.form.get('ordem', 0))
        db.session.commit()
        registrar_log('editar_destaque', f'Editou destaque: {destaque.titulo}')
        flash('✅ Destaque atualizado!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Erro: {str(e)}', 'danger')
    return redirect(url_for('admin_destaques'))

@app.route('/admin/destaques/<int:destaque_id>/excluir', methods=['POST'])
@login_required
@admin_required
def admin_excluir_destaque(destaque_id):
    destaque = Destaque.query.get_or_404(destaque_id)
    titulo = destaque.titulo
    db.session.delete(destaque)
    db.session.commit()
    registrar_log('excluir_destaque', f'Excluiu destaque: {titulo}')
    flash(f'✅ Destaque "{titulo}" excluído!', 'success')
    return redirect(url_for('admin_destaques'))

# ============ GERENCIAR NOTAS DE ATUALIZAÇÃO ============
@app.route('/admin/notas')
@login_required
@admin_required
def admin_notas():
    notas = NotaAtualizacao.query.order_by(NotaAtualizacao.ordem).all()
    notas_dict = [n.to_dict() for n in notas]
    return render_template('admin/notas.html', notas=notas_dict)

@app.route('/admin/notas/criar', methods=['POST'])
@login_required
@admin_required
def admin_criar_nota():
    try:
        tipo = request.form.get('tipo', 'versao')
        versao = request.form.get('versao', '') if tipo == 'versao' else None
        
        nota = NotaAtualizacao(
            data=request.form['data'],
            tipo=tipo,
            versao=versao,
            titulo=request.form['titulo'],
            descricao=request.form['descricao'],
            ativo=request.form.get('ativo') == 'on',
            ordem=int(request.form.get('ordem', 0)),
            criado_por=current_user.id
        )
        db.session.add(nota)
        db.session.commit()
        registrar_log('criar_nota', f'Criou nota: {nota.titulo}')
        flash('✅ Nota criada com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Erro: {str(e)}', 'danger')
    return redirect(url_for('admin_notas'))

@app.route('/admin/notas/<int:nota_id>/editar', methods=['POST'])
@login_required
@admin_required
def admin_editar_nota(nota_id):
    nota = NotaAtualizacao.query.get_or_404(nota_id)
    try:
        tipo = request.form.get('tipo', 'versao')
        versao = request.form.get('versao', '') if tipo == 'versao' else None
        
        nota.data = request.form['data']
        nota.tipo = tipo
        nota.versao = versao
        nota.titulo = request.form['titulo']
        nota.descricao = request.form['descricao']
        nota.ativo = request.form.get('ativo') == 'on'
        nota.ordem = int(request.form.get('ordem', 0))
        db.session.commit()
        registrar_log('editar_nota', f'Editou nota: {nota.titulo}')
        flash('✅ Nota atualizada!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Erro: {str(e)}', 'danger')
    return redirect(url_for('admin_notas'))

@app.route('/admin/notas/<int:nota_id>/excluir', methods=['POST'])
@login_required
@admin_required
def admin_excluir_nota(nota_id):
    nota = NotaAtualizacao.query.get_or_404(nota_id)
    titulo = nota.titulo
    db.session.delete(nota)
    db.session.commit()
    registrar_log('excluir_nota', f'Excluiu nota: {titulo}')
    flash(f'✅ Nota "{titulo}" excluída!', 'success')
    return redirect(url_for('admin_notas'))

# ============ FINANCEIRO ============
@app.route('/admin/financeiro')
@login_required
@admin_required
def financeiro():
    return render_template('admin/financeiro.html')

@app.route('/admin/api/jogador/<int:jogador_id>/pagar-mensalidade', methods=['POST'])
@login_required
@admin_required
def pagar_mensalidade(jogador_id):
    jogador = Jogador.query.get_or_404(jogador_id)
    try:
        jogador.mensalidade_paga = True
        jogador.data_pagamento = datetime.utcnow()
        db.session.commit()
        registrar_log('pagar_mensalidade', f'Mensalidade de {jogador.nome} paga')
        return jsonify({'sucesso': True, 'mensagem': 'Mensalidade paga com sucesso!'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'sucesso': False, 'mensagem': str(e)})

@app.route('/admin/api/financeiro')
@login_required
@admin_required
def api_financeiro():
    jogadores = Jogador.query.filter_by(criado_por=current_user.id).all()
    
    total_mensalistas = sum(1 for j in jogadores if j.tipo == 'mensalista')
    total_diaristas = sum(1 for j in jogadores if j.tipo == 'diarista')
    total_visitantes = sum(1 for j in jogadores if j.tipo == 'visitante')
    total_jogadores = len(jogadores)
    
    mensalidades_pagas = sum(1 for j in jogadores if j.tipo == 'mensalista' and j.mensalidade_paga)
    mensalidades_pendentes = sum(1 for j in jogadores if j.tipo == 'mensalista' and not j.mensalidade_paga and (not j.data_vencimento or j.data_vencimento >= datetime.utcnow()))
    mensalidades_vencidas = sum(1 for j in jogadores if j.tipo == 'mensalista' and not j.mensalidade_paga and j.data_vencimento and j.data_vencimento < datetime.utcnow())
    
    valor_total = sum(j.valor_mensalidade for j in jogadores if j.tipo == 'mensalista' and j.mensalidade_paga)
    
    pendentes = []
    for j in jogadores:
        if j.tipo == 'mensalista' and not j.mensalidade_paga:
            pendentes.append({
                'id': j.id,
                'nome': j.nome + (' ' + j.sobrenome if j.sobrenome else ''),
                'valor': j.valor_mensalidade,
                'vencimento': j.data_vencimento.strftime('%d/%m/%Y') if j.data_vencimento else 'Não definido',
                'status': 'vencido' if j.data_vencimento and j.data_vencimento < datetime.utcnow() else 'pendente'
            })
    
    return jsonify({
        'total_jogadores': total_jogadores,
        'total_mensalistas': total_mensalistas,
        'total_diaristas': total_diaristas,
        'total_visitantes': total_visitantes,
        'mensalidades_pagas': mensalidades_pagas,
        'mensalidades_pendentes': mensalidades_pendentes,
        'mensalidades_vencidas': mensalidades_vencidas,
        'valor_total': valor_total,
        'pendentes': pendentes
    })

@app.route('/api/time/sortear-automatico', methods=['POST'])
@login_required
def sortear_automatico():
    data = request.json
    evento_id = data.get('evento_id')
    evento = Evento.query.get_or_404(evento_id)
    
    try:
        # Buscar todos os jogadores presentes
        inscricoes = Inscricao.query.filter_by(
            evento_id=evento_id,
            presente=True,
            data_cancelamento=None
        ).all()
        
        if not inscricoes:
            return jsonify({'sucesso': False, 'mensagem': 'Nenhum jogador presente!'})
        
        # Buscar times
        times = Time.query.filter_by(evento_id=evento_id).all()
        if not times:
            return jsonify({'sucesso': False, 'mensagem': 'Nenhum time criado!'})
        
        # Limpar todos os times
        TimeJogador.query.join(Time).filter(Time.evento_id == evento_id).delete()
        db.session.commit()
        
        # Embaralhar jogadores
        import random
        random.shuffle(inscricoes)
        
        # Distribuir jogadores nos times
        vagas_por_time = 5  # Pode ser ajustado
        for i, insc in enumerate(inscricoes):
            time_idx = i % len(times)
            time = times[time_idx]
            
            tj = TimeJogador(
                time_id=time.id,
                inscricao_id=insc.id,
                ordem=TimeJogador.query.filter_by(time_id=time.id).count() + 1
            )
            db.session.add(tj)
        
        db.session.commit()
        return jsonify({'sucesso': True, 'mensagem': 'Times sorteados com sucesso!'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'sucesso': False, 'mensagem': str(e)})

@app.route('/admin/usuarios/<int:user_id>/alterar-permissao', methods=['POST'])
@login_required
@admin_required
def admin_alterar_permissao(user_id):
    user = Admin.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('❌ Não pode alterar sua própria permissão!', 'danger')
        return redirect(url_for('admin_usuarios'))
    
    novo_role = request.form.get('role', 'operador')
    user.role = novo_role
    db.session.commit()
    registrar_log('alterar_permissao', f'Alterou permissão de {user.username} para {novo_role}')
    flash(f'✅ Permissão de {user.username} alterada para {novo_role}!', 'success')
    return redirect(url_for('admin_usuarios'))

@app.route('/admin/usuarios/<int:user_id>/toggle', methods=['POST'])
@login_required
@admin_required
def admin_toggle_usuario(user_id):
    user = Admin.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('❌ Não pode desativar a si mesmo!', 'danger')
        return redirect(url_for('admin_usuarios'))
    user.ativo = not user.ativo
    db.session.commit()
    registrar_log('toggle_usuario', f"{'Ativou' if user.ativo else 'Desativou'} {user.username}")
    flash(f'✅ Usuário {user.username} {"ativado" if user.ativo else "desativado"}!', 'success')
    return redirect(url_for('admin_usuarios'))

@app.route('/admin/logs')
@login_required
@admin_required
def admin_logs():
    page = request.args.get('page', 1, type=int)
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')
    user_id = request.args.get('user_id', type=int)
    acao = request.args.get('acao')
    
    query = LogAcesso.query
    
    if data_inicio:
        query = query.filter(LogAcesso.data >= datetime.strptime(data_inicio, '%Y-%m-%d'))
    if data_fim:
        query = query.filter(LogAcesso.data <= datetime.strptime(data_fim + ' 23:59:59', '%Y-%m-%d %H:%M:%S'))
    if user_id:
        query = query.filter_by(user_id=user_id)
    if acao:
        query = query.filter_by(acao=acao)
    
    logs = query.order_by(LogAcesso.data.desc()).paginate(page=page, per_page=30)
    usuarios_filtro = Admin.query.order_by(Admin.username).all()
    
    return render_template('admin/logs.html', logs=logs, usuarios_filtro=usuarios_filtro)

# ============ JOGADORES (CADASTRO MANUAL) ============
@app.route('/admin/jogadores')
@login_required
@admin_required
def jogadores():
    jogadores = Jogador.query.filter_by(criado_por=current_user.id).order_by(Jogador.nome).all()
    return render_template('admin/jogadores.html', jogadores=jogadores, now=datetime.utcnow())

@app.route('/admin/jogador/cadastrar', methods=['POST'])
@login_required
@admin_required
def cadastrar_jogador():
    try:
        nome = request.form.get('nome', '').strip().upper()
        sobrenome = request.form.get('sobrenome', '').strip().upper()
        
        if not nome or not sobrenome:
            flash('❌ Nome e Sobrenome são obrigatórios!', 'danger')
            return redirect(url_for('jogadores'))
        
        apelido = request.form.get('apelido', '').strip()
        funcao = request.form.get('funcao', 'GERAL').strip().upper()
        telefone = request.form.get('telefone', '').strip()
        email = request.form.get('email', '').strip()
        tipo = request.form.get('tipo', 'mensalista')
        
        data_vencimento = None
        valor_mensalidade = 0.0
        mensalidade_paga = False
        mes_referencia = None
        
        if tipo == 'mensalista':
            data_vencimento_str = request.form.get('data_vencimento')
            if data_vencimento_str:
                data_vencimento = datetime.strptime(data_vencimento_str, '%Y-%m-%d')
            valor_mensalidade = float(request.form.get('valor_mensalidade', 0))
            mensalidade_paga = request.form.get('mensalidade_paga') == 'on'
            mes_referencia = request.form.get('mes_referencia', '').strip()
        
        jogador = Jogador(
            nome=nome,
            sobrenome=sobrenome,
            apelido=apelido,
            funcao=funcao,
            telefone=telefone,
            email=email,
            tipo=tipo,
            mensalidade_paga=mensalidade_paga,
            data_vencimento=data_vencimento,
            valor_mensalidade=valor_mensalidade,
            mes_referencia=mes_referencia,
            data_pagamento=datetime.utcnow() if mensalidade_paga else None,
            ativo=True,
            bloqueado=False,
            criado_por=current_user.id
        )
        db.session.add(jogador)
        db.session.commit()
        registrar_log('cadastrar_jogador', f'Cadastrou jogador: {nome} {sobrenome}')
        flash(f'✅ Jogador {nome} {sobrenome} cadastrado com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Erro ao cadastrar: {str(e)}', 'danger')
    return redirect(url_for('jogadores'))

@app.route('/admin/jogador/<int:jogador_id>/editar', methods=['POST'])
@login_required
@admin_required
def editar_jogador(jogador_id):
    jogador = Jogador.query.get_or_404(jogador_id)
    try:
        jogador.nome = request.form.get('nome', '').strip().upper()
        jogador.sobrenome = request.form.get('sobrenome', '').strip().upper()
        jogador.apelido = request.form.get('apelido', '').strip()
        jogador.funcao = request.form.get('funcao', 'GERAL').strip().upper()
        jogador.telefone = request.form.get('telefone', '').strip()
        jogador.email = request.form.get('email', '').strip()
        jogador.tipo = request.form.get('tipo', 'mensalista')
        jogador.mensalidade_paga = request.form.get('mensalidade_paga') == 'on'
        jogador.ativo = request.form.get('ativo') == 'on'
        jogador.bloqueado = request.form.get('bloqueado') == 'on'
        
        if jogador.tipo == 'mensalista':
            data_vencimento_str = request.form.get('data_vencimento')
            if data_vencimento_str:
                jogador.data_vencimento = datetime.strptime(data_vencimento_str, '%Y-%m-%d')
            else:
                jogador.data_vencimento = None
            jogador.valor_mensalidade = float(request.form.get('valor_mensalidade', 0))
        else:
            jogador.data_vencimento = None
            jogador.valor_mensalidade = 0.0
            jogador.mensalidade_paga = False
        
        jogador.atualizado_em = datetime.utcnow()
        db.session.commit()
        registrar_log('editar_jogador', f'Editou jogador: {jogador.nome}')
        flash(f'✅ Jogador {jogador.nome} atualizado!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Erro ao editar: {str(e)}', 'danger')
    return redirect(url_for('jogadores'))

@app.route('/admin/jogador/<int:jogador_id>/excluir', methods=['POST'])
@login_required
@admin_required
def excluir_jogador(jogador_id):
    jogador = Jogador.query.get_or_404(jogador_id)
    nome = jogador.nome
    db.session.delete(jogador)
    db.session.commit()
    registrar_log('excluir_jogador', f'Excluiu jogador: {nome}')
    flash(f'✅ Jogador {nome} excluído!', 'success')
    return redirect(url_for('jogadores'))

@app.route('/admin/jogador/<int:jogador_id>/toggle-status', methods=['POST'])
@login_required
@admin_required
def toggle_jogador_status(jogador_id):
    jogador = Jogador.query.get_or_404(jogador_id)
    jogador.ativo = not jogador.ativo
    db.session.commit()
    status = 'ativado' if jogador.ativo else 'desativado'
    registrar_log('toggle_jogador_status', f'{status} jogador: {jogador.nome}')
    flash(f'✅ Jogador {jogador.nome} {status}!', 'success')
    return redirect(url_for('jogadores'))

@app.route('/admin/jogador/<int:jogador_id>/toggle-bloqueio', methods=['POST'])
@login_required
@admin_required
def toggle_jogador_bloqueio(jogador_id):
    jogador = Jogador.query.get_or_404(jogador_id)
    jogador.bloqueado = not jogador.bloqueado
    jogador.data_bloqueio = datetime.utcnow() if jogador.bloqueado else None
    db.session.commit()
    status = 'bloqueado' if jogador.bloqueado else 'desbloqueado'
    registrar_log('toggle_jogador_bloqueio', f'{status} jogador: {jogador.nome}')
    flash(f'✅ Jogador {jogador.nome} {status}!', 'success')
    return redirect(url_for('jogadores'))

@app.route('/admin/api/jogador/<int:jogador_id>')
@login_required
@admin_required
def api_jogador(jogador_id):
    jogador = Jogador.query.get_or_404(jogador_id)
    return jsonify(jogador.to_dict())

# ============ UPLOAD FUNCIONÁRIOS ============
@app.route('/admin/cadastrar-funcionarios', methods=['GET', 'POST'])
@login_required
def cadastrar_funcionarios():
    total_cadastrados = MatriculaCadastrada.query.filter(
        MatriculaCadastrada.evento_id.is_(None),
        MatriculaCadastrada.criado_por == current_user.id
    ).count()
    
    if request.method == 'POST':
        if 'arquivo' not in request.files:
            flash('❌ Nenhum arquivo enviado', 'danger')
            return redirect(request.url)
        
        file = request.files['arquivo']
        if file.filename == '':
            flash('❌ Arquivo não selecionado', 'danger')
            return redirect(request.url)
        
        if file and file.filename.endswith(('.xlsx', '.xls', '.csv')):
            try:
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                
                rows = []
                if filename.endswith('.csv'):
                    with open(filepath, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            parts = line.split('\t') if '\t' in line else line.split(',')
                            if len(parts) >= 2:
                                rows.append(parts)
                else:
                    wb = openpyxl.load_workbook(filepath, read_only=True)
                    ws = wb.active
                    for row in ws.iter_rows(values_only=True):
                        if row and row[0] and row[1]:
                            rows.append(row)
                
                sistema = ['000010', '000063', '000099', '000777', '000888', '000999', '888888']
                
                existentes_dict = {}
                for existente in MatriculaCadastrada.query.filter(
                    MatriculaCadastrada.evento_id.is_(None),
                    MatriculaCadastrada.criado_por == current_user.id
                ).all():
                    existentes_dict[existente.matricula] = existente
                
                novos = []
                atualizados = 0
                linhas_ignoradas = 0
                
                for row in rows:
                    try:
                        if len(row) < 2:
                            linhas_ignoradas += 1
                            continue
                        
                        try:
                            matricula = str(int(float(row[0]))).zfill(6)
                        except:
                            linhas_ignoradas += 1
                            continue
                        
                        if matricula in sistema:
                            continue
                        
                        nome = str(row[1]).strip().upper()
                        if not nome:
                            continue
                        
                        if len(row) >= 3 and row[2]:
                            funcao = str(row[2]).strip().upper()
                        else:
                            funcao = 'GERAL'
                        
                        if matricula in existentes_dict:
                            existentes_dict[matricula].nome = nome
                            existentes_dict[matricula].funcao = funcao
                            atualizados += 1
                        else:
                            novos.append({
                                'evento_id': None,
                                'matricula': matricula,
                                'nome': nome,
                                'funcao': funcao,
                                'ativo': True,
                                'criado_por': current_user.id
                            })
                    except Exception as e:
                        linhas_ignoradas += 1
                        continue
                
                if novos:
                    db.session.bulk_insert_mappings(MatriculaCadastrada, novos)
                
                db.session.commit()
                os.remove(filepath)
                
                mensagem = f'✅ {len(novos)} novos | {atualizados} atualizados'
                if linhas_ignoradas > 0:
                    mensagem += f' | ⚠️ {linhas_ignoradas} linhas ignoradas'
                flash(mensagem, 'success')
                return redirect(url_for('dashboard'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'❌ Erro: {str(e)}', 'danger')
                return redirect(request.url)
    
    return render_template('admin/cadastrar_funcionarios.html', total_cadastrados=total_cadastrados)

@app.route('/admin/limpar-matriculas', methods=['POST'])
@login_required
def limpar_matriculas():
    total = MatriculaCadastrada.query.filter(
        MatriculaCadastrada.evento_id.is_(None),
        MatriculaCadastrada.criado_por == current_user.id
    ).count()
    
    if total == 0:
        flash('📂 Nenhuma matrícula para remover.', 'info')
        return redirect(url_for('cadastrar_funcionarios'))
    
    MatriculaCadastrada.query.filter(
        MatriculaCadastrada.evento_id.is_(None),
        MatriculaCadastrada.criado_por == current_user.id
    ).delete()
    
    db.session.commit()
    registrar_log('limpar_matriculas', f'Removeu {total} matrículas da base')
    flash(f'🗑️ {total} matrículas removidas da base!', 'success')
    return redirect(url_for('cadastrar_funcionarios'))

# ============ CRIAR EVENTO ============
@app.route('/admin/criar-evento', methods=['GET', 'POST'])
@login_required
def criar_evento():
    funcoes = db.session.query(MatriculaCadastrada.funcao)\
        .filter(
            MatriculaCadastrada.evento_id.is_(None),
            MatriculaCadastrada.criado_por == current_user.id,
            MatriculaCadastrada.ativo == True
        )\
        .distinct().order_by(MatriculaCadastrada.funcao).all()
    funcoes = [f[0] for f in funcoes]
    
    if request.method == 'POST':
        try:
            tipo = request.form.get('tipo_inscricao', 'nome')
            
            usar_prioridades = request.form.get('usar_prioridades') == 'on'
            vagas_mensalistas = int(request.form.get('vagas_mensalistas', 0))
            vagas_diaristas = int(request.form.get('vagas_diaristas', 0))
            vagas_visitantes = int(request.form.get('vagas_visitantes', 0))
            total_vagas = int(request.form['total_vagas'])
            
            evento = Evento(
                nome=request.form['nome'],
                data_evento=datetime.strptime(request.form['data_evento'], '%Y-%m-%dT%H:%M'),
                total_vagas=total_vagas,
                codigo_link=gerar_codigo_unico(),
                status='aberto',
                tipo_inscricao=tipo,
                usar_prioridades=usar_prioridades,
                vagas_mensalistas=vagas_mensalistas,
                vagas_diaristas=vagas_diaristas,
                vagas_visitantes=vagas_visitantes,
                criado_por=current_user.id
            )
            db.session.add(evento)
            db.session.flush()
            
            if tipo == 'matricula':
                base = MatriculaCadastrada.query.filter(
                    MatriculaCadastrada.evento_id.is_(None),
                    MatriculaCadastrada.criado_por == current_user.id,
                    MatriculaCadastrada.ativo == True
                ).all()
                for func in base:
                    mat = MatriculaCadastrada(
                        evento_id=evento.id,
                        matricula=func.matricula,
                        nome=func.nome,
                        funcao=func.funcao,
                        ativo=True
                    )
                    db.session.add(mat)
                
                funcoes_bloquear = request.form.getlist('funcoes_bloquear')
                for funcao in funcoes_bloquear:
                    bloqueio = FuncaoBloqueada(evento_id=evento.id, funcao=funcao)
                    db.session.add(bloqueio)
            
            db.session.commit()
            registrar_log('criar_evento', f'Evento: {evento.nome} ({tipo})', evento.id)
            
            link = f"{request.host_url}e/{evento.codigo_link}"
            flash(f'✅ Evento criado!<br>Link: <a href="{link}" target="_blank">{link}</a>', 'success')
            return redirect(url_for('gerenciar_evento', evento_id=evento.id))
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Erro: {str(e)}', 'danger')
    
    return render_template('admin/criar_evento.html', funcoes=funcoes)

@app.route('/admin/evento/<int:evento_id>/recalcular-vagas', methods=['POST'])
@login_required
def recalcular_vagas(evento_id):
    evento = Evento.query.get_or_404(evento_id)
    try:
        total_inscritos = Inscricao.query.filter_by(evento_id=evento.id, data_cancelamento=None).count()
        
        if evento.usar_prioridades and total_inscritos > 0:
            pass
        
        db.session.commit()
        return jsonify({'sucesso': True, 'mensagem': 'Vagas recalculadas!'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'sucesso': False, 'mensagem': str(e)})

# ============ APIs PÚBLICAS ============
@app.route('/api/jogadores/lista')
def api_jogadores_lista():
    jogadores = Jogador.query.filter_by(ativo=True, bloqueado=False).all()
    dados = []
    for j in jogadores:
        mensalidade_vencida = False
        if j.tipo == 'mensalista' and not j.mensalidade_paga:
            if j.data_vencimento and j.data_vencimento < datetime.utcnow():
                mensalidade_vencida = True
        
        dados.append({
            'id': j.id,
            'nome': j.nome,
            'sobrenome': j.sobrenome,
            'apelido': j.apelido,
            'funcao': j.funcao,
            'tipo': j.tipo,
            'ativo': j.ativo,
            'bloqueado': j.bloqueado,
            'mensalidade_paga': j.mensalidade_paga,
            'mensalidade_vencida': mensalidade_vencida
        })
    return jsonify({'jogadores': dados})

@app.route('/admin/evento/<int:evento_id>/atualizar-config-vagas', methods=['POST'])
@login_required
def atualizar_config_vagas(evento_id):
    evento = Evento.query.get_or_404(evento_id)
    try:
        evento.usar_prioridades = request.form.get('usar_prioridades') == 'on'
        evento.vagas_mensalistas = int(request.form.get('vagas_mensalistas', 0))
        evento.vagas_diaristas = int(request.form.get('vagas_diaristas', 0))
        evento.vagas_visitantes = int(request.form.get('vagas_visitantes', 0))
        db.session.commit()
        registrar_log('atualizar_config_vagas', f'Atualizou configuração de vagas do evento: {evento.nome}', evento.id)
        flash('✅ Configuração de vagas atualizada!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Erro: {str(e)}', 'danger')
    return redirect(url_for('gerenciar_evento', evento_id=evento_id))

@app.route('/api/limpeza-automatica')
def limpeza_automatica():
    data_limite = datetime.utcnow() - timedelta(days=7)
    
    eventos_para_limpar = Evento.query.filter(
        Evento.excluido == True,
        Evento.data_exclusao <= data_limite
    ).all()
    
    if eventos_para_limpar:
        for evento in eventos_para_limpar:
            times = Time.query.filter_by(evento_id=evento.id).all()
            for time in times:
                TimeJogador.query.filter_by(time_id=time.id).delete()
            Time.query.filter_by(evento_id=evento.id).delete()
            MatriculaBloqueada.query.filter_by(evento_id=evento.id).delete()
            Inscricao.query.filter_by(evento_id=evento.id).delete()
            MatriculaCadastrada.query.filter_by(evento_id=evento.id).delete()
            FuncaoBloqueada.query.filter_by(evento_id=evento.id).delete()
            LogAcesso.query.filter_by(evento_id=evento.id).delete()
            db.session.delete(evento)
        db.session.commit()
        print(f"✅ Limpeza: {len(eventos_para_limpar)} evento(s) removido(s)")
        return jsonify({'status': 'ok', 'limpos': len(eventos_para_limpar)})
    
    return jsonify({'status': 'ok', 'limpos': 0})

@app.route('/admin/evento/<int:evento_id>')
@login_required
def gerenciar_evento(evento_id):
    evento = Evento.query.get_or_404(evento_id)
    inscricoes = Inscricao.query.filter_by(evento_id=evento.id, data_cancelamento=None).order_by(Inscricao.data_inscricao).all()
    vagas_ocupadas = len(inscricoes)
    vagas_disponiveis = evento.total_vagas - vagas_ocupadas
    bloqueios = MatriculaBloqueada.query.filter_by(evento_id=evento.id).all()
    
    return render_template('admin/gerenciar_evento.html', evento=evento, inscricoes=inscricoes,
                         vagas_ocupadas=vagas_ocupadas, vagas_disponiveis=vagas_disponiveis, bloqueios=bloqueios)

@app.route('/admin/evento/<int:evento_id>/excluir', methods=['POST'])
@login_required
def excluir_evento(evento_id):
    evento = Evento.query.get_or_404(evento_id)
    evento.excluido = True
    evento.data_exclusao = datetime.utcnow()
    evento.excluido_por = current_user.id
    db.session.commit()
    registrar_log('excluir_evento', f'Evento: {evento.nome}', evento.id)
    flash('✅ Evento excluído!', 'success')
    return redirect(url_for('dashboard'))

@app.route('/e/<codigo>')
def pagina_inscricao(codigo):
    evento = Evento.query.filter_by(codigo_link=codigo).first_or_404()
    
    if evento.excluido:
        return render_template('public/evento_fechado.html', evento=evento, motivo='excluido')
    
    if evento.status != 'aberto':
        return render_template('public/evento_fechado.html', evento=evento, motivo='encerrado')
    
    vagas_ocupadas = Inscricao.query.filter_by(
        evento_id=evento.id,
        data_cancelamento=None
    ).count()
    
    vagas_disponiveis = evento.total_vagas - vagas_ocupadas
    
    if vagas_disponiveis <= 0:
        return render_template('public/vagas_esgotadas.html', evento=evento)
    
    porcentagem = int((vagas_disponiveis / evento.total_vagas) * 100) if evento.total_vagas > 0 else 0
    
    return render_template('public/inscricao.html',
                         evento=evento,
                         vagas_disponiveis=vagas_disponiveis,
                         porcentagem=porcentagem)

@app.route('/api/validar-matricula', methods=['POST'])
def validar_matricula():
    data = request.json
    codigo = data['codigo_evento']
    matricula = data['matricula'].zfill(6)
    
    evento = Evento.query.filter_by(codigo_link=codigo).first()
    if not evento:
        return jsonify({'valido': False, 'mensagem': 'Evento não encontrado'})
    
    bloqueio = MatriculaBloqueada.query.filter_by(evento_id=evento.id, matricula=matricula).first()
    if bloqueio:
        if bloqueio.data_expiracao and bloqueio.data_expiracao < datetime.utcnow():
            db.session.delete(bloqueio)
            db.session.commit()
        else:
            expira_em = f' Expira em {bloqueio.data_expiracao.strftime("%d/%m/%Y")}.' if bloqueio.data_expiracao else ' Bloqueio permanente.'
            return jsonify({'valido': False, 'mensagem': f'🚫 Matrícula bloqueada: {bloqueio.motivo}.{expira_em}'})
    
    cadastro = MatriculaCadastrada.query.filter_by(evento_id=evento.id, matricula=matricula, ativo=True).first()
    if not cadastro:
        return jsonify({'valido': False, 'mensagem': 'Matrícula não autorizada'})
    
    funcao_bloqueada = FuncaoBloqueada.query.filter_by(evento_id=evento.id, funcao=cadastro.funcao).first()
    if funcao_bloqueada:
        return jsonify({'valido': False, 'mensagem': f'Inscrições não permitidas para: {cadastro.funcao}'})
    
    inscricao_existente = Inscricao.query.filter_by(evento_id=evento.id, matricula=matricula, data_cancelamento=None).first()
    if inscricao_existente:
        return jsonify({'valido': False, 'mensagem': 'Você já está inscrito!', 'pode_cancelar': True, 'inscricao_id': inscricao_existente.id})
    
    vagas_ocupadas = Inscricao.query.filter_by(evento_id=evento.id, data_cancelamento=None).count()
    if vagas_ocupadas >= evento.total_vagas:
        return jsonify({'valido': False, 'mensagem': 'Vagas esgotadas!'})
    
    return jsonify({'valido': True, 'nome': cadastro.nome, 'funcao': cadastro.funcao, 'vagas_restantes': evento.total_vagas - vagas_ocupadas})

@app.route('/api/inscrever', methods=['POST'])
def inscrever():
    try:
        data = request.json
        print(f"📥 Dados recebidos: {data}")
        
        codigo = data.get('codigo_evento', '')
        evento = Evento.query.filter_by(codigo_link=codigo).first()
        
        if not evento:
            return jsonify({'sucesso': False, 'mensagem': 'Evento não encontrado'}), 404
        
        if evento.status != 'aberto':
            return jsonify({'sucesso': False, 'mensagem': 'Evento encerrado'})
        
        vagas_ocupadas = Inscricao.query.filter_by(
            evento_id=evento.id, 
            data_cancelamento=None
        ).count()
        
        if vagas_ocupadas >= evento.total_vagas:
            return jsonify({
                'sucesso': False, 
                'mensagem': 'Vagas esgotadas!', 
                'vagas_restantes': 0
            })
        
        # ==================== INSCRIÇÃO POR JOGADOR ====================
        jogador_id = data.get('jogador_id')
        
        if jogador_id:
            jogador = Jogador.query.get(jogador_id)
            if not jogador:
                return jsonify({'sucesso': False, 'mensagem': 'Jogador não encontrado'})
            
            if not jogador.ativo:
                return jsonify({'sucesso': False, 'mensagem': 'Jogador inativo'})
            
            if jogador.bloqueado:
                return jsonify({'sucesso': False, 'mensagem': 'Jogador bloqueado'})
            
            if jogador.tipo == 'mensalista':
                mensalidade_vencida = False
                if not jogador.mensalidade_paga:
                    if jogador.data_vencimento and jogador.data_vencimento < datetime.utcnow():
                        mensalidade_vencida = True
                
                if mensalidade_vencida:
                    return jsonify({
                        'sucesso': False, 
                        'mensagem': 'Mensalidade vencida! Regularize para se inscrever.'
                    })
            
            inscricao_existente = Inscricao.query.filter_by(
                evento_id=evento.id, 
                jogador_id=jogador.id,
                data_cancelamento=None
            ).first()
            
            if inscricao_existente:
                return jsonify({'sucesso': False, 'mensagem': 'Você já está inscrito!'})
            
            nome_completo = jogador.nome
            if jogador.sobrenome:
                nome_completo += ' ' + jogador.sobrenome
            
            inscricao = Inscricao(
                evento_id=evento.id,
                jogador_id=jogador.id,
                nome=nome_completo,
                funcao=jogador.funcao or 'JOGADOR',
                matricula=None
            )
            db.session.add(inscricao)
            db.session.commit()
            
            vagas_restantes = evento.total_vagas - (vagas_ocupadas + 1)
            return jsonify({
                'sucesso': True,
                'mensagem': f'{jogador.nome} inscrito com sucesso!',
                'vagas_restantes': vagas_restantes
            })
        
        # ==================== INSCRIÇÃO POR NOME ====================
        if evento.tipo_inscricao == 'nome':
            nome = data.get('nome', '').strip()
            if not nome:
                return jsonify({'sucesso': False, 'mensagem': 'Digite seu nome!'})
            
            inscricao = Inscricao(
                evento_id=evento.id,
                matricula='NOME',
                nome=nome.upper(),
                funcao='PARTICIPANTE',
                jogador_id=None
            )
            db.session.add(inscricao)
            db.session.commit()
            
            vagas_restantes = evento.total_vagas - (vagas_ocupadas + 1)
            return jsonify({
                'sucesso': True,
                'mensagem': f'{nome} inscrito!',
                'vagas_restantes': vagas_restantes
            })
        
        # ==================== INSCRIÇÃO POR MATRÍCULA ====================
        matricula = data.get('matricula', '').zfill(6)
        cadastro = MatriculaCadastrada.query.filter_by(
            evento_id=evento.id, 
            matricula=matricula, 
            ativo=True
        ).first()
        
        if not cadastro:
            return jsonify({'sucesso': False, 'mensagem': 'Matrícula não autorizada'}), 403
        
        inscricao_existente = Inscricao.query.filter_by(
            evento_id=evento.id, 
            matricula=matricula, 
            data_cancelamento=None
        ).first()
        
        if inscricao_existente:
            return jsonify({'sucesso': False, 'mensagem': 'Você já está inscrito!'})
        
        inscricao = Inscricao(
            evento_id=evento.id,
            matricula=matricula,
            nome=cadastro.nome,
            funcao=cadastro.funcao,
            jogador_id=None
        )
        db.session.add(inscricao)
        db.session.commit()
        
        vagas_restantes = evento.total_vagas - (vagas_ocupadas + 1)
        return jsonify({
            'sucesso': True,
            'mensagem': f'{cadastro.nome.split()[0]} inscrito!',
            'vagas_restantes': vagas_restantes
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'sucesso': False, 
            'mensagem': f'Erro interno: {str(e)}'
        }), 500

@app.route('/api/cancelar-inscricao', methods=['POST'])
def cancelar_inscricao():
    data = request.json
    inscricao = Inscricao.query.get(data['inscricao_id'])
    if not inscricao:
        return jsonify({'erro': 'Inscrição não encontrada'}), 404
    inscricao.data_cancelamento = datetime.utcnow()
    inscricao.cancelado_por = 'usuario'
    db.session.commit()
    evento = Evento.query.get(inscricao.evento_id)
    vagas_ocupadas = Inscricao.query.filter_by(evento_id=evento.id, data_cancelamento=None).count()
    return jsonify({'sucesso': True, 'mensagem': 'Inscrição cancelada!', 'vagas_restantes': evento.total_vagas - vagas_ocupadas})

# ============ PAINEL AO VIVO ============
@app.route('/admin/evento/<int:evento_id>/ao-vivo')
@login_required
def painel_ao_vivo(evento_id):
    evento = Evento.query.get_or_404(evento_id)
    return render_template('admin/ao_vivo.html', evento=evento)

@app.route('/api/evento/<int:evento_id>/status')
@login_required
def api_status_evento(evento_id):
    evento = Evento.query.get_or_404(evento_id)
    inscricoes = Inscricao.query.filter_by(evento_id=evento.id, data_cancelamento=None).order_by(Inscricao.data_inscricao).all()
    presentes = sum(1 for i in inscricoes if i.presente == True)
    faltas = sum(1 for i in inscricoes if i.presente == False)
    pendentes = sum(1 for i in inscricoes if i.presente == None)
    return jsonify({
        'total_vagas': evento.total_vagas, 'inscritos': len(inscricoes),
        'presentes': presentes, 'faltas': faltas, 'pendentes': pendentes,
        'lista': [{'id': i.id, 'nome': i.nome, 'matricula': i.matricula, 'funcao': i.funcao, 'presente': i.presente,
                    'hora_inscricao': i.data_inscricao.strftime('%H:%M') if i.data_inscricao else ''} for i in inscricoes]
    })

@app.route('/api/inscricao/<int:inscricao_id>/presenca', methods=['POST'])
@login_required
def marcar_presenca(inscricao_id):
    data = request.json
    status = data.get('status')
    inscricao = Inscricao.query.get_or_404(inscricao_id)
    
    if status == 'presente':
        inscricao.presente = True
        inscricao.data_confirmacao_presenca = datetime.utcnow()
    elif status == 'falta':
        inscricao.presente = False
    elif status == 'pendente':
        inscricao.presente = None
        inscricao.data_confirmacao_presenca = None
    db.session.commit()
    
    if status == 'presente':
        distribuir_jogador_automaticamente(inscricao)
    return jsonify({'sucesso': True})

def distribuir_jogador_automaticamente(inscricao):
    evento_id = inscricao.evento_id
    
    times = Time.query.filter_by(evento_id=evento_id).order_by(Time.nome).all()
    if not times:
        return
    
    ja_em_time = TimeJogador.query.filter_by(inscricao_id=inscricao.id).first()
    if ja_em_time:
        return
    
    num_times = len(times)
    vagas_por_time = 5
    sorteio_qtd = vagas_por_time * 2
    
    times_nomes = [t.nome for t in times]
    time_dict = {t.nome: t for t in times}
    
    total_em_times = TimeJogador.query.join(Time).filter(Time.evento_id == evento_id).count()
    posicao = total_em_times + 1
    
    if posicao <= sorteio_qtd:
        time_nome = 'A' if posicao % 2 == 1 else 'B'
    else:
        restante = posicao - sorteio_qtd - 1
        bloco_idx = restante // vagas_por_time
        time_nome = times_nomes[bloco_idx % num_times]
    
    if time_nome not in time_dict:
        for nome in times_nomes:
            t = time_dict[nome]
            count = TimeJogador.query.filter_by(time_id=t.id).count()
            if count < vagas_por_time:
                time_nome = nome
                break
    
    if time_nome not in time_dict:
        return
    
    time = time_dict[time_nome]
    
    count = TimeJogador.query.filter_by(time_id=time.id).count()
    if count >= vagas_por_time:
        for nome in times_nomes:
            t = time_dict[nome]
            if TimeJogador.query.filter_by(time_id=t.id).count() < vagas_por_time:
                time = t
                break
    
    count = TimeJogador.query.filter_by(time_id=time.id).count()
    if count >= vagas_por_time:
        return
    
    tj = TimeJogador(
        time_id=time.id,
        inscricao_id=inscricao.id,
        ordem=count + 1
    )
    db.session.add(tj)
    db.session.commit()

@app.route('/admin/usuarios/<int:user_id>/reset-senha', methods=['POST'])
@login_required
@admin_required
def admin_reset_senha(user_id):
    user = Admin.query.get_or_404(user_id)
    nova_senha = request.form['nova_senha']
    user.password = generate_password_hash(nova_senha)
    db.session.commit()
    registrar_log('reset_senha', f'Resetou senha de {user.username}')
    flash(f'✅ Senha de {user.username} redefinida!', 'success')
    return redirect(url_for('admin_usuarios'))

@app.route('/admin/evento/<int:evento_id>/relatorio')
@login_required
def gerar_relatorio(evento_id):
    evento = Evento.query.get_or_404(evento_id)
    inscricoes = Inscricao.query.filter_by(evento_id=evento.id, data_cancelamento=None).order_by(Inscricao.nome).all()
    
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, height - 50, "RELATÓRIO DE PRESENÇA")
    p.setFont("Helvetica", 12)
    p.drawString(50, height - 70, f"Evento: {evento.nome}")
    p.drawString(50, height - 85, f"Data: {evento.data_evento.strftime('%d/%m/%Y %H:%M')}")
    p.drawString(50, height - 100, f"Vagas: {evento.total_vagas} | Presentes: {sum(1 for i in inscricoes if i.presente == True)}")
    p.line(50, height - 110, width - 50, height - 110)
    
    y = height - 130
    p.setFont("Helvetica-Bold", 10)
    p.drawString(50, y, "MATRÍCULA"); p.drawString(130, y, "NOME"); p.drawString(350, y, "FUNÇÃO"); p.drawString(480, y, "STATUS")
    y -= 20
    p.setFont("Helvetica", 9)
    
    for insc in inscricoes:
        if y < 50:
            p.showPage()
            y = height - 50
        p.drawString(50, y, insc.matricula or '-')
        p.drawString(130, y, insc.nome[:40])
        p.drawString(350, y, (insc.funcao or '')[:20])
        if insc.presente == True:
            p.setFillColor(colors.green); p.drawString(480, y, "✓ PRESENTE")
        elif insc.presente == False:
            p.setFillColor(colors.red); p.drawString(480, y, "✗ FALTA")
        else:
            p.setFillColor(colors.orange); p.drawString(480, y, "○ PENDENTE")
        p.setFillColor(colors.black)
        y -= 15
    
    p.save(); buffer.seek(0)
    return send_file(buffer, mimetype='application/pdf', as_attachment=True, download_name=f'relatorio_{evento.nome.replace(" ", "_")}.pdf')

@app.route('/admin/usuarios/<int:user_id>/excluir', methods=['POST'])
@login_required
@admin_required
def admin_excluir_usuario(user_id):
    user = Admin.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('❌ Não pode excluir a si mesmo!', 'danger')
        return redirect(url_for('admin_usuarios'))
    
    username = user.username
    db.session.delete(user)
    db.session.commit()
    registrar_log('excluir_usuario', f'Excluiu usuário {username}')
    flash(f'✅ Usuário {username} excluído!', 'success')
    return redirect(url_for('admin_usuarios'))

# ============ SORTEIO DE TIMES ============
@app.route('/admin/evento/<int:evento_id>/times')
@login_required
def sorteio_times(evento_id):
    evento = Evento.query.get_or_404(evento_id)
    num_times = max(2, min(10, int(request.args.get('num_times', 6))))
    vagas_por_time = max(3, min(15, int(request.args.get('vagas_por_time', 5))))
    total_vagas = num_times * vagas_por_time
    sorteio_qtd = vagas_por_time * 2
    times_nomes = [chr(65 + i) for i in range(num_times)]
    cores = ['#10b981', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#6366f1', '#84cc16']
    
    times_existentes = Time.query.filter_by(evento_id=evento.id).all()
    if len(times_existentes) != num_times or not times_existentes:
        Time.query.filter_by(evento_id=evento.id).delete()
        db.session.commit()
        for i, nome in enumerate(times_nomes):
            time = Time(evento_id=evento.id, nome=nome, cor=cores[i % len(cores)])
            db.session.add(time)
        db.session.commit()
        times = Time.query.filter_by(evento_id=evento.id).all()
    else:
        times = times_existentes
    
    times_data = {}
    for time in times:
        times_data[time] = TimeJogador.query.filter_by(time_id=time.id).join(Inscricao).order_by(TimeJogador.ordem).all()
    
    ids_em_times = [i[0] for i in db.session.query(TimeJogador.inscricao_id).join(Time).filter(Time.evento_id == evento.id).all()]
    espera = Inscricao.query.filter_by(evento_id=evento.id, presente=True, data_cancelamento=None)\
        .filter(~Inscricao.id.in_(ids_em_times) if ids_em_times else True)\
        .order_by(Inscricao.data_confirmacao_presenca).all()
    
    total_presentes = Inscricao.query.filter_by(evento_id=evento.id, presente=True, data_cancelamento=None).count()
    
    return render_template('admin/sorteio_times.html', evento=evento, times=times, times_data=times_data,
                         espera=espera, vagas_por_time=vagas_por_time, total_presentes=total_presentes,
                         total_vagas=total_vagas, sorteio_qtd=sorteio_qtd, num_times=num_times)

# ============ APIs DOS TIMES ============
@app.route('/api/time/remover-jogador/<int:tj_id>', methods=['POST'])
@login_required
def remover_jogador_time(tj_id):
    tj = TimeJogador.query.get_or_404(tj_id)
    time_nome = tj.time.nome
    db.session.delete(tj)
    db.session.commit()
    return jsonify({'sucesso': True, 'mensagem': f'Jogador removido do Time {time_nome}'})

@app.route('/api/time/mover-jogador', methods=['POST'])
@login_required
def mover_jogador():
    data = request.json
    tj = TimeJogador.query.get(data['time_jogador_id'])
    if not tj:
        return jsonify({'sucesso': False, 'mensagem': 'Jogador não encontrado'})
    
    time_destino = Time.query.filter_by(evento_id=tj.time.evento_id, nome=data['time_destino']).first()
    if not time_destino:
        return jsonify({'sucesso': False, 'mensagem': 'Time não encontrado'})
    
    count = TimeJogador.query.filter_by(time_id=time_destino.id).count()
    if count >= 5:
        return jsonify({'sucesso': False, 'mensagem': 'Time cheio'})
    
    time_origem = tj.time.nome
    tj.time_id = time_destino.id
    tj.ordem = count + 1
    tj.manual = True
    db.session.commit()
    return jsonify({'sucesso': True, 'mensagem': f'Movido do Time {time_origem} para {data["time_destino"]}'})

@app.route('/api/time/reorganizar', methods=['POST'])
@login_required
def reorganizar_times():
    import random
    data = request.json
    time_a = Time.query.filter_by(evento_id=data['evento_id'], nome=data['time_a']).first()
    time_b = Time.query.filter_by(evento_id=data['evento_id'], nome=data['time_b']).first()
    if not time_a or not time_b:
        return jsonify({'sucesso': False})
    
    todos = TimeJogador.query.filter(TimeJogador.time_id.in_([time_a.id, time_b.id])).all()
    random.shuffle(todos)
    for i, jogador in enumerate(todos):
        jogador.time_id = time_a.id if i % 2 == 0 else time_b.id
        jogador.ordem = (i // 2) + 1
        jogador.manual = True
    db.session.commit()
    return jsonify({'sucesso': True})

@app.route('/api/time/completar-time', methods=['POST'])
@login_required
def completar_time():
    import random
    data = request.json
    receptor = Time.query.filter_by(evento_id=data['evento_id'], nome=data['time_receptor']).first()
    doador = Time.query.filter_by(evento_id=data['evento_id'], nome=data['time_doador']).first()
    if not receptor or not doador:
        return jsonify({'sucesso': False})
    
    faltam = 5 - TimeJogador.query.filter_by(time_id=receptor.id).count()
    if faltam <= 0:
        return jsonify({'sucesso': False, 'mensagem': 'Time completo'})
    
    jogadores = TimeJogador.query.filter_by(time_id=doador.id).all()
    sorteados = random.sample(jogadores, min(faltam, len(jogadores)))
    for jogador in sorteados:
        jogador.time_id = receptor.id
        jogador.manual = True
    db.session.commit()
    return jsonify({'sucesso': True, 'mensagem': f'{len(sorteados)} transferido(s)'})

@app.route('/api/time/adicionar-jogador', methods=['POST'])
@login_required
def adicionar_jogador_time():
    data = request.json
    time = Time.query.filter_by(evento_id=data['evento_id'], nome=data['time_nome']).first()
    if not time or TimeJogador.query.filter_by(time_id=time.id).count() >= 5:
        return jsonify({'sucesso': False, 'mensagem': 'Time cheio ou não encontrado'})
    
    ja_em_time = TimeJogador.query.filter_by(inscricao_id=data['inscricao_id']).join(Time).filter(Time.evento_id == data['evento_id']).first()
    if ja_em_time:
        return jsonify({'sucesso': False, 'mensagem': 'Já está em um time'})
    
    tj = TimeJogador(time_id=time.id, inscricao_id=data['inscricao_id'], ordem=TimeJogador.query.filter_by(time_id=time.id).count()+1, manual=True)
    db.session.add(tj)
    db.session.commit()
    return jsonify({'sucesso': True})

@app.route('/api/time/adicionar-avulso', methods=['POST'])
@login_required
def adicionar_avulso():
    data = request.json
    time = Time.query.filter_by(evento_id=data['evento_id'], nome=data['time_nome']).first()
    if not time or TimeJogador.query.filter_by(time_id=time.id).count() >= 5:
        return jsonify({'sucesso': False, 'mensagem': 'Time cheio'})
    
    nome = data['nome'].strip()
    sobrenome = data.get('sobrenome', '').strip()
    nome_completo = nome + (' ' + sobrenome if sobrenome else '')
    
    inscricao = Inscricao(evento_id=data['evento_id'], matricula='AVULSO', nome=nome_completo.upper(), funcao='JOGADOR AVULSO', presente=True, data_confirmacao_presenca=datetime.utcnow())
    db.session.add(inscricao)
    db.session.flush()
    
    tj = TimeJogador(time_id=time.id, inscricao_id=inscricao.id, ordem=TimeJogador.query.filter_by(time_id=time.id).count()+1, manual=True)
    db.session.add(tj)
    db.session.commit()
    return jsonify({'sucesso': True, 'mensagem': nome_completo + ' adicionado ao Time ' + data['time_nome']})

# ============ BLOQUEIO DE MATRÍCULA ============
@app.route('/admin/evento/<int:evento_id>/bloquear-matricula', methods=['POST'])
@login_required
def bloquear_matricula(evento_id):
    matricula = request.form.get('matricula', '').zfill(6)
    motivo = request.form.get('motivo', 'Bloqueio administrativo')
    duracao = request.form.get('duracao', 'permanente')
    
    cadastro = MatriculaCadastrada.query.filter_by(evento_id=evento_id, matricula=matricula).first()
    if not cadastro:
        flash('❌ Matrícula não encontrada!', 'danger')
        return redirect(url_for('gerenciar_evento', evento_id=evento_id))
    
    if MatriculaBloqueada.query.filter_by(evento_id=evento_id, matricula=matricula).first():
        flash('❌ Já está bloqueada!', 'danger')
        return redirect(url_for('gerenciar_evento', evento_id=evento_id))
    
    data_expiracao = None
    if duracao == '1_semana': data_expiracao = datetime.utcnow() + timedelta(days=7)
    elif duracao == '2_semanas': data_expiracao = datetime.utcnow() + timedelta(days=14)
    elif duracao == '1_mes': data_expiracao = datetime.utcnow() + timedelta(days=30)
    
    bloqueio = MatriculaBloqueada(evento_id=evento_id, matricula=matricula, motivo=motivo, data_expiracao=data_expiracao)
    db.session.add(bloqueio)
    
    inscricao = Inscricao.query.filter_by(evento_id=evento_id, matricula=matricula, data_cancelamento=None).first()
    if inscricao:
        inscricao.data_cancelamento = datetime.utcnow()
        inscricao.cancelado_por = 'admin_bloqueio'
    
    db.session.commit()
    flash(f'🔒 Matrícula {matricula} bloqueada!', 'success')
    return redirect(url_for('gerenciar_evento', evento_id=evento_id))

@app.route('/admin/evento/<int:evento_id>/desbloquear-matricula/<int:bloqueio_id>', methods=['POST'])
@login_required
def desbloquear_matricula(evento_id, bloqueio_id):
    bloqueio = MatriculaBloqueada.query.get_or_404(bloqueio_id)
    matricula = bloqueio.matricula
    db.session.delete(bloqueio)
    db.session.commit()
    flash(f'🔓 Matrícula {matricula} desbloqueada!', 'success')
    return redirect(url_for('gerenciar_evento', evento_id=evento_id))

# ============ SINCRONIZAR / ATUALIZAR VAGAS ============
@app.route('/admin/evento/<int:evento_id>/sincronizar-base', methods=['POST'])
@login_required
def sincronizar_base(evento_id):
    base = MatriculaCadastrada.query.filter(
        MatriculaCadastrada.evento_id.is_(None),
        MatriculaCadastrada.criado_por == current_user.id,
        MatriculaCadastrada.ativo == True
    ).all()
    contador = 0
    for cadastro in base:
        if not MatriculaCadastrada.query.filter_by(evento_id=evento_id, matricula=cadastro.matricula).first():
            db.session.add(MatriculaCadastrada(evento_id=evento_id, matricula=cadastro.matricula, nome=cadastro.nome, funcao=cadastro.funcao, ativo=True))
            contador += 1
    db.session.commit()
    flash(f'✅ {contador} matrículas sincronizadas!', 'success')
    return redirect(url_for('gerenciar_evento', evento_id=evento_id))

@app.route('/admin/evento/<int:evento_id>/atualizar-vagas', methods=['POST'])
@login_required
def atualizar_vagas(evento_id):
    evento = Evento.query.get_or_404(evento_id)
    novo_total = int(request.form['total_vagas'])
    if novo_total < 1:
        flash('❌ Número inválido', 'danger')
    else:
        evento.total_vagas = novo_total
        db.session.commit()
        flash(f'✅ Vagas atualizadas para {novo_total}!', 'success')
    return redirect(url_for('gerenciar_evento', evento_id=evento_id))

@app.teardown_appcontext
def shutdown_session(exception=None):
    db.session.remove()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)