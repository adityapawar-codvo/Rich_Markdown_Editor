"""Minimal migration runner: numbered .sql files, applied once, each with a tested down script."""
from __future__ import annotations

from pathlib import Path

from .db import Database
from .timefmt import utc_now_iso

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _files(directory: Path) -> list[Path]:
    return sorted(directory.glob("[0-9]*.sql"))


def _ensure_table(conn) -> None:
    conn.execute("create table if not exists schema_migrations (version text primary key, applied_at text not null)")


def _run(db: Database, script: str) -> None:
    """Run one script atomically. Foreign keys are off while it runs and verified afterwards."""
    with db.read() as conn:
        conn.execute("pragma foreign_keys = off")
        try:
            conn.executescript(f"begin;\n{script}\n")
            violations = conn.execute("pragma foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"migration left {len(violations)} foreign key violation(s)")
            conn.execute("commit")
        except BaseException:
            if conn.in_transaction:
                conn.execute("rollback")
            raise


def applied_versions(db: Database) -> list[str]:
    with db.read() as conn:
        _ensure_table(conn)
        return [r["version"] for r in conn.execute("select version from schema_migrations order by version")]


def migrate(db: Database, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply every pending migration in order. Returns the versions applied."""
    done = set(applied_versions(db))
    applied: list[str] = []
    for path in _files(directory):
        version = path.stem
        if version in done:
            continue
        _run(db, f"{path.read_text()}\ninsert into schema_migrations values ('{version}', '{utc_now_iso()}');")
        applied.append(version)
    return applied


def rollback_last(db: Database, directory: Path = MIGRATIONS_DIR) -> str | None:
    """Run the down script of the most recently applied migration."""
    versions = applied_versions(db)
    if not versions:
        return None
    version = versions[-1]
    down = directory / "rollback" / f"{version}_down.sql"
    _run(db, f"{down.read_text()}\ndelete from schema_migrations where version = '{version}';")
    return version
