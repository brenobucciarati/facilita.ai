from flask import Flask, render_template, request, jsonify, redirect, session, url_for, flash, send_file
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from models import db, Admin, Evento, MatriculaCadastrada, FuncaoBloqueada, Inscricao, MatriculaBloqueada, Time, TimeJogador, LogAcesso, gerar_codigo_unico
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

# ✅ CONFIGURAÇÃO SSL CORRETA
# ✅ MAIS RÁPIDO:
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 10,  # Aumentado
    'pool_recycle': 600,
    'pool_pre_ping': True,
    'max_overflow': 20,
    'connect_args': {
        'sslmode': 'require',
        'connect_timeout': 5,  # Reduzido
    }
}

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'admin_login'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

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

# ============ INICIALIZAÇÃO DO BANCO (DENTRO DO CONTEXTO) ============
with app.app_context():
    db.create_all()
    
    # Criar admin se não existir
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
    
    total_cadastrados = MatriculaCadastrada.query.filter(MatriculaCadastrada.evento_id.is_(None)).count()
    return render_template('admin/dashboard.html', eventos=eventos, total_cadastrados=total_cadastrados)

@app.route('/admin/usuarios')
@login_required
@admin_required
def admin_usuarios():
    usuarios = Admin.query.order_by(Admin.created_at.desc()).all()
    return render_template('admin/usuarios.html', usuarios=usuarios)

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

# ============ UPLOAD FUNCIONÁRIOS (COM RETRY) ============
@app.route('/admin/cadastrar-funcionarios', methods=['GET', 'POST'])
@login_required
def cadastrar_funcionarios():
    # Usar None em vez de 0 para base geral
    total_cadastrados = MatriculaCadastrada.query.filter(MatriculaCadastrada.evento_id.is_(None)).count()
    
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
                
                # Ler arquivo
                rows = []
                if filename.endswith('.csv'):
                    with open(filepath, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if not line:  # Pular linhas vazias
                                continue
                            parts = line.split('\t') if '\t' in line else line.split(',')
                            if len(parts) >= 2:  # Pelo menos 2 colunas
                                rows.append(parts)
                else:
                    wb = openpyxl.load_workbook(filepath, read_only=True)
                    ws = wb.active
                    for row in ws.iter_rows(values_only=True):
                        if row and row[0] and row[1]:  # Tem matrícula e nome
                            rows.append(row)
                
                sistema = ['000010', '000063', '000099', '000777', '000888', '000999', '888888']
                
                # Buscar todos os existentes de uma vez
                existentes_dict = {}
                for existente in MatriculaCadastrada.query.filter(MatriculaCadastrada.evento_id.is_(None)).all():
                    existentes_dict[existente.matricula] = existente
                
                novos = []
                atualizados = 0
                linhas_ignoradas = 0
                
                for row in rows:
                    try:
                        # Garantir que temos pelo menos 2 colunas
                        if len(row) < 2:
                            linhas_ignoradas += 1
                            continue
                        
                        # Processar matrícula
                        try:
                            matricula = str(int(float(row[0]))).zfill(6)
                        except:
                            linhas_ignoradas += 1
                            continue
                        
                        if matricula in sistema:
                            continue
                        
                        # Processar nome
                        nome = str(row[1]).strip().upper()
                        if not nome:
                            continue
                        
                        # Processar função (3ª coluna ou padrão)
                        if len(row) >= 3 and row[2]:
                            funcao = str(row[2]).strip().upper()
                        else:
                            funcao = 'GERAL'
                        
                        if matricula in existentes_dict:
                            # Atualizar existente
                            existentes_dict[matricula].nome = nome
                            existentes_dict[matricula].funcao = funcao
                            atualizados += 1
                        else:
                            # Adicionar à lista de novos
                            novos.append({
                                'evento_id': None,
                                'matricula': matricula,
                                'nome': nome,
                                'funcao': funcao,
                                'ativo': True
                            })
                    except Exception as e:
                        linhas_ignoradas += 1
                        continue
                
                # Inserir todos de uma vez
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
# ============ CRIAR EVENTO ============
@app.route('/admin/criar-evento', methods=['GET', 'POST'])
@login_required
def criar_evento():
    funcoes = db.session.query(MatriculaCadastrada.funcao)\
        .filter(MatriculaCadastrada.evento_id.is_(None), MatriculaCadastrada.ativo == True)\
        .distinct().order_by(MatriculaCadastrada.funcao).all()
    funcoes = [f[0] for f in funcoes]
    
    if request.method == 'POST':
        try:
            tipo = request.form.get('tipo_inscricao', 'nome')
            
            evento = Evento(
                nome=request.form['nome'],
                data_evento=datetime.strptime(request.form['data_evento'], '%Y-%m-%dT%H:%M'),
                total_vagas=int(request.form['total_vagas']),
                codigo_link=gerar_codigo_unico(),
                status='aberto',
                tipo_inscricao=tipo,
                criado_por=current_user.id
            )
            db.session.add(evento)
            db.session.flush()
            
            if tipo == 'matricula':
                base = MatriculaCadastrada.query.filter(MatriculaCadastrada.evento_id.is_(None), MatriculaCadastrada.ativo == True).all()
                for func in base:
                    mat = MatriculaCadastrada(evento_id=evento.id, matricula=func.matricula, nome=func.nome, funcao=func.funcao, ativo=True)
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

@app.route('/api/limpeza-automatica')
def limpeza_automatica():
    """Rota que pode ser chamada pelo UptimeRobot ou cron job para limpar eventos antigos"""
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

# ============ GERENCIAR EVENTO ============
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

# ============ EXCLUIR EVENTO (SOFT DELETE) ============
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

# ============ APIs PÚBLICAS ============
@app.route('/e/<codigo>')
def pagina_inscricao(codigo):
    evento = Evento.query.filter_by(codigo_link=codigo).first_or_404()
    
    # ✅ Verificar se o evento foi excluído
    if evento.excluido:
        return render_template('public/evento_fechado.html', evento=evento, motivo='excluido')
    
    # ✅ Verificar se o evento está fechado
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
    data = request.json
    codigo = data.get('codigo_evento', '')
    evento = Evento.query.filter_by(codigo_link=codigo).first()
    if not evento:
        return jsonify({'sucesso': False, 'mensagem': 'Evento não encontrado'}), 404
    
    # ✅ INSCRIÇÃO POR NOME
    if evento.tipo_inscricao == 'nome':
        nome = data.get('nome', '').strip()
        if not nome:
            return jsonify({'sucesso': False, 'mensagem': 'Digite seu nome!'})
        
        vagas_ocupadas = Inscricao.query.filter_by(evento_id=evento.id, data_cancelamento=None).count()
        if vagas_ocupadas >= evento.total_vagas:
            return jsonify({'sucesso': False, 'mensagem': 'Vagas esgotadas!', 'vagas_restantes': 0})
        
        inscricao = Inscricao(evento_id=evento.id, matricula='NOME', nome=nome.upper(), funcao='PARTICIPANTE')
        db.session.add(inscricao)
        db.session.commit()
        
        vagas_ocupadas = Inscricao.query.filter_by(evento_id=evento.id, data_cancelamento=None).count()
        return jsonify({'sucesso': True, 'mensagem': f'{nome} inscrito!', 'vagas_restantes': evento.total_vagas - vagas_ocupadas})
    
    # ✅ INSCRIÇÃO POR MATRÍCULA
    matricula = data.get('matricula', '').zfill(6)
    cadastro = MatriculaCadastrada.query.filter_by(evento_id=evento.id, matricula=matricula, ativo=True).first()
    if not cadastro:
        return jsonify({'sucesso': False, 'mensagem': 'Matrícula não autorizada'}), 403
    
    funcao_bloqueada = FuncaoBloqueada.query.filter_by(evento_id=evento.id, funcao=cadastro.funcao).first()
    if funcao_bloqueada:
        return jsonify({'sucesso': False, 'mensagem': f'Inscrições não permitidas para: {cadastro.funcao}'})
    
    inscricao_existente = Inscricao.query.filter_by(evento_id=evento.id, matricula=matricula, data_cancelamento=None).first()
    if inscricao_existente:
        return jsonify({'sucesso': False, 'mensagem': 'Você já está inscrito!'})
    
    vagas_ocupadas = Inscricao.query.filter_by(evento_id=evento.id, data_cancelamento=None).count()
    if vagas_ocupadas >= evento.total_vagas:
        return jsonify({'sucesso': False, 'mensagem': 'Vagas esgotadas!', 'vagas_restantes': 0})
    
    inscricao = Inscricao(evento_id=evento.id, matricula=matricula, nome=cadastro.nome, funcao=cadastro.funcao)
    db.session.add(inscricao)
    db.session.commit()
    
    vagas_ocupadas = Inscricao.query.filter_by(evento_id=evento.id, data_cancelamento=None).count()
    return jsonify({'sucesso': True, 'mensagem': f'{cadastro.nome.split()[0]} inscrito!', 'vagas_restantes': evento.total_vagas - vagas_ocupadas})

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
    """Coloca o jogador no time correto automaticamente"""
    evento_id = inscricao.evento_id
    
    # Verificar se já existem times criados para este evento
    times = Time.query.filter_by(evento_id=evento_id).all()
    if not times:
        return  # Não tem times configurados ainda
    
    # Verificar se o jogador já está em algum time
    ja_em_time = TimeJogador.query.filter_by(inscricao_id=inscricao.id).first()
    if ja_em_time:
        return  # Já está em um time
    
    # Pegar configuração do evento (ou usar padrão)
    num_times = len(times)
    vagas_por_time = 5  # Padrão
    
    times_nomes = [t.nome for t in times]
    sorteio_qtd = vagas_por_time * 2
    
    # Contar quantos presentes já estão nos times
    total_em_times = TimeJogador.query.join(Time).filter(
        Time.evento_id == evento_id
    ).count()
    
    posicao = total_em_times + 1  # Próxima posição
    
    # Aplicar lógica de distribuição
    if posicao <= sorteio_qtd:
        time_nome = 'A' if posicao % 2 == 1 else 'B'
    else:
        restante = posicao - sorteio_qtd - 1
        bloco_idx = restante // vagas_por_time
        time_nome = times_nomes[bloco_idx % num_times]
    
    # Encontrar o time
    time_dict = {t.nome: t for t in times}
    if time_nome not in time_dict:
    # Procura qualquer time com vaga
        for nome in times_nomes:
            t = time_dict[nome]
            if TimeJogador.query.filter_by(time_id=t.id).count() < vagas_por_time:
                time_nome = nome
                break
    
    time = time_dict[time_nome]
    
    # Verificar se o time não está cheio
    count = TimeJogador.query.filter_by(time_id=time.id).count()
    if count >= vagas_por_time:
        # Procurar próximo time com vaga
        for nome in times_nomes:
            t = time_dict[nome]
            if TimeJogador.query.filter_by(time_id=t.id).count() < vagas_por_time:
                time = t
                break
    
    # Adicionar ao time
    tj = TimeJogador(
        time_id=time.id,
        inscricao_id=inscricao.id,
        ordem=TimeJogador.query.filter_by(time_id=time.id).count() + 1
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
# ============ RELATÓRIO PDF ============
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
    base = MatriculaCadastrada.query.filter(MatriculaCadastrada.evento_id.is_(None), MatriculaCadastrada.ativo == True).all()
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
from sqlalchemy import text  # ← Adicione no topo do arquivo

@app.before_request
def before_request():
    try:
        db.session.execute(text('SELECT 1'))  # ← CORRETO
    except Exception as e:
        print(f"Erro: {e}")
        db.session.remove()

@app.teardown_appcontext
def shutdown_session(exception=None):
    """Garantir que a sessão seja fechada ao final da requisição"""
    db.session.remove()
# ============ INICIAR ============
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
