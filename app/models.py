# Heimdall API — modelos ORM
from datetime import datetime
from sqlalchemy import (Column, Integer, String, Float, Boolean, DateTime,
                        ForeignKey, Text, UniqueConstraint, JSON)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    profiles = relationship("LfmProfile", back_populates="user", cascade="all, delete-orphan")


class LfmProfile(Base):
    __tablename__ = "lfm_profiles"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    lfm_user_id = Column(Integer, nullable=False, index=True)
    username = Column(String(120))
    vorname = Column(String(120))
    nachname = Column(String(120))
    shortname = Column(String(20))
    origin = Column(String(4))
    avatar = Column(Text)
    license = Column(String(30))
    safety_rating = Column(Float)
    division = Column(Integer)
    c_rating = Column(Integer)
    cc_rating = Column(Integer)
    team_name = Column(String(120))
    team_logo = Column(Text)
    rating_by_sim = Column(JSON)  # rating/licencia/división por simulador
    achievements_json = Column(JSON)  # logros completos del piloto
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = relationship("User", back_populates="profiles")
    races = relationship("Race", back_populates="profile", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("user_id", "lfm_user_id", name="uq_user_lfm"),)


class Race(Base):
    __tablename__ = "races"
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("lfm_profiles.id"), nullable=False, index=True)
    lfm_race_id = Column(Integer, nullable=False)
    result_id = Column(Integer, nullable=False)
    event_id = Column(Integer)
    event_name = Column(String(200))
    event_type = Column(String(50))
    race_date = Column(DateTime, index=True)
    track_name = Column(String(120))
    track_id = Column(Integer)
    car_name = Column(String(120))
    car_number = Column(Integer)
    split = Column(Integer)
    sof = Column(Integer)
    start_pos = Column(Integer)
    finish_pos = Column(Integer)
    laps = Column(Integer)
    best_lap = Column(String(20))
    total_time = Column(String(30))
    gap = Column(String(30))
    rating_change = Column(Float)
    sr_change = Column(Float)
    points = Column(Float)
    incidents = Column(Integer)
    best_of_week = Column(Boolean, default=False)
    position_gain = Column(Integer)
    dnf = Column(Boolean, default=False)
    dns = Column(Boolean, default=False)
    dsq = Column(Boolean, default=False)
    session_running = Column(Boolean, default=False)
    lap_retry_count = Column(Integer, default=0)
    profile = relationship("LfmProfile", back_populates="races")
    laps_detail = relationship("Lap", back_populates="race", cascade="all, delete-orphan")
    incidents_detail = relationship("Incident", back_populates="race", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("profile_id", "lfm_race_id", name="uq_profile_race"),)


class Track(Base):
    """Perfil de circuito cacheado desde LFM (mapa, curvas, km)."""
    __tablename__ = "tracks"
    track_id = Column(Integer, primary_key=True)
    track_name = Column(String(120))
    track_year = Column(Integer)
    acc_track_name = Column(String(200))
    thumbnail = Column(String(500))
    trackmap = Column(String(500))
    country = Column(String(10))
    turns = Column(Integer)
    km = Column(Integer)
    city = Column(String(120))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Lap(Base):
    __tablename__ = "laps"
    id = Column(Integer, primary_key=True)
    race_id = Column(Integer, ForeignKey("races.id"), nullable=False, index=True)
    lfm_user_id = Column(Integer, nullable=False)
    driver_name = Column(String(120))
    car_lap = Column(Integer)
    lap_time = Column(String(20))
    lap_time_ms = Column(Integer)
    s1 = Column(String(12))
    s1_ms = Column(Integer)
    s2 = Column(String(12))
    s2_ms = Column(Integer)
    s3 = Column(String(12))
    s3_ms = Column(Integer)
    lap_valid = Column(Boolean, default=True)
    session_type = Column(String(4))
    race = relationship("Race", back_populates="laps_detail")
    __table_args__ = (UniqueConstraint("race_id", "lfm_user_id", "car_lap", name="uq_race_user_lap"),)


class Incident(Base):
    __tablename__ = "incidents"
    id = Column(Integer, primary_key=True)
    race_id = Column(Integer, ForeignKey("races.id"), nullable=False, index=True)
    lfm_user_id = Column(Integer, nullable=False)
    driver_name = Column(String(120))
    incident_type = Column(String(4))
    session_time = Column(String(30))
    server_time_ms = Column(Integer)
    race = relationship("Race", back_populates="incidents_detail")


class Standing(Base):
    __tablename__ = "standings"
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("lfm_profiles.id"), nullable=False, index=True)
    event_id = Column(Integer, nullable=False)
    event_name = Column(String(200))
    car_class = Column(String(80))
    position = Column(Integer)
    user_id = Column(Integer)
    driver_name = Column(String(120))
    races = Column(Integer)
    points = Column(Integer)
    elo = Column(Integer)
    origin = Column(String(4))
    division = Column(Integer)
    week_points = Column(JSON)  # {"week_1": 760, ...}
    __table_args__ = (UniqueConstraint("profile_id", "event_id", "car_class", name="uq_profile_event_class"),)


class SyncState(Base):
    __tablename__ = "sync_state"
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("lfm_profiles.id"), nullable=False, unique=True)
    status = Column(String(20), default="pending")  # pending|running|done|error
    phase = Column(String(60))
    total_steps = Column(Integer, default=0)
    done_steps = Column(Integer, default=0)
    current_msg = Column(String(255))
    last_error = Column(Text)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced_race_id = Column(Integer, default=0)


class PositionChart(Base):
    """Posición REAL vuelta a vuelta de cada piloto (endpoint positionChart de LFM).

    Fuente oficial de LFM: /api/race/{race_id}/positionChart/{split}
    La posición por vuelta se usa en la narrativa de carrera para decir con
    datos reales cuándo y por qué se ganó/perdió una posición.
    """
    __tablename__ = "position_chart"
    id = Column(Integer, primary_key=True)
    race_id = Column(Integer, ForeignKey("races.id"), nullable=False, index=True)
    lfm_user_id = Column(Integer, nullable=False, index=True)
    driver_name = Column(String(120))
    lap = Column(Integer, nullable=False)
    position = Column(Integer, nullable=False)
    pit_lap = Column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("race_id", "lfm_user_id", "lap",
                                       name="uq_race_user_lap_pos"),)


class ScheduleCache(Base):
    """Calendario de temporada cacheado desde LFM (getMinifiedSeasonBySim +
    getSeasonWeeks). Guardado en BD para no depender de la API de LFM:
    si LFM falla, servimos lo último que descargamos.
    """
    __tablename__ = "schedule_cache"
    id = Column(Integer, primary_key=True)
    sim_id = Column(Integer, nullable=False, unique=True, index=True)
    season_name = Column(String(60))
    season_week = Column(Integer)
    payload = Column(JSON)  # serie -> semanas/carreras/coches
    fetched_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ApiCache(Base):
    """Caché genérica de endpoints LFM auxiliares (getCars, getSeasonWeeks).
    key = identidad del recurso; payload JSON; fetched_at para TTL.
    El calendario ya no llama a LFM en cada request: sirve de BD y el
    scheduler refresca cuando toca.
    """
    __tablename__ = "api_cache"
    id = Column(Integer, primary_key=True)
    key = Column(String(120), nullable=False, unique=True, index=True)
    payload = Column(JSON)
    fetched_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TrackRecord(Base):
    """Récord oficial LFM por circuito + clase de coche (qualifying/carrera).
    Cacheado en BD para sobrevivir a caídas de la API de LFM.
    """
    __tablename__ = "track_records"
    id = Column(Integer, primary_key=True)
    track_name = Column(String(120), index=True)
    car_class = Column(String(60))
    mode = Column(String(20))          # qualifying | race
    lap = Column(String(20))
    lap_ms = Column(Integer)
    driver = Column(String(120))
    origin = Column(String(10))
    car = Column(String(120))
    date = Column(String(20))
    fetched_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("track_name", "car_class", "mode",
                                       name="uq_track_class_mode"),)


class TrackVideo(Base):
    """Video de YouTube (track guide/hotlap) cacheado por circuito.
    La búsqueda con yt-dlp es lenta (~8s), así que se guarda en BD y solo
    se refresca si el cache caduca (24h)."""
    __tablename__ = "track_videos"
    id = Column(Integer, primary_key=True)
    track_name = Column(String(120), index=True)
    car_class = Column(String(60))
    video_id = Column(String(40), nullable=False)
    title = Column(String(300))
    channel = Column(String(150))
    duration = Column(Integer)
    url = Column(String(300))
    thumbnail = Column(String(300))
    fetched_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("video_id", name="uq_video_id"),)


class RaceReplay(Base):
    """Replay de datos de una carrera LFM: positionChart (posición vuelta a
    vuelta de todos), lapDetails (vueltas con splits de pilotos clave) y
    enlaces de VOD/stream si la carrera fue transmitida. Cacheado en BD para
    sobrevivir a caídas de la API de LFM (patrón Heimdall)."""
    __tablename__ = "race_replays"
    id = Column(Integer, primary_key=True)
    lfm_race_id = Column(Integer, nullable=False, index=True)
    split = Column(Integer, default=1)
    payload = Column(JSON)
    fetched_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("lfm_race_id", "split",
                                       name="uq_race_split"),)
