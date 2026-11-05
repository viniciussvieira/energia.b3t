from pydantic import BaseModel, Field, validator
from datetime import datetime
from typing import List, Optional

# --- Schemas de Aposta ---
class ApostaCreate(BaseModel):
    nome_usuario: str = Field(..., min_length=2, max_length=50)
    gols_time_a: int = Field(..., ge=0, description="Gols não podem ser negativos")
    gols_time_b: int = Field(..., ge=0)

class ApostaResponse(ApostaCreate):
    id: int
    criado_em: datetime

    class Config:
        from_attributes = True

# --- Schemas de Bolão (Atualizados para listar as apostas atreladas) ---
class BolaoCreate(BaseModel):
    time_a: str = Field(..., min_length=2, max_length=50)
    time_b: str = Field(..., min_length=2, max_length=50)
    data_encerramento: datetime

    @validator('data_encerramento')
    def validar_data_futura(cls, v):
        if v <= datetime.utcnow():
            raise ValueError('A data de encerramento deve ser no futuro.')
        return v

class BolaoResponse(BolaoCreate):
    id: int
    issue_key: str
    status: str
    criado_em: datetime
    apostas: List[ApostaResponse] = [] # Agora o bolão retorna a lista de apostas dele!

    class Config:
        from_attributes = True

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
    criado_em: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    usuario: UsuarioResponse
