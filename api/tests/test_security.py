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
