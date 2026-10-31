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
