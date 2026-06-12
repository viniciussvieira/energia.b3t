from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Nova identidade do banco de dados do Kanvira
SQLALCHEMY_DATABASE_URL = "sqlite:///./kanvira.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()