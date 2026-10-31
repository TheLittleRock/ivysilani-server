import pytest
from app.services.drm import is_drm_stream, parse_duration, parse_timestamp, find_widevine_pssh
from app.services.drm_proxy import DrmSessionManager, patch_init_kid

def test_parse_duration():
    assert parse_duration("PT1M5S") == 65.0
    assert parse_duration("PT1H1M5S") == 3665.0
    assert parse_duration("PT0S") == 0.0

def test_parse_timestamp():
    # ISO-8601 UTC time format
    ts = parse_timestamp("2026-10-31T12:00:00Z")
    assert ts > 0

def test_is_drm_stream():
    assert is_drm_stream("https://example.com/stream?drmOnly=true") is True
    assert is_drm_stream("https://example.com/stream?drmOnly=false") is False
    assert is_drm_stream("https://example.com/stream") is False

def test_drm_session_manager():
    manager = DrmSessionManager()
    session_id = manager.create_session(
        source_url="https://example.com/manifest.mpd",
        user_agent="TestAgent",
        base_url="http://localhost:5002"
    )
    assert session_id is not None
    assert len(session_id) > 10
    adapter = manager.get_adapter(session_id)
    assert adapter is not None
    assert adapter.source == "https://example.com/manifest.mpd"
