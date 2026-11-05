import datetime
from sqlalchemy import Boolean, Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base

class BolaoIssue(Base):
    __tablename__ = "bolao_issues"

    id = Column(Integer, primary_key=True, index=True)
    issue_key = Column(String, unique=True, index=True)  # Ex: KAN-1
    time_a = Column(String, index=True) 
    time_b = Column(String, index=True) 
    data_encerramento = Column(DateTime)
    status = Column(String, default="TO DO") 
    criado_em = Column(DateTime, default=datetime.datetime.utcnow)

    # Relacionamento: Um bolão tem várias apostas
    apostas = relationship("Aposta", back_populates="bolao", cascade="all, delete-orphan")

class Aposta(Base):
    __tablename__ = "apostas"

    id = Column(Integer, primary_key=True, index=True)
    nome_usuario = Column(String, index=True)
    gols_time_a = Column(Integer) # Placar do mandante
    gols_time_b = Column(Integer) # Placar do visitante
    criado_em = Column(DateTime, default=datetime.datetime.utcnow)
    
    # Chave Estrangeira ligando a aposta ao Bolão correto
    bolao_id = Column(Integer, ForeignKey("bolao_issues.id"))
    bolao = relationship("BolaoIssue", back_populates="apostas")

class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    senha_hash = Column(String, nullable=False)
    saldo = Column(Integer, default=1000)  # Saldo em Jussana Coins (JC)
    is_admin = Column(Boolean, default=False)  # Admin pode criar cards de bolão
    criado_em = Column(DateTime, default=datetime.datetime.utcnow)
