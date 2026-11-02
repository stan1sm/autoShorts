import pytest

from shorts.state import StateStore


@pytest.fixture
def store(tmp_path):
    s = StateStore(tmp_path / "sub" / "state.db")
    yield s
    s.close()


def test_source_lifecycle(store):
    assert not store.is_done("h")
    store.register("h", "src1", "/x.mp4")
    assert not store.is_done("h")
    store.mark("h", "done")
    assert store.is_done("h")


def test_hosted_upsert_replaces(store):
    store.upsert_hosted("c.mp4", "http://a", None, "h1")
    store.upsert_hosted("c.mp4", "http://b", None, "h2")
    rec = store.get_hosted("c.mp4")
    assert (rec.hosted_url, rec.file_hash) == ("http://b", "h2")
    store.delete_hosted("c.mp4")
    assert store.get_hosted("c.mp4") is None


def test_post_attempt_is_idempotent_and_tracks_failures(store):
    first = store.create_post_attempt("s", "c.mp4", "youtube", "ch1")
    again = store.create_post_attempt("s", "c.mp4", "youtube", "ch1")
    assert first.id == again.id and first.status == "pending"

    store.mark_post_failed("c.mp4", "youtube", "boom")
    rec = store.get_post("c.mp4", "youtube")
    assert (rec.status, rec.last_error, rec.attempt_count) == ("failed", "boom", 1)
    assert [r.id for r in store.list_posts(status="failed")] == [first.id]

    store.mark_post_scheduled("c.mp4", "youtube", "bp1", "scheduled", None)
    rec = store.get_post("c.mp4", "youtube")
    assert (rec.status, rec.buffer_post_id, rec.last_error) == ("scheduled", "bp1", None)


def test_key_value(store):
    assert store.get_value("k") is None
    store.set_value("k", "v1")
    store.set_value("k", "v2")
    assert store.get_value("k") == "v2"
