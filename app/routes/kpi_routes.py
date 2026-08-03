# Heimdall API — rutas de KPIs
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import LfmProfile, Race, Track, Lap
from ..deps import get_current_user
from ..services import kpis

router = APIRouter(prefix="/api")


def _get_profile(profile_id: int, user, db: Session) -> LfmProfile:
    p = db.query(LfmProfile).filter_by(id=profile_id, user_id=user.id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    return p


@router.get("/profile/{profile_id}/insight")
def insight(profile_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _get_profile(profile_id, user, db)
    return kpis.insight(db, profile_id)


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
            "position_gain": r.position_gain,
            "split": r.split,
            "sof": r.sof,
            "rating_change": r.rating_change,
            "sr_change": r.sr_change,
            "points": r.points,
            "incidents": r.incidents,
            "dnf": r.dnf,
            "dns": r.dns,
            "dsq": r.dsq,
            "best_lap": r.best_lap,
            "best_of_week": r.best_of_week,
            "car_name": r.car_name,
            "car_logo": kpis.car_logo_url(r.car_name),
        }
        for r in rows
    ]


@router.get("/profile/{profile_id}/races/{race_pk}/story")
def race_story(profile_id: int, race_pk: int, user=Depends(get_current_user),
               db: Session = Depends(get_db)):
    _get_profile(profile_id, user, db)
    data = kpis.race_story(db, profile_id, race_pk)
    if not data:
        raise HTTPException(status_code=404, detail="Carrera no encontrada")
    return data


@router.get("/profile/{profile_id}/races/{race_pk}")
def race_detail(profile_id: int, race_pk: int, user=Depends(get_current_user),
                db: Session = Depends(get_db)):
    _get_profile(profile_id, user, db)
    data = kpis.race_detail(db, profile_id, race_pk)
    if not data:
        raise HTTPException(status_code=404, detail="Carrera no encontrada")
    return data


@router.get("/profile/{profile_id}/races/{race_pk}/replay")
def race_replay(profile_id: int, race_pk: int,
                user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Replay de datos de la carrera: posición vuelta a vuelta de todos,
    vueltas con splits de pilotos clave y enlaces de VOD/stream si fue
    transmitida. Cacheado en BD (patrón Heimdall)."""
    from ..services.race_replay import race_replay as replay_svc
    _get_profile(profile_id, user, db)
    race = db.query(Race).filter_by(id=race_pk, profile_id=profile_id).first()
    if not race:
        raise HTTPException(status_code=404, detail="Carrera no encontrada")
    if not race.lfm_race_id:
        raise HTTPException(status_code=400, detail="Esta carrera no tiene ID de LFM")
    my_uid = None
    profile = db.query(LfmProfile).filter_by(id=profile_id).first()
    if profile:
        my_name = f"{profile.vorname or ''} {profile.nachname or ''}".strip().lower()
        laps = (db.query(Lap).filter_by(race_id=race.id)
                .order_by(Lap.lfm_user_id).all())
        by_user = {}
        for L in laps:
            by_user.setdefault(L.lfm_user_id, []).append(L)
        for uid, ulaps in by_user.items():
            nm = (ulaps[0].driver_name or "").lower()
            if my_name and (my_name in nm or nm in my_name):
                my_uid = uid
                break
        if my_uid is None and by_user:
            my_uid = max(by_user, key=lambda u: len(by_user[u]))
    try:
        return replay_svc(db, race.lfm_race_id, race.split or 1, my_uid)
    except Exception:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=502,
                            detail="No se pudo obtener el replay (LFM caído y sin caché)")


@router.get("/profile/{profile_id}/sectors")
def sectors(profile_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _get_profile(profile_id, user, db)
    return kpis.sectors_analysis(db, profile_id)


@router.get("/profile/{profile_id}/consistency")
def consistency(profile_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _get_profile(profile_id, user, db)
    return kpis.consistency_analysis(db, profile_id)


@router.get("/schedule/guide")
def schedule_guide(track: str, car_class: str | None = None,
                   user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Guía de un circuito del calendario: récord oficial LFM + videos de
    YouTube (track guides/hotlaps). Se llama bajo demanda al tocar un
    circuito (la búsqueda de YouTube tarda unos segundos). Los datos se
    guardan en BD y se reutilizan si la fuente falla."""
    from ..services.track_guides import track_guides
    data = track_guides(db, track, car_class)
    if not data:
        raise HTTPException(status_code=404, detail="Sin datos de guía")
    return data


@router.get("/schedule")
def schedule(profile_id: int | None = None,
             user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Calendario de todas las series de Assetto Corsa en LFM (público LFM,
    autenticado para Heimdall). Por serie: circuito activo, próximas carreras,
    clases/coches, calendario semanal completo y si el perfil puede correrla."""
    from ..services.schedule_service import schedule as build_schedule
    data = build_schedule(db=db, profile_id=profile_id)
    if not data:
        raise HTTPException(status_code=502, detail="No se pudo obtener el calendario de LFM")
    return data


@router.get("/global/status")
def global_status(user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Estado LFM en vivo: servidores ACC, usuarios online, simuladores."""
    from ..services.global_stats import lfm_status
    return lfm_status(db)


@router.get("/global/sr-percentile/{profile_id}")
def sr_percentile(profile_id: int, user=Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Percentil global del SR del usuario (¿mejor que qué % de LFM?)."""
    from ..services.global_stats import sr_distribution, percentile_of
    prof = _get_profile(profile_id, user, db)
    dist = sr_distribution(db)
    pct = percentile_of(prof.safety_rating or 0, dist)
    return {
        "sr": prof.safety_rating,
        "license": prof.license,
        "division": prof.division,
        "percentile": pct,
        "distribution": {
            "overall": (dist or {}).get("overall"),
            "average_sr": (dist or {}).get("average_sr"),
            "ranges": (dist or {}).get("ranges"),
        },
    }


@router.get("/global/incident-reasons")
def global_incident_reasons(user=Depends(get_current_user),
                            db: Session = Depends(get_db)):
    """Taxonomía oficial de incidentes LFM con penalización de SR."""
    from ..services.global_stats import incident_reasons
    return incident_reasons(db)


@router.get("/profile/{profile_id}/achievements")
def profile_achievements(profile_id: int, user=Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """Logros del piloto (guardados en BD durante el sync)."""
    prof = _get_profile(profile_id, user, db)
    return {
        "achievements": prof.achievements_json or {},
        "rating_by_sim": prof.rating_by_sim or [],
        "synced_at": prof.updated_at.isoformat() if prof.updated_at else None,
    }


@router.get("/profile/{profile_id}/standings")
def profile_standings(profile_id: int, user=Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """Eventos con clasificación disponible para el perfil."""
    _get_profile(profile_id, user, db)
    from ..services.standings_service import my_events
    return {"events": my_events(db, profile_id)}


@router.get("/profile/{profile_id}/standings/{event_id}")
def profile_standings_event(profile_id: int, event_id: int,
                            car_class: str | None = None,
                            user=Depends(get_current_user),
                            db: Session = Depends(get_db)):
    """Leaderboard de la división del usuario en un evento."""
    _get_profile(profile_id, user, db)
    from ..services.standings_service import division_standings
    data = division_standings(db, profile_id, event_id, car_class)
    if not data:
        raise HTTPException(status_code=404, detail="Sin clasificación para este evento")
    return data


@router.get("/profile/{profile_id}/circuit")
def circuit(profile_id: int, track_name: str | None = None,
            user=Depends(get_current_user), db: Session = Depends(get_db)):
    _get_profile(profile_id, user, db)
    data = kpis.circuit_analysis(db, profile_id, track_name)
    if not data:
        raise HTTPException(status_code=404, detail="Sin datos de circuito")
    return data

@router.get("/trackmap/{track_id}")
def trackmap(track_id: int, db: Session = Depends(get_db)):
    """Proxy del mapa del circuito: LFM/racingcircuits no envía CORS, y Flutter
    web bloquea la imagen. Este endpoint descarga el PNG y lo reenvía con CORS.
    El PNG se cachea en disco (30 días): no se descarga en cada request.
    Público (sin auth): es una imagen de circuito, no hay datos del piloto.
    """
    import urllib.request
    from ..services import trackmap_cache
    t = db.query(Track).filter_by(track_id=track_id).first()
    if not t or not t.trackmap:
        raise HTTPException(status_code=404, detail="Circuito sin mapa")
    cached = trackmap_cache.get_base(track_id)
    if cached is not None:
        return Response(
            content=cached,
            media_type="image/png",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=86400",
            },
        )
    try:
        req = urllib.request.Request(t.trackmap, headers={"User-Agent": "HeimdallApp/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error descargando mapa: {e}")
    trackmap_cache.set_base(track_id, data)
    return Response(
        content=data,
        media_type="image/png",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=86400",
        },
    )


@router.get("/trackmap/{track_id}/colored")
def trackmap_colored(track_id: int,
                     s1: int, s2: int, s3: int,
                     t1: int, t2: int, t3: int,
                     user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Mapa del circuito pintado por sectores: rojo = pierdes, verde = ganas.
    s1/s2/s3 = deltas por sector (ms, positivo = pierdes).
    t1/t2/t3 = duración real de cada sector (ms) -> proporción del trazado.
    Requiere auth porque contiene datos del piloto.
    """
    import urllib.request
    from ..services.trackmap_painter import paint_trackmap
    from ..services import trackmap_cache

    t = db.query(Track).filter_by(track_id=track_id).first()
    if not t or not t.trackmap:
        raise HTTPException(status_code=404, detail="Circuito sin mapa")

    deltas = [s1, s2, s3]
    times = [t1, t2, t3]

    # Mapa pintado cacheado por (track, deltas, tiempos): el pipeline de
    # visión por computadora solo corre la primera vez con esa clave.
    cached = trackmap_cache.get_painted(track_id, deltas, times)
    if cached is not None:
        return Response(
            content=cached,
            media_type="image/png",
            headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"},
        )

    # PNG base cacheado en disco (30 días); si no, descarga y guarda.
    base = trackmap_cache.get_base(track_id)
    if base is None:
        try:
            req = urllib.request.Request(t.trackmap, headers={"User-Agent": "HeimdallApp/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                base = r.read()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Error descargando mapa: {e}")
        trackmap_cache.set_base(track_id, base)
    try:
        painted = paint_trackmap(base, deltas, times)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    trackmap_cache.set_painted(track_id, deltas, times, painted)
    return Response(
        content=painted,
        media_type="image/png",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-store",
        },
    )


@router.get("/profile/{profile_id}/incidents")
def incidents(profile_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _get_profile(profile_id, user, db)
    return kpis.incidents_heatmap(db, profile_id)


@router.get("/profile/{profile_id}/incidents/{race_pk}")
def incidents_detail(profile_id: int, race_pk: int, user=Depends(get_current_user),
                     db: Session = Depends(get_db)):
    _get_profile(profile_id, user, db)
    data = kpis.incidents_detail(db, profile_id, race_pk)
    if not data:
        raise HTTPException(status_code=404, detail="Carrera no encontrada")
    return data


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
