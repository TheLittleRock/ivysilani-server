import pytest
import asyncio
from app.services.ct_service import ct_service, LIVE_CHANNELS

@pytest.mark.asyncio
async def test_live_channels_definitions():
    assert len(LIVE_CHANNELS) >= 14
    assert "CH_1" in LIVE_CHANNELS
    assert "CH_2" in LIVE_CHANNELS
    assert "CH_24" in LIVE_CHANNELS
    assert "CH_4" in LIVE_CHANNELS
    assert LIVE_CHANNELS["CH_1"]["name"] == "ČT1"

@pytest.mark.asyncio
async def test_resolve_live_stream():
    # Test resolving stream for ČT24 (news channel usually has 24/7 rights)
    stream_info = await ct_service.resolve_live_stream("CH_24")
    assert stream_info is not None
    assert "url" in stream_info
    assert stream_info["url"].startswith("http")
    assert "streamType=" in stream_info["url"] or "m3u8" in stream_info["url"] or "mpd" in stream_info["url"]
    assert stream_info["channel_id"] == "CH_24"

@pytest.mark.asyncio
async def test_resolve_live_stream_ct2_native_live():
    # Verify that live stream for ČT2 uses native live HLS stream (contentType=live) rather than historical timeshift
    stream_info = await ct_service.resolve_live_stream("CH_2", allow_drm=False)
    assert stream_info is not None
    assert stream_info["channel_id"] == "CH_2"
    assert "contentType=live" in stream_info["hls_url"]
    assert "duration=14400" not in stream_info["hls_url"]
    assert stream_info["dash_url"] is not None

@pytest.mark.asyncio
async def test_resolve_vod_stream_drm_fallback():
    # Bod obnovy (IDEC 21951212035) requires DRM on web profile, but resolves to unencrypted HLS via HbbTV fallback
    stream_info = await ct_service.resolve_vod_stream("21951212035", allow_drm=True)
    assert stream_info is not None
    assert "url" in stream_info
    assert stream_info["url"].startswith("http")
    # Verify it has subtitles if present
    assert "subtitles" in stream_info

def test_parse_season_number():
    from app.services.ct_service import parse_season_number
    assert parse_season_number("I. řada") == 1
    assert parse_season_number("2. série") == 2
    assert parse_season_number("StarDance XIV (2026)") == 14
    assert parse_season_number("42× 26 minut", default=1) == 1
    assert parse_season_number("21× 52 minut", default=1) == 1
    assert parse_season_number("14 dílů", default=1) == 1
    assert parse_season_number("V. řada") == 5

