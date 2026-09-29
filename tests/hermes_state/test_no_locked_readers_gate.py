"""A WAL reader must not convoy a writer on the same SessionDB."""

from contextlib import contextmanager
from threading import Event, Thread

import pytest

from hermes_state import SessionDB


@pytest.mark.requires_wal
def test_get_session_reader_does_not_hold_writer_lock(tmp_path, monkeypatch):
    db = SessionDB(db_path=tmp_path / "state.db")
    entered = Event()
    release = Event()
    writer_done = Event()
    errors = []
    reader = writer = None
    try:
        db.create_session(session_id="s1", source="cli", model="m")
        original = db._read_ctx

        @contextmanager
        def held_read():
            with original() as conn:
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("reader was not released")
                yield conn

        monkeypatch.setattr(db, "_read_ctx", held_read)

        def read():
            try:
                assert db.get_session("s1")["id"] == "s1"
            except BaseException as exc:
                errors.append(exc)

        def write():
            try:
                db.append_message("s1", role="user", content="writer committed")
            except BaseException as exc:
                errors.append(exc)
            finally:
                writer_done.set()

        reader = Thread(target=read)
        reader.start()
        assert entered.wait(5), "public get_session did not reach the read connection"
        writer = Thread(target=write)
        writer.start()
        assert writer_done.wait(2), "writer convoyed behind WAL reader's writer lock"
    finally:
        release.set()
        if reader:
            reader.join(timeout=6)
        if writer:
            writer.join(timeout=6)
        db.close()
    assert not errors, errors
    assert not reader.is_alive() and not writer.is_alive()
