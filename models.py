from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
import secrets

db = SQLAlchemy()

# ============ USUÁRIO ADMIN MASTER ============
class Admin(UserMixin, db.Model):
    """Usuário master (acesso total)"""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(300), nullable=False)
    nome = db.Column(db.String(100), nullable=False, default='Administrador')
    email = db.Column(db.String(120))
    role = db.Column(db.String(20), default='admin')  # 'admin' ou 'operador'
    ativo = db.Column(db.Boolean, default=True)
    ultimo_acesso = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    eventos_criados = db.relationship('Evento', backref='criador', lazy=True, foreign_keys='Evento.criado_por')
    logs = db.relationship('LogAcesso', backref='usuario', lazy=True)

# ============ LOG DE ACESSOS ============
class LogAcesso(db.Model):
    """Registro de ações e acessos"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=True)
    evento_id = db.Column(db.Integer, db.ForeignKey('evento.id'), nullable=True)
    acao = db.Column(db.String(50), nullable=False)  # 'login', 'criar_evento', 'excluir_evento', 'inscricao'
    descricao = db.Column(db.String(300))
    ip = db.Column(db.String(45))
    user_agent = db.Column(db.String(300))
    data = db.Column(db.DateTime, default=datetime.utcnow)

# ============ EVENTO ============
class Evento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False)
    data_evento = db.Column(db.DateTime, nullable=False)
    total_vagas = db.Column(db.Integer, nullable=False)
    codigo_link = db.Column(db.String(10), unique=True, nullable=False)
    status = db.Column(db.String(20), default='aberto')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # ✅ NOVO: Tipo de inscrição
    tipo_inscricao = db.Column(db.String(20), default='nome')  # 'nome' ou 'matricula'
    
    # ✅ NOVO: Quem criou / excluiu
    criado_por = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=True)
    excluido = db.Column(db.Boolean, default=False)
    data_exclusao = db.Column(db.DateTime, nullable=True)
    excluido_por = db.Column(db.Integer, nullable=True)
    
    matriculas = db.relationship('MatriculaCadastrada', backref='evento', lazy=True)
    inscricoes = db.relationship('Inscricao', backref='evento', lazy=True)
    funcoes_bloqueadas = db.relationship('FuncaoBloqueada', backref='evento', lazy=True)

class MatriculaCadastrada(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    evento_id = db.Column(db.Integer, db.ForeignKey('evento.id'), nullable=True)
    matricula = db.Column(db.String(6), nullable=False)
    nome = db.Column(db.String(100), nullable=False)
    funcao = db.Column(db.String(50), nullable=False)
    ativo = db.Column(db.Boolean, default=True)
    
class FuncaoBloqueada(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    evento_id = db.Column(db.Integer, db.ForeignKey('evento.id'), nullable=False)
    funcao = db.Column(db.String(50), nullable=False)

class Inscricao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    evento_id = db.Column(db.Integer, db.ForeignKey('evento.id'), nullable=False)
    matricula = db.Column(db.String(6), nullable=True)  # ✅ Pode ser nulo (inscrição por nome)
    nome = db.Column(db.String(100), nullable=False)
    funcao = db.Column(db.String(50), nullable=True)  # ✅ Pode ser nulo
    presente = db.Column(db.Boolean, default=None)
    data_inscricao = db.Column(db.DateTime, default=datetime.utcnow)
    data_cancelamento = db.Column(db.DateTime, nullable=True)
    cancelado_por = db.Column(db.String(50), nullable=True)
    data_confirmacao_presenca = db.Column(db.DateTime, nullable=True)

class MatriculaBloqueada(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    evento_id = db.Column(db.Integer, db.ForeignKey('evento.id'), nullable=False)
    matricula = db.Column(db.String(6), nullable=False)
    motivo = db.Column(db.String(200), nullable=False)
    data_bloqueio = db.Column(db.DateTime, default=datetime.utcnow)
    data_expiracao = db.Column(db.DateTime, nullable=True)
    evento = db.relationship('Evento', backref='matriculas_bloqueadas')

# ============ SORTEIO DE TIMES ============
class Time(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    evento_id = db.Column(db.Integer, db.ForeignKey('evento.id'), nullable=False)
    nome = db.Column(db.String(20), nullable=False)
    cor = db.Column(db.String(20), default='#10b981')
    evento = db.relationship('Evento', backref='times')

class TimeJogador(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    time_id = db.Column(db.Integer, db.ForeignKey('time.id'), nullable=False)
    inscricao_id = db.Column(db.Integer, db.ForeignKey('inscricao.id'), nullable=False)
    ordem = db.Column(db.Integer)
    manual = db.Column(db.Boolean, default=False)
    
    time = db.relationship('Time', backref='jogadores')
    inscricao = db.relationship('Inscricao')

def gerar_codigo_unico():
    import string
    caracteres = string.ascii_uppercase + string.digits
    while True:
        codigo = ''.join(secrets.choice(caracteres) for _ in range(6))
        if not Evento.query.filter_by(codigo_link=codigo).first():
            return codigo