from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import models, schemas
from database import engine, get_db
from datetime import datetime

# Cria as tabelas no banco de dados do Kanvira
models.Base.metadata.create_all(bind=engine)

# Swagger agora com a marca Kanvira
app = FastAPI(
    title="Kanvira API",
    description="Motor de gestão de tickets e bolões do Kanvira",
    version="1.0.0"
)

# Configuração do CORS para permitir que o front-end converse com a API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Em produção, colocaríamos a URL exata do seu front-end
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# ... (resto do código)

def gerar_issue_key(db: Session, prefixo: str = "KAN") -> str:
    """Gerar a chave sequencial estilo Kanvira (ex: KAN-1, KAN-2)"""
    ultimo_ticket = db.query(models.BolaoIssue).order_by(models.BolaoIssue.id.desc()).first()
    proximo_id = ultimo_ticket.id + 1 if ultimo_ticket else 1
    return f"{prefixo}-{proximo_id}"

@app.post("/api/v1/tickets/bolao", response_model=schemas.BolaoResponse, status_code=status.HTTP_201_CREATED)
def criar_ticket_bolao(bolao: schemas.BolaoCreate, db: Session = Depends(get_db)):
    nova_issue_key = gerar_issue_key(db, prefixo="KAN")
    
    novo_ticket = models.BolaoIssue(
        issue_key=nova_issue_key,
        time_a=bolao.time_a,
        time_b=bolao.time_b,
        data_encerramento=bolao.data_encerramento,
        status="TO DO"  
    )
    
    try:
        db.add(novo_ticket)
        db.commit()
        db.refresh(novo_ticket)
        return novo_ticket
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Erro interno ao salvar o ticket no Kanvira.")

@app.post("/api/v1/tickets/{issue_key}/apostas", response_model=schemas.ApostaResponse, status_code=status.HTTP_201_CREATED)
def registrar_aposta(issue_key: str, aposta: schemas.ApostaCreate, db: Session = Depends(get_db)):
    # 1. Verifica se o ticket (ex: KAN-1) existe no banco
    bolao = db.query(models.BolaoIssue).filter(models.BolaoIssue.issue_key == issue_key).first()
    
    if not bolao:
        raise HTTPException(status_code=404, detail="Card de bolão não encontrado no Kanvira.")
    
    # 2. Regra de Negócio: Bloqueia apostas após o horário do jogo
    if bolao.data_encerramento <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="Este bolão já está encerrado para novos palpites.")

    # 3. Salva o palpite vinculado ao ID do bolão
    nova_aposta = models.Aposta(
        nome_usuario=aposta.nome_usuario,
        gols_time_a=aposta.gols_time_a,
        gols_time_b=aposta.gols_time_b,
        bolao_id=bolao.id
    )
    
    try:
        db.add(nova_aposta)
        db.commit()
        db.refresh(nova_aposta)
        return nova_aposta
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Erro interno ao registrar aposta.")