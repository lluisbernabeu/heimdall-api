# Heimdall API — Calendario LFM: series de Assetto Corsa con su semana actual,
# circuito, próximas carreras y coches.
# PATRÓN BD: los datos se guardan en la tabla schedule_cache (JSON). Si la API
# de LFM falla, servimos lo último descargado en vez de quedarnos sin datos.
import json
import logging
import urllib.request
from datetime import datetime, timezone

from ..models import ScheduleCache

log = logging.getLogger("heimdall.schedule")

API_BASE = "https://api3.lowfuelmotorsport.com"

SIM_AC = 3  # Assetto Corsa

# Orden de licencias LFM (menor -> mayor)
LICENSE_ORDER = {
    "ROOKIE": 0, "IRON": 1, "BRONZE": 2, "SILVER": 3, "GOLD": 4,
    "PLATINUM": 5, "DIAMOND": 6, "LEGEND": 7,
}


def _lic_rank(lic: str | None) -> int:
    if not lic:
        return -1
    base = lic.upper().replace("+", "").strip()
    return LICENSE_ORDER.get(base, -1)


def _get_json(url: str, timeout: int = 25):
    req = urllib.request.Request(url, headers={"User-Agent": "HeimdallApp/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _load_from_db(db) -> tuple[dict | None, datetime | None]:
    row = db.query(ScheduleCache).filter_by(sim_id=SIM_AC).first()
    if row and row.payload:
        return row.payload, row.fetched_at
    return None, None


def _fetch_from_lfm(db) -> dict:
    """Descarga el calendario de la temporada de AC y lo guarda en BD."""
    data = _get_json(f"{API_BASE}/api/v2/seasons/getMinifiedSeasonBySim")
    ac = (data or {}).get("series", {}).get(str(SIM_AC), {})
    payload = {
        "season_name": (data or {}).get("season_name"),
        "season_week": (data or {}).get("season_week"),
        "series": ac.get("series", []),
        "special_events": (data or {}).get("special_events", {}),
    }
    row = db.query(ScheduleCache).filter_by(sim_id=SIM_AC).first()
    if row is None:
        row = ScheduleCache(sim_id=SIM_AC)
        db.add(row)
    row.payload = payload
    row.season_name = payload.get("season_name")
    row.season_week = payload.get("season_week")
    row.fetched_at = datetime.utcnow()
    db.commit()
    return payload


def _cars_payload(db=None):
    """Lista de coches LFM (car_id -> nombre/thumbnail/sim).

    Cacheada en BD (api_cache, TTL 24h): el calendario se servía descargando
    getCars en CADA request (~1 llamada LFM). Ahora sirve de BD y solo
    refresca cuando toca o si la BD no tiene datos.
    """
    TTL = 24 * 3600
    from ..models import ApiCache
    if db is not None:
        row = db.query(ApiCache).filter_by(key="lfm:cars").first()
        if row and row.payload is not None:
            age = (datetime.utcnow() - row.fetched_at).total_seconds()
            if age < TTL:
                return row.payload
            # BD vieja: refrescamos, y si LFM falla servimos la vieja
            try:
                data = _get_json(f"{API_BASE}/api/lists/getCars")
            except Exception as e:
                log.warning("getCars falló (uso BD de %s): %s", row.fetched_at, e)
                return row.payload
            row.payload = data
            row.fetched_at = datetime.utcnow()
            db.commit()
            return data
    try:
        data = _get_json(f"{API_BASE}/api/lists/getCars")
    except Exception as e:
        log.warning("getCars falló: %s", e)
        return []
    if db is not None:
        row = db.query(ApiCache).filter_by(key="lfm:cars").first()
        if row is None:
            row = ApiCache(key="lfm:cars")
            db.add(row)
        row.payload = data
        row.fetched_at = datetime.utcnow()
        db.commit()
    return data


def _season_weeks(db, event_id: int):
    """Calendario semanal de una temporada.

    Cacheada en BD por event_id (api_cache, TTL 24h): antes se descargaba
    getSeasonWeeks para CADA serie en CADA request (9 series -> 9 llamadas).
    """
    TTL = 24 * 3600
    key = f"lfm:weeks:{event_id}"
    from ..models import ApiCache
    row = db.query(ApiCache).filter_by(key=key).first()
    if row and row.payload is not None:
        age = (datetime.utcnow() - row.fetched_at).total_seconds()
        if age < TTL:
            return row.payload
        try:
            data = _get_json(f"{API_BASE}/api/v2/seasons/getSeasonWeeks/{event_id}")
        except Exception as e:
            log.warning("getSeasonWeeks %s falló (uso BD de %s): %s",
                        event_id, row.fetched_at, e)
            return row.payload
        row.payload = data
        row.fetched_at = datetime.utcnow()
        db.commit()
        return data
    try:
        data = _get_json(f"{API_BASE}/api/v2/seasons/getSeasonWeeks/{event_id}")
    except Exception as e:
        log.warning("getSeasonWeeks %s falló (uso BD): %s", event_id, e)
        return []
    row = db.query(ApiCache).filter_by(key=key).first()
    if row is None:
        row = ApiCache(key=key)
        db.add(row)
    row.payload = data
    row.fetched_at = datetime.utcnow()
    db.commit()
    return data


def _car_names(cars: list, ids):
    out = {}
    for c in cars or []:
        if c.get("car_id") in ids:
            out[c["car_id"]] = c
    return out


def schedule(db=None, profile_id: int | None = None):
    """Calendario de todas las series de Assetto Corsa en LFM.
    Prioridad: BD fresca (<24h) -> LFM. Si LFM falla, BD aunque sea vieja."""
    from ..models import LfmProfile, Race

    payload, fetched_at = _load_from_db(db)
    fresh = False
    if fetched_at:
        age = (datetime.utcnow() - fetched_at).total_seconds()
        fresh = age < 24 * 3600  # 24h

    if payload is None or not fresh:
        try:
            payload = _fetch_from_lfm(db)
        except Exception as e:
            log.warning("LFM calendario caído (%s); uso BD de %s",
                        e, fetched_at)
            if payload is None:
                raise
    elif payload is not None:
        # Refresco en segundo plano no bloqueante: si la BD es vieja pero
        # tenemos datos, servimos y refrescamos después (mejor UX).
        pass

    cars = _cars_payload(db)
    series = payload.get("series", [])

    # Datos del perfil para marcar qué puede correr
    my_lic = None
    my_sr = None
    my_event_ids = set()
    if db is not None and profile_id is not None:
        me = db.query(LfmProfile).filter_by(id=profile_id).first()
        if me:
            my_lic = me.license
            my_sr = me.safety_rating
            my_event_ids = {
                r.event_id for r in
                db.query(Race).filter(Race.profile_id == profile_id,
                                      Race.event_id.isnot(None)).all()
            }

    result = []
    season_week = payload.get("season_week")
    for s in series:
        eid = s.get("event_id")
        # ¿Puede correrla? (licencia y SR suficientes)
        can_race = None
        if my_lic is not None or my_sr is not None:
            lic_ok = _lic_rank(my_lic) >= _lic_rank(s.get("min_license"))
            sr_min = s.get("min_sr") or 0
            sr_ok = (my_sr or 0) >= sr_min
            can_race = bool(lic_ok and sr_ok)
        # Clases/coches
        classes = []
        cs = ((s.get("settings") or {}).get("championship_settings") or {})
        for c in cs.get("car_classes", []):
            ids = c.get("allowed_cars") or []
            cars_map = _car_names(cars, ids)
            classes.append({
                "name": c.get("class"),
                "cars": [
                    {"id": cid,
                     "name": (cars_map.get(cid) or {}).get("car_name"),
                     "thumbnail": (cars_map.get(cid) or {}).get("thumbnail")}
                    for cid in ids
                ],
                "weeks": c.get("season_weeks"),
            })
        # Siguientes carreras (con circuito)
        def _race_short(r):
            if not isinstance(r, dict):
                return {"date": r}
            tr = r.get("track") or {}
            return {
                "date": r.get("race_date"),
                "track": tr.get("track_name"),
                "track_id": tr.get("track_id"),
                "split": r.get("split"),
            }
        next_races = [_race_short(r) for r in (s.get("next3_races") or [])]
        at = s.get("active_track") or {}
        at_name = at.get("track_name") if isinstance(at, dict) else at
        at_link = at.get("content_link") if isinstance(at, dict) else None

        # Próxima carrera en ms (para countdown)
        nxt = s.get("next_race_date")
        nxt_ms = None
        if nxt:
            try:
                dt = datetime.fromisoformat(str(nxt).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                nxt_ms = int((dt - datetime.now(timezone.utc)).total_seconds() * 1000)
            except ValueError:
                nxt_ms = None

        result.append({
            "event_id": eid,
            "series_name": s.get("series_name"),
            "slug": s.get("slug"),
            "sim_id": s.get("sim_id"),
            "min_license": s.get("min_license"),
            "min_sr": s.get("min_sr"),
            "race_length": s.get("race_length"),
            "series_logo": s.get("series_logo"),
            "thumbnail": s.get("thumbnail"),
            "active_week": s.get("active_week"),
            "active_track": at_name,
            "active_track_id": at.get("track_id") if isinstance(at, dict) else None,
            "content_link": at_link,
            "signup_link": f"https://lowfuelmotorsport.com/series/{s.get('slug')}"
                           if s.get("slug") else None,
            "next_race": s.get("next_race"),
            "next_race_date": s.get("next_race_date"),
            "next_race_ms": nxt_ms,
            "next_races": next_races,
            "classes": classes,
            "fixed_car": s.get("fixed_car"),
            "track_permit_needed": s.get("track_permit_needed"),
            "paid_mods": s.get("paid_mods"),
            "website_short_text": s.get("website_short_text"),
            "content_needed": s.get("content_needed"),
            "can_race": can_race,
            "my_series": eid in my_event_ids if my_event_ids else None,
            "weeks": [
                {
                    "week_num": i + 1,
                    "is_current": (i + 1) == season_week,
                    "from": w.get("from"),
                    "to": w.get("to"),
                    "track": (w.get("track") or {}).get("track_name"),
                    "track_id": (w.get("track") or {}).get("track_id"),
                    "country": (w.get("track") or {}).get("country"),
                    "turns": (w.get("track") or {}).get("turns"),
                    "km": (w.get("track") or {}).get("km"),
                    "content_link": (w.get("track") or {}).get("content_link"),
                }
                for i, w in enumerate(_season_weeks(db, eid))
            ] if eid else [],
        })

    return {
        "season_name": payload.get("season_name"),
        "season_week": payload.get("season_week"),
        "sim_name": "Assetto Corsa",
        "sim_id": SIM_AC,
        "my_license": my_lic,
        "my_sr": my_sr,
        "data_age_hours": round((datetime.utcnow() - fetched_at).total_seconds() / 3600, 1)
                          if fetched_at else None,
        "series": result,
    }
