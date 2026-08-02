# Heimdall API — KPIs: métricas y análisis calculados sobre la BD local
# Todo se sirve desde datos ya sincronizados (sin llamadas a LFM).
import statistics
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import LfmProfile, Race, Lap, Incident, Standing, PositionChart

# --- Logos de copas/series (CDN público de LFM) ---
# Mapea fabricante -> nombre del logo en el CDN. El fabricante se extrae
# del car_name (primera palabra). Fallback: None (la app muestra un icono).
_MANUFACTURER_LOGOS = {
    "mazda": "mazda", "audi": "audi", "hyundai": "hyundai", "cupra": "cupra",
    "bmw": "bmw", "mercedes": "mercedes", "porsche": "porsche", "ferrari": "ferrari",
    "toyota": "toyota", "volkswagen": "volkswagen", "vw": "volkswagen",
    "seat": "seat", "honda": "honda", "ford": "ford", "renault": "renault",
    "peugeot": "peugeot", "skoda": "skoda", "aston": "aston_martin",
    "lamborghini": "lamborghini", "mclaren": "mclaren", "nissan": "nissan",
    "alpine": "alpine", "alfa": "alfa_romeo", "lexus": "lexus", "corvette": "corvette",
}
LOGO_CDN = "https://cdn.lowfuelmotorsport.com/images/manufacturers/{name}.png"

# --- Explicaciones de tipos de incidente LFM (es-ES) ---
# Fuente: bundle JS oficial de lowfuelmotorsport.com (tabla de vueltas + leyenda SR):
#   C -> "1x"  = Track cut (corte de pista): 1 punto de incidente, la vuelta NO cuenta
#   D -> "4x"  = Daño/contacto (coches o muro): 4 puntos de incidente
#   R -> "-2x" = Riego (relaunch del servidor en carrera)
INCIDENT_EXPLAIN = {
    "C": {"label": "Corte de pista (cut)", "icon": "✂️",
          "msg": "Cortaste la pista (4 ruedas fuera de los límites) y la vuelta no contó. Cuesta 1 punto de incidente."},
    "D": {"label": "Contacto / daño", "icon": "💥",
          "msg": "Hubo contacto con daño (otro coche o muro). Es lo que más sube tus puntos de incidente (4x)."},
    "O": {"label": "Fuera de pista", "icon": "🚧",
          "msg": "Te saliste de los límites de pista. Acumular muchos resta SR."},
    "R": {"label": "Riego (relaunch)", "icon": "🔁",
          "msg": "Reinicio del servidor en carrera."},
}


def car_logo_url(car_name):
    """Devuelve la URL del logo del fabricante a partir del car_name, o None."""
    if not car_name:
        return None
    first = car_name.split()[0].lower()
    key = _MANUFACTURER_LOGOS.get(first)
    if not key:
        return None
    return LOGO_CDN.format(name=key)


def _sec(ms):
    if ms is None:
        return None
    return ms / 1000.0


def _fmt_ms(ms):
    if ms is None:
        return None
    total = int(round(ms))
    m, s = divmod(total, 60000)
    s /= 1000.0
    return f"{m}:{s:06.3f}"


def overview(db: Session, profile_id: int):
    profile = db.query(LfmProfile).filter_by(id=profile_id).first()
    if not profile:
        return None
    races = (db.query(Race).filter_by(profile_id=profile_id)
             .order_by(Race.race_date.desc()).all())
    finished = [r for r in races if not r.dns and not r.dsq and r.finish_pos]
    n = len(races)
    wins = sum(1 for r in finished if r.finish_pos == 1)
    podiums = sum(1 for r in finished if r.finish_pos <= 3)
    top5 = sum(1 for r in finished if r.finish_pos <= 5)
    avg_finish = round(statistics.mean([r.finish_pos for r in finished]), 2) if finished else None
    best = min((r.finish_pos for r in finished), default=None)
    bow = sum(1 for r in races if r.best_of_week)
    total_incs = sum(r.incidents or 0 for r in races)
    avg_incs = round(total_incs / n, 1) if n else None
    rating_changes = [r.rating_change for r in races if r.rating_change is not None]
    sr_changes = [r.sr_change for r in races if r.sr_change is not None]
    rating_trend = round(sum(rating_changes[-5:]), 1) if rating_changes else None
    sr_trend = round(sum(sr_changes[-5:]), 2) if sr_changes else None

    # último split y evolución
    last_races = races[:10]
    return {
        "profile": {
            "lfm_user_id": profile.lfm_user_id,
            "username": profile.username,
            "vorname": profile.vorname,
            "nachname": profile.nachname,
            "origin": profile.origin,
            "avatar": profile.avatar,
            "license": profile.license,
            "safety_rating": profile.safety_rating,
            "division": profile.division,
            "team_name": profile.team_name,
            "team_logo": profile.team_logo,
        },
        "stats": {
            "races": n,
            "wins": wins,
            "podiums": podiums,
            "top5": top5,
            "win_rate": round(100 * wins / n, 1) if n else 0,
            "podium_rate": round(100 * podiums / n, 1) if n else 0,
            "avg_finish": avg_finish,
            "best_finish": best,
            "best_of_week": bow,
            "avg_incidents": avg_incs,
            "total_incidents": total_incs,
            "rating_trend_5": rating_trend,
            "sr_trend_5": sr_trend,
        },
        "last_races": [
            {
                "race_id": r.id,
                "lfm_race_id": r.lfm_race_id,
                "event_name": r.event_name,
                "track_name": r.track_name,
                "race_date": r.race_date.isoformat() if r.race_date else None,
                "finish_pos": r.finish_pos,
                "split": r.split,
                "start_pos": r.start_pos,
                "rating_change": r.rating_change,
                "sr_change": r.sr_change,
                "incidents": r.incidents,
                "best_lap": r.best_lap,
                "best_of_week": r.best_of_week,
                "points": r.points,
                "car_name": r.car_name,
                "car_logo": car_logo_url(r.car_name),
            }
            for r in last_races
        ],
    }


def progression(db: Session, profile_id: int):
    """Serie temporal de rating y SR por carrera."""
    races = (db.query(Race).filter_by(profile_id=profile_id)
             .filter(Race.race_date.isnot(None))
             .order_by(Race.race_date.asc()).all())
    pts = []
    rating = 1500.0
    sr = 3.0
    for r in races:
        if r.rating_change is not None:
            rating += r.rating_change
        if r.sr_change is not None:
            sr = max(0.0, sr + r.sr_change)
        pts.append({
            "date": r.race_date.isoformat(),
            "event": r.event_name,
            "track": r.track_name,
            "finish_pos": r.finish_pos,
            "rating": round(rating, 0),
            "sr": round(sr, 2),
        })
    return pts


def race_detail(db: Session, profile_id: int, race_pk: int):
    race = db.query(Race).filter_by(id=race_pk, profile_id=profile_id).first()
    if not race:
        return None
    profile = db.query(LfmProfile).filter_by(id=profile_id).first()
    # pilotos del split: agrupar vueltas por lfm_user_id
    laps = (db.query(Lap).filter_by(race_id=race.id)
            .order_by(Lap.lfm_user_id, Lap.car_lap).all())
    by_user = {}
    for L in laps:
        by_user.setdefault(L.lfm_user_id, []).append(L)
    # mejor vuelta por piloto + tiempos
    pilots = []
    for uid, ulaps in by_user.items():
        valid = [L for L in ulaps if L.lap_valid and L.lap_time_ms]
        best = min(valid, key=lambda L: L.lap_time_ms) if valid else None
        name = ulaps[0].driver_name or str(uid)
        pilots.append({
            "user_id": uid,
            "name": name,
            "best_lap": _fmt_ms(best.lap_time_ms) if best else None,
            "best_lap_ms": best.lap_time_ms if best else None,
            "laps": len(ulaps),
            "avg_lap_ms": round(statistics.mean([L.lap_time_ms for L in valid]), 1) if valid else None,
        })
    pilots.sort(key=lambda p: (p["best_lap_ms"] is None, p["best_lap_ms"] or 0))

    # El piloto del usuario: identificar por nombre del perfil
    my_uid = None
    my_name = f"{profile.vorname or ''} {profile.nachname or ''}".strip().lower()
    for uid, ulaps in by_user.items():
        nm = (ulaps[0].driver_name or "").lower()
        if my_name and (my_name in nm or nm in my_name):
            my_uid = uid
            break
    if my_uid is None:
        # fallback: el usuario con más vueltas (suele ser el propio)
        my_uid = max(by_user, key=lambda u: len(by_user[u])) if by_user else None

    my_laps = sorted(by_user.get(my_uid, []), key=lambda L: L.car_lap or 0)
    # delta por vuelta vs el más rápido del split (misma vuelta)
    lap_chart = []
    fastest_by_lap = {}
    for uid, ulaps in by_user.items():
        for L in ulaps:
            if L.lap_valid and L.lap_time_ms and L.car_lap is not None:
                cur = fastest_by_lap.get(L.car_lap)
                if cur is None or L.lap_time_ms < cur:
                    fastest_by_lap[L.car_lap] = L.lap_time_ms
    for L in my_laps:
        if L.car_lap is None:
            continue
        ref = fastest_by_lap.get(L.car_lap)
        lap_chart.append({
            "lap": L.car_lap,
            "time_ms": L.lap_time_ms,
            "s1_ms": L.s1_ms,
            "s2_ms": L.s2_ms,
            "s3_ms": L.s3_ms,
            "valid": L.lap_valid,
            "gap_to_fastest_ms": (L.lap_time_ms - ref) if (L.lap_time_ms and ref) else None,
        })

    incidents = (db.query(Incident).filter_by(race_id=race.id, lfm_user_id=my_uid)
                 .order_by(Incident.server_time_ms).all())
    return {
        "race": {
            "id": race.id,
            "lfm_race_id": race.lfm_race_id,
            "event_name": race.event_name,
            "track_name": race.track_name,
            "race_date": race.race_date.isoformat() if race.race_date else None,
            "finish_pos": race.finish_pos,
            "start_pos": race.start_pos,
            "split": race.split,
            "sof": race.sof,
            "best_lap": race.best_lap,
            "incidents": race.incidents,
            "rating_change": race.rating_change,
            "sr_change": race.sr_change,
            "points": race.points,
            "car_name": race.car_name,
            "car_logo": car_logo_url(race.car_name),
        },
        "pilots": pilots,
        "my_user_id": my_uid,
        "my_laps": [
            {
                "lap": L.car_lap,
                "time_ms": L.lap_time_ms,
                "s1_ms": L.s1_ms,
                "s2_ms": L.s2_ms,
                "s3_ms": L.s3_ms,
                "valid": L.lap_valid,
            }
            for L in my_laps
        ],
        "lap_chart": lap_chart,
        "incidents": [
            {
                "type": i.incident_type,
                "time": i.session_time,
                "server_time_ms": i.server_time_ms,
            }
            for i in incidents
        ],
    }


def sectors_analysis(db: Session, profile_id: int):
    """Comparativa de sectores en las carreras con vueltas detalladas:
    mejor S1/S2/S3 del usuario vs el mejor absoluto de cada carrera."""
    races = (db.query(Race).filter_by(profile_id=profile_id)
             .filter(Race.race_date.isnot(None))
             .order_by(Race.race_date.desc()).all())
    out = []
    for race in races:
        laps = db.query(Lap).filter_by(race_id=race.id).all()
        if not laps:
            continue
        my_name = f"{_profile_name(db, profile_id)}".lower()
        mine = [L for L in laps if my_name in (L.driver_name or "").lower()]
        if not mine:
            continue
        best_s1 = min((L.s1_ms for L in laps if L.lap_valid and L.s1_ms), default=None)
        best_s2 = min((L.s2_ms for L in laps if L.lap_valid and L.s2_ms), default=None)
        best_s3 = min((L.s3_ms for L in laps if L.lap_valid and L.s3_ms), default=None)
        my_s1 = min((L.s1_ms for L in mine if L.lap_valid and L.s1_ms), default=None)
        my_s2 = min((L.s2_ms for L in mine if L.lap_valid and L.s2_ms), default=None)
        my_s3 = min((L.s3_ms for L in mine if L.lap_valid and L.s3_ms), default=None)
        g1 = (my_s1 - best_s1) if (my_s1 and best_s1) else None
        g2 = (my_s2 - best_s2) if (my_s2 and best_s2) else None
        g3 = (my_s3 - best_s3) if (my_s3 and best_s3) else None
        gaps = [g for g in (g1, g2, g3) if g is not None]
        out.append({
            "race_id": race.id,
            "event_name": race.event_name,
            "track_name": race.track_name,
            "race_date": race.race_date.isoformat() if race.race_date else None,
            "split": race.split,
            "laps": len([L for L in mine if L.lap_valid]),
            "my_s1": _fmt_ms(my_s1), "my_s1_ms": my_s1,
            "my_s2": _fmt_ms(my_s2), "my_s2_ms": my_s2,
            "my_s3": _fmt_ms(my_s3), "my_s3_ms": my_s3,
            "best_s1": _fmt_ms(best_s1), "best_s1_ms": best_s1,
            "best_s2": _fmt_ms(best_s2), "best_s2_ms": best_s2,
            "best_s3": _fmt_ms(best_s3), "best_s3_ms": best_s3,
            "gap_s1_ms": g1,
            "gap_s2_ms": g2,
            "gap_s3_ms": g3,
            "total_gap_ms": round(sum(gaps), 1) if gaps else None,
        })
    return out


def consistency_analysis(db: Session, profile_id: int):
    """Desviación estándar de tiempos por carrera (solo vueltas válidas) -> consistencia."""
    races = (db.query(Race).filter_by(profile_id=profile_id)
             .filter(Race.race_date.isnot(None))
             .order_by(Race.race_date.asc()).all())
    my_name = _profile_name(db, profile_id).lower()
    out = []
    for race in races:
        laps = db.query(Lap).filter_by(race_id=race.id).all()
        mine = [L for L in laps if my_name in (L.driver_name or "").lower()
                and L.lap_valid and L.lap_time_ms]
        if len(mine) < 3:
            continue
        times = [L.lap_time_ms for L in mine]
        out.append({
            "race_id": race.id,
            "event_name": race.event_name,
            "track_name": race.track_name,
            "race_date": race.race_date.isoformat() if race.race_date else None,
            "laps": len(times),
            "avg_ms": round(statistics.mean(times), 1),
            "std_ms": round(statistics.pstdev(times), 1),
            "best_ms": min(times),
            "worst_ms": max(times),
            "spread_ms": max(times) - min(times),
        })
    return out


def incidents_heatmap(db: Session, profile_id: int):
    """Distribución de incidentes: minuto de carrera y tipo.
    SOLO los incidentes del piloto (antes contaba los de todo el split)."""
    prof = db.query(LfmProfile).filter_by(id=profile_id).first()
    if not prof:
        return {"by_minute": {}, "by_type": {}, "total": 0}
    races = (db.query(Race.id).filter_by(profile_id=profile_id)).all()
    race_ids = [r[0] for r in races]
    if not race_ids:
        return {"by_minute": {}, "by_type": {}, "total": 0}
    incs = (db.query(Incident)
            .filter(Incident.race_id.in_(race_ids))
            .filter(Incident.lfm_user_id == prof.lfm_user_id)
            .filter(Incident.server_time_ms.isnot(None)).all())
    by_minute = {}
    by_type = {}
    # Por carrera: track + fecha + conteo por tipo
    race_cache = {}
    for rid in race_ids:
        r = db.query(Race).filter_by(id=rid).first()
        if r:
            race_cache[rid] = r
    by_race = {}
    for i in incs:
        minute = int(i.server_time_ms // 60000)
        by_minute[minute] = by_minute.get(minute, 0) + 1
        t = i.incident_type or "?"
        by_type[t] = by_type.get(t, 0) + 1
        rid = i.race_id
        slot = by_race.setdefault(rid, {"track": None, "event": None, "date": None, "counts": {}})
        slot["counts"][t] = slot["counts"].get(t, 0) + 1
    by_race_list = []
    for rid, slot in by_race.items():
        r = race_cache.get(rid)
        by_race_list.append({
            "race_id": rid,
            "track_name": r.track_name if r else None,
            "event_name": r.event_name if r else None,
            "race_date": r.race_date.isoformat() if r and r.race_date else None,
            "split": r.split if r else None,
            "finish_pos": r.finish_pos if r else None,
            "total": sum(slot["counts"].values()),
            "counts": slot["counts"],
        })
    # Orden: más incidentes primero
    by_race_list.sort(key=lambda x: -x["total"])
    return {"by_minute": by_minute, "by_type": by_type, "by_race": by_race_list, "total": len(incs)}


def incidents_detail(db: Session, profile_id: int, race_pk: int):
    """Incidentes individuales de UNA carrera del piloto, con vuelta estimada.

    La vuelta se estima acumulando los tiempos de vuelta del propio piloto:
    el incidente ocurre en la vuelta cuyo rango de tiempo de sesión contiene
    server_time_ms. Si ocurre antes de completar la vuelta 1 -> vuelta 1.
    """
    race = db.query(Race).filter_by(id=race_pk, profile_id=profile_id).first()
    if not race:
        return None
    prof = db.query(LfmProfile).filter_by(id=profile_id).first()
    if not prof:
        return None
    my_name = _profile_name(db, profile_id).lower()
    laps = (db.query(Lap).filter_by(race_id=race.id)
            .order_by(Lap.car_lap).all())
    mine = [L for L in laps if my_name in (L.driver_name or "").lower()
            and L.lap_valid and L.lap_time_ms]
    # acumulado de tiempo de sesión por vuelta (inicio de cada vuelta)
    bounds = []
    acc = 0
    for L in mine:
        bounds.append((acc, L.car_lap))
        acc += L.lap_time_ms or 0
    bounds.append((acc, (mine[-1].car_lap or 0) + 1))  # cierre

    def _lap_of(ts):
        if ts is None:
            return None
        for i in range(len(bounds) - 1):
            if bounds[i][0] <= ts < bounds[i + 1][0]:
                return bounds[i][1]
        return bounds[-1][1] if bounds else None

    incs = (db.query(Incident).filter_by(race_id=race.id, lfm_user_id=prof.lfm_user_id)
            .order_by(Incident.server_time_ms).all())
    out = []
    for i in incs:
        out.append({
            "type": i.incident_type,
            "session_time": i.session_time,
            "server_time_ms": i.server_time_ms,
            "lap": _lap_of(i.server_time_ms),
        })
    counts = {}
    for i in out:
        t = i["type"] or "?"
        counts[t] = counts.get(t, 0) + 1
    return {
        "race": {
            "id": race.id,
            "event_name": race.event_name,
            "track_name": race.track_name,
            "race_date": race.race_date.isoformat() if race.race_date else None,
            "split": race.split,
            "finish_pos": race.finish_pos,
            "start_pos": race.start_pos,
            "laps": race.laps,
            "incidents": race.incidents,
        },
        "total": len(out),
        "counts": counts,
        "items": out,
    }


def standings_view(db: Session, profile_id: int):
    sts = (db.query(Standing).filter_by(profile_id=profile_id)
           .order_by(Standing.event_id).all())
    return [
        {
            "event_id": s.event_id,
            "event_name": s.event_name,
            "car_class": s.car_class,
            "position": s.position,
            "races": s.races,
            "points": s.points,
            "elo": s.elo,
            "division": s.division,
            "week_points": s.week_points or {},
        }
        for s in sts
    ]


def compare(db: Session, profile_a: int, profile_b: int):
    """Comparativa head-to-head de dos perfiles."""
    def _agg(pid):
        races = (db.query(Race).filter_by(profile_id=pid)
                 .filter(Race.race_date.isnot(None))
                 .order_by(Race.race_date.asc()).all())
        laps = []
        for r in races:
            rs = db.query(Lap).filter_by(race_id=r.id).all()
            name = _profile_name(db, pid).lower()
            mine = [L for L in rs if name in (L.driver_name or "").lower()
                    and L.lap_valid and L.lap_time_ms]
            laps.extend(mine)
        n = len(races)
        finished = [r for r in races if not r.dns and not r.dsq and r.finish_pos]
        podiums = sum(1 for r in finished if r.finish_pos <= 3)
        wins = sum(1 for r in finished if r.finish_pos == 1)
        avg_incs = round(statistics.mean([r.incidents or 0 for r in races]), 1) if n else 0
        std = round(statistics.pstdev([L.lap_time_ms for L in laps]), 1) if len(laps) >= 3 else None
        best = min((L.lap_time_ms for L in laps), default=None)
        prof = db.query(LfmProfile).filter_by(id=pid).first()
        return {
            "id": pid,
            "name": f"{prof.vorname or ''} {prof.nachname or ''}".strip() or prof.username,
            "lfm_user_id": prof.lfm_user_id,
            "avatar": prof.avatar,
            "license": prof.license,
            "safety_rating": prof.safety_rating,
            "division": prof.division,
            "rating": prof.c_rating,
            "races": n,
            "wins": wins,
            "podiums": podiums,
            "avg_finish": round(statistics.mean([r.finish_pos for r in finished]), 2) if finished else None,
            "avg_incidents": avg_incs,
            "best_lap_ms": best,
            "best_lap": _fmt_ms(best),
            "consistency_std_ms": std,
        }
    a = _agg(profile_a)
    b = _agg(profile_b)
    return {"a": a, "b": b}


def _profile_name(db: Session, profile_id: int) -> str:
    p = db.query(LfmProfile).filter_by(id=profile_id).first()
    if not p:
        return ""
    return f"{p.vorname or ''} {p.nachname or ''}".strip()


def insight(db: Session, profile_id: int):
    """Veredicto en lenguaje natural sobre la forma actual del piloto.

    Combina tendencia de rating/SR, incidentes, sector más débil y última
    carrera para decir QUÉ está pasando, no solo mostrar números.
    """
    ov = overview(db, profile_id)
    if not ov:
        return None
    profile = ov["profile"]
    s = ov["stats"]
    last = (ov["last_races"] or [{}])[0]
    sectors = sectors_analysis(db, profile_id)

    name = (f"{profile.get('vorname') or ''} {profile.get('nachname') or ''}"
            .strip() or profile.get("username") or "Piloto")
    rt = s.get("rating_trend_5")
    st = s.get("sr_trend_5")
    avg_inc = s.get("avg_incidents") or 0

    # --- Veredicto general ---
    if rt is not None and rt <= -100:
        verdict = {
            "title": "En caída",
            "emoji": "📉",
            "tone": "red",
            "msg": (f"{name}, tu rating ha perdido {abs(rt):.0f} puntos en las "
                    f"últimas 5 carreras. La buena noticia: tu último resultado "
                    f"remonta la tendencia."),
        }
    elif rt is not None and rt >= 100:
        verdict = {
            "title": "En racha",
            "emoji": "🔥",
            "tone": "green",
            "msg": (f"{name}, vas como un tiro: +{rt:.0f} puntos de rating en "
                    f"las últimas 5 carreras. Sigue así."),
        }
    else:
        verdict = {
            "title": "Estable",
            "emoji": "⚖️",
            "tone": "cyan",
            "msg": (f"{name}, tu rating se mantiene estable en las últimas 5 "
                    f"carreras. El margen está en los detalles."),
        }

    # --- Señal 1: incidentes (lo que más hunde SR) ---
    insights = []
    sr_now = profile.get("safety_rating")
    if avg_inc >= 10:
        insights.append({
            "icon": "warning",
            "tone": "red",
            "title": "Demasiados incidentes",
            "msg": (f"Promedias {avg_inc:.1f} incidentes por carrera — eso es "
                    f"lo que está hundiendo tu SR ({sr_now}). "
                    f"Bajar a <6 por carrera cambiaría tu curva por completo."),
        })
    elif avg_inc >= 6:
        insights.append({
            "icon": "warning",
            "tone": "orange",
            "title": "Incidentes a vigilar",
            "msg": (f"Promedias {avg_inc:.1f} incidentes por carrera. "
                    f"Reducirlos a la mitad te subiría el SR de forma clara."),
        })
    else:
        insights.append({
            "icon": "shield",
            "tone": "green",
            "title": "Conducción limpia",
            "msg": (f"Solo {avg_inc:.1f} incidentes de media por carrera — "
                    f"tu SR agradece la limpieza."),
        })

    # --- Señal 2: sector más débil ---
    if sectors:
        gaps = {
            "S1": [x.get("gap_s1_ms") for x in sectors if x.get("gap_s1_ms")],
            "S2": [x.get("gap_s2_ms") for x in sectors if x.get("gap_s2_ms")],
            "S3": [x.get("gap_s3_ms") for x in sectors if x.get("gap_s3_ms")],
        }
        avg_gap = {k: sum(v) / len(v) for k, v in gaps.items() if v}
        if avg_gap:
            weak = max(avg_gap, key=lambda k: avg_gap[k])
            strong = min(avg_gap, key=lambda k: avg_gap[k])
            w_ms = avg_gap[weak]
            s_ms = avg_gap[strong]
            if w_ms >= 300:
                insights.append({
                    "icon": "sector",
                    "tone": "red",
                    "title": f"Tu sector más flojo es {weak}",
                    "msg": (f"De media pierdes {(w_ms/1000):.2f}s en {weak} "
                            f"contra el más rápido del split. Si lo recortas "
                            f"a la mitad, ganas ~{(w_ms/2000):.2f}s por vuelta."),
                })
            else:
                insights.append({
                    "icon": "sector",
                    "tone": "green",
                    "title": f"Sectores equilibrados",
                    "msg": (f"Tu peor sector ({weak}) solo te cuesta "
                            f"{(w_ms/1000):.2f}s — buen equilibrio general."),
                })

    # --- Señal 3: última carrera ---
    if last and last.get("finish_pos"):
        rc = last.get("rating_change")
        bow = last.get("best_of_week")
        if rc is not None and rc > 0:
            extra = " ¡Y Best of Week! ⭐" if bow else ""
            insights.append({
                "icon": "trophy",
                "tone": "green",
                "title": f"P{last['finish_pos']} en {last.get('track_name')}",
                "msg": (f"Tu última carrera sumó +{rc:.0f} de rating "
                        f"({last.get('event_name')}).{extra}"),
            })
        elif rc is not None:
            insights.append({
                "icon": "trophy",
                "tone": "cyan",
                "title": f"P{last['finish_pos']} en {last.get('track_name')}",
                "msg": (f"Tu última carrera restó {rc:.0f} de rating "
                        f"({last.get('event_name')}). Toca analizar qué pasó."),
            })

    # --- Qué hacer ahora ---
    action = None
    if avg_inc >= 10:
        action = {
            "icon": "target",
            "title": "Tu prioridad: supervivencia",
            "msg": ("Una carrera limpia (0-3 incidentes) vale más que "
                    "10 décimas de ritmo. Corre al 90% y deja pasar las "
                    "peleas de la primera vuelta."),
        }
    elif sectors:
        gaps = {
            "S1": [x.get("gap_s1_ms") for x in sectors if x.get("gap_s1_ms")],
            "S2": [x.get("gap_s2_ms") for x in sectors if x.get("gap_s2_ms")],
            "S3": [x.get("gap_s3_ms") for x in sectors if x.get("gap_s3_ms")],
        }
        avg_gap = {k: sum(v) / len(v) for k, v in gaps.items() if v}
        if avg_gap:
            weak = max(avg_gap, key=lambda k: avg_gap[k])
            action = {
                "icon": "target",
                "title": f"Entrena {weak}",
                "msg": (f"Practica {weak} en solitario hasta igualar al más "
                        f"rápido del split — es tu mayor margen de mejora."),
            }
        else:
            action = {
                "icon": "target",
                "title": "Sigue acumulando carreras",
                "msg": "Cuantas más carreras limpias, más sube todo. La constancia gana.",
            }
    else:
        action = {
            "icon": "target",
            "title": "Sigue acumulando carreras",
            "msg": "Cuantas más carreras limpias, más sube todo. La constancia gana.",
        }

    return {
        "profile_name": name,
        "verdict": verdict,
        "insights": insights,
        "action": action,
    }


def race_story(db: Session, profile_id: int, race_pk: int):
    """Explica QUÉ pasó en la carrera: posición vuelta a vuelta, cuándo
    perdiste/ganaste posiciones y por qué (vueltas lentas, incidentes,
    sanciones). Además: qué hicieron los pilotos que quedaron por delante."""
    race = db.query(Race).filter_by(id=race_pk, profile_id=profile_id).first()
    if not race:
        return None
    profile = db.query(LfmProfile).filter_by(id=profile_id).first()
    my_name = f"{profile.vorname or ''} {profile.nachname or ''}".strip().lower()
    my_uid = profile.lfm_user_id

    laps = (db.query(Lap).filter_by(race_id=race.id)
            .order_by(Lap.car_lap, Lap.lfm_user_id).all())
    by_user = {}
    for L in laps:
        by_user.setdefault(L.lfm_user_id, []).append(L)

    # Identificar al usuario (por nombre o por lfm_user_id)
    if my_uid in by_user:
        my_laps = by_user[my_uid]
    else:
        my_laps = []
        for uid, ulaps in by_user.items():
            nm = (ulaps[0].driver_name or "").lower()
            if my_name and (my_name in nm or nm in my_name):
                my_uid, my_laps = uid, ulaps
                break
    if not my_laps:
        # Carrera sin vueltas descargadas del usuario: devolver estructura
        # completa (con datos de la carrera) para que la app no pinte "null".
        return {
            "race": {
                "id": race.id,
                "event_name": race.event_name,
                "track_name": race.track_name,
                "start_pos": race.start_pos,
                "finish_pos": race.finish_pos,
                "incidents": race.incidents,
                "car_name": race.car_name,
                "car_logo": car_logo_url(race.car_name),
                "race_date": race.race_date.isoformat() if race.race_date else None,
            },
            "summary": {
                "positions_gained": (race.start_pos - race.finish_pos)
                    if (race.start_pos and race.finish_pos) else 0,
                "total_incidents": race.incidents or 0,
                "first_incident_lap": None,
                "final_lap": None,
            },
            "position_events": [],
            "incidents": [],
            "laps": [],
            "ahead": [],
            "my_best_lap": None,
            "my_avg_lap": None,
            "my_std_lap": None,
            "no_laps": True,
        }

    # --- Clasificación vuelta a vuelta (position chart REAL de LFM) ---
    # Fuente: tabla position_chart, descargada del endpoint oficial
    # /api/race/{race_id}/positionChart/{split}. NADA inventado.
    chart_rows = (db.query(PositionChart)
                  .filter_by(race_id=race.id, lfm_user_id=my_uid)
                  .order_by(PositionChart.lap).all())
    # posición del usuario por vuelta: lap -> position
    my_positions = {c.lap: c.position for c in chart_rows}

    # --- Eventos de posición (cambios) con datos reales ---
    pos_events = []
    prev_pos = race.start_pos  # parrilla = posición oficial en vuelta 0
    for lap_num in sorted(my_positions):
        cur = my_positions[lap_num]
        if cur is None or cur == 0:
            continue  # sin posición registrada (vuelta de formación o DNF)
        if cur != prev_pos:
            delta = prev_pos - cur if prev_pos else 0
            pos_events.append({
                "lap": lap_num,
                "from_pos": prev_pos,
                "to_pos": cur,
                "delta": delta,  # positivo = ganaste posiciones
            })
            prev_pos = cur

    # --- Incidentes del usuario con explicación + vuelta aproximada ---
    incidents = (db.query(Incident).filter_by(race_id=race.id, lfm_user_id=my_uid)
                 .order_by(Incident.server_time_ms).all())
    # estimar vuelta desde server_time_ms: la vuelta 1 empieza en 0 y cada
    # vuelta dura ~ mejor tiempo medio. Usamos el tiempo acumulado del usuario.
    lap_start_ms = {}
    acc = 0
    for L in sorted(my_laps, key=lambda x: x.car_lap or 0):
        lap_start_ms[L.car_lap] = acc
        if L.lap_time_ms:
            acc += L.lap_time_ms
    last_lap = max([L.car_lap for L in my_laps if L.car_lap], default=1)
    race_duration = acc if acc > 0 else last_lap * 120000  # fallback ~2min/vuelta

    incident_events = []
    # mapa vuelta -> tiempo para detectar vueltas invalidadas por cut
    my_laps_by_num = {}
    for L in my_laps:
        if L.car_lap and L.lap_time:
            my_laps_by_num.setdefault(L.car_lap, []).append(L)
    for i in incidents:
        t = (i.incident_type or "?").upper()
        expl = INCIDENT_EXPLAIN.get(t, {"label": t, "icon": "⚠️", "msg": "Incidente registrado por LFM."})
        t_ms = i.server_time_ms or 0
        # estimar vuelta por el tiempo de carrera transcurrido
        est_lap = 1
        for ln, start in sorted(lap_start_ms.items()):
            if t_ms >= start:
                est_lap = ln
            else:
                break
        explanation = expl["msg"]
        # Si es un cut: buscar la vuelta invalidada más cercana para decir su tiempo
        if t == "C":
            cand = my_laps_by_num.get(est_lap) or my_laps_by_num.get(est_lap + 1) or []
            inv = [L for L in cand if not L.lap_valid and L.lap_time]
            if inv:
                explanation += (f" Tu vuelta {est_lap} ({inv[0].lap_time}) no contó "
                                f"para tu mejor tiempo.")
        incident_events.append({
            "type": t,
            "type_label": expl["label"],
            "icon": expl["icon"],
            "explanation": explanation,
            "time": i.session_time,
            "server_time_ms": t_ms,
            "lap": est_lap,
        })

    # --- Qué hicieron los que quedaron delante (top 3 del split) ---
    # Mejor vuelta, consistencia e incidentes de los 3 primeros del ranking final
    final_rank = []
    for uid, ulaps in by_user.items():
        valid = [L for L in ulaps if L.lap_valid and L.lap_time_ms]
        if not valid:
            continue
        times = [L.lap_time_ms for L in valid]
        final_rank.append({
            "user_id": uid,
            "name": ulaps[0].driver_name or str(uid),
            "best_ms": min(times),
            "avg_ms": round(statistics.mean(times), 1),
            "std_ms": round(statistics.pstdev(times), 1),
            "laps": len(times),
            "is_me": uid == my_uid,
        })
    final_rank.sort(key=lambda x: x["best_ms"])
    ahead = [p for p in final_rank if not p["is_me"]][:3]
    me_rank = next((p for p in final_rank if p["is_me"]), None)

    ahead_insights = []
    if me_rank and ahead:
        # consistencia (delta: va en segundos, es una diferencia)
        if ahead[0]["std_ms"] and me_rank["std_ms"]:
            if me_rank["std_ms"] > ahead[0]["std_ms"] * 1.5:
                ahead_insights.append({
                    "title": "Son más consistentes",
                    "msg": (f"Tu desviación por vuelta es {me_rank['std_ms']/1000:.2f}s, "
                            f"frente a {(ahead[0]['std_ms']/1000):.2f}s de {ahead[0]['name']}. "
                            f"Reducir tus errores te acerca a ellos más que ganar ritmo puro."),
                    "tone": "red",
                })
        # mejor vuelta (tiempos completos: formatear m:ss.mmm)
        if ahead[0]["best_ms"] and me_rank["best_ms"]:
            gap = (me_rank["best_ms"] - ahead[0]["best_ms"]) / 1000
            if gap > 0:
                ahead_insights.append({
                    "title": f"Te falta ritmo: {gap:.2f}s",
                    "msg": (f"Tu mejor vuelta es {_fmt_ms(me_rank['best_ms'])} y la de "
                            f"{ahead[0]['name']} {_fmt_ms(ahead[0]['best_ms'])}. "
                            f"Ese gap de {gap:.2f}s se nota en carrera."),
                    "tone": "cyan",
                })
            else:
                ahead_insights.append({
                    "title": "Tienes ritmo de sobra",
                    "msg": (f"Tu mejor vuelta ({_fmt_ms(me_rank['best_ms'])}) supera a la de "
                            f"{ahead[0]['name']} ({_fmt_ms(ahead[0]['best_ms'])}) "
                            f"por {abs(gap):.2f}s. El problema no es la velocidad."),
                    "tone": "green",
                })

    # --- Vuelta a vuelta: detalle completo para análisis ---
    # Cada vuelta del usuario: tiempo, splits, posición real, incidentes.
    laps_out = []
    for L in sorted(my_laps, key=lambda x: x.car_lap or 0):
        if not L.car_lap:
            continue
        laps_out.append({
            "lap": L.car_lap,
            "time": L.lap_time,
            "time_ms": L.lap_time_ms,
            "s1": L.s1, "s1_ms": L.s1_ms,
            "s2": L.s2, "s2_ms": L.s2_ms,
            "s3": L.s3, "s3_ms": L.s3_ms,
            "valid": bool(L.lap_valid),
            "position": my_positions.get(L.car_lap),
            "incidents": [e for e in incident_events if e["lap"] == L.car_lap],
        })

    return {
        "race": {
            "id": race.id,
            "event_name": race.event_name,
            "track_name": race.track_name,
            "start_pos": race.start_pos,
            "finish_pos": race.finish_pos,
            "incidents": race.incidents,
            "car_name": race.car_name,
            "car_logo": car_logo_url(race.car_name),
            "race_date": race.race_date.isoformat() if race.race_date else None,
        },
        "summary": {
            "positions_gained": race.start_pos - race.finish_pos
                if (race.start_pos and race.finish_pos) else 0,
            "total_incidents": race.incidents or 0,
            "first_incident_lap": next((e["lap"] for e in incident_events), None),
            "final_lap": last_lap,
        },
        "position_events": pos_events,
        "incidents": incident_events,
        "laps": laps_out,
        "ahead": ahead_insights,
        "my_best_lap": _fmt_ms(me_rank["best_ms"]) if me_rank else None,
        "my_avg_lap": _fmt_ms(me_rank["avg_ms"]) if me_rank else None,
        "my_std_lap": _fmt_ms(me_rank["std_ms"]) if me_rank else None,
    }
