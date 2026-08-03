# Heimdall API — Replay de datos de carrera LFM.
# Reconstruye la carrera vuelta a vuelta con:
#  1) positionChart/{split}  — posición de TODOS los pilotos vuelta a vuelta
#  2) getLapDetails/{result_id} — vueltas con splits por sector de pilotos clave
#  3) vod_link / live_video / multiTwitch — enlaces si fue transmitida
# PATRÓN BD: se cachea en race_replays. Si LFM falla, servimos lo guardado.
import json
import logging
import urllib.request
from datetime import datetime, timedelta

from ..models import RaceReplay

log = logging.getLogger("heimdall.racereplay")

API_BASE = "https://api3.lowfuelmotorsport.com"
REPLAY_TTL = timedelta(hours=6)  # el positionChart no cambia; 6h es de sobra

# Máximo de pilotos con vueltas detalladas (los más relevantes)
MAX_LAP_PILOTS = 8


def _get_json(url: str, timeout: int = 25):
    req = urllib.request.Request(url, headers={"User-Agent": "HeimdallApp/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _parse_lap_ms(lap_str):
    """'01:03.907' -> 63907 ms"""
    try:
        parts = str(lap_str).split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60000 + int(float(parts[1]) * 1000)
        if len(parts) == 3:
            return (int(parts[0]) * 3600000 + int(parts[1]) * 60000
                    + int(float(parts[2]) * 1000))
    except (ValueError, TypeError):
        pass
    return None


def _short_name(full: str | None) -> str:
    """'Jorge Herrera' -> 'J. Herrera'; None -> 'Piloto'"""
    if not full:
        return "Piloto"
    parts = full.strip().split()
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0][0]}. {parts[-1]}"


def _driver_label(driver: str | None, uid) -> str:
    """'#1 | Jorge Herrera' -> 'J. Herrera' (uid como fallback)."""
    if driver:
        clean = driver.split("|")[-1].strip()
        return _short_name(clean)
    return str(uid)


def _load_from_db(db, lfm_race_id: int, split: int):
    row = (db.query(RaceReplay)
           .filter_by(lfm_race_id=lfm_race_id, split=split).first())
    if row and row.payload:
        return row.payload, row.fetched_at
    return None, None


def _fetch_replay(db, lfm_race_id: int, split: int, my_user_id: int | None = None) -> dict:
    """Descarga el replay de datos de LFM y lo guarda en BD."""
    race = _get_json(f"{API_BASE}/api/race/{lfm_race_id}")

    # --- 1) PositionChart (posición vuelta a vuelta de todos) ---
    chart = []
    try:
        chart = _get_json(f"{API_BASE}/api/race/{lfm_race_id}/positionChart/{split}")
    except Exception as e:
        log.warning("positionChart %s split %s falló: %s", lfm_race_id, split, e)

    # --- 2) Resultados del split para mapear result_id -> piloto ---
    results = []
    try:
        rrs = race.get("race_results_splits") or []
        if isinstance(rrs, list) and len(rrs) >= split:
            # {clase: {OVERALL: [...]}}
            splits_map = rrs[split - 1] if rrs else {}
            for cls in (splits_map or {}).values() or []:
                for entry in (cls or {}).get("OVERALL", []) or []:
                    results.append({
                        "result_id": entry.get("result_id"),
                        "user_id": entry.get("user_id"),
                        "driver": f"{entry.get('vorname') or ''} {entry.get('nachname') or ''}".strip(),
                        "position": entry.get("position"),
                        "laps": entry.get("laps"),
                        "bestlap": entry.get("bestlap"),
                        "car_name": entry.get("car_name"),
                    })
    except Exception as e:
        log.warning("resultados %s falló: %s", lfm_race_id, e)
    results.sort(key=lambda r: (r["position"] is None, r["position"] or 999))

    # --- 3) Pilotos con vueltas detalladas (splits por sector) ---
    # Prioridad: mi piloto, el ganador, y el resto por posición
    ordered = sorted(results, key=lambda r: (r["position"] is None, r["position"] or 999))
    if my_user_id is not None:
        ordered = sorted(ordered,
                         key=lambda r: 0 if r["user_id"] == my_user_id else
                         (1 if (r["position"] or 999) == 1 else 2))
    lap_pilots = []
    for res in ordered[:MAX_LAP_PILOTS]:
        rid = res.get("result_id")
        if not rid:
            continue
        try:
            ld = _get_json(f"{API_BASE}/api/race/{lfm_race_id}/getLapDetails/{rid}")
            laps = []
            for L in (ld.get("laps") or [])[:80]:
                splits = L.get("splits") or []
                laps.append({
                    "lap": L.get("car_lap") or L.get("lap"),
                    "time_ms": _parse_lap_ms(L.get("lapTime")),
                    "s1_ms": _parse_lap_ms(splits[0]) if len(splits) > 0 else None,
                    "s2_ms": _parse_lap_ms(splits[1]) if len(splits) > 1 else None,
                    "s3_ms": _parse_lap_ms(splits[2]) if len(splits) > 2 else None,
                    "valid": bool(L.get("lap_valid")),
                })
            if laps:
                lap_pilots.append({
                    "user_id": res.get("user_id"),
                    "name": _short_name(res.get("driver")),
                    "result_id": rid,
                    "position": res.get("position"),
                    "car_name": res.get("car_name"),
                    "bestlap": res.get("bestlap"),
                    "laps": laps,
                })
        except Exception as e:
            log.warning("lapDetails %s/%s falló: %s", lfm_race_id, rid, e)

    payload = {
        "lfm_race_id": lfm_race_id,
        "split": split,
        "track_name": (race.get("track") or {}).get("track_name"),
        "race_date": race.get("race_date"),
        "vod_link": race.get("vod_link") or None,
        "live_video": race.get("live_video") or None,
        "videolink": race.get("videolink") or None,
        "broadcaster": race.get("session_broadcaster"),
        "multiTwitch": race.get("multiTwitch") or [],
        "position_chart": chart,
        "results": results,
        "lap_pilots": lap_pilots,
        "fetched_at": datetime.utcnow().isoformat(),
    }

    row = (db.query(RaceReplay)
           .filter_by(lfm_race_id=lfm_race_id, split=split).first())
    if row is None:
        row = RaceReplay(lfm_race_id=lfm_race_id, split=split)
        db.add(row)
    row.payload = payload
    row.fetched_at = datetime.utcnow()
    db.commit()
    return payload


def race_replay(db, lfm_race_id: int, split: int = 1,
                my_user_id: int | None = None):
    """Replay de datos de una carrera. BD fresca primero; si no, LFM con
    guardado en BD; si LFM falla, BD aunque sea vieja."""
    payload, fetched_at = _load_from_db(db, lfm_race_id, split)
    fresh = False
    if fetched_at:
        fresh = (datetime.utcnow() - fetched_at) < REPLAY_TTL

    if payload is None or not fresh:
        try:
            payload = _fetch_replay(db, lfm_race_id, split, my_user_id)
        except Exception as e:
            log.warning("replay %s falló (%s); uso BD de %s",
                        lfm_race_id, e, fetched_at)
            if payload is None:
                raise

    # Añadir edad para la UI
    out = dict(payload or {})
    if fetched_at:
        out["data_age_hours"] = round(
            (datetime.utcnow() - fetched_at).total_seconds() / 3600, 1)
    elif payload and payload.get("fetched_at"):
        try:
            fa = datetime.fromisoformat(payload["fetched_at"])
            out["data_age_hours"] = round(
                (datetime.utcnow() - fa).total_seconds() / 3600, 1)
        except ValueError:
            out["data_age_hours"] = None
    return out
