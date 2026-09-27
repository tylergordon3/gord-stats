"""
The D1 schema and its migrations agree, and dropping the user_id indexes cost
no lookup its index.

Migration 004 dropped favorites_by_user and leagues_by_user: each indexed
user_id alone, the leading column of its table's primary key, so it was a
second copy of an index SQLite already had - and a write apiece on every
insert and delete, against a free tier that allows 100,000 a day. Pure
sqlite3, no browser: this runs everywhere the suite does.
"""
import sqlite3

import pytest

from functions_harness import MIGRATION_004, SCHEMA, before_004


def _shape(db):
    tables = [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    return {
        "indexes": sorted(r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'")),
        "columns": {t: [tuple(c) for c in db.execute(f"PRAGMA table_xinfo({t})")]
                    for t in tables},
    }


def test_migration_004_brings_an_old_database_to_the_schema():
    old = sqlite3.connect(":memory:")
    old.executescript(before_004())
    assert "favorites_by_user" in _shape(old)["indexes"]
    old.executescript(MIGRATION_004.read_text())

    fresh = sqlite3.connect(":memory:")
    fresh.executescript(SCHEMA.read_text())
    assert _shape(old) == _shape(fresh)


@pytest.mark.parametrize("query", [
    "SELECT sport, team_id FROM favorites WHERE user_id = ?",
    "SELECT league_id FROM leagues WHERE user_id = ?",
    "DELETE FROM favorites WHERE user_id = ?",
])
def test_reader_lookups_still_use_an_index(query):
    """The dropped indexes were copies of the primary keys' leading column."""
    db = sqlite3.connect(":memory:")
    db.executescript(SCHEMA.read_text())
    plan = " ".join(r[-1] for r in db.execute(f"EXPLAIN QUERY PLAN {query}", ("u",)))
    assert "sqlite_autoindex_" in plan and "SCAN" not in plan.replace("SCAN CONSTANT", "")
