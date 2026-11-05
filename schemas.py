from pydantic import BaseModel, Field, field_validator
from datetime import datetime, timezone
from typing import List, Optional


def para_utc_sem_fuso(v: datetime) -> datetime:
    """Converte datas com fuso (ex: 2026-11-05T23:00:00Z) para UTC 'ingênuo',
    que é como guardamos no SQLite e comparamos com datetime.utcnow()."""
    if v.tzinfo is not None:
        v = v.astimezone(timezone.utc).replace(tzinfo=None)
    return v


# --- Schemas de Aposta ---
class ApostaCreate(BaseModel):
    gols_time_a: int = Field(..., ge=0, le=99, description="Gols não podem ser negativos")
    gols_time_b: int = Field(..., ge=0, le=99)
    valor: int = Field(..., ge=1, description="Quantidade de Jussana Coins apostadas")

class ApostaResponse(BaseModel):
    id: int
    nome_usuario: str
    gols_time_a: int
    gols_time_b: int
    valor: int
    odd_resultado: Optional[float] = None
    odd_placar: Optional[float] = None
    criado_em: datetime

    class Config:
        from_attributes = True

class ApostaRegistrada(ApostaResponse):
    saldo_atual: int  # Saldo do usuário depois de descontar a aposta


# --- ODDs ---
def _odd():
    return Field(..., ge=1.01, le=1000, description="Multiplicador pago a quem acertar")

class Odds(BaseModel):
    odd_casa: float = _odd()
    odd_empate: float = _odd()
    odd_fora: float = _odd()
    odd_placar: float = _odd()

    @field_validator('odd_casa', 'odd_empate', 'odd_fora', 'odd_placar')
    @classmethod
    def duas_casas(cls, v):
        return round(v, 2)


# --- Schemas de Bolão ---
class BolaoCreate(Odds):
    time_a: str = Field(..., min_length=2, max_length=50)
    time_b: str = Field(..., min_length=2, max_length=50)
    data_encerramento: datetime
    escudo_a: Optional[str] = Field(None, max_length=500)
    escudo_b: Optional[str] = Field(None, max_length=500)

    @field_validator('escudo_a', 'escudo_b')
    @classmethod
    def validar_escudo(cls, v):
        # Só aceitamos imagens da ESPN, de onde vem a busca de times
        if v and not v.startswith('https://a.espncdn.com/'):
            raise ValueError('Escudo inválido.')
        return v or None

    @field_validator('data_encerramento')
    @classmethod
    def validar_data_futura(cls, v):
        v = para_utc_sem_fuso(v)
        if v <= datetime.utcnow():
            raise ValueError('A data de encerramento deve ser no futuro.')
        return v

class BolaoResponse(BaseModel):
    id: int
    issue_key: str
    time_a: str
    time_b: str
    escudo_a: Optional[str] = None
    escudo_b: Optional[str] = None
    odd_casa: Optional[float] = None
    odd_empate: Optional[float] = None
    odd_fora: Optional[float] = None
    odd_placar: Optional[float] = None
    data_encerramento: datetime
    status: str
    criado_em: datetime
    apostas: List[ApostaResponse] = []

    class Config:
        from_attributes = True

class MinhaAposta(BaseModel):
    gols_time_a: int
    gols_time_b: int
    valor: int
    odd_resultado: Optional[float] = None
    odd_placar: Optional[float] = None

class BolaoAberto(BaseModel):
    """Card de bolão como aparece na tela de palpites."""
    issue_key: str
    time_a: str
    time_b: str
    escudo_a: Optional[str] = None
    escudo_b: Optional[str] = None
    odd_casa: Optional[float] = None
    odd_empate: Optional[float] = None
    odd_fora: Optional[float] = None
    odd_placar: Optional[float] = None
    data_encerramento: datetime  # UTC
    total_apostas: Optional[int] = None  # só enviado para o admin
    pote: Optional[int] = None  # Soma das JC apostadas (só enviado para o admin)
    minha_aposta: Optional[MinhaAposta] = None


class TimeEncontrado(BaseModel):
    id: str
    nome: str
    escudo: Optional[str] = None
    liga: str


# --- Schemas de Usuário / Autenticação ---
class UsuarioCadastro(BaseModel):
    username: str = Field(..., min_length=3, max_length=30, pattern=r"^[A-Za-z0-9_.]+$")
    senha: str = Field(..., min_length=6, max_length=128)


class UsuarioLogin(BaseModel):
    username: str
    senha: str


class UsuarioResponse(BaseModel):
    id: int
    username: str
    saldo: int
    is_admin: bool
    ativo: bool = True
    criado_em: datetime

    class Config:
        from_attributes = True


# --- Gestão de contas (admin) ---
class ContaAdmin(BaseModel):
    id: int
    username: str
    saldo: int
    is_admin: bool
    ativo: bool
    criado_em: datetime
    total_apostas: int
    total_apostado: int


class AjusteSaldo(BaseModel):
    valor: int = Field(..., description="Positivo para dar JC, negativo para tirar")

    @field_validator('valor')
    @classmethod
    def nao_zero(cls, v):
        if v == 0:
            raise ValueError('O ajuste não pode ser zero.')
        return v


class AlteracaoConta(BaseModel):
    is_admin: Optional[bool] = None
    ativo: Optional[bool] = None


class NovaSenha(BaseModel):
    nova_senha: str = Field(..., min_length=6, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    usuario: UsuarioResponse
