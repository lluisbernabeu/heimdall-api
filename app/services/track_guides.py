# Heimdall API — Guías de circuito para el Calendario LFM.
# Combina:
#  1) Récords oficiales LFM por circuito/clase  (/api/tracks/records)
#  2) Videos de YouTube de track guides/hotlaps (búsqueda con yt-dlp)
# PATRÓN BD: los datos se guardan en track_records y track_videos. Si LFM o
# YouTube fallan, servimos lo último guardado.
import json
import logging
import re
import subprocess
import urllib.request
from datetime import datetime, timedelta

from ..models import TrackRecord, TrackVideo

log = logging.getLogger("heimdall.trackguides")

API_BASE = "https://api3.lowfuelmotorsport.com"
RECORDS_TTL = timedelta(hours=24)   # refrescar récords una vez al día
VIDEO_TTL = timedelta(hours=72)     # refrescar videos cada 3 días

# Consultas de búsqueda en YouTube por serie (clase)
SEARCH_QUERIES = {
    "MX5 Cup": ["{track} mx5 cup low fuel motorsport track guide",
                "{track} assetto corsa mx5 hotlap"],
    "TCR": ["{track} tcr low fuel motorsport track guide",
            "{track} assetto corsa tcr setup track guide"],
    "PCUP": ["{track} porsche cup low fuel motorsport track guide",
             "{track} assetto corsa porsche 992 cup track guide"],
    "SR3": ["{track} radical sr3 track guide",
            "{track} assetto corsa radical hotlap"],
    "F4": ["{track} f4 low fuel motorsport track guide",
           "{track} assetto corsa formula 4 hotlap"],
    "ACF GT3": ["{track} gt3 low fuel motorsport track guide",
                "{track} assetto corsa gt3 hotlap"],
    "ACF Supra": ["{track} supra gt4 track guide assetto corsa"],
    "GT3": ["{track} gt3 low fuel motorsport track guide",
            "{track} assetto corsa gt3 hotlap"],
    "ACF HY": ["{track} hypercar assetto corsa track guide"],
    "default": ["{track} assetto corsa track guide",
                "{track} low fuel motorsport track guide"],
}


def _get_json(url: str, timeout: int = 25):
    req = urllib.request.Request(url, headers={"User-Agent": "HeimdallApp/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _records_payload():
    """Récords LFM por circuito (sim=3). Se pide a LFM; los guardamos por
    circuito/clase en track_records dentro de track_guides()."""
    return _get_json(f"{API_BASE}/api/tracks/records?sim=3")


def _match_track(records: list, track_name: str):
    norm = re.sub(r"[^a-z0-9]", "", (track_name or "").lower())
    if not norm:
        return None
    best = None
    for t in records:
        tn = re.sub(r"[^a-z0-9]", "", (t.get("track_name") or "").lower())
        if not tn:
            continue
        if tn == norm:
            if _has_records(t):
                return t
            if best is None:
                best = t
            continue
        if (tn.startswith(norm) or norm.startswith(tn)) and len(tn) >= 8:
            if _has_records(t):
                return t
            if best is None:
                best = t
    return best


def _has_records(t):
    records = t.get("records") or {}
    return any((e or {}).get("qualifying") or (e or {}).get("race")
               for e in records.values())


def _parse_lap(lap_str):
    try:
        parts = str(lap_str).split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60000 + int(float(parts[1]) * 1000)
        if len(parts) == 3:
            return int(parts[0]) * 3600000 + int(parts[1]) * 60000 + int(float(parts[2]) * 1000)
    except (ValueError, TypeError):
        pass
    return None


def _youtube_search(query: str, limit: int = 4):
    try:
        cmd = ["yt-dlp", f"ytsearch{limit}:{query}", "--flat-playlist",
               "-J", "--no-warnings", "--no-playlist", "--skip-download"]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        d = json.loads(out.stdout)
        entries = d.get("entries") or []
        results = []
        for e in entries:
            vid = e.get("id")
            if not vid:
                continue
            results.append({
                "video_id": vid,
                "title": e.get("title"),
                "channel": e.get("channel"),
                "duration": e.get("duration"),
                "url": f"https://www.youtube.com/watch?v={vid}",
                "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            })
        return results
    except Exception as e:
        log.warning("búsqueda YouTube '%s' falló: %s", query[:40], e)
        return []


def _prefer_lfm(results):
    def score(r):
        t = (r.get("title") or "").lower()
        s = 0
        if "lfm" in t or "low fuel" in t: s += 4
        if "mx5" in t or "mazda" in t: s += 3
        if "track guide" in t or "setup" in t: s += 2
        if "hotlap" in t or "race" in t: s += 1
        return s
    return sorted(results, key=score, reverse=True)


_CLASS_FALLBACKS = ("MX5 Cup", "TCR", "PCUP", "SR3", "F4", "ACF GT3",
                    "ACF Supra", "GT3", "GT4", "ACF HY")


def _store_class_records(db, track_name, car_class, track_match):
    """Guarda los récords qualifying/race de la clase pedida (o fallback)
    para un circuito ya emparejado con la respuesta de /api/tracks/records."""
    cls = track_match.get("records") or {}
    entry = None
    classes_to_try = [c for c in (car_class, *_CLASS_FALLBACKS) if c]
    for key in classes_to_try:
        if key in cls:
            e = cls[key] or {}
            if e.get("qualifying") or e.get("race"):
                entry = e
                break
    if entry:
        q = entry.get("qualifying") or {}
        r = entry.get("race") or {}
        if q:
            _store_record_db(db, track_name, car_class, "qualifying", q)
        if r:
            _store_record_db(db, track_name, car_class, "race", r)
        db.commit()


def _search_and_rank(track_name, car_class, limit=3):
    """Busca videos en YouTube y los ordena priorizando LFM/MX5/track guide."""
    queries = (SEARCH_QUERIES.get(car_class, SEARCH_QUERIES["default"])
               if car_class else SEARCH_QUERIES["default"])
    found = []
    for q in queries:
        found.extend(_youtube_search(q.format(track=track_name), limit=limit))
        if len(found) >= limit:
            break
    return _prefer_lfm(found)[:limit]


def prewarm(db, pairs, limit: int = 3):
    """Pre-calienta en BD récords + videos para una lista de (track, class).
    Los récords se descargan de LFM UNA sola vez para todos los circuitos;
    los videos con yt-dlp por circuito (lento, solo si faltan o caducan)."""
    pairs = list(dict.fromkeys(pairs))  # dedupe preservando orden
    missing = [(t, c) for (t, c) in pairs
               if _load_record_db(db, t, c) is None
               or not _records_fresh(db, t, c)]
    if missing:
        try:
            records = _records_payload()
            for t, c in missing:
                m = _match_track(records, t)
                if m:
                    _store_class_records(db, t, c, m)
        except Exception as e:
            log.warning("prewarm récords falló: %s", e)
    for t, c in pairs:
        if _load_videos_db(db, t, c)[0] is None:
            try:
                found = _search_and_rank(t, c, limit)
                if found:
                    _store_videos_db(db, t, c, found)
            except Exception as e:
                log.warning("prewarm videos %s falló: %s", t, e)


def _load_record_db(db, track_name, car_class):
    """Récord desde BD (mejor tiempo qualifying + race)."""
    rows = (db.query(TrackRecord)
            .filter_by(track_name=track_name, car_class=car_class).all())
    if not rows:
        return None
    out = {"track_name": track_name, "car_class": car_class,
           "qualifying": None, "race": None}
    for r in rows:
        d = {"lap": r.lap, "lap_ms": r.lap_ms, "driver": r.driver,
             "origin": r.origin, "car": r.car, "date": r.date}
        if r.mode == "qualifying":
            out["qualifying"] = d
        elif r.mode == "race":
            out["race"] = d
    if not out["qualifying"] and not out["race"]:
        return None
    return out


def _records_fresh(db, track_name, car_class, ttl=RECORDS_TTL):
    """¿Existe un récord para (track, class) y tiene menos de `ttl`?"""
    row = (db.query(TrackRecord)
           .filter_by(track_name=track_name, car_class=car_class)
           .order_by(TrackRecord.fetched_at.desc()).first())
    if row is None or row.fetched_at is None:
        return False
    return datetime.utcnow() - row.fetched_at <= ttl


def _store_record_db(db, track_name, car_class, mode, entry):
    row = (db.query(TrackRecord)
           .filter_by(track_name=track_name, car_class=car_class, mode=mode)
           .first())
    lap_ms = _parse_lap(entry.get("lap"))
    vals = dict(lap=entry.get("lap"), lap_ms=lap_ms,
                driver=entry.get("driver"), origin=entry.get("origin"),
                car=entry.get("car_name"), date=entry.get("date"),
                fetched_at=datetime.utcnow())
    if row is None:
        row = TrackRecord(track_name=track_name, car_class=car_class,
                          mode=mode, **vals)
        db.add(row)
    else:
        for k, v in vals.items():
            setattr(row, k, v)


def _load_videos_db(db, track_name, car_class, ttl=VIDEO_TTL):
    rows = (db.query(TrackVideo)
            .filter_by(track_name=track_name)
            .order_by(TrackVideo.fetched_at.desc())
            .all())
    if not rows:
        return None, None
    newest = max((r.fetched_at or datetime.utcnow()) for r in rows)
    if datetime.utcnow() - newest > ttl:
        return None, newest
    return [{
        "video_id": r.video_id, "title": r.title, "channel": r.channel,
        "duration": r.duration, "url": r.url, "thumbnail": r.thumbnail,
    } for r in rows], newest


def _store_videos_db(db, track_name, car_class, videos):
    for v in videos:
        row = db.query(TrackVideo).filter_by(video_id=v["video_id"]).first()
        vals = dict(track_name=track_name, car_class=car_class,
                    title=v.get("title"), channel=v.get("channel"),
                    duration=v.get("duration"), url=v.get("url"),
                    thumbnail=v.get("thumbnail"), fetched_at=datetime.utcnow())
        if row is None:
            row = TrackVideo(video_id=v["video_id"], **vals)
            db.add(row)
        else:
            for k, val in vals.items():
                setattr(row, k, val)
    db.commit()


def track_guides(db, track_name: str, car_class: str | None = None, limit: int = 3):
    """Guías para un circuito: récord oficial LFM + videos YouTube.
    BD primero; si está fresca se sirve; si no, se descarga y se guarda.
    Si la fuente falla, se sirve lo que haya en BD (aunque sea viejo)."""
    if db is None:
        raise ValueError("track_guides requiere sesión BD")

    # --- 1) Récord LFM ---
    record = _load_record_db(db, track_name, car_class)
    if record is None:
        try:
            records = _records_payload()
            t = _match_track(records, track_name)
            if t:
                _store_class_records(db, track_name, car_class, t)
            record = _load_record_db(db, track_name, car_class)
        except Exception as e:
            log.warning("récords para %s falló (uso BD): %s", track_name, e)
            record = _load_record_db(db, track_name, car_class)

    # --- 2) Videos YouTube ---
    videos, _ = _load_videos_db(db, track_name, car_class)
    if videos is None:
        try:
            found = _search_and_rank(track_name, car_class, limit)
            if found:
                _store_videos_db(db, track_name, car_class, found)
                videos = found
        except Exception as e:
            log.warning("videos para %s falló (uso BD): %s", track_name, e)
            videos, _ = _load_videos_db(db, track_name, car_class, ttl=timedelta(days=365))

    return {
        "track_name": track_name,
        "car_class": car_class,
        "record": record,
        "videos": videos or [],
    }
