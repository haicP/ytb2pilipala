from collections.abc import Generator
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.config import get_settings


class Base(DeclarativeBase):
    pass


def _sqlite_path_from_url(database_url: str) -> Path | None:
    if database_url.startswith("sqlite:///./"):
        return Path(database_url.removeprefix("sqlite:///"))
    if database_url.startswith("sqlite:////"):
        return Path(database_url.removeprefix("sqlite:///"))
    return None


settings = get_settings()
sqlite_path = _sqlite_path_from_url(settings.database_url)
if sqlite_path is not None:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _migrate_sqlite_metadata_columns()


def _migrate_sqlite_metadata_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    expected_columns = {
        "copyright_type": "INTEGER NOT NULL DEFAULT 2",
        "bilibili_aid": "VARCHAR(128) NOT NULL DEFAULT ''",
        "bilibili_cid": "VARCHAR(128) NOT NULL DEFAULT ''",
        "bilibili_filename": "VARCHAR(255) NOT NULL DEFAULT ''",
        "bilibili_cover_url": "TEXT NOT NULL DEFAULT ''",
    }
    inspector = inspect(engine)
    if "submission_metadata" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("submission_metadata")}
    with engine.begin() as connection:
        for column_name, column_definition in expected_columns.items():
            if column_name not in existing_columns:
                connection.execute(
                    text(f"ALTER TABLE submission_metadata ADD COLUMN {column_name} {column_definition}")
                )


def get_db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
