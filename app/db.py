# Heimdall API — sesión BD
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .config import DB_URL

engine = create_engine(DB_URL, pool_size=10, max_overflow=20, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from . import models  # noqa
    models.Base.metadata.create_all(bind=engine)
