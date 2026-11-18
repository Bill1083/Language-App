from app.config import get_settings
from app.security import allowed_ws_origin


def test_origin_matching_host_is_allowed():
    assert allowed_ws_origin("http://localhost:7892", "localhost:7892")
    assert not allowed_ws_origin("https://evil.example", "localhost:7892")
    assert not allowed_ws_origin(None, "localhost:7892")


def test_origin_matching_domain_survives_a_rewritten_host(monkeypatch):
    # Nginx locations with their own proxy_set_header lines forward Host as the upstream name
    monkeypatch.setenv("DOMAIN", "lang.example.com")
    get_settings.cache_clear()
    try:
        assert allowed_ws_origin("https://lang.example.com", "parlo_app")
        assert allowed_ws_origin("https://lang.example.com", "parlo_app", "lang.example.com")
        assert not allowed_ws_origin("https://other.example.com", "parlo_app")
    finally:
        monkeypatch.delenv("DOMAIN", raising=False)
        get_settings.cache_clear()


async def test_last_seen_is_refreshed_but_not_on_every_request():
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from app.deps import LAST_SEEN_EVERY, touch_last_seen

    class FakeDb:
        commits = 0

        async def commit(self):
            self.commits += 1

    db, now = FakeDb(), datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
    user = SimpleNamespace(last_seen_at=now - timedelta(days=2))  # signed in days ago, still using the app
    assert await touch_last_seen(db, user, now) is True and user.last_seen_at == now
    assert await touch_last_seen(db, user, now + timedelta(minutes=1)) is False  # throttled
    assert await touch_last_seen(db, user, now + LAST_SEEN_EVERY) is True
    assert db.commits == 2
    assert await touch_last_seen(db, SimpleNamespace(last_seen_at=None), now) is True  # never seen
