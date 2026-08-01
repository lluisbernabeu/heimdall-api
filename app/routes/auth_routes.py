# Heimdall API — rutas auth y perfil
import re
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from ..db import get_db, SessionLocal
from ..models import User, LfmProfile, SyncState
from ..deps import get_current_user
from ..services.auth import create_token, hash_password, verify_password
from ..services.sync_service import SyncService, SyncError

router = APIRouter(prefix="/api")


class RegisterIn(BaseModel):
    email: EmailStr
    password: str


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class LinkLfmIn(BaseModel):
    lfm_user_id: int


class LinkLfmUrlIn(BaseModel):
    url: str


def _extract_user_id(url: str) -> int:
    m = re.search(r"/profile/(\d+)", url)
    if m:
        return int(m.group(1))
    m2 = re.search(r"(\d{4,})", url)
    if m2:
        return int(m2.group(1))
    raise HTTPException(status_code=400, detail="No se pudo extraer el ID de usuario de la URL")


@router.post("/auth/register")
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter_by(email=body.email.lower()).first():
        raise HTTPException(status_code=409, detail="El email ya está registrado")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 6 caracteres")
    user = User(email=body.email.lower(), password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"token": create_token(user.id, user.email), "email": user.email}


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=body.email.lower()).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email o contraseña incorrectos")
    return {"token": create_token(user.id, user.email), "email": user.email}


@router.post("/auth/verify")
def verify(user: User = Depends(get_current_user)):
    return {"email": user.email, "id": user.id}


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profiles = db.query(LfmProfile).filter_by(user_id=user.id).all()
    return {
        "email": user.email,
        "profiles": [
            {
                "id": p.id,
                "lfm_user_id": p.lfm_user_id,
                "username": p.username,
                "vorname": p.vorname,
                "nachname": p.nachname,
                "origin": p.origin,
                "avatar": p.avatar,
                "license": p.license,
                "safety_rating": p.safety_rating,
                "division": p.division,
                "team_name": p.team_name,
                "team_logo": p.team_logo,
            }
            for p in profiles
        ],
    }


@router.post("/profile/link")
def link_lfm(body: LinkLfmIn, user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    existing = (db.query(LfmProfile)
                .filter_by(user_id=user.id, lfm_user_id=body.lfm_user_id).first())
    if existing:
        return {"id": existing.id, "already": True}
    profile = LfmProfile(user_id=user.id, lfm_user_id=body.lfm_user_id)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return {"id": profile.id, "already": False}


@router.post("/profile/link-url")
def link_lfm_url(body: LinkLfmUrlIn, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    uid = _extract_user_id(body.url)
    existing = (db.query(LfmProfile)
                .filter_by(user_id=user.id, lfm_user_id=uid).first())
    if existing:
        return {"id": existing.id, "already": True, "lfm_user_id": uid}
    profile = LfmProfile(user_id=user.id, lfm_user_id=uid)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return {"id": profile.id, "already": False, "lfm_user_id": uid}


def _run_sync_in_background(profile_id: int):
    """Ejecuta la sync con su propia sesión BD (thread de background)."""
    db = SessionLocal()
    try:
        profile = db.query(LfmProfile).filter_by(id=profile_id).first()
        if not profile:
            return
        svc = SyncService(db)
        try:
            svc.start_sync(profile)
        except SyncError as e:
            # ya registrado en el estado
            pass
        except Exception:
            pass
    finally:
        db.close()


@router.post("/profile/{profile_id}/sync")
def start_sync(profile_id: int, background: BackgroundTasks,
               user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    profile = db.query(LfmProfile).filter_by(id=profile_id, user_id=user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    svc = SyncService(db)
    st = svc.get_status(profile.id)
    if st["status"] == "running":
        raise HTTPException(status_code=409, detail="Ya hay una sincronización en curso")
    # Marcar como running antes de lanzar el background (para evitar doble sync)
    state = db.query(SyncState).filter_by(profile_id=profile.id).first()
    if state is None:
        state = SyncState(profile_id=profile.id)
        db.add(state)
    state.status = "running"
    db.commit()
    background.add_task(_run_sync_in_background, profile.id)
    return {"started": True, "status": "running"}


@router.get("/profile/{profile_id}/sync/status")
def sync_status(profile_id: int, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    profile = db.query(LfmProfile).filter_by(id=profile_id, user_id=user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    svc = SyncService(db)
    return svc.get_status(profile.id)
