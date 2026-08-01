# Heimdall API — rutas de KPIs
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import LfmProfile, Race
from ..deps import get_current_user
from ..services import kpis

router = APIRouter(prefix="/api")


def _get_profile(profile_id: int, user, db: Session) -> LfmProfile:
    p = db.query(LfmProfile).filter_by(id=profile_id, user_id=user.id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    return p


@router.get("/profile/{profile_id}/overview")
def overview(profile_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _get_profile(profile_id, user, db)
    data = kpis.overview(db, profile_id)
    if not data:
        raise HTTPException(status_code=404, detail="Sin datos")
    return data


@router.get("/profile/{profile_id}/progression")
def progression(profile_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _get_profile(profile_id, user, db)
    return kpis.progression(db, profile_id)


@router.get("/profile/{profile_id}/races")
def races_list(profile_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _get_profile(profile_id, user, db)
    rows = (db.query(Race).filter_by(profile_id=profile_id)
            .order_by(Race.race_date.desc()).all())
    return [
        {
            "id": r.id,
            "lfm_race_id": r.lfm_race_id,
            "event_name": r.event_name,
            "track_name": r.track_name,
            "race_date": r.race_date.isoformat() if r.race_date else None,
            "finish_pos": r.finish_pos,
            "start_pos": r.start_pos,
            "split": r.split,
            "sof": r.sof,
            "rating_change": r.rating_change,
            "sr_change": r.sr_change,
            "points": r.points,
            "incidents": r.incidents,
            "best_lap": r.best_lap,
            "best_of_week": r.best_of_week,
            "car_name": r.car_name,
        }
        for r in rows
    ]


@router.get("/profile/{profile_id}/races/{race_pk}")
def race_detail(profile_id: int, race_pk: int, user=Depends(get_current_user),
                db: Session = Depends(get_db)):
    _get_profile(profile_id, user, db)
    data = kpis.race_detail(db, profile_id, race_pk)
    if not data:
        raise HTTPException(status_code=404, detail="Carrera no encontrada")
    return data


@router.get("/profile/{profile_id}/sectors")
def sectors(profile_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _get_profile(profile_id, user, db)
    return kpis.sectors_analysis(db, profile_id)


@router.get("/profile/{profile_id}/consistency")
def consistency(profile_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _get_profile(profile_id, user, db)
    return kpis.consistency_analysis(db, profile_id)


@router.get("/profile/{profile_id}/incidents")
def incidents(profile_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _get_profile(profile_id, user, db)
    return kpis.incidents_heatmap(db, profile_id)


@router.get("/profile/{profile_id}/standings")
def standings(profile_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _get_profile(profile_id, user, db)
    return kpis.standings_view(db, profile_id)


@router.get("/profile/{profile_id}/compare/{other_id}")
def compare(profile_id: int, other_id: int, user=Depends(get_current_user),
            db: Session = Depends(get_db)):
    _get_profile(profile_id, user, db)
    other = db.query(LfmProfile).filter_by(id=other_id).first()
    if not other:
        raise HTTPException(status_code=404, detail="Perfil comparado no encontrado")
    # Se permite comparar contra cualquier perfil del sistema (tú u otros pilotos)
    return kpis.compare(db, profile_id, other_id)


@router.get("/profiles")
def list_profiles(user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Lista perfiles con datos suficientes para comparar (todo el sistema)."""
    rows = (db.query(LfmProfile)
            .filter(LfmProfile.username.isnot(None))
            .order_by(LfmProfile.username)
            .all())
    return [
        {
            "id": p.id,
            "lfm_user_id": p.lfm_user_id,
            "username": p.username,
            "vorname": p.vorname,
            "nachname": p.nachname,
            "avatar": p.avatar,
            "license": p.license,
            "safety_rating": p.safety_rating,
            "team_name": p.team_name,
            "races": db.query(Race).filter_by(profile_id=p.id).count(),
        }
        for p in rows
    ]
