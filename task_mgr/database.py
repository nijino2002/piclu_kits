from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config import DATABASE_URL


Base = declarative_base()
_engine = None
_session_factory = None


def get_engine():
    global _engine, _session_factory
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not configured. Example: "
            "mysql+pymysql://piclu:password@127.0.0.1:3306/piclu?charset=utf8mb4"
        )
    if _engine is None:
        _engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            pool_recycle=1800,
            future=True,
        )
        _session_factory = sessionmaker(
            bind=_engine,
            autoflush=False,
            expire_on_commit=False,
            future=True,
        )
    return _engine


@contextmanager
def session_scope():
    get_engine()
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
