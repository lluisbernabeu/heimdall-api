# Heimdall API — SyncService: descarga en cascada de datos LFM a BD local
# Fases: perfil -> historial (N carreras) -> detalles de cada carrera (resultados,
# vueltas con sectores de los pilotos del split, incidentes) -> standings.
# Resumible: si se interrumpe, al relanzar se salta lo ya descargado.
import logging
from datetime import datetime

from ..config import SYNC_RACE_LIMIT, SYNC_LAP_RACES, SYNC_MAX_RETRIES
from ..models import (LfmProfile, Race, Lap, Incident, Standing, SyncState,
                      PositionChart)
from . import lfm_client as lfm

log = logging.getLogger("heimdall.sync")


class SyncError(Exception):
    pass


class SyncService:
    def __init__(self, db):
        self.db = db

    # ---------- helpers ----------

    def _state(self, profile_id) -> SyncState:
        st = self.db.query(SyncState).filter_by(profile_id=profile_id).first()
        if not st:
            st = SyncState(profile_id=profile_id)
            self.db.add(st)
            self.db.commit()
            self.db.refresh(st)
        return st

    def _update_state(self, st, **kw):
        for k, v in kw.items():
            setattr(st, k, v)
        st.updated_at = datetime.utcnow()
        self.db.commit()

    def get_status(self, profile_id):
        st = self._state(profile_id)
        self.db.refresh(st)
        return {
            "status": st.status,
            "phase": st.phase,
            "total_steps": st.total_steps,
            "done_steps": st.done_steps,
            "current_msg": st.current_msg,
            "last_error": st.last_error,
            "last_synced_race_id": st.last_synced_race_id,
            "started_at": st.started_at.isoformat() if st.started_at else None,
            "finished_at": st.finished_at.isoformat() if st.finished_at else None,
        }

    def _mark_done(self, st):
        st.status = "done"
        st.phase = "completado"
        st.finished_at = datetime.utcnow()
        st.updated_at = datetime.utcnow()
        self.db.commit()

    def _mark_error(self, st, msg):
        st.status = "error"
        st.last_error = msg
        st.updated_at = datetime.utcnow()
        self.db.commit()
        log.error("Sync error: %s", msg)

    # ---------- fases ----------

    def _sync_profile(self, profile: LfmProfile):
        try:
            data = lfm.get_user_data(profile.lfm_user_id)
        except Exception as e:
            raise SyncError(f"No se pudo obtener el perfil: {e}")
        profile.username = data.get("username") or data.get("name")
        profile.vorname = data.get("vorname")
        profile.nachname = data.get("nachname")
        profile.shortname = data.get("shortname")
        profile.origin = data.get("origin")
        profile.avatar = data.get("avatar")
        profile.license = data.get("license")
        profile.safety_rating = _num(data.get("safety_rating"))
        profile.division = data.get("division")
        profile.c_rating = data.get("c_rating")
        profile.cc_rating = data.get("cc_rating")
        profile.rating_by_sim = data.get("rating_by_sim") or []
        profile.achievements_json = data.get("achievements") or {}
        team = data.get("team") or {}
        profile.team_name = team.get("teamname") if isinstance(team, dict) else None
        profile.team_logo = team.get("teamlogo") if isinstance(team, dict) else None
        profile.updated_at = datetime.utcnow()
        self.db.commit()
        lfm.sleep_between_calls()

    def _sync_races(self, profile: LfmProfile, st: SyncState, limit: int):
        """Descarga el historial COMPLETO de carreras paginando (LFM devuelve
        como máximo `limit` por página; se recorre hasta agotar el historial)."""
        races = []
        start = 0
        page = limit if limit > 0 else 50
        while True:
            try:
                batch = lfm.get_user_past_races(profile.lfm_user_id, start=start, limit=page)
            except Exception as e:
                if not races:
                    raise SyncError(f"No se pudo obtener el historial: {e}")
                log.warning("historial página %d falló (continúo con %d carreras): %s",
                            start, len(races), e)
                break
            if not isinstance(batch, list) or not batch:
                break
            races.extend(batch)
            lfm.sleep_between_calls()
            if len(batch) < page:
                break  # última página
            start += page
            # Techo de seguridad: nunca más de 10 páginas (500 carreras)
            if start >= page * 10:
                break
        return races

    def _upsert_race(self, profile: LfmProfile, r) -> Race:
        lfm_id = r.get("race_id")
        race = (self.db.query(Race)
                .filter_by(profile_id=profile.id, lfm_race_id=lfm_id).first())
        rd = r.get("race_date")
        try:
            rdate = datetime.fromisoformat(str(rd).replace(" ", "T")) if rd else None
        except ValueError:
            rdate = None
        vals = dict(
            result_id=r.get("result_id") or 0,
            event_id=r.get("event_id"),
            event_name=r.get("event_name"),
            event_type=r.get("event_type"),
            race_date=rdate,
            track_name=r.get("track_name"),
            track_id=r.get("track_id"),
            car_name=r.get("car_name") or r.get("car"),
            car_number=_int_or_none(r.get("car_number")),
            split=r.get("user_split") or r.get("split"),
            sof=r.get("sof"),
            start_pos=r.get("start_pos"),
            finish_pos=r.get("finishing_pos") or r.get("position"),
            laps=r.get("laps"),
            best_lap=r.get("bestlap"),
            total_time=r.get("time"),
            gap=r.get("gap"),
            rating_change=_num(r.get("rating_change")),
            sr_change=_num(r.get("sr_change")),
            points=_num(r.get("points")),
            incidents=r.get("incidents"),
            best_of_week=bool(r.get("best_of_week")),
            position_gain=r.get("position_gain"),
            dnf=bool(r.get("dnf")),
            dns=bool(r.get("dns")),
            dsq=bool(r.get("dsq")),
        )
        if race is None:
            race = Race(profile_id=profile.id, lfm_race_id=lfm_id, **vals)
            self.db.add(race)
        else:
            for k, v in vals.items():
                setattr(race, k, v)
        self.db.flush()
        return race

    def _sync_race_detail(self, race: Race, only_me: bool = False):
        """Descarga la carrera completa (resultados de todos los pilotos), y para los
        pilotos del split guarda vueltas con sectores + incidentes.
        Si only_me=True (carreras antiguas), solo descarga las vueltas del propio
        usuario para no saturar la API de LFM."""
        try:
            data = lfm.get_race(race.lfm_race_id)
        except Exception as e:
            log.warning("race %s detalle falló: %s", race.lfm_race_id, e)
            race.lap_retry_count = (race.lap_retry_count or 0) + 1
            self.db.commit()
            return
        lfm.sleep_between_calls()

        split = race.split or 1
        # results del split: race_results_splits es lista [{class: {OVERALL: [...]}}]
        results = []
        rrs = data.get("race_results_splits") or []
        if isinstance(rrs, list) and len(rrs) >= split:
            entry = rrs[split - 1]
            if isinstance(entry, dict):
                for cls, overall in entry.items():
                    if isinstance(overall, dict) and isinstance(overall.get("OVERALL"), list):
                        results.extend(overall["OVERALL"])
        if not results:
            # fallback: participant del usuario
            results = data.get("participants") or []

        # session_running para marcar carreras en vivo
        race.session_running = bool(data.get("session_running") or
                                    data.get(f"split{split}_session_running"))
        self.db.commit()

        # Para cada piloto del split, guardar vueltas detalladas (solo si la carrera
        # no es en vivo y tenemos result_id). Limitamos el nº de pilotos para no
        # saturar la API: en las primeras SYNC_LAP_RACES carreras procesamos a todos;
        # en el resto solo al usuario.
        pilots = {}
        for p in results:
            uid = p.get("user_id")
            if uid is None:
                continue
            pilots[uid] = p

        detail_users = list(pilots.keys())
        if only_me:
            # Carreras antiguas: solo el propio usuario (evitar saturar la API)
            me = (self.db.query(LfmProfile)
                  .filter_by(id=race.profile_id).first())
            me_uid = me.lfm_user_id if me else None
            detail_users = [u for u in detail_users if u == me_uid]

        # Guardar resultados de todos los pilotos como vueltas "vacías" no — las vueltas
        # solo se guardan con getLapDetails. Aquí guardamos incidentes del resultado resumido
        # y marcamos qué pilotos procesar en detalle.
        race_detail_meta = getattr(race, "_detail_users", None)

        for uid in detail_users:
            p = pilots[uid]
            r = race
            # Obtener detalle de vueltas
            rid = p.get("result_id")
            if not rid:
                continue
            try:
                ld = lfm.get_lap_details(r.lfm_race_id, rid)
            except Exception as e:
                log.warning("laps %s/%s falló: %s", r.lfm_race_id, rid, e)
                lfm.sleep_between_calls()
                continue
            lfm.sleep_between_calls()
            self._store_laps(r, uid, p, ld)

    def _store_laps(self, race: Race, uid, pilot, ld: dict):
        laps = ld.get("laps") or []
        incs = ld.get("incs") or []
        name = f"{pilot.get('vorname','')} {pilot.get('nachname','')}".strip()
        # vueltas
        for L in laps:
            car_lap = L.get("car_lap")
            if car_lap is None:
                continue
            lap = (self.db.query(Lap)
                   .filter_by(race_id=race.id, lfm_user_id=uid, car_lap=car_lap).first())
            splits = L.get("splits") or ["", "", ""]
            lt = L.get("lapTime")
            vals = dict(
                driver_name=name,
                lap_time=lt,
                lap_time_ms=lfm._t2ms(lt),
                s1=splits[0] if len(splits) > 0 else "",
                s1_ms=lfm._t2ms(splits[0]) if len(splits) > 0 else None,
                s2=splits[1] if len(splits) > 1 else "",
                s2_ms=lfm._t2ms(splits[1]) if len(splits) > 1 else None,
                s3=splits[2] if len(splits) > 2 else "",
                s3_ms=lfm._t2ms(splits[2]) if len(splits) > 2 else None,
                lap_valid=bool(L.get("lap_valid")),
                session_type=L.get("session_type"),
            )
            if lap is None:
                lap = Lap(race_id=race.id, lfm_user_id=uid, car_lap=car_lap, **vals)
                self.db.add(lap)
            else:
                for k, v in vals.items():
                    setattr(lap, k, v)
        # incidentes
        for I in incs:
            it = I.get("incident_type")
            st = I.get("session_time")
            existing = (self.db.query(Incident)
                        .filter_by(race_id=race.id, lfm_user_id=uid,
                                   session_time=st, incident_type=it).first())
            if existing:
                continue
            self.db.add(Incident(
                race_id=race.id, lfm_user_id=uid, driver_name=name,
                incident_type=it, session_time=st,
                server_time_ms=I.get("server_timestamp"),
            ))
        self.db.commit()

    def _sync_position_chart(self, race: Race):
        """Descarga el position chart REAL de LFM (posición oficial vuelta a
        vuelta de cada piloto del split) y lo guarda en position_chart."""
        try:
            data = lfm.get_position_chart(race.lfm_race_id, race.split or 1)
        except Exception as e:
            log.warning("positionChart %s falló: %s", race.lfm_race_id, e)
            lfm.sleep_between_calls()
            return
        lfm.sleep_between_calls()
        if not isinstance(data, list):
            return
        for pilot in data:
            if not isinstance(pilot, dict):
                continue
            uid = pilot.get("user_id")
            if uid is None:
                continue
            name = pilot.get("driver") or ""
            for lap_entry in (pilot.get("laps") or []):
                if not isinstance(lap_entry, dict):
                    continue
                lap = lap_entry.get("lap")
                pos = lap_entry.get("position")
                if lap is None or pos is None:
                    continue
                existing = (self.db.query(PositionChart)
                            .filter_by(race_id=race.id, lfm_user_id=uid,
                                       lap=lap).first())
                vals = dict(driver_name=name, position=pos,
                            pit_lap=bool(lap_entry.get("pit_lap")))
                if existing:
                    for k, v in vals.items():
                        setattr(existing, k, v)
                else:
                    self.db.add(PositionChart(race_id=race.id, lfm_user_id=uid,
                                              lap=lap, **vals))
        self.db.commit()

    def _sync_standings(self, profile: LfmProfile, event_ids):
        from ..models import ApiCache
        for eid in event_ids:
            try:
                data = lfm.get_season_standings(eid)
            except Exception as e:
                log.warning("standings %s falló: %s", eid, e)
                continue
            lfm.sleep_between_calls()
            if not isinstance(data, dict):
                continue
            # Leaderboard COMPLETO en api_cache (regla nº1: todo externo -> BD)
            try:
                row = self.db.query(ApiCache).filter_by(key=f"lfm:standings:{eid}").first()
                if row is None:
                    row = ApiCache(key=f"lfm:standings:{eid}")
                    self.db.add(row)
                row.payload = data
                row.fetched_at = datetime.utcnow()
                self.db.commit()
            except Exception as e:
                log.warning("caché standings %s falló: %s", eid, e)
            for car_class, divisions in data.items():
                if not isinstance(divisions, dict):
                    continue
                for div, entries in divisions.items():
                    if not isinstance(entries, list):
                        continue
                    for e in entries:
                        if not isinstance(e, dict):
                            continue
                        uid = e.get("user_id")
                        if uid != profile.lfm_user_id:
                            continue
                        # Solo guardamos la fila del propio usuario
                        st = (self.db.query(Standing)
                              .filter_by(profile_id=profile.id, event_id=eid,
                                         car_class=car_class).first())
                        wk = {}
                        for k, v in e.items():
                            if k.startswith("week_"):
                                wk[k] = v
                        vals = dict(
                            event_name=e.get("event_name") or "",
                            position=e.get("position"),
                            user_id=uid,
                            driver_name=f"{e.get('vorname','')} {e.get('nachname','')}".strip(),
                            races=e.get("races"),
                            points=e.get("points"),
                            elo=e.get("elo"),
                            origin=e.get("origin"),
                            division=e.get("division"),
                            week_points=wk,
                        )
                        if st is None:
                            st = Standing(profile_id=profile.id, event_id=eid,
                                          car_class=car_class, **vals)
                            self.db.add(st)
                        else:
                            for k, v in vals.items():
                                setattr(st, k, v)
            self.db.commit()

    # ---------- orquestación ----------

    def start_sync(self, profile: LfmProfile, force=False):
        st = self._state(profile.id)
        if st.status == "running" and not force:
            raise SyncError("Ya hay una sincronización en curso")

        st.status = "running"
        st.last_error = None
        st.started_at = datetime.utcnow()
        st.finished_at = None
        st.done_steps = 0
        self.db.commit()

        try:
            # Fase 1: perfil
            self._update_state(st, phase="Perfil", current_msg="Descargando perfil de LFM...",
                               total_steps=2)
            self._sync_profile(profile)
            self._update_state(st, done_steps=1)

            # Fase 2: historial
            self._update_state(st, phase="Historial",
                               current_msg="Descargando historial de carreras...", total_steps=2)
            races = self._sync_races(profile, st, SYNC_RACE_LIMIT)
            if not races:
                raise SyncError("LFM no devolvió carreras para este usuario")
            self._update_state(st, done_steps=2)

            # Fase 3: detalles (TODAS las carreras sin vueltas)
            # - Las SYNC_LAP_RACES más recientes: detalle completo (todos los pilotos)
            # - El resto: solo las vueltas del propio usuario (no saturar la API)
            # - Reintentos: las que fallaron antes (lap_retry_count) se vuelven a
            #   intentar hasta SYNC_MAX_RETRIES veces; force=True lo resetea todo.
            total = len(races)
            st.total_steps = 2 + total
            self._update_state(st, phase="Carreras",
                               current_msg=f"Descargando {total} carreras...",
                               done_steps=2)

            new_races = []
            for r in races:
                race = self._upsert_race(profile, r)
                if race.id not in [x.id for x in new_races]:
                    new_races.append(race)

            max_retries = SYNC_MAX_RETRIES if SYNC_MAX_RETRIES > 0 else 1
            detail_targets = []
            for i, race in enumerate(new_races):
                has_laps = self.db.query(Lap).filter_by(race_id=race.id).first()
                if has_laps:
                    # Ya tiene vueltas: resetear contador de reintentos
                    if race.lap_retry_count:
                        race.lap_retry_count = 0
                        self.db.commit()
                    continue
                retries = race.lap_retry_count or 0
                if not force and retries >= max_retries:
                    log.warning("race %s (%s) sin vueltas tras %d intentos; se salta "
                                "(usa force=True para resetear)", race.id,
                                race.track_name, retries)
                    continue
                detail_targets.append((i, race))

            for i, race in detail_targets:
                only_me = i >= SYNC_LAP_RACES if SYNC_LAP_RACES > 0 else True
                self._update_state(st, phase="Vueltas",
                                   current_msg=f"Descargando vueltas de {race.event_name} "
                                               f"({race.track_name})...",
                                   done_steps=2 + i)
                self._sync_race_detail(race, only_me=only_me)
                # Posición oficial vuelta a vuelta (narrativa "qué pasó")
                self._sync_position_chart(race)

            # Fase 4: standings (eventos presentes en el historial)
            event_ids = sorted({r.get("event_id") for r in races if r.get("event_id")})
            if event_ids:
                st.total_steps = 2 + len(detail_targets) + len(event_ids)
                self._update_state(st, phase="Campeonato",
                                   current_msg="Descargando clasificaciones del campeonato...",
                                   done_steps=2 + len(detail_targets))
                self._sync_standings(profile, event_ids)

            # Actualizar last_synced_race_id
            max_id = max((r.get("race_id") for r in races), default=0)
            st.last_synced_race_id = max_id

            self._mark_done(st)
            return self.get_status(profile.id)

        except SyncError as e:
            self._mark_error(st, str(e))
            raise
        except Exception as e:
            self._mark_error(st, f"Error inesperado: {e}")
            log.exception("sync crash")
            raise


def _num(v):
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _int_or_none(v):
    try:
        if v is None or v == "":
            return None
        return int(v)
    except (TypeError, ValueError):
        return None
