# Heimdall API — Estadísticas globales LFM y contexto de la comunidad.
# Endpoints públicos de api3 sin login, todos cacheados en BD (regla nº1).
import logging
import urllib.request
from datetime import datetime

from ..models import ApiCache

log = logging.getLogger("heimdall.globalstats")

API_BASE = "https://api3.lowfuelmotorsport.com"
TTL_SR = 24 * 3600        # distribución SR: 1/día
TTL_STATUS = 5 * 60       # estado LFM en vivo: 5 min
TTL_REASONS = 7 * 24 * 3600  # taxonomía incidentes: 1/semana


def _get_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": "HeimdallApp/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json_loads(r.read())


import json


def json_loads(b):
    return json.loads(b)


def _cache_get(db, key: str, ttl: int):
    row = db.query(ApiCache).filter_by(key=key).first()
    if row and row.payload is not None:
        age = (datetime.utcnow() - row.fetched_at).total_seconds()
        return row.payload, age
    return None, None


def _cache_set(db, key: str, payload):
    row = db.query(ApiCache).filter_by(key=key).first()
    if row is None:
        row = ApiCache(key=key)
        db.add(row)
    row.payload = payload
    row.fetched_at = datetime.utcnow()
    db.commit()


def _fetch_refresh(db, key: str, url: str, ttl: int, fallback=None):
    """BD primero; si vieja o ausente, LFM; si LFM falla, BD aunque sea vieja."""
    cached, age = _cache_get(db, key, ttl)
    if cached is not None and age is not None and age < ttl:
        return cached, True
    try:
        data = _get_json(url)
        _cache_set(db, key, data)
        return data, True
    except Exception as e:
        log.warning("%s falló (uso BD de %s): %s", key, age, e)
        if cached is not None:
            return cached, False
        if fallback is not None:
            return fallback, False
        raise


def sr_distribution(db):
    """Distribución global de SR + percentil del usuario."""
    data, fresh = _fetch_refresh(db, "lfm:srdist",
                                 f"{API_BASE}/api/statistics/getSRDistribution",
                                 TTL_SR, fallback=None)
    return data


def lfm_status(db):
    """Estado en vivo: servidores, usuarios online, simuladores, LFM+."""
    out = {}
    for key, url in [
        ("accstatus", f"{API_BASE}/api/accstatus"),
        ("online_users", f"{API_BASE}/api/online-users"),
        ("lfmplus", f"{API_BASE}/api/lfmplusmembers"),
    ]:
        try:
            d, _ = _fetch_refresh(db, f"lfm:{key}", url, TTL_STATUS, fallback={})
            out[key] = d if isinstance(d, dict) else {}
        except Exception as e:
            log.warning("status %s falló: %s", key, e)
            out[key] = {}
    # Simulaciones (cambia poco: 1/día)
    try:
        sims, _ = _fetch_refresh(db, "lfm:sims", f"{API_BASE}/api/simulations",
                                 24 * 3600, fallback=[])
        out["simulations"] = sims if isinstance(sims, list) else []
    except Exception as e:
        log.warning("sims falló: %s", e)
        out["simulations"] = []
    return out


def incident_reasons(db):
    """Categorías oficiales de incidentes con penalización de SR."""
    data, _ = _fetch_refresh(db, "lfm:reasons",
                             f"{API_BASE}/api/getReportingReasons2",
                             TTL_REASONS, fallback={"reasons": []})
    return data


def percentile_of(sr: float, dist: dict | None) -> dict | None:
    """Percentil del SR del usuario en la distribución global.
    'mejor que el X% de la comunidad'. dist = {overall, average_sr, ranges}.
    """
    if not dist:
        return None
    ranges = dist.get("ranges") or []
    overall = dist.get("overall") or 0
    if not ranges or not overall:
        return None
    # Los rangos vienen con percent acumulado (percent = % que está EN o POR
    # ENCIMA de ese rango). El rango del usuario es el primero donde
    # sr está dentro de [lo, hi].
    for r in ranges:
        name = r.get("name") or ""
        if "-" in name:
            lo, hi = name.split("-")
            try:
                lo_f, hi_f = float(lo), float(hi)
            except ValueError:
                continue
            if lo_f <= sr <= hi_f:
                return {
                    "sr": sr,
                    "range": name,
                    "amount": r.get("amount"),
                    "percentile": r.get("percent"),
                    "better_than_pct": 100 - float(r.get("percent") or 0),
                    "overall": overall,
                    "average_sr": dist.get("average_sr"),
                }
    return None
