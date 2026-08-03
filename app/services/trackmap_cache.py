# Heimdall API — Caché en disco de imágenes de circuito.
# El PNG base (racingcircuits.info) se descargaba en CADA request del mapa.
# Ahora se guarda en disco la primera vez y se reutiliza. El mapa pintado
# (trackmap_colored) también se cachea por (track_id + deltas + tiempos):
# el pipeline de visión por computadora solo corre la primera vez.
import hashlib
import logging
import os
import time

log = logging.getLogger("heimdall.trackmapcache")

CACHE_DIR = os.getenv("HEIMDALL_TRACKMAP_CACHE", "/tmp/heimdall_trackmaps")
BASE_TTL = 30 * 24 * 3600   # el PNG base apenas cambia: 30 días
PAINT_TTL = 24 * 3600       # el pintado es determinista por clave: 24h

os.makedirs(CACHE_DIR, exist_ok=True)


def _path(key: str) -> str:
    return os.path.join(CACHE_DIR, key)


def _fresh(path: str, ttl: int) -> bool:
    try:
        return time.time() - os.path.getmtime(path) < ttl
    except OSError:
        return False


def get_base(track_id: int):
    """PNG base del circuito desde disco si está fresco; si no, None."""
    p = _path(f"base_{track_id}.png")
    if _fresh(p, BASE_TTL):
        with open(p, "rb") as f:
            return f.read()
    return None


def set_base(track_id: int, data: bytes):
    p = _path(f"base_{track_id}.png")
    try:
        with open(p, "wb") as f:
            f.write(data)
    except OSError as e:
        log.warning("no pude guardar base %s: %s", track_id, e)


def get_painted(track_id: int, deltas_ms, sector_times_ms):
    """PNG pintado desde disco si es fresco para esa clave exacta."""
    key = _paint_key(track_id, deltas_ms, sector_times_ms)
    p = _path(f"paint_{key}.png")
    if _fresh(p, PAINT_TTL):
        with open(p, "rb") as f:
            return f.read()
    return None


def set_painted(track_id: int, deltas_ms, sector_times_ms, data: bytes):
    key = _paint_key(track_id, deltas_ms, sector_times_ms)
    p = _path(f"paint_{key}.png")
    try:
        with open(p, "wb") as f:
            f.write(data)
    except OSError as e:
        log.warning("no pude guardar paint %s: %s", key, e)


def _paint_key(track_id: int, deltas_ms, sector_times_ms) -> str:
    raw = f"{track_id}|{','.join(map(str, deltas_ms))}|{','.join(map(str, sector_times_ms))}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]
