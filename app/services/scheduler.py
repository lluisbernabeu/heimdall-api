# Heimdall API — scheduler interno de sync automático
# El backend es AUTOSUFICIENTE: un thread daemon arrancado con la app revisa
# periódicamente todos los perfiles y lanza el sync si no hay uno en curso.
# No depende de cron externo ni de Hermes: si el backend corre, se sincroniza solo.
import logging
import threading
import time
from datetime import datetime

from ..config import AUTO_SYNC_INTERVAL_HOURS, AUTO_SYNC_STARTUP_DELAY
from .sync_service import SyncService

log = logging.getLogger("heimdall.scheduler")


def _run_auto_sync():
    """Ejecuta el sync de todos los perfiles (cada uno en su propio thread)."""
    from ..db import SessionLocal
    from ..models import LfmProfile
    db = SessionLocal()
    try:
        svc = SyncService(db)
        profiles = db.query(LfmProfile).order_by(LfmProfile.id).all()
        for p in profiles:
            st = svc.get_status(p.id)
            if st["status"] == "running":
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


def _sync_one(profile_id: int):
    from ..db import SessionLocal
    from ..models import LfmProfile
    db = SessionLocal()
    try:
        profile = db.query(LfmProfile).filter_by(id=profile_id).first()
        if not profile:
            return
        svc = SyncService(db)
        svc.start_sync(profile, force=False)
        log.info("auto-sync: perfil %d sync completado", profile_id)
    except Exception:
        log.exception("auto-sync: sync perfil %d falló", profile_id)
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
            time.sleep(AUTO_SYNC_INTERVAL_HOURS * 3600)

    t = threading.Thread(target=loop, name="heimdall-auto-sync", daemon=True)
    t.start()
    log.info("scheduler: arrancado (intervalo %dh)", AUTO_SYNC_INTERVAL_HOURS)
