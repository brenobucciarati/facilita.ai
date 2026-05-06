from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
import secrets

db = SQLAlchemy()

class Admin(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Evento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False)
    data_evento = db.Column(db.DateTime, nullable=False)
    total_vagas = db.Column(db.Integer, nullable=False)
    codigo_link = db.Column(db.String(10), unique=True, nullable=False)
    status = db.Column(db.String(20), default='aberto')  # aberto, em_andamento, finalizado
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relacionamentos
    matriculas = db.relationship('MatriculaCadastrada', backref='evento', lazy=True)
    inscricoes = db.relationship('Inscricao', backref='evento', lazy=True)
    funcoes_bloqueadas = db.relationship('FuncaoBloqueada', backref='evento', lazy=True)

class MatriculaCadastrada(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    evento_id = db.Column(db.Integer, db.ForeignKey('evento.id'), nullable=False)
    matricula = db.Column(db.String(6), nullable=False)
    nome = db.Column(db.String(100), nullable=False)
    funcao = db.Column(db.String(50), nullable=False)  # motorista, eletricista, etc
    ativo = db.Column(db.Boolean, default=True)  # Para bloqueio individual
    
class FuncaoBloqueada(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    evento_id = db.Column(db.Integer, db.ForeignKey('evento.id'), nullable=False)
    funcao = db.Column(db.String(50), nullable=False)

class Inscricao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    evento_id = db.Column(db.Integer, db.ForeignKey('evento.id'), nullable=False)
    matricula = db.Column(db.String(6), nullable=False)
    nome = db.Column(db.String(100), nullable=False)
    funcao = db.Column(db.String(50), nullable=False)
    presente = db.Column(db.Boolean, default=None)  # None=pendente, True=presente, False=falta
    data_inscricao = db.Column(db.DateTime, default=datetime.utcnow)
    data_cancelamento = db.Column(db.DateTime, nullable=True)
    cancelado_por = db.Column(db.String(50), nullable=True)  # 'usuario' ou 'admin'
    data_confirmacao_presenca = db.Column(db.DateTime, nullable=True)
    
class MatriculaBloqueada(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    evento_id = db.Column(db.Integer, db.ForeignKey('evento.id'), nullable=False)
    matricula = db.Column(db.String(6), nullable=False)
    motivo = db.Column(db.String(200), nullable=False)
    data_bloqueio = db.Column(db.DateTime, default=datetime.utcnow)
    data_expiracao = db.Column(db.DateTime, nullable=True)  # None = permanente
    
    evento = db.relationship('Evento', backref='matriculas_bloqueadas')

def gerar_codigo_unico():
    """Gera código único de 6 caracteres para o link do evento"""
    import string
    caracteres = string.ascii_uppercase + string.digits
    while True:
        codigo = ''.join(secrets.choice(caracteres) for _ in range(6))
        if not Evento.query.filter_by(codigo_link=codigo).first():
            return codigo