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
    
    # Relacionamentos para Destaque e NotaAtualizacao
    destaques_criados = db.relationship('Destaque', backref='criador', lazy=True, foreign_keys='Destaque.criado_por')
    notas_criadas = db.relationship('NotaAtualizacao', backref='criador', lazy=True, foreign_keys='NotaAtualizacao.criado_por')
    
    # Relacionamento para Jogadores
    jogadores_criados = db.relationship('Jogador', backref='criador', lazy=True, foreign_keys='Jogador.criado_por')


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


# ============ DESTAQUE ============
class Destaque(db.Model):
    __tablename__ = 'destaques'
    
    id = db.Column(db.Integer, primary_key=True)
    imagem_url = db.Column(db.String(500), nullable=True)
    titulo = db.Column(db.String(200), nullable=False)
    descricao = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(500), nullable=True)
    ativo = db.Column(db.Boolean, default=True)
    ordem = db.Column(db.Integer, default=0)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    criado_por = db.Column(db.Integer, db.ForeignKey('admin.id'))
    
    def to_dict(self):
        return {
            'id': self.id,
            'imagem_url': self.imagem_url,
            'titulo': self.titulo,
            'descricao': self.descricao,
            'link': self.link,
            'ativo': self.ativo,
            'ordem': self.ordem,
        }


# ============ NOTAS DE ATUALIZAÇÃO ============
class NotaAtualizacao(db.Model):
    __tablename__ = 'notas_atualizacao'
    
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.String(20), nullable=False)
    versao = db.Column(db.String(20), nullable=True)  # Pode ser nulo para novidades
    tipo = db.Column(db.String(20), default='versao')  # 'versao' ou 'novidade'
    titulo = db.Column(db.String(200), nullable=False)
    descricao = db.Column(db.Text, nullable=False)
    ativo = db.Column(db.Boolean, default=True)
    ordem = db.Column(db.Integer, default=0)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    criado_por = db.Column(db.Integer, db.ForeignKey('admin.id'))
    
    def to_dict(self):
        return {
            'id': self.id,
            'data': self.data,
            'versao': self.versao,
            'tipo': self.tipo,
            'titulo': self.titulo,
            'descricao': self.descricao,
            'ativo': self.ativo,
            'ordem': self.ordem,
        }


# ============ JOGADOR (CADASTRO MANUAL) ============
class Jogador(db.Model):
    __tablename__ = 'jogadores'
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    sobrenome = db.Column(db.String(100), nullable=True)
    apelido = db.Column(db.String(50), nullable=True)
    funcao = db.Column(db.String(50), default='GERAL')
    telefone = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    
    # Tipo de jogador
    tipo = db.Column(db.String(20), default='mensalista')  # mensalista, diarista, visitante
    
    # Controle de mensalidade (apenas para mensalistas)
    mensalidade_paga = db.Column(db.Boolean, default=False)
    data_vencimento = db.Column(db.DateTime, nullable=True)
    data_pagamento = db.Column(db.DateTime, nullable=True)
    valor_mensalidade = db.Column(db.Float, default=0.0)
    mes_referencia = db.Column(db.String(7), nullable=True)  # Ex: '2026-09'
    
    # Controle de acesso
    ativo = db.Column(db.Boolean, default=True)
    bloqueado = db.Column(db.Boolean, default=False)
    motivo_bloqueio = db.Column(db.String(200), nullable=True)
    data_bloqueio = db.Column(db.DateTime, nullable=True)
    
    # Relacionamentos
    criado_por = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def is_mensalidade_vencida(self):
        """Verifica se a mensalidade está vencida"""
        if self.tipo != 'mensalista':
            return False
        if self.mensalidade_paga:
            return False
        if self.data_vencimento and self.data_vencimento < datetime.utcnow():
            return True
        return False
    
    def pode_inscrever(self):
        """Verifica se o jogador pode se inscrever em eventos"""
        if not self.ativo:
            return False
        if self.bloqueado:
            return False
        if self.tipo == 'mensalista' and self.is_mensalidade_vencida():
            return False
        return True
    
    def get_status_mensalidade(self):
        """Retorna o status da mensalidade"""
        if self.tipo != 'mensalista':
            return 'N/A'
        if self.mensalidade_paga:
            return 'pago'
        if self.data_vencimento and self.data_vencimento < datetime.utcnow():
            return 'vencido'
        return 'pendente'
    
    def to_dict(self):
        return {
            'id': self.id,
            'nome': self.nome,
            'sobrenome': self.sobrenome,
            'apelido': self.apelido,
            'funcao': self.funcao,
            'telefone': self.telefone,
            'email': self.email,
            'tipo': self.tipo,
            'mensalidade_paga': self.mensalidade_paga,
            'data_vencimento': self.data_vencimento.strftime('%Y-%m-%d') if self.data_vencimento else None,
            'data_pagamento': self.data_pagamento.strftime('%Y-%m-%d') if self.data_pagamento else None,
            'valor_mensalidade': self.valor_mensalidade,
            'mes_referencia': self.mes_referencia,
            'ativo': self.ativo,
            'bloqueado': self.bloqueado,
        }


# ============ EVENTO ============
class Evento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False)
    data_evento = db.Column(db.DateTime, nullable=False)
    total_vagas = db.Column(db.Integer, nullable=False)
    codigo_link = db.Column(db.String(10), unique=True, nullable=False)
    status = db.Column(db.String(20), default='aberto')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    tipo_inscricao = db.Column(db.String(20), default='nome')
    
    # ✅ NOVOS CAMPOS PARA CONFIGURAÇÃO DE VAGAS POR TIPO
    vagas_mensalistas = db.Column(db.Integer, default=0)
    vagas_diaristas = db.Column(db.Integer, default=0)
    vagas_visitantes = db.Column(db.Integer, default=0)
    usar_prioridades = db.Column(db.Boolean, default=False)
    
    criado_por = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=True)
    excluido = db.Column(db.Boolean, default=False)
    data_exclusao = db.Column(db.DateTime, nullable=True)
    excluido_por = db.Column(db.Integer, nullable=True)
    
    matriculas = db.relationship('MatriculaCadastrada', backref='evento', lazy=True)
    inscricoes = db.relationship('Inscricao', backref='evento', lazy=True)
    funcoes_bloqueadas = db.relationship('FuncaoBloqueada', backref='evento', lazy=True)


# ============ MATRÍCULA CADASTRADA ============
class MatriculaCadastrada(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    evento_id = db.Column(db.Integer, db.ForeignKey('evento.id'), nullable=True)
    matricula = db.Column(db.String(6), nullable=False)
    nome = db.Column(db.String(100), nullable=False)
    funcao = db.Column(db.String(50), nullable=False)
    ativo = db.Column(db.Boolean, default=True)
    criado_por = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=True)


# ============ FUNÇÃO BLOQUEADA ============
class FuncaoBloqueada(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    evento_id = db.Column(db.Integer, db.ForeignKey('evento.id'), nullable=False)
    funcao = db.Column(db.String(50), nullable=False)


# ============ INSCRIÇÃO ============
class Inscricao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    evento_id = db.Column(db.Integer, db.ForeignKey('evento.id'), nullable=False)
    jogador_id = db.Column(db.Integer, db.ForeignKey('jogadores.id'), nullable=True)  # ✅ ADICIONAR
    matricula = db.Column(db.String(6), nullable=True)
    nome = db.Column(db.String(100), nullable=False)
    funcao = db.Column(db.String(50), nullable=True)
    presente = db.Column(db.Boolean, default=None)
    data_inscricao = db.Column(db.DateTime, default=datetime.utcnow)
    data_cancelamento = db.Column(db.DateTime, nullable=True)
    cancelado_por = db.Column(db.String(50), nullable=True)
    data_confirmacao_presenca = db.Column(db.DateTime, nullable=True)
    
    jogador = db.relationship('Jogador', backref='inscricoes', lazy=True)  # ✅ ADICIONAR


# ============ MATRÍCULA BLOQUEADA ============
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


# ============ FUNÇÃO AUXILIAR ============
def gerar_codigo_unico():
    import string
    caracteres = string.ascii_uppercase + string.digits
    while True:
        codigo = ''.join(secrets.choice(caracteres) for _ in range(6))
        if not Evento.query.filter_by(codigo_link=codigo).first():
            return codigo