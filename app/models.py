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
    profile = relationship("LfmProfile", back_populates="races")
    laps_detail = relationship("Lap", back_populates="race", cascade="all, delete-orphan")
    incidents_detail = relationship("Incident", back_populates="race", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("profile_id", "lfm_race_id", name="uq_profile_race"),)


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
