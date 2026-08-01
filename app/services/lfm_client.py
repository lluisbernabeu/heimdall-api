# Heimdall API — cliente de la API pública de LFM
# Endpoints verificados manualmente (2026-08-01), todos públicos sin auth:
#   GET /api/race/{race_id}                          -> carrera completa (resultados, splits)
#   GET /api/race/{race_id}/getLapDetails/{result_id}-> vueltas con splits S1/S2/S3 + incidentes
#   GET /api/race/{race_id}/consistency/{split}      -> consistencia por piloto (%)
#   GET /api/race/{race_id}/positionChart/{split}    -> posiciones vuelta a vuelta
#   GET /api/users/getUserData/{user_id}             -> perfil completo
#   GET /api/users/getUsersPastRaces/{user_id}       -> historial de carreras (paginado)
#   GET /api/v2/seasons/getSeasonStandings/{season}  -> standings del campeonato
#   GET /api/v2/seasons/getSeasonTeamStandings/{season}
#   GET /api/v2/seasons/getSeasonWeeks/{season}
import json
import time
import urllib.request
import urllib.parse
import logging

from ..config import LFM_API_BASE, SYNC_DELAY_SECS

log = logging.getLogger("heimdall.lfm")

UA = "HeimdallApp/1.0 (LFM analytics; personal use)"


def _get(path, params=None, timeout=30, retries=3):
    url = LFM_API_BASE + path
    if params:
        qs = urllib.parse.urlencode(params)
        url += ("&" if "?" in url else "?") + qs
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last_err = e
            log.warning("LFM GET %s intento %d falló: %s", path, attempt + 1, e)
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"LFM API {path}: {last_err}")


def _t2ms(t):
    """'01:05.784' -> 65784 ms. None si no parseable."""
    if not t:
        return None
    try:
        p = t.split(":")
        if len(p) == 2:
            return int(p[0]) * 60000 + int(round(float(p[1]) * 1000))
        if len(p) == 3:
            return int(p[0]) * 3600000 + int(p[1]) * 60000 + int(round(float(p[2]) * 1000))
    except (ValueError, IndexError):
        return None
    return None


def get_user_data(user_id):
    return _get(f"/api/users/getUserData/{user_id}?with_achievements=true")


def get_user_past_races(user_id, start=0, limit=50, event="", season=""):
    return _get(f"/api/users/getUsersPastRaces/{user_id}",
                {"start": start, "limit": limit, "event": event, "season": season})


def get_race(race_id):
    return _get(f"/api/race/{race_id}")


def get_lap_details(race_id, result_id):
    return _get(f"/api/race/{race_id}/getLapDetails/{result_id}")


def get_consistency(race_id, split):
    return _get(f"/api/race/{race_id}/consistency/{split}")


def get_position_chart(race_id, split):
    return _get(f"/api/race/{race_id}/positionChart/{split}")


def get_season_standings(season_id):
    return _get(f"/api/v2/seasons/getSeasonStandings/{season_id}")


def get_season_weeks(season_id):
    return _get(f"/api/v2/seasons/getSeasonWeeks/{season_id}")


def sleep_between_calls():
    time.sleep(SYNC_DELAY_SECS)
