"""Autenticação do Kanvira usando só a biblioteca padrão do Python.

- Senhas: PBKDF2-SHA256 com salt aleatório (nunca guardamos a senha em texto).
- Tokens: "id_usuario.expiracao.assinatura", assinados com HMAC-SHA256.
"""
import base64
import hashlib
import hmac
import os
import secrets
import time

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

import models
from database import get_db

# Em produção, defina KANVIRA_SECRET no ambiente. Sem ela, uma chave aleatória
# é gerada a cada reinício do servidor (e todos precisam logar de novo).
SECRET_KEY = os.environ.get("KANVIRA_SECRET") or secrets.token_hex(32)
TOKEN_VALIDADE_SEGUNDOS = 60 * 60 * 24 * 7  # 7 dias
PBKDF2_ITERACOES = 200_000

bearer = HTTPBearer(auto_error=False)


def gerar_hash_senha(senha: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", senha.encode(), salt, PBKDF2_ITERACOES)
    return f"pbkdf2_sha256${PBKDF2_ITERACOES}${salt.hex()}${dk.hex()}"


def verificar_senha(senha: str, senha_hash: str) -> bool:
    try:
        _, iteracoes, salt_hex, dk_hex = senha_hash.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", senha.encode(), bytes.fromhex(salt_hex), int(iteracoes))
        return hmac.compare_digest(dk.hex(), dk_hex)
    except (ValueError, TypeError):
        return False


def _assinar(payload: str) -> str:
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=")


def criar_token(usuario_id: int) -> str:
    payload = f"{usuario_id}.{int(time.time()) + TOKEN_VALIDADE_SEGUNDOS}"
    return f"{payload}.{_assinar(payload)}"


def ler_token(token: str) -> int | None:
    try:
        usuario_id, exp, sig = token.split(".")
    except ValueError:
        return None
    if not hmac.compare_digest(sig, _assinar(f"{usuario_id}.{exp}")):
        return None
    if int(exp) < time.time():
        return None
    return int(usuario_id)


def usuario_atual(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> models.Usuario:
    erro = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sessão inválida ou expirada. Faça login novamente.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if cred is None:
        raise erro
    usuario_id = ler_token(cred.credentials)
    if usuario_id is None:
        raise erro
    usuario = db.get(models.Usuario, usuario_id)
    if usuario is None or usuario.ativo is False:
        raise erro
    return usuario


def admin_atual(usuario: models.Usuario = Depends(usuario_atual)) -> models.Usuario:
    if not usuario.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Área só para o administrador.")
    return usuario
