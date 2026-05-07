from flask import Flask, render_template, request, jsonify, redirect, session, url_for, flash, send_file
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from models import db, Admin, Evento, MatriculaCadastrada, FuncaoBloqueada, Inscricao, MatriculaBloqueada, gerar_codigo_unico
from config import Config
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
import openpyxl  # ✅ Adicione esta
import os

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'admin_login'

# Criar pasta uploads
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

@login_manager.user_loader
def load_user(user_id):
    return Admin.query.get(int(user_id))

# ============ CRIAÇÃO INICIAL ============
with app.app_context():
    db.create_all()
    if not Admin.query.first():
        admin = Admin(
            username='admin',
            password=generate_password_hash('admin123')
        )
        db.session.add(admin)
        db.session.commit()
        print("✅ Admin padrão criado: admin / admin123")

# ============ ROTAS ADMIN ============

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        admin = Admin.query.filter_by(username=request.form['username']).first()
        if admin and check_password_hash(admin.password, request.form['password']):
            login_user(admin)
            flash('✅ Login realizado com sucesso!', 'success')
            return redirect(url_for('dashboard'))
        flash('❌ Usuário ou senha inválidos', 'danger')
    return render_template('admin/login.html')

@app.route('/admin/logout')
@login_required
def admin_logout():
    logout_user()
    return redirect(url_for('admin_login'))

@app.route('/admin/dashboard')
@login_required
def dashboard():
    eventos = Evento.query.order_by(Evento.created_at.desc()).all()
    total_cadastrados = MatriculaCadastrada.query.filter_by(evento_id=0).count()
    return render_template('admin/dashboard.html', 
                         eventos=eventos,
                         total_cadastrados=total_cadastrados)

# ============ CADASTRO PERMANENTE DE FUNCIONÁRIOS ============

# Upload de funcionários - sem Pandas
@app.route('/admin/cadastrar-funcionarios', methods=['GET', 'POST'])
@login_required
def cadastrar_funcionarios():
    # ✅ Adicione esta linha
    total_cadastrados = MatriculaCadastrada.query.filter_by(evento_id=0).count()
    
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
                
                import openpyxl
                
                if filename.endswith('.csv'):
                    rows = []
                    with open(filepath, 'r', encoding='utf-8') as f:
                        for line in f:
                            parts = line.strip().split('\t') if '\t' in line else line.strip().split(',')
                            if len(parts) >= 2:
                                rows.append(parts)
                else:
                    wb = openpyxl.load_workbook(filepath)
                    ws = wb.active
                    rows = list(ws.iter_rows(values_only=True))
                
                sistema = ['000010', '000063', '000099', '000777', '000888', '000999', '888888']
                contador_novos = 0
                contador_atualizados = 0
                
                for row in rows:
                    if not row[0] or not row[1]:
                        continue
                    
                    try:
                        matricula = str(int(row[0])).zfill(6)
                    except:
                        continue
                    
                    if matricula in sistema:
                        continue
                    
                    nome = str(row[1]).strip().upper()
                    funcao = str(row[2]).strip().upper() if len(row) > 2 and row[2] else 'NÃO INFORMADO'
                    
                    existente = MatriculaCadastrada.query.filter_by(
                        evento_id=0,
                        matricula=matricula
                    ).first()
                    
                    if existente:
                        existente.nome = nome
                        existente.funcao = funcao
                        contador_atualizados += 1
                    else:
                        novo = MatriculaCadastrada(
                            evento_id=0,
                            matricula=matricula,
                            nome=nome,
                            funcao=funcao,
                            ativo=True
                        )
                        db.session.add(novo)
                        contador_novos += 1
                
                db.session.commit()
                os.remove(filepath)
                
                flash(f'✅ {contador_novos} novos | {contador_atualizados} atualizados', 'success')
                return redirect(url_for('dashboard'))
                
            except Exception as e:
                flash(f'❌ Erro: {str(e)}', 'danger')
                return redirect(request.url)
    
    # ✅ Passe a variável
    return render_template('admin/cadastrar_funcionarios.html', 
                         total_cadastrados=total_cadastrados)

@app.route('/admin/reset-db')
def reset_db():
    import os
    
    # Deletar banco antigo
    try:
        os.remove('pelada.db')
    except:
        pass
    
    # Recriar tabelas
    db.create_all()
    
    # Criar admin
    from werkzeug.security import generate_password_hash
    admin = Admin(
        username='admin',
        password=generate_password_hash('admin123')
    )
    db.session.add(admin)
    db.session.commit()
    
    return '✅ Banco SQLite criado!<br>Login: admin / admin123<br><a href="/admin/login">Ir para Login</a>'

@app.route('/admin/evento/<int:evento_id>/atualizar-vagas', methods=['POST'])
@login_required
def atualizar_vagas(evento_id):
    evento = Evento.query.get_or_404(evento_id)
    novo_total = int(request.form['total_vagas'])
    
    if novo_total < 1:
        flash('❌ Número de vagas inválido', 'danger')
        return redirect(url_for('gerenciar_evento', evento_id=evento_id))
    
    vagas_ocupadas = Inscricao.query.filter_by(
        evento_id=evento_id,
        data_cancelamento=None
    ).count()
    
    if novo_total < vagas_ocupadas:
        flash(f'❌ Não é possível reduzir para {novo_total} vagas — já há {vagas_ocupadas} inscritos', 'danger')
        return redirect(url_for('gerenciar_evento', evento_id=evento_id))
    
    evento.total_vagas = novo_total
    db.session.commit()
    flash(f'✅ Vagas atualizadas para {novo_total}!', 'success')
    return redirect(url_for('gerenciar_evento', evento_id=evento_id))

# ============ CRIAR EVENTO ============

@app.route('/admin/criar-evento', methods=['GET', 'POST'])
@login_required
def criar_evento():
    # Busca funções da base permanente
    funcoes = db.session.query(MatriculaCadastrada.funcao)\
        .filter(MatriculaCadastrada.evento_id == 0, MatriculaCadastrada.ativo == True)\
        .distinct()\
        .order_by(MatriculaCadastrada.funcao)\
        .all()
    funcoes = [f[0] for f in funcoes]
    
    if request.method == 'POST':
        try:
            # Cria evento
            evento = Evento(
                nome=request.form['nome'],
                data_evento=datetime.strptime(request.form['data_evento'], '%Y-%m-%dT%H:%M'),
                total_vagas=int(request.form['total_vagas']),
                codigo_link=gerar_codigo_unico(),
                status='aberto'
            )
            db.session.add(evento)
            db.session.flush()
            
            # Copia funcionários da base para o evento
            base = MatriculaCadastrada.query.filter_by(evento_id=0, ativo=True).all()
            for func in base:
                mat = MatriculaCadastrada(
                    evento_id=evento.id,
                    matricula=func.matricula,
                    nome=func.nome,
                    funcao=func.funcao,
                    ativo=True
                )
                db.session.add(mat)
            
            # Bloqueia funções selecionadas
            funcoes_bloquear = request.form.getlist('funcoes_bloquear')
            for funcao in funcoes_bloquear:
                bloqueio = FuncaoBloqueada(
                    evento_id=evento.id,
                    funcao=funcao
                )
                db.session.add(bloqueio)
            
            db.session.commit()
            
            link = f"{request.host_url}e/{evento.codigo_link}"
            flash(f'✅ Evento criado!<br>Link: <a href="{link}" target="_blank">{link}</a>', 'success')
            return redirect(url_for('gerenciar_evento', evento_id=evento.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Erro: {str(e)}', 'danger')
    
    return render_template('admin/criar_evento.html', funcoes=funcoes)

@app.route('/admin/evento/<int:evento_id>/sincronizar-base', methods=['POST'])
@login_required
def sincronizar_base(evento_id):
    base = MatriculaCadastrada.query.filter_by(evento_id=0, ativo=True).all()
    
    contador = 0
    for cadastro in base:
        existente = MatriculaCadastrada.query.filter_by(
            evento_id=evento_id,
            matricula=cadastro.matricula
        ).first()
        
        if not existente:
            db.session.add(MatriculaCadastrada(
                evento_id=evento_id,
                matricula=cadastro.matricula,
                nome=cadastro.nome,
                funcao=cadastro.funcao,
                ativo=True
            ))
            contador += 1
    
    db.session.commit()
    flash(f'✅ {contador} matrículas sincronizadas!', 'success')
    return redirect(url_for('gerenciar_evento', evento_id=evento_id))
# ============ GERENCIAR EVENTO ============

@app.route('/admin/evento/<int:evento_id>')
@login_required
def gerenciar_evento(evento_id):
    evento = Evento.query.get_or_404(evento_id)
    inscricoes = Inscricao.query.filter_by(
        evento_id=evento.id,
        data_cancelamento=None
    ).order_by(Inscricao.data_inscricao).all()
    
    vagas_ocupadas = len(inscricoes)
    vagas_disponiveis = evento.total_vagas - vagas_ocupadas
    
    # ✅ ADICIONE ESTA LINHA
    bloqueios = MatriculaBloqueada.query.filter_by(evento_id=evento.id).all()
    
    return render_template('admin/gerenciar_evento.html',
                         evento=evento,
                         inscricoes=inscricoes,
                         vagas_ocupadas=vagas_ocupadas,
                         vagas_disponiveis=vagas_disponiveis,
                         bloqueios=bloqueios)  # ✅ ADICIONE AQUI

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
    
    inscricoes = Inscricao.query.filter_by(
        evento_id=evento.id,
        data_cancelamento=None
    ).order_by(Inscricao.data_inscricao).all()
    
    presentes = sum(1 for i in inscricoes if i.presente == True)
    faltas = sum(1 for i in inscricoes if i.presente == False)
    pendentes = sum(1 for i in inscricoes if i.presente == None)
    
    return jsonify({
        'total_vagas': evento.total_vagas,
        'inscritos': len(inscricoes),
        'presentes': presentes,
        'faltas': faltas,
        'pendentes': pendentes,
        'lista': [{
            'id': i.id,
            'nome': i.nome,
            'matricula': i.matricula,
            'funcao': i.funcao,
            'presente': i.presente,
            'hora_inscricao': i.data_inscricao.strftime('%H:%M') if i.data_inscricao else ''
        } for i in inscricoes]
    })

@app.route('/api/inscricao/<int:inscricao_id>/presenca', methods=['POST'])
@login_required
def marcar_presenca(inscricao_id):
    data = request.json
    status = data.get('status')  # True, False ou None
    
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
    
    return jsonify({'sucesso': True})

# ============ RELATÓRIO PDF ============

@app.route('/admin/evento/<int:evento_id>/relatorio')
@login_required
def gerar_relatorio(evento_id):
    evento = Evento.query.get_or_404(evento_id)
    
    inscricoes = Inscricao.query.filter_by(
        evento_id=evento.id,
        data_cancelamento=None
    ).order_by(Inscricao.nome).all()
    
    # Criar PDF
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # Título
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, height - 50, f"RELATÓRIO DE PRESENÇA")
    p.setFont("Helvetica", 12)
    p.drawString(50, height - 70, f"Evento: {evento.nome}")
    p.drawString(50, height - 85, f"Data: {evento.data_evento.strftime('%d/%m/%Y %H:%M')}")
    p.drawString(50, height - 100, f"Vagas: {evento.total_vagas} | Presentes: {sum(1 for i in inscricoes if i.presente == True)}")
    
    # Linha separadora
    p.line(50, height - 110, width - 50, height - 110)
    
    # Cabeçalho da tabela
    y = height - 130
    p.setFont("Helvetica-Bold", 10)
    p.drawString(50, y, "MATRÍCULA")
    p.drawString(130, y, "NOME")
    p.drawString(350, y, "FUNÇÃO")
    p.drawString(480, y, "STATUS")
    
    # Dados
    y -= 20
    p.setFont("Helvetica", 9)
    
    for i, insc in enumerate(inscricoes):
        if y < 50:  # Nova página
            p.showPage()
            y = height - 50
        
        # Matrícula
        p.drawString(50, y, insc.matricula)
        # Nome (truncado se muito grande)
        nome = insc.nome[:40] if len(insc.nome) > 40 else insc.nome
        p.drawString(130, y, nome)
        # Função
        p.drawString(350, y, insc.funcao[:20])
        
        # Status com cores
        if insc.presente == True:
            p.setFillColor(colors.green)
            p.drawString(480, y, "✓ PRESENTE")
        elif insc.presente == False:
            p.setFillColor(colors.red)
            p.drawString(480, y, "✗ FALTA")
        else:
            p.setFillColor(colors.orange)
            p.drawString(480, y, "○ PENDENTE")
        
        p.setFillColor(colors.black)
        y -= 15
    
    p.save()
    buffer.seek(0)
    
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'relatorio_{evento.nome.replace(" ", "_")}.pdf'
    )

# ============ ROTAS PÚBLICAS ============

@app.route('/e/<codigo>')
def pagina_inscricao(codigo):
    evento = Evento.query.filter_by(codigo_link=codigo).first_or_404()
    
    if evento.status != 'aberto':
        return render_template('public/evento_fechado.html', evento=evento)
    
    vagas_ocupadas = Inscricao.query.filter_by(
        evento_id=evento.id,
        data_cancelamento=None
    ).count()
    
    vagas_disponiveis = evento.total_vagas - vagas_ocupadas
    
    if vagas_disponiveis <= 0:
        return render_template('public/vagas_esgotadas.html', evento=evento)
    
    return render_template('public/inscricao.html',
                         evento=evento,
                         vagas_disponiveis=vagas_disponiveis)
@app.route('/')
def index():
    return redirect(url_for('admin_login'))

@app.route('/api/validar-matricula', methods=['POST'])
def validar_matricula():
    data = request.json
    codigo = data['codigo_evento']
    matricula = data['matricula'].zfill(6)
    
    evento = Evento.query.filter_by(codigo_link=codigo).first()
    if not evento:
        return jsonify({'valido': False, 'mensagem': 'Evento não encontrado'})
    
    # ✅ NOVA VERIFICAÇÃO: Matrícula bloqueada individualmente
    bloqueio = MatriculaBloqueada.query.filter_by(
        evento_id=evento.id,
        matricula=matricula
    ).first()
    
    if bloqueio:
        # Verificar se expirou
        if bloqueio.data_expiracao and bloqueio.data_expiracao < datetime.utcnow():
            # Expirou - remover bloqueio automaticamente
            db.session.delete(bloqueio)
            db.session.commit()
        else:
            expira_em = ''
            if bloqueio.data_expiracao:
                expira_em = f' Expira em {bloqueio.data_expiracao.strftime("%d/%m/%Y")}.'
            else:
                expira_em = ' Bloqueio permanente.'
            
            return jsonify({
                'valido': False,
                'mensagem': f'🚫 Matrícula bloqueada: {bloqueio.motivo}.{expira_em}'
            })
    
    # Verificações existentes continuam...
    cadastro = MatriculaCadastrada.query.filter_by(
        evento_id=evento.id,
        matricula=matricula,
        ativo=True
    ).first()
    
    if not cadastro:
        return jsonify({'valido': False, 'mensagem': 'Matrícula não autorizada'})
    
    funcao_bloqueada = FuncaoBloqueada.query.filter_by(
        evento_id=evento.id,
        funcao=cadastro.funcao
    ).first()
    
    if funcao_bloqueada:
        return jsonify({
            'valido': False,
            'mensagem': f'Inscrições não permitidas para: {cadastro.funcao}'
        })
    
    inscricao_existente = Inscricao.query.filter_by(
        evento_id=evento.id,
        matricula=matricula,
        data_cancelamento=None
    ).first()
    
    if inscricao_existente:
        return jsonify({
            'valido': False,
            'mensagem': 'Você já está inscrito!',
            'pode_cancelar': True,
            'inscricao_id': inscricao_existente.id
        })
    
    vagas_ocupadas = Inscricao.query.filter_by(
        evento_id=evento.id,
        data_cancelamento=None
    ).count()
    
    if vagas_ocupadas >= evento.total_vagas:
        return jsonify({'valido': False, 'mensagem': 'Vagas esgotadas!'})
    
    return jsonify({
        'valido': True,
        'nome': cadastro.nome,
        'funcao': cadastro.funcao,
        'vagas_restantes': evento.total_vagas - vagas_ocupadas
    })

@app.route('/admin/evento/<int:evento_id>/excluir', methods=['POST'])
@login_required
def excluir_evento(evento_id):
    evento = Evento.query.get_or_404(evento_id)
    
    # Remove inscrições do evento
    Inscricao.query.filter_by(evento_id=evento.id).delete()
    # Remove matrículas do evento
    MatriculaCadastrada.query.filter_by(evento_id=evento.id).delete()
    # Remove funções bloqueadas
    FuncaoBloqueada.query.filter_by(evento_id=evento.id).delete()
    # Remove o evento
    db.session.delete(evento)
    db.session.commit()
    
    flash('✅ Evento excluído com sucesso!', 'success')
    return redirect(url_for('dashboard'))

@app.route('/api/inscrever', methods=['POST'])
def inscrever():
    data = request.json
    codigo = data.get('codigo_evento', '')
    matricula = data.get('matricula', '').zfill(6)
    
    # 1. Verificar se o evento existe
    evento = Evento.query.filter_by(codigo_link=codigo).first()
    if not evento:
        return jsonify({'sucesso': False, 'mensagem': 'Evento não encontrado'}), 404
    
    # 2. Verificar se a matrícula está cadastrada
    cadastro = MatriculaCadastrada.query.filter_by(
        evento_id=evento.id,
        matricula=matricula,
        ativo=True
    ).first()
    
    if not cadastro:
        return jsonify({'sucesso': False, 'mensagem': 'Matrícula não autorizada'}), 403
    
    # 3. Verificar se a função está bloqueada
    funcao_bloqueada = FuncaoBloqueada.query.filter_by(
        evento_id=evento.id,
        funcao=cadastro.funcao
    ).first()
    
    if funcao_bloqueada:
        return jsonify({
            'sucesso': False,
            'mensagem': f'Inscrições não permitidas para: {cadastro.funcao}'
        })
    
    # 4. Verificar se já está inscrito
    inscricao_existente = Inscricao.query.filter_by(
        evento_id=evento.id,
        matricula=matricula,
        data_cancelamento=None
    ).first()
    
    if inscricao_existente:
        return jsonify({
            'sucesso': False,
            'mensagem': 'Você já está inscrito neste evento!'
        })
    
    # 5. Verificar se há vagas disponíveis
    vagas_ocupadas = Inscricao.query.filter_by(
        evento_id=evento.id,
        data_cancelamento=None
    ).count()
    
    if vagas_ocupadas >= evento.total_vagas:
        return jsonify({
            'sucesso': False,
            'mensagem': '😔 Vagas esgotadas! Alguém se inscreveu antes de você.',
            'vagas_restantes': 0
        })
    
    # 6. Criar inscrição
    inscricao = Inscricao(
        evento_id=evento.id,
        matricula=matricula,
        nome=cadastro.nome,
        funcao=cadastro.funcao
    )
    
    db.session.add(inscricao)
    db.session.commit()
    
    # 7. Recalcular vagas
    vagas_ocupadas = Inscricao.query.filter_by(
        evento_id=evento.id,
        data_cancelamento=None
    ).count()
    vagas_restantes = evento.total_vagas - vagas_ocupadas
    
    return jsonify({
        'sucesso': True,
        'mensagem': f'{cadastro.nome.split()[0]} inscrito com sucesso!',
        'vagas_restantes': vagas_restantes,
        'inscricao_id': inscricao.id
    })

@app.route('/api/cancelar-inscricao', methods=['POST'])
def cancelar_inscricao():
    data = request.json
    inscricao_id = data['inscricao_id']
    
    inscricao = Inscricao.query.get(inscricao_id)
    if not inscricao:
        return jsonify({'erro': 'Inscrição não encontrada'}), 404
    
    inscricao.data_cancelamento = datetime.utcnow()
    inscricao.cancelado_por = 'usuario'
    db.session.commit()
    
    evento = Evento.query.get(inscricao.evento_id)
    vagas_ocupadas = Inscricao.query.filter_by(
        evento_id=evento.id,
        data_cancelamento=None
    ).count()
    
    return jsonify({
        'sucesso': True,
        'mensagem': 'Inscrição cancelada com sucesso!',
        'vagas_restantes': evento.total_vagas - vagas_ocupadas
    })

# ============ BLOQUEAR MATRÍCULA ESPECÍFICA ============

@app.route('/admin/evento/<int:evento_id>/bloquear-matricula', methods=['POST'])
@login_required
def bloquear_matricula(evento_id):
    evento = Evento.query.get_or_404(evento_id)
    matricula = request.form.get('matricula', '').zfill(6)
    motivo = request.form.get('motivo', 'Bloqueio administrativo')
    duracao = request.form.get('duracao', 'permanente')  # 'permanente', '1_semana', '2_semanas', '1_mes'
    
    # Verificar se matrícula existe no evento
    cadastro = MatriculaCadastrada.query.filter_by(
        evento_id=evento.id,
        matricula=matricula
    ).first()
    
    if not cadastro:
        flash('❌ Matrícula não encontrada no evento!', 'danger')
        return redirect(url_for('gerenciar_evento', evento_id=evento.id))
    
    # Verificar se já está bloqueada
    ja_bloqueada = MatriculaBloqueada.query.filter_by(
        evento_id=evento.id,
        matricula=matricula
    ).first()
    
    if ja_bloqueada:
        flash('❌ Esta matrícula já está bloqueada!', 'danger')
        return redirect(url_for('gerenciar_evento', evento_id=evento.id))
    
    # Calcular data de expiração
    data_expiracao = None
    if duracao == '1_semana':
        data_expiracao = datetime.utcnow() + timedelta(days=7)
    elif duracao == '2_semanas':
        data_expiracao = datetime.utcnow() + timedelta(days=14)
    elif duracao == '1_mes':
        data_expiracao = datetime.utcnow() + timedelta(days=30)
    
    bloqueio = MatriculaBloqueada(
        evento_id=evento.id,
        matricula=matricula,
        motivo=motivo,
        data_expiracao=data_expiracao
    )
    
    db.session.add(bloqueio)
    
    # Também remover inscrição se existir
    inscricao = Inscricao.query.filter_by(
        evento_id=evento.id,
        matricula=matricula,
        data_cancelamento=None
    ).first()
    
    if inscricao:
        inscricao.data_cancelamento = datetime.utcnow()
        inscricao.cancelado_por = 'admin_bloqueio'
    
    db.session.commit()
    
    flash(f'🔒 Matrícula {matricula} bloqueada! Motivo: {motivo}', 'success')
    return redirect(url_for('gerenciar_evento', evento_id=evento.id))


@app.route('/admin/evento/<int:evento_id>/desbloquear-matricula/<int:bloqueio_id>', methods=['POST'])
@login_required
def desbloquear_matricula(evento_id, bloqueio_id):
    bloqueio = MatriculaBloqueada.query.get_or_404(bloqueio_id)
    matricula = bloqueio.matricula
    
    db.session.delete(bloqueio)
    db.session.commit()
    
    flash(f'🔓 Matrícula {matricula} desbloqueada!', 'success')
    return redirect(url_for('gerenciar_evento', evento_id=evento_id))
# ============ INICIAR ============

# No final do arquivo
if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)