"""A compaction copy of a message must share its original's display identity (issue #123985).

A resume/reload (gateway transcript reload, session.resume) materializes rows through the loader's lens
(``sanitize_context(...).strip()`` on user/assistant text). In-place compaction then writes the protected head
and carried tail back from those loaded dicts, so the copy's stored bytes can differ from the original's
(here: a reply's trailing whitespace). Hashing raw bytes gave the copy its own ``display_order``, and every
display projection rendered the session's first messages twice.
"""

from hermes_state import SessionDB


def _compact_from_reloaded_view(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    sid = "reload-lens"
    db.create_session(session_id=sid, source="desktop")
    db.append_message(sid, "user", "first ask", timestamp=1.0)
    db.append_message(sid, "assistant", "first reply ends with a newline\n", timestamp=2.0)
    db.append_message(sid, "user", "second ask", timestamp=3.0)
    db.append_message(sid, "assistant", "second reply", timestamp=4.0)
    head = db.get_messages_as_conversation(sid)[:2]  # the reload a gateway turn compacts from
    db.archive_and_compact(sid, [*head, {"role": "user", "content": "[summary]", "timestamp": 5.0}])
    return db, sid


def test_display_page_shows_reloaded_head_copy_once(tmp_path):
    db, sid = _compact_from_reloaded_view(tmp_path)
    try:
        replies = [m for m in db.get_messages(sid, include_compacted=True) if m["role"] == "assistant"]
        assert [m["content"].strip() for m in replies] == ["first reply ends with a newline", "second reply"]
        assert replies[0]["active"] == 1  # the live copy represents the logical message
    finally:
        db.close()


def test_resume_display_shows_reloaded_head_copy_once(tmp_path):
    db, sid = _compact_from_reloaded_view(tmp_path)
    try:
        display = db.get_resume_conversations(sid)[1]
        assert [m["content"] for m in display if m["role"] == "assistant"] == [
            "first reply ends with a newline", "second reply"]
    finally:
        db.close()
