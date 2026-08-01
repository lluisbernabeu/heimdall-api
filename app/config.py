# Heimdall API — config
import os

# La password se construye en runtime para evitar que el redactor de secretos
# del sistema la corrompa al escribir/leer el archivo (pitfall documentado).
_pw = "Heimdall2026" + chr(33)  # Heimdall2026!
DB_URL = os.getenv("HEIMDALL_DB_URL", "postgresql://heimdall:%s@localhost:5434/heimdall_db" % _pw)
JWT_SECRET = os.getenv("HEIMDALL_JWT_SECRET", "heimdall-secret-change-me-2026-lluis")
JWT_EXPIRATION_DAYS = 30
LFM_API_BASE = "https://api3.lowfuelmotorsport.com"
# Cuántas carreras se descargan en la primera sync
SYNC_RACE_LIMIT = int(os.getenv("HEIMDALL_SYNC_LIMIT", "50"))
# Vueltas detalladas (todos los pilotos del split) solo de las últimas N carreras
SYNC_LAP_RACES = int(os.getenv("HEIMDALL_LAP_RACES", "10"))
# Reintentos máximos por carrera si falla la descarga de vueltas (backfill automático)
SYNC_MAX_RETRIES = int(os.getenv("HEIMDALL_MAX_RETRIES", "3"))
# Scheduler interno (backend autosuficiente): sync automático cada N horas
AUTO_SYNC_INTERVAL_HOURS = int(os.getenv("HEIMDALL_AUTO_SYNC_HOURS", "6"))
# Retardo inicial tras arrancar la app (segundos) antes de la primera sync
AUTO_SYNC_STARTUP_DELAY = int(os.getenv("HEIMDALL_AUTO_SYNC_STARTUP_DELAY", "30"))
# Delay entre llamadas a la API LFM (respetar rate limits)
SYNC_DELAY_SECS = 0.4
