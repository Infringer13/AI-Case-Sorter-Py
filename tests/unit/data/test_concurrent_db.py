"""Cross-thread use of the one shared connection.

``sqlite3.Row`` keeps the cursor's column description. A second statement on
the same connection — the run thread listing headstamps while the UI thread
reads them — can rebind that description before ``row["id"]`` indexes the
values. That is ``IndexError: tuple index out of range`` (or
``InterfaceError``). ``Database.execute`` holds the connection lock across
the fetch and copies the row out.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from sorter.data.config import Config
from sorter.data.db import Database
from sorter.data.repository import HeadstampRepo, ModelRepo, SettingsRepo


def test_execute_rows_survive_after_the_cursor_moves_on(tmp_path: Path) -> None:
    db = Database(tmp_path / "rows.db")
    db.ensure_initialized()
    row = db.execute("SELECT id, name FROM cartridges").fetchone()
    assert row is not None
    assert row["name"] == "9mm"
    assert row[0] == row["id"]
    assert "name" in row.keys()
    assert dict(row)["name"] == "9mm"
    # A later statement must not change a row already handed back.
    db.execute("SELECT 1")
    assert row["name"] == "9mm"
    with pytest.raises(IndexError):
        row["no_such_column"]


def test_concurrent_headstamp_reads_and_writes(tmp_path: Path) -> None:
    """The upstream race: readers in config.headstamps, a writer on the same connection."""
    db = Database(tmp_path / "race.db")
    db.ensure_initialized()
    config = Config(db).load()
    model = ModelRepo(db).list()[0]
    SettingsRepo(db).set_active_model_id(model.id)
    for index in range(20):
        config.add_headstamp(f"H{index:02d}", slot=index % 8)
    stamps = HeadstampRepo(db).list_for_model(model.id)

    errors: list[BaseException] = []
    loops = 80
    start = threading.Barrier(4)

    def read() -> None:
        start.wait()
        for _ in range(loops):
            try:
                rows = config.headstamps
                assert len(rows) == 20
                for entry in rows:
                    assert isinstance(entry["name"], str)
                    assert isinstance(entry["id"], int)
                assert config.slot_for_headstamp("H00") == 0
            except Exception as exc:
                errors.append(exc)
                return

    def write() -> None:
        start.wait()
        settings = SettingsRepo(db)
        repo = HeadstampRepo(db)
        for index in range(loops):
            try:
                settings.set("probe", index)
                assert settings.get("probe") == index
                # Leave H00 on slot 0 so the readers' assertion stays stable.
                stamp = stamps[(index % (len(stamps) - 1)) + 1]
                repo.update_slot(stamp.id, index % 8)
                rows = config.headstamps
                assert rows[0]["name"]
            except Exception as exc:
                errors.append(exc)
                return

    threads = [threading.Thread(target=read) for _ in range(3)]
    threads.append(threading.Thread(target=write))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
