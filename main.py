from datetime import datetime
from typing import List

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models, schemas
from auth import criar_token, gerar_hash_senha, usuario_atual, verificar_senha
from database import engine, get_db
from times import buscar_times, pre_carregar_times

# Cria as tabelas no banco de dados do Kanvira
models.Base.metadata.create_all(bind=engine)


def migrar_banco():
    """create_all não altera tabelas que já existem. Aqui adicionamos as colunas
    novas de 'apostas' num kanvira.db criado antes do login/Jussana Coins."""
    colunas = {c["name"] for c in inspect(engine).get_columns("apostas")}
    colunas_bolao = {c["name"] for c in inspect(engine).get_columns("bolao_issues")}
    with engine.begin() as conn:
        for coluna in ("escudo_a", "escudo_b"):
            if coluna not in colunas_bolao:
                conn.execute(text(f"ALTER TABLE bolao_issues ADD COLUMN {coluna} VARCHAR"))
        if "valor" not in colunas:
            conn.execute(text("ALTER TABLE apostas ADD COLUMN valor INTEGER DEFAULT 0"))
        if "usuario_id" not in colunas:
            conn.execute(text("ALTER TABLE apostas ADD COLUMN usuario_id INTEGER REFERENCES usuarios(id)"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_aposta_usuario_bolao ON apostas (bolao_id, usuario_id)"
        ))


migrar_banco()
pre_carregar_times()  # baixa a lista de times da ESPN em segundo plano

# Swagger agora com a marca Kanvira
app = FastAPI(
    title="Kanvira API",
    description="Motor de gestão de tickets e bolões do Kanvira",
    version="1.1.0"
)

# Configuração do CORS para permitir que o front-end converse com a API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Em produção, colocaríamos a URL exata do seu front-end
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SALDO_INICIAL_JC = 1000  # Jussana Coins de boas-vindas


# --- Autenticação ---
@app.post("/api/v1/auth/cadastro", response_model=schemas.TokenResponse, status_code=status.HTTP_201_CREATED)
def cadastrar_usuario(dados: schemas.UsuarioCadastro, db: Session = Depends(get_db)):
    username = dados.username.strip().lower()
    if db.query(models.Usuario).filter(models.Usuario.username == username).first():
        raise HTTPException(status_code=409, detail="Esse nome de usuário já está em uso.")

    # O primeiro usuário cadastrado vira administrador (quem cria os cards)
    primeiro = db.query(models.Usuario).first() is None

    usuario = models.Usuario(
        username=username,
        senha_hash=gerar_hash_senha(dados.senha),
        saldo=SALDO_INICIAL_JC,
        is_admin=primeiro,
    )
    try:
        db.add(usuario)
        db.commit()
        db.refresh(usuario)
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Erro interno ao criar a conta.")

    return {"access_token": criar_token(usuario.id), "usuario": usuario}


@app.post("/api/v1/auth/login", response_model=schemas.TokenResponse)
def login(dados: schemas.UsuarioLogin, db: Session = Depends(get_db)):
    usuario = db.query(models.Usuario).filter(models.Usuario.username == dados.username.strip().lower()).first()
    if not usuario or not verificar_senha(dados.senha, usuario.senha_hash):
        raise HTTPException(status_code=401, detail="Usuário ou senha incorretos.")
    return {"access_token": criar_token(usuario.id), "usuario": usuario}


@app.get("/api/v1/auth/me", response_model=schemas.UsuarioResponse)
def meu_perfil(usuario: models.Usuario = Depends(usuario_atual)):
    return usuario


# --- Bolões ---
def gerar_issue_key(db: Session, prefixo: str = "KAN") -> str:
    """Gerar a chave sequencial estilo Kanvira (ex: KAN-1, KAN-2)"""
    ultimo_ticket = db.query(models.BolaoIssue).order_by(models.BolaoIssue.id.desc()).first()
    proximo_id = ultimo_ticket.id + 1 if ultimo_ticket else 1
    return f"{prefixo}-{proximo_id}"


@app.post("/api/v1/tickets/bolao", response_model=schemas.BolaoResponse, status_code=status.HTTP_201_CREATED)
def criar_ticket_bolao(
    bolao: schemas.BolaoCreate,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(usuario_atual),
):
    if not usuario.is_admin:
        raise HTTPException(status_code=403, detail="Só o administrador pode criar cards de bolão.")

    nova_issue_key = gerar_issue_key(db, prefixo="KAN")

    novo_ticket = models.BolaoIssue(
        issue_key=nova_issue_key,
        time_a=bolao.time_a,
        time_b=bolao.time_b,
        escudo_a=bolao.escudo_a,
        escudo_b=bolao.escudo_b,
        data_encerramento=bolao.data_encerramento,
        status="TO DO"
    )

    try:
        db.add(novo_ticket)
        db.commit()
        db.refresh(novo_ticket)
        return novo_ticket
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Erro interno ao salvar o ticket no Kanvira.")


@app.get("/api/v1/times/busca", response_model=List[schemas.TimeEncontrado])
def buscar_time(q: str, usuario: models.Usuario = Depends(usuario_atual)):
    """Busca times pelo nome (ex: ?q=fla) e devolve o escudo de cada um."""
    return buscar_times(q)


@app.get("/api/v1/tickets/abertos", response_model=List[schemas.BolaoAberto])
def listar_boloes_abertos(
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(usuario_atual),
):
    """Bolões que ainda aceitam palpites, do que fecha primeiro para o último."""
    boloes = (
        db.query(models.BolaoIssue)
        .filter(models.BolaoIssue.data_encerramento > datetime.utcnow())
        .order_by(models.BolaoIssue.data_encerramento)
        .all()
    )

    resultado = []
    for b in boloes:
        total, pote = (
            db.query(func.count(models.Aposta.id), func.coalesce(func.sum(models.Aposta.valor), 0))
            .filter(models.Aposta.bolao_id == b.id)
            .one()
        )
        minha = (
            db.query(models.Aposta)
            .filter(models.Aposta.bolao_id == b.id, models.Aposta.usuario_id == usuario.id)
            .first()
        )
        resultado.append({
            "issue_key": b.issue_key,
            "time_a": b.time_a,
            "time_b": b.time_b,
            "escudo_a": b.escudo_a,
            "escudo_b": b.escudo_b,
            "data_encerramento": b.data_encerramento,
            "total_apostas": total,
            "pote": pote,
            "minha_aposta": minha and {
                "gols_time_a": minha.gols_time_a,
                "gols_time_b": minha.gols_time_b,
                "valor": minha.valor or 0,
            },
        })
    return resultado


@app.post("/api/v1/tickets/{issue_key}/apostas", response_model=schemas.ApostaRegistrada, status_code=status.HTTP_201_CREATED)
def registrar_aposta(
    issue_key: str,
    aposta: schemas.ApostaCreate,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(usuario_atual),
):
    # 1. Verifica se o ticket (ex: KAN-1) existe no banco
    bolao = db.query(models.BolaoIssue).filter(models.BolaoIssue.issue_key == issue_key.upper()).first()

    if not bolao:
        raise HTTPException(status_code=404, detail="Card de bolão não encontrado no Kanvira.")

    # 2. Regra de Negócio: Bloqueia apostas após o horário do jogo
    if bolao.data_encerramento <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="Este bolão já está encerrado para novos palpites.")

    # 3. Um palpite por pessoa em cada bolão
    ja_apostou = (
        db.query(models.Aposta)
        .filter(models.Aposta.bolao_id == bolao.id, models.Aposta.usuario_id == usuario.id)
        .first()
    )
    if ja_apostou:
        raise HTTPException(status_code=409, detail="Você já fez seu palpite neste bolão.")

    try:
        # 4. Desconta as Jussana Coins só se houver saldo (em um único UPDATE,
        #    para dois cliques rápidos não gastarem mais do que o saldo)
        debitou = db.execute(
            text("UPDATE usuarios SET saldo = saldo - :valor WHERE id = :id AND saldo >= :valor"),
            {"valor": aposta.valor, "id": usuario.id},
        ).rowcount
        if not debitou:
            db.rollback()
            raise HTTPException(status_code=400, detail=f"Saldo insuficiente. Você tem {usuario.saldo} JC.")

        # 5. Salva o palpite vinculado ao bolão e ao usuário
        nova_aposta = models.Aposta(
            nome_usuario=usuario.username,
            gols_time_a=aposta.gols_time_a,
            gols_time_b=aposta.gols_time_b,
            valor=aposta.valor,
            bolao_id=bolao.id,
            usuario_id=usuario.id,
        )
        db.add(nova_aposta)
        db.commit()
    except HTTPException:
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Você já fez seu palpite neste bolão.")
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Erro interno ao registrar aposta.")

    db.refresh(nova_aposta)
    db.refresh(usuario)
    return {**schemas.ApostaResponse.model_validate(nova_aposta).model_dump(), "saldo_atual": usuario.saldo}
