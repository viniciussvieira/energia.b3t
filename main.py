import math
from datetime import datetime
from typing import List

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import case, func, inspect, text
from sqlalchemy.orm import Session

import models, schemas
from auth import admin_atual, criar_token, gerar_hash_senha, usuario_atual, verificar_senha
from database import engine, get_db
from times import buscar_times, pre_carregar_times

# Cria as tabelas no banco de dados do Kanvira
models.Base.metadata.create_all(bind=engine)


def migrar_banco():
    """create_all não altera tabelas que já existem. Aqui adicionamos as colunas
    novas de 'apostas' num kanvira.db criado antes do login/Jussana Coins."""
    colunas = {c["name"] for c in inspect(engine).get_columns("apostas")}
    colunas_bolao = {c["name"] for c in inspect(engine).get_columns("bolao_issues")}
    colunas_usuario = {c["name"] for c in inspect(engine).get_columns("usuarios")}
    with engine.begin() as conn:
        if "ativo" not in colunas_usuario:
            verdadeiro = "1" if engine.dialect.name == "sqlite" else "TRUE"
            conn.execute(text(f"ALTER TABLE usuarios ADD COLUMN ativo BOOLEAN DEFAULT {verdadeiro}"))
        for coluna in ("escudo_a", "escudo_b"):
            if coluna not in colunas_bolao:
                conn.execute(text(f"ALTER TABLE bolao_issues ADD COLUMN {coluna} VARCHAR"))
        for coluna in ("odd_casa", "odd_empate", "odd_fora", "odd_placar"):
            if coluna not in colunas_bolao:
                conn.execute(text(f"ALTER TABLE bolao_issues ADD COLUMN {coluna} FLOAT"))
        for coluna in ("odd_resultado", "odd_placar"):
            if coluna not in colunas:
                conn.execute(text(f"ALTER TABLE apostas ADD COLUMN {coluna} FLOAT"))
        # Resultado do jogo e prêmio de cada palpite
        for coluna, tipo in (("gols_final_a", "INTEGER"), ("gols_final_b", "INTEGER"), ("encerrado_em", "TIMESTAMP")):
            if coluna not in colunas_bolao:
                conn.execute(text(f"ALTER TABLE bolao_issues ADD COLUMN {coluna} {tipo}"))
        for coluna, tipo in (("premio", "INTEGER"), ("situacao", "VARCHAR")):
            if coluna not in colunas:
                conn.execute(text(f"ALTER TABLE apostas ADD COLUMN {coluna} {tipo}"))
        if "valor" not in colunas:
            conn.execute(text("ALTER TABLE apostas ADD COLUMN valor INTEGER DEFAULT 0"))
        if "usuario_id" not in colunas:
            conn.execute(text("ALTER TABLE apostas ADD COLUMN usuario_id INTEGER REFERENCES usuarios(id)"))
        # Antes era 1 palpite por bolão; agora pode vários. Remove a trava antiga do banco.
        if engine.dialect.name == "postgresql":
            conn.execute(text("ALTER TABLE apostas DROP CONSTRAINT IF EXISTS uq_aposta_usuario_bolao"))
        conn.execute(text("DROP INDEX IF EXISTS uq_aposta_usuario_bolao"))


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
    if usuario.ativo is False:
        raise HTTPException(status_code=403, detail="Sua conta está bloqueada. Fale com o administrador.")
    return {"access_token": criar_token(usuario.id), "usuario": usuario}


# --- Gestão de contas (só admin) ---
def _conta_ou_404(db: Session, usuario_id: int) -> models.Usuario:
    conta = db.get(models.Usuario, usuario_id)
    if not conta:
        raise HTTPException(status_code=404, detail="Conta não encontrada.")
    return conta


def _conta_admin(db: Session, conta: models.Usuario) -> dict:
    total, apostado = (
        db.query(func.count(models.Aposta.id), func.coalesce(func.sum(models.Aposta.valor), 0))
        .filter(models.Aposta.usuario_id == conta.id)
        .one()
    )
    return {
        "id": conta.id, "username": conta.username, "saldo": conta.saldo,
        "is_admin": bool(conta.is_admin), "ativo": conta.ativo is not False,
        "criado_em": conta.criado_em, "total_apostas": total, "total_apostado": apostado,
    }


@app.get("/api/v1/admin/usuarios", response_model=List[schemas.ContaAdmin])
def listar_contas(db: Session = Depends(get_db), admin: models.Usuario = Depends(admin_atual)):
    contas = db.query(models.Usuario).order_by(models.Usuario.username).all()
    return [_conta_admin(db, c) for c in contas]


@app.post("/api/v1/admin/usuarios/{usuario_id}/saldo", response_model=schemas.ContaAdmin)
def ajustar_saldo(
    usuario_id: int,
    ajuste: schemas.AjusteSaldo,
    db: Session = Depends(get_db),
    admin: models.Usuario = Depends(admin_atual),
):
    conta = _conta_ou_404(db, usuario_id)
    # Um único UPDATE: soma o ajuste só se o saldo não ficar negativo
    alterou = db.execute(
        text("UPDATE usuarios SET saldo = saldo + :v WHERE id = :id AND saldo + :v >= 0"),
        {"v": ajuste.valor, "id": conta.id},
    ).rowcount
    if not alterou:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"O saldo não pode ficar negativo. Saldo atual: {conta.saldo} JC.")
    db.commit()
    db.refresh(conta)
    return _conta_admin(db, conta)


@app.patch("/api/v1/admin/usuarios/{usuario_id}", response_model=schemas.ContaAdmin)
def alterar_conta(
    usuario_id: int,
    dados: schemas.AlteracaoConta,
    db: Session = Depends(get_db),
    admin: models.Usuario = Depends(admin_atual),
):
    conta = _conta_ou_404(db, usuario_id)
    if conta.id == admin.id and (dados.is_admin is False or dados.ativo is False):
        raise HTTPException(status_code=400, detail="Você não pode bloquear nem tirar o admin da sua própria conta.")
    if dados.is_admin is not None:
        conta.is_admin = dados.is_admin
    if dados.ativo is not None:
        conta.ativo = dados.ativo
    db.commit()
    db.refresh(conta)
    return _conta_admin(db, conta)


@app.post("/api/v1/admin/usuarios/{usuario_id}/senha", status_code=status.HTTP_204_NO_CONTENT)
def redefinir_senha(
    usuario_id: int,
    dados: schemas.NovaSenha,
    db: Session = Depends(get_db),
    admin: models.Usuario = Depends(admin_atual),
):
    conta = _conta_ou_404(db, usuario_id)
    conta.senha_hash = gerar_hash_senha(dados.nova_senha)
    db.commit()


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
        odd_casa=bolao.odd_casa,
        odd_empate=bolao.odd_empate,
        odd_fora=bolao.odd_fora,
        odd_placar=bolao.odd_placar,
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


def odd_do_resultado(bolao: models.BolaoIssue, gols_a: int, gols_b: int) -> float:
    """ODD do resultado que o palpite indica: vitória do mandante, empate ou vitória do visitante."""
    if gols_a > gols_b:
        return bolao.odd_casa
    if gols_a < gols_b:
        return bolao.odd_fora
    return bolao.odd_empate


@app.put("/api/v1/tickets/{issue_key}", response_model=schemas.BolaoResponse)
def editar_bolao(
    issue_key: str,
    dados: schemas.BolaoEdicao,
    db: Session = Depends(get_db),
    admin: models.Usuario = Depends(admin_atual),
):
    """Admin altera nomes, escudos e ODDs de um bolão já criado.
    ODDs novas valem só para palpites novos: os já feitos mantêm a ODD da hora da aposta."""
    bolao = db.query(models.BolaoIssue).filter(models.BolaoIssue.issue_key == issue_key.upper()).first()
    if not bolao:
        raise HTTPException(status_code=404, detail="Card de bolão não encontrado.")

    for campo, valor in dados.model_dump().items():
        setattr(bolao, campo, valor)
    db.commit()
    db.refresh(bolao)
    return bolao


@app.get("/api/v1/apostas/minhas", response_model=List[schemas.MeuPalpite])
def meus_palpites(db: Session = Depends(get_db), usuario: models.Usuario = Depends(usuario_atual)):
    """Todos os palpites do usuário logado, do mais recente para o mais antigo."""
    agora = datetime.utcnow()
    linhas = (
        db.query(models.Aposta, models.BolaoIssue)
        .join(models.BolaoIssue, models.Aposta.bolao_id == models.BolaoIssue.id)
        .filter(models.Aposta.usuario_id == usuario.id)
        .order_by(models.Aposta.criado_em.desc(), models.Aposta.id.desc())
        .all()
    )
    return [{
        "id": a.id,
        "issue_key": b.issue_key,
        "time_a": b.time_a,
        "time_b": b.time_b,
        "escudo_a": b.escudo_a,
        "escudo_b": b.escudo_b,
        "data_encerramento": b.data_encerramento,
        "aberto": b.data_encerramento > agora and b.encerrado_em is None,
        "gols_time_a": a.gols_time_a,
        "gols_time_b": a.gols_time_b,
        "valor": a.valor or 0,
        "odd_resultado": a.odd_resultado,
        "odd_placar": a.odd_placar,
        "criado_em": a.criado_em,
        "gols_final_a": b.gols_final_a,
        "gols_final_b": b.gols_final_b,
        "premio": a.premio,
        "situacao": a.situacao,
    } for a, b in linhas]


# --- Resultado do jogo e pagamento (só admin) ---
def multiplicar(valor: int, odd: float) -> int:
    """valor × ODD arredondado para baixo, sem o erro de casas decimais (100 × 2.3 = 230, não 229)."""
    return int(math.floor(round(valor * odd, 6)))


def _sinal(gols_a: int, gols_b: int) -> int:
    """1 = vitória do mandante, 0 = empate, -1 = vitória do visitante."""
    return (gols_a > gols_b) - (gols_a < gols_b)


def calcular_premio(aposta: models.Aposta, gols_a: int, gols_b: int) -> tuple[int, str]:
    """Quanto o palpite recebe, usando as ODDs travadas na hora da aposta."""
    valor = aposta.valor or 0
    if aposta.odd_placar is None or aposta.odd_resultado is None:
        # Palpite antigo, de antes das ODDs: devolve o que foi apostado
        return valor, "devolvido"
    if aposta.gols_time_a == gols_a and aposta.gols_time_b == gols_b:
        return multiplicar(valor, aposta.odd_placar), "placar"
    if _sinal(aposta.gols_time_a, aposta.gols_time_b) == _sinal(gols_a, gols_b):
        return multiplicar(valor, aposta.odd_resultado), "resultado"
    return 0, "perdeu"


def _bolao_admin(db: Session, b: models.BolaoIssue) -> dict:
    total, apostado, pago, vencedores = (
        db.query(
            func.count(models.Aposta.id),
            func.coalesce(func.sum(models.Aposta.valor), 0),
            func.coalesce(func.sum(models.Aposta.premio), 0),
            func.coalesce(func.sum(case((models.Aposta.situacao.in_(("placar", "resultado")), 1), else_=0)), 0),
        )
        .filter(models.Aposta.bolao_id == b.id)
        .one()
    )
    return {
        "issue_key": b.issue_key, "time_a": b.time_a, "time_b": b.time_b,
        "escudo_a": b.escudo_a, "escudo_b": b.escudo_b,
        "data_encerramento": b.data_encerramento,
        "gols_final_a": b.gols_final_a, "gols_final_b": b.gols_final_b, "encerrado_em": b.encerrado_em,
        "total_apostas": total, "total_apostado": apostado, "total_pago": pago, "vencedores": vencedores,
    }


@app.get("/api/v1/admin/resultados", response_model=schemas.PainelResultados)
def painel_resultados(db: Session = Depends(get_db), admin: models.Usuario = Depends(admin_atual)):
    """Bolões que já fecharam e esperam o placar, e os últimos já pagos."""
    agora = datetime.utcnow()
    pendentes = (
        db.query(models.BolaoIssue)
        .filter(models.BolaoIssue.encerrado_em.is_(None), models.BolaoIssue.data_encerramento <= agora)
        .order_by(models.BolaoIssue.data_encerramento)
        .all()
    )
    encerrados = (
        db.query(models.BolaoIssue)
        .filter(models.BolaoIssue.encerrado_em.isnot(None))
        .order_by(models.BolaoIssue.encerrado_em.desc())
        .limit(20)
        .all()
    )
    return {
        "pendentes": [_bolao_admin(db, b) for b in pendentes],
        "encerrados": [_bolao_admin(db, b) for b in encerrados],
    }


@app.post("/api/v1/tickets/{issue_key}/resultado", response_model=schemas.BolaoAdmin)
def lancar_resultado(
    issue_key: str,
    resultado: schemas.ResultadoJogo,
    db: Session = Depends(get_db),
    admin: models.Usuario = Depends(admin_atual),
):
    """Admin informa o placar real: cada palpite é calculado e o prêmio vai para o saldo."""
    bolao = db.query(models.BolaoIssue).filter(models.BolaoIssue.issue_key == issue_key.upper()).first()
    if not bolao:
        raise HTTPException(status_code=404, detail="Card de bolão não encontrado.")
    if bolao.encerrado_em is not None:
        raise HTTPException(status_code=409, detail="Este bolão já foi encerrado e pago.")
    if bolao.data_encerramento > datetime.utcnow():
        raise HTTPException(status_code=400, detail="Este bolão ainda está aceitando palpites. Espere o horário de fechamento.")

    ga, gb = resultado.gols_time_a, resultado.gols_time_b
    try:
        # Tudo numa transação só: ou paga todo mundo, ou ninguém.
        # Primeiro "trava" o bolão: se dois cliques chegarem juntos, só um passa daqui.
        travou = db.execute(
            text("UPDATE bolao_issues SET encerrado_em = :agora WHERE id = :id AND encerrado_em IS NULL"),
            {"agora": datetime.utcnow(), "id": bolao.id},
        ).rowcount
        if not travou:
            db.rollback()
            raise HTTPException(status_code=409, detail="Este bolão já foi encerrado e pago.")

        apostas = db.query(models.Aposta).filter(models.Aposta.bolao_id == bolao.id).all()
        for aposta in apostas:
            premio, situacao = calcular_premio(aposta, ga, gb)
            aposta.premio = premio
            aposta.situacao = situacao
            if premio > 0 and aposta.usuario_id is not None:
                db.execute(
                    text("UPDATE usuarios SET saldo = saldo + :premio WHERE id = :id"),
                    {"premio": premio, "id": aposta.usuario_id},
                )
        bolao.gols_final_a = ga
        bolao.gols_final_b = gb
        bolao.status = "DONE"
        db.commit()
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Erro ao lançar o resultado. Nada foi pago; tente de novo.")

    db.refresh(bolao)
    return _bolao_admin(db, bolao)


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
        .filter(models.BolaoIssue.encerrado_em.is_(None))
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
        minhas = (
            db.query(models.Aposta)
            .filter(models.Aposta.bolao_id == b.id, models.Aposta.usuario_id == usuario.id)
            .order_by(models.Aposta.criado_em)
            .all()
        )
        resultado.append({
            "issue_key": b.issue_key,
            "time_a": b.time_a,
            "time_b": b.time_b,
            "escudo_a": b.escudo_a,
            "escudo_b": b.escudo_b,
            "odd_casa": b.odd_casa,
            "odd_empate": b.odd_empate,
            "odd_fora": b.odd_fora,
            "odd_placar": b.odd_placar,
            "data_encerramento": b.data_encerramento,
            "total_apostas": total if usuario.is_admin else None,  # só o admin vê
            "pote": pote if usuario.is_admin else None,  # só o admin vê o pote
            "minhas_apostas": [{
                "gols_time_a": m.gols_time_a,
                "gols_time_b": m.gols_time_b,
                "valor": m.valor or 0,
                "odd_resultado": m.odd_resultado,
                "odd_placar": m.odd_placar,
            } for m in minhas],
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
    if bolao.encerrado_em is not None or bolao.data_encerramento <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="Este bolão já está encerrado para novos palpites.")

    # 2b. Sem ODD definida não dá para saber quanto pagar
    if None in (bolao.odd_casa, bolao.odd_empate, bolao.odd_fora, bolao.odd_placar):
        raise HTTPException(status_code=400, detail="Este bolão ainda não tem ODDs definidas pelo admin.")

    # 3. Pode fazer quantos palpites quiser até o fechamento (cada um desconta do saldo)

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
            odd_resultado=odd_do_resultado(bolao, aposta.gols_time_a, aposta.gols_time_b),
            odd_placar=bolao.odd_placar,
            bolao_id=bolao.id,
            usuario_id=usuario.id,
        )
        db.add(nova_aposta)
        db.commit()
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Erro interno ao registrar aposta.")

    db.refresh(nova_aposta)
    db.refresh(usuario)
    return {**schemas.ApostaResponse.model_validate(nova_aposta).model_dump(), "saldo_atual": usuario.saldo}
