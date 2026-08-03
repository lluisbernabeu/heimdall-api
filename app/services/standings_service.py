# Heimdall API — Clasificación de temporada por división.
# Los standings completos están cacheados en api_cache (lfm:standings:{eid})
# por el sync. Aquí se construye el leaderboard de la división del usuario:
# su posición, vecinos, puntos por semana, y cuánto le falta para subir.
from ..models import ApiCache, LfmProfile, Race


def _week_keys(entry: dict) -> list[str]:
    return [k for k in entry.keys() if k.startswith("week_")]


def division_standings(db, profile_id: int, event_id: int,
                       car_class: str | None = None,
                       neighbors: int = 5) -> dict | None:
    """Leaderboard de la división del usuario en un evento.
    Devuelve: {event_name, car_class, division, my_position, my_entry,
    ahead, behind, top, updated} o None si no hay datos.
    """
    prof = db.query(LfmProfile).filter_by(id=profile_id).first()
    if not prof:
        return None
    row = db.query(ApiCache).filter_by(key=f"lfm:standings:{event_id}").first()
    if not row or not row.payload:
        return None
    data = row.payload  # {car_class: {div: [entries]}}

    # Elegir clase: la pedida o la primera donde esté el usuario
    classes = [c for c in data.keys() if isinstance(data.get(c), dict)]
    if car_class and car_class in classes:
        classes = [car_class] + [c for c in classes if c != car_class]
    for cls in classes:
        divisions = data[cls]
        if not isinstance(divisions, dict):
            continue
        # División del usuario (por su perfil o buscando en entries)
        my_division = None
        for div, entries in divisions.items():
            if not isinstance(entries, list):
                continue
            if any(e.get("user_id") == prof.lfm_user_id for e in entries):
                my_division = div
                break
        if my_division is None:
            continue
        entries = divisions[my_division]
        if not isinstance(entries, list) or not entries:
            continue
        sorted_entries = sorted(entries,
                                key=lambda e: (e.get("position") is None,
                                               e.get("position") or 99999))
        # Posición del usuario
        my_idx = None
        for i, e in enumerate(sorted_entries):
            if e.get("user_id") == prof.lfm_user_id:
                my_idx = i
                break
        if my_idx is None:
            # El usuario no está en esta división (aún): mostrar top
            return _build(db, cls, my_division, sorted_entries, None, neighbors,
                          row.fetched_at, event_id)
        return _build(db, cls, my_division, sorted_entries, my_idx, neighbors,
                      row.fetched_at, event_id)
    return None


def _build(db, car_class, division, entries, my_idx, neighbors, fetched_at,
           event_id):
    def _short(e):
        wk = {}
        for k in _week_keys(e):
            v = e.get(k)
            if v:
                wk[k.replace("week_", "S")] = v
        return {
            "position": e.get("position"),
            "user_id": e.get("user_id"),
            "name": f"{e.get('vorname') or ''} {e.get('nachname') or ''}".strip(),
            "shortname": e.get("shortname"),
            "origin": e.get("origin"),
            "races": e.get("races"),
            "points": e.get("points"),
            "elo": e.get("elo"),
            "weeks_counted": e.get("weeks_counted"),
            "weeks": wk,
        }

    top = [_short(e) for e in entries[:10]]
    my_entry = _short(entries[my_idx]) if my_idx is not None else None

    ahead = []
    behind = []
    if my_idx is not None:
        for i in range(max(0, my_idx - neighbors), my_idx):
            ahead.append(_short(entries[i]))
        for i in range(my_idx + 1, min(len(entries), my_idx + neighbors + 1)):
            behind.append(_short(entries[i]))

    # Cuánto le falta para subir (diferencia con el de delante)
    next_up = None
    if my_idx is not None and my_idx > 0:
        nxt = entries[my_idx - 1]
        cur_pts = (entries[my_idx].get("points") or 0)
        next_up = {
            "name": f"{nxt.get('vorname') or ''} {nxt.get('nachname') or ''}".strip(),
            "points": nxt.get("points"),
            "gap_points": (nxt.get("points") or 0) - cur_pts,
        }

    total = len(entries)
    return {
        "event_id": event_id,
        "car_class": car_class,
        "division": division,
        "total": total,
        "my_position": (my_idx + 1) if my_idx is not None else None,
        "my_entry": my_entry,
        "ahead": ahead,
        "behind": behind,
        "next_up": next_up,
        "top": top,
        "updated": fetched_at.isoformat() if fetched_at else None,
    }


def my_events(db, profile_id: int) -> list[dict]:
    """Eventos donde el usuario ha corrido (para la lista de clasificaciones)."""
    rows = (db.query(Race.event_id, Race.event_name)
            .filter(Race.profile_id == profile_id,
                    Race.event_id.isnot(None))
            .distinct().order_by(Race.event_name).all())
    return [{"event_id": e, "event_name": n} for e, n in rows]
