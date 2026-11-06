import datetime
from sqlalchemy import Boolean, Column, Float, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base

class BolaoIssue(Base):
    __tablename__ = "bolao_issues"

    id = Column(Integer, primary_key=True, index=True)
    issue_key = Column(String, unique=True, index=True)  # Ex: KAN-1
    time_a = Column(String, index=True)
    time_b = Column(String, index=True)
    escudo_a = Column(String, nullable=True)  # URL da imagem do escudo (ESPN)
    escudo_b = Column(String, nullable=True)
    # ODDs definidas pelo admin (multiplicador pago a quem acertar)
    odd_casa = Column(Float, nullable=True)     # vitória do mandante (time A)
    odd_empate = Column(Float, nullable=True)
    odd_fora = Column(Float, nullable=True)     # vitória do visitante (time B)
    odd_placar = Column(Float, nullable=True)   # placar exato
    # Resultado real, informado pelo admin depois do jogo
    gols_final_a = Column(Integer, nullable=True)
    gols_final_b = Column(Integer, nullable=True)
    encerrado_em = Column(DateTime, nullable=True)  # quando o admin lançou o resultado e pagou
    data_encerramento = Column(DateTime)  # Sempre em UTC
    status = Column(String, default="TO DO")
    criado_em = Column(DateTime, default=datetime.datetime.utcnow)

    # Relacionamento: Um bolão tem várias apostas
    apostas = relationship("Aposta", back_populates="bolao", cascade="all, delete-orphan")

class Aposta(Base):
    __tablename__ = "apostas"
    # Cada usuário pode fazer vários palpites no mesmo bolão (até o fechamento)

    id = Column(Integer, primary_key=True, index=True)
    nome_usuario = Column(String, index=True)
    gols_time_a = Column(Integer) # Placar do mandante
    gols_time_b = Column(Integer) # Placar do visitante
    valor = Column(Integer, default=0)  # Jussana Coins apostadas
    # ODDs "travadas" no momento da aposta (editar o bolão depois não muda isso)
    odd_resultado = Column(Float, nullable=True)  # ODD do resultado palpitado (casa/empate/fora)
    odd_placar = Column(Float, nullable=True)     # ODD de placar exato
    # Preenchidos quando o admin lança o resultado do jogo
    premio = Column(Integer, nullable=True)       # JC recebidas (0 = perdeu; vazio = jogo sem resultado ainda)
    situacao = Column(String, nullable=True)      # "placar", "resultado", "perdeu" ou "devolvido"
    criado_em = Column(DateTime, default=datetime.datetime.utcnow)

    # Chave Estrangeira ligando a aposta ao Bolão correto
    bolao_id = Column(Integer, ForeignKey("bolao_issues.id"))
    bolao = relationship("BolaoIssue", back_populates="apostas")

    # Quem apostou
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), index=True)
    usuario = relationship("Usuario", back_populates="apostas")


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    senha_hash = Column(String, nullable=False)
    saldo = Column(Integer, default=1000)  # Saldo em Jussana Coins (JC)
    is_admin = Column(Boolean, default=False)  # Admin pode criar cards de bolão
    ativo = Column(Boolean, default=True)  # Conta bloqueada pelo admin não consegue entrar
    criado_em = Column(DateTime, default=datetime.datetime.utcnow)

    apostas = relationship("Aposta", back_populates="usuario")
