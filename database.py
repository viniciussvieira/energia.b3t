import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# No seu PC: usa o arquivo kanvira.db (SQLite).
# Online (Render): defina DATABASE_URL com a connection string do Neon (Postgres).
SQLALCHEMY_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./kanvira.db")

# O Neon entrega "postgres://..." ou "postgresql://..."; o SQLAlchemy precisa saber o driver (psycopg 3)
for prefixo in ("postgres://", "postgresql://"):
    if SQLALCHEMY_DATABASE_URL.startswith(prefixo):
        SQLALCHEMY_DATABASE_URL = "postgresql+psycopg://" + SQLALCHEMY_DATABASE_URL[len(prefixo):]
        break

if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # pool_pre_ping: o Neon "dorme" após 5 min sem uso; isso evita erro com conexões velhas
    engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True, pool_recycle=300)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
