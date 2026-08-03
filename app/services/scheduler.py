# Heimdall API — scheduler interno de sync automático
# El backend es AUTOSUFICIENTE: un thread daemon arrancado con la app revisa
# periódicamente todos los perfiles y lanza el sync si no hay uno en curso.
# No depende de cron externo ni de Hermes: si el backend corre, se sincroniza solo.
import logging
import threading
import time
from datetime import datetime, timedelta

from ..config import AUTO_SYNC_INTERVAL_HOURS, AUTO_SYNC_STARTUP_DELAY
from .sync_service import SyncService

log = logging.getLogger("heimdall.scheduler")

# Un sync que no actualiza su estado en este tiempo (min) se considera
# huérfano (el proceso murió a mitad de trabajo) y se relanza con force.
STALE_SYNC_MINUTES = 30


def _run_auto_sync():
    """Ejecuta el sync de todos los perfiles (cada uno en su propio thread)."""
    from ..db import SessionLocal
    from ..models import LfmProfile
    db = SessionLocal()
    try:
        svc = SyncService(db)
        profiles = db.query(LfmProfile).order_by(LfmProfile.id).all()
        for p in profiles:
            st = svc._state(p.id)
            if st.status == "running":
                stale = False
                if st.updated_at:
                    age = (datetime.utcnow() - st.updated_at).total_seconds()
                    stale = age > STALE_SYNC_MINUTES * 60
                if stale:
                    # Watchdog: sync colgado (crash del proceso) -> relanzar
                    log.warning(
                        "auto-sync: perfil %d (%s %s) sync colgado desde %s "
                        "(última actividad %s) — relanzando con force",
                        p.id, p.vorname or "", p.nachname or "",
                        st.started_at, st.updated_at)
                    t = threading.Thread(
                        target=_sync_one, args=(p.id, True), daemon=True)
                    t.start()
                else:
                    log.info("auto-sync: perfil %d (%s %s) ya sincronizando, salto",
                             p.id, p.vorname or "", p.nachname or "")
                continue
            log.info("auto-sync: perfil %d (%s %s) — lanzando sync",
                     p.id, p.vorname or "", p.nachname or "")
            # Cada perfil en su propio thread para no bloquear el loop
            t = threading.Thread(target=_sync_one, args=(p.id,), daemon=True)
            t.start()
    except Exception:
        log.exception("auto-sync: error al revisar perfiles")
    finally:
        db.close()


def _sync_one(profile_id: int, force: bool = False):
    from ..db import SessionLocal
    from ..models import LfmProfile
    db = SessionLocal()
    try:
        profile = db.query(LfmProfile).filter_by(id=profile_id).first()
        if not profile:
            return
        svc = SyncService(db)
        svc.start_sync(profile, force=force)
        log.info("auto-sync: perfil %d sync completado", profile_id)
    except Exception:
        log.exception("auto-sync: sync perfil %d falló", profile_id)
    finally:
        db.close()


def _prewarm_catalog():
    """Mantiene caliente la BD del Calendario: refresca el payload de LFM
    (schedule_cache) y pre-calienta récords + videos de los circuitos activos
    de las series AC (track_records / track_videos). Si una fuente falla,
    se queda con lo guardado: la app siempre tiene datos."""
    from ..db import SessionLocal
    from .schedule_service import _fetch_from_lfm, SIM_AC
    from .track_guides import prewarm
    db = SessionLocal()
    try:
        # 1) Refrescar calendario (payload de la temporada AC)
        try:
            _fetch_from_lfm(db)
            log.info("catalog: calendario LFM refrescado en BD")
        except Exception as e:
            log.warning("catalog: calendario LFM falló (BD conserva lo previo): %s", e)

        # 1b) Pre-calentar cachés auxiliares del calendario (getCars + semanas
        # de cada serie): así el primer /schedule del día no hace 10 llamadas
        # secuenciales a LFM (era la causa de los ~5s de carga).
        try:
            from ..models import ScheduleCache
            row = db.query(ScheduleCache).filter_by(sim_id=SIM_AC).first()
            if row and row.payload:
                from .schedule_service import _cars_payload, _season_weeks
                _cars_payload(db)
                for s in (row.payload.get("series") or []):
                    eid = s.get("event_id")
                    if eid:
                        _season_weeks(db, eid)
                log.info("catalog: cachés auxiliares (cars + semanas) precalentadas")
        except Exception as e:
            log.warning("catalog: prewarm cachés auxiliares falló: %s", e)

        # 2) Pre-calentar récords + videos de los circuitos de esta semana
        try:
            from ..models import ScheduleCache
            row = db.query(ScheduleCache).filter_by(sim_id=SIM_AC).first()
            pairs = []
            if row and row.payload:
                for s in (row.payload.get("series") or []):
                    at = s.get("active_track") or {}
                    track = (at.get("track_name")
                             if isinstance(at, dict) else at)
                    if track:
                        cls = None
                        cs = ((s.get("settings") or {})
                              .get("championship_settings") or {})
                        for c in cs.get("car_classes", []):
                            if c.get("class"):
                                cls = c.get("class")
                                break
                        pairs.append((track, cls))
            if pairs:
                prewarm(db, pairs)
                log.info("catalog: prewarm %d circuitos (%s)",
                         len(set(p[0] for p in pairs)),
                         ", ".join(sorted(set(p[0] for p in pairs))))
        except Exception as e:
            log.warning("catalog: prewarm de circuitos falló: %s", e)
    finally:
        db.close()


def start_scheduler():
    """Arranca el thread daemon del scheduler (llamado en startup de FastAPI)."""
    def loop():
        delay = max(AUTO_SYNC_STARTUP_DELAY, 10)
        log.info("scheduler: primer sync automático en %.0fs (cada %dh)",
                 delay, AUTO_SYNC_INTERVAL_HOURS)
        time.sleep(delay)
        while True:
            try:
                _run_auto_sync()
            except Exception:
                log.exception("scheduler: pasada falló")
            try:
                _prewarm_catalog()
            except Exception:
                log.exception("scheduler: prewarm catálogo falló")
            time.sleep(AUTO_SYNC_INTERVAL_HOURS * 3600)

    t = threading.Thread(target=loop, name="heimdall-auto-sync", daemon=True)
    t.start()
    log.info("scheduler: arrancado (intervalo %dh)", AUTO_SYNC_INTERVAL_HOURS)
