import psycopg
import pytest

from backend import db


def test_without_a_database_url_the_engine_is_sqlite_on_the_given_file(
    client, tmp_path
):
    engine = db.engine()
    assert engine.url.drivername == "sqlite"
    assert engine.url.database == str(tmp_path / "test.db")


def test_an_empty_database_url_counts_as_unset(client, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    assert db.engine().url.drivername == "sqlite"


def test_a_database_url_makes_a_postgres_engine_on_the_psycopg_driver(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://user.ref:secret@host:5432/postgres"
    )
    engine = db.engine()
    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.url.host == "host"
    assert "secret" not in db.describe()


def test_the_postgres_engine_uses_the_undercover_schema(monkeypatch):
    seen = {}

    def refuse(*_args, **kwargs):
        seen.update(kwargs)
        raise ConnectionError("no network in the tests")

    monkeypatch.setattr(psycopg, "connect", refuse)
    engine = db.make_engine(
        db.postgres_url("postgresql://user:secret@host:5432/postgres")
    )
    with pytest.raises(ConnectionError):
        engine.connect()
    assert seen["options"] == "-c search_path=undercover"


def test_the_postgres_pool_holds_four_connections_at_most():
    engine = db.make_engine(
        db.postgres_url("postgresql://user:secret@host:5432/postgres")
    )
    assert engine.pool.size() + engine.pool._max_overflow == 4  # type: ignore[attr-defined]  # noqa: SLF001


def test_tables_exist_after_a_seed_and_not_before(tmp_path, monkeypatch):
    monkeypatch.setenv("UNDERCOVER_DB", str(tmp_path / "empty.db"))
    assert db.tables_exist() is False
    db.reset_schema()
    assert db.tables_exist() is True
