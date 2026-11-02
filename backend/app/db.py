import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./erp.db")
# Keep the database pool explicit: the web request path and background
# report/sync loops share this engine. A bounded pool prevents requests from
# sitting on SQLAlchemy's default 30-second checkout timeout under report load.
_engine_options = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    _engine_options["connect_args"] = {"check_same_thread": False, "timeout": 30}
else:
    _engine_options.update(
        pool_size=max(5, int(os.getenv("DB_POOL_SIZE", "10"))),
        max_overflow=max(0, int(os.getenv("DB_MAX_OVERFLOW", "10"))),
        pool_timeout=max(5, int(os.getenv("DB_POOL_TIMEOUT_SECONDS", "12"))),
        pool_recycle=max(300, int(os.getenv("DB_POOL_RECYCLE_SECONDS", "1800"))),
    )
engine = create_engine(DATABASE_URL, **_engine_options)
if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def sqlite_pragmas(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")


SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    with SessionLocal() as db:
        try:
            yield db
        except Exception:
            db.rollback()
            raise
