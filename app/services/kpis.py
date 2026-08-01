# Heimdall API — KPIs: métricas y análisis calculados sobre la BD local
# Todo se sirve desde datos ya sincronizados (sin llamadas a LFM).
import statistics
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import LfmProfile, Race, Lap, Incident, Standing


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
            "car_number": race.car_number,
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
        out.append({
            "race_id": race.id,
            "event_name": race.event_name,
            "track_name": race.track_name,
            "race_date": race.race_date.isoformat() if race.race_date else None,
            "split": race.split,
            "my_s1": _fmt_ms(my_s1), "my_s1_ms": my_s1,
            "my_s2": _fmt_ms(my_s2), "my_s2_ms": my_s2,
            "my_s3": _fmt_ms(my_s3), "my_s3_ms": my_s3,
            "best_s1": _fmt_ms(best_s1), "best_s1_ms": best_s1,
            "best_s2": _fmt_ms(best_s2), "best_s2_ms": best_s2,
            "best_s3": _fmt_ms(best_s3), "best_s3_ms": best_s3,
            "gap_s1_ms": (my_s1 - best_s1) if (my_s1 and best_s1) else None,
            "gap_s2_ms": (my_s2 - best_s2) if (my_s2 and best_s2) else None,
            "gap_s3_ms": (my_s3 - best_s3) if (my_s3 and best_s3) else None,
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
    """Distribución de incidentes: minuto de carrera y tipo."""
    races = (db.query(Race.id).filter_by(profile_id=profile_id)).all()
    race_ids = [r[0] for r in races]
    if not race_ids:
        return {"by_minute": {}, "by_type": {}, "total": 0}
    incs = (db.query(Incident).filter(Incident.race_id.in_(race_ids))
            .filter(Incident.server_time_ms.isnot(None)).all())
    by_minute = {}
    by_type = {}
    for i in incs:
        minute = int(i.server_time_ms // 60000)
        by_minute[minute] = by_minute.get(minute, 0) + 1
        t = i.incident_type or "?"
        by_type[t] = by_type.get(t, 0) + 1
    return {"by_minute": by_minute, "by_type": by_type, "total": len(incs)}


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
