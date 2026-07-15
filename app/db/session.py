import os
from pathlib import Path

import redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

master_url = settings.master_url or os.environ.get("DATABASE_MASTER_URL") or os.environ.get("DATABASE_URL") or "sqlite:///./app.db"
replica_url = settings.replica_url or os.environ.get("DATABASE_REPLICA_URL") or os.environ.get("DATABASE_URL_READ") or os.environ.get("DATABASE_URL") or "sqlite:///./app.db"

engine_kwargs = {"pool_size": 5, "pool_pre_ping": True}
if master_url.startswith("sqlite"):
    engine_kwargs = {"connect_args": {"check_same_thread": False}}

master_engine = create_engine(master_url, **engine_kwargs)
replica_engine = create_engine(replica_url, pool_size=10, pool_pre_ping=True)
if replica_url.startswith("sqlite"):
    replica_engine = create_engine(replica_url, connect_args={"check_same_thread": False})

MasterSessionLocal = sessionmaker(bind=master_engine, expire_on_commit=False)
ReplicaSessionLocal = sessionmaker(bind=replica_engine, expire_on_commit=False)

redis_client = redis.from_url(settings.redis_url or os.environ.get("REDIS_URL"), decode_responses=True) if (settings.redis_url or os.environ.get("REDIS_URL")) else None


def get_master_session():
    session = MasterSessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_replica_session():
    session = ReplicaSessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_redis_client():
    return redis_client
