# Heimdall API — dependencias FastAPI (auth)
from fastapi import Depends, HTTPException, Header
from sqlalchemy.orm import Session

from .db import get_db
from .models import User
from .services.auth import decode_token


def get_current_user(authorization: str = Header(default=""),
                     db: Session = Depends(get_db)) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Falta token")
    payload = decode_token(authorization[7:])
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")
    user = db.query(User).filter_by(id=int(payload["sub"])).first()
    if not user:
        raise HTTPException(status_code=401, detail="Usuario no existe")
    return user
