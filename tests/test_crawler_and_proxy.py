import pytest
import io
from PIL import Image

from app.db import crud
from app.services.ct_service import clean_episode_title, parse_season_number, parse_episode_number
from app.services.image_proxy import image_proxy
from app.api.stream import shift_vtt_timestamps

def test_clean_episode_title():
    # 1. Číslo s lomítkem (např. 1/13 Ztracený případ)
    num, title = clean_episode_title("1/13 Ztracený případ")
    assert num == 1
    assert title == "Ztracený případ"

    # 2. Běžný název bez prefixu
    num2, title2 = clean_episode_title("Od začátku")
    assert num2 is None
    assert title2 == "Od začátku"

    # 3. Non-breaking space
    num3, title3 = clean_episode_title("2/25\xa0Druhý díl")
    assert num3 == 2
    assert title3 == "Druhý díl"

def test_parse_season_number():
    # StarDance s římskými číslicemi
    assert parse_season_number("StarDance XIV (2026)") == 14
    assert parse_season_number("StarDance I (2006)") == 1
    assert parse_season_number("StarDance Tour (2025)") == 0

    # StarDance bonusové materiály a speciály
    assert parse_season_number("…kolem dokola") == 0
    assert parse_season_number("Videochaty") == 0
    assert parse_season_number("Speciály") == 0

    # Vyprávěj Osudy a bonusy
    assert parse_season_number("Osudy") == 6
    assert parse_season_number("Filmy o seriálu") == 0
    assert parse_season_number("I. řada") == 1
    assert parse_season_number("V. řada") == 5

def test_clear_catalog_and_delete_show():
    # Vložíme testovací pořad a epizodu
    crud.upsert_show(
        show_id="test_show_999",
        title="Testovací Pořad",
        slug="test-show-999"
    )
    crud.upsert_episode(
        ep_id="test_show_999_ep1",
        show_id="test_show_999",
        idec="99901",
        title="Test Díl 1"
    )
    assert crud.get_show_by_id("test_show_999") is not None
    assert len(crud.get_episodes_by_show("test_show_999")) == 1

    # Otestujeme smazání konkrétního pořadu
    deleted = crud.delete_show("test_show_999")
    assert deleted is True
    assert crud.get_show_by_id("test_show_999") is None
    assert len(crud.get_episodes_by_show("test_show_999")) == 0

@pytest.mark.asyncio
async def test_image_proxy_pillow_padding():
    # Vytvoříme testovací 4:3 obrázek (400x300 px) v paměti
    img = Image.new("RGB", (400, 300), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    raw_bytes = buf.getvalue()

    # Vložíme do diskové cache jako originál
    test_url = "https://img.ceskatelevize.cz/test_image.jpg"
    raw_cache_path = image_proxy.get_cache_path(test_url, pad=None)
    raw_cache_path.write_bytes(raw_bytes)

    # Vyžádáme obrázek s pad="2x3"
    padded_bytes, media_type = await image_proxy.fetch_image(test_url, pad="2x3")
    assert padded_bytes is not None
    assert media_type == "image/jpeg"

    # Ověříme, že výsledný obrázek má přesně rozměry 600x900 (2:3 poměr stran)
    padded_img = Image.open(io.BytesIO(padded_bytes))
    assert padded_img.size == (600, 900)
    # Ověříme adaptivní pozadí s barevným vzorkováním okrajů
    corner_pixel = padded_img.getpixel((5, 5))
    assert isinstance(corner_pixel, tuple) and len(corner_pixel) == 3

def test_shift_vtt_timestamps():
    sample_vtt = (
        "WEBVTT\n\n"
        "1\n"
        "00:00:10.000 --> 00:00:15.500\n"
        "První řádek titulků\n\n"
        "2\n"
        "01:59:58.500 --> 02:00:01.000\n"
        "Druhý řádek přes hranici hodiny\n"
    )
    # Default shift +1.8 seconds
    shifted = shift_vtt_timestamps(sample_vtt, 1.8)
    assert "00:00:11.800 --> 00:00:17.300" in shifted
    assert "02:00:00.300 --> 02:00:02.800" in shifted

    # Negative offset (e.g. -5s) with floor at 0
    sample_early = "00:00:02.000 --> 00:00:06.000"
    shifted_early = shift_vtt_timestamps(sample_early, -5.0)
    assert "00:00:00.000 --> 00:00:01.000" in shifted_early

@pytest.mark.asyncio
async def test_direct_vtt_and_hls_subtitle_routes(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services.ct_service import ct_service

    async def mock_resolve_vod(idec, allow_drm=False):
        return {
            "hls_url": "https://ivys-cdn.cz/master.m3u8",
            "subtitles": [
                {"language": "ces", "label": "Čeština", "url": "https://ctfs.cz/test.vtt"}
            ]
        }

    monkeypatch.setattr(ct_service, "resolve_vod_stream", mock_resolve_vod)

    client = TestClient(app)

    # 1. HLS WebVTT subtitle playlist musí obsahovat segment končící na .vtt
    resp_sub = client.get("/api/hls/subtitles/12345.m3u8")
    assert resp_sub.status_code == 200
    assert "/api/subtitles/12345.vtt" in resp_sub.text

    # 2. Master playlist musí nabízet HLS .m3u8 odkaz v #EXT-X-MEDIA (podle RFC 8216)
    import unittest.mock as mock
    with mock.patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=5000000\nstream.m3u8"
        mock_get.return_value = mock_resp

        # a) Požadavek s xtream=1
        resp_crawler = client.get("/api/hls/master/12345.m3u8?xtream=1")
        assert resp_crawler.status_code == 200
        assert 'URI="http://testserver/api/hls/subtitles/12345.m3u8"' in resp_crawler.text

        # b) Požadavek s User-Agentem xtream-gui
        resp_ua = client.get("/api/hls/master/12345.m3u8", headers={"User-Agent": "Mozilla/5.0 (compatible; xtream-gui/1.0)"})
        assert resp_ua.status_code == 200
        assert 'URI="http://testserver/api/hls/subtitles/12345.m3u8"' in resp_ua.text

        # c) Běžný přehrávač (např. TiviMate/VLC)
        resp_player = client.get("/api/hls/master/12345.m3u8", headers={"User-Agent": "TiviMate/4.7.0"})
        assert resp_player.status_code == 200
        assert 'URI="http://testserver/api/hls/subtitles/12345.m3u8"' in resp_player.text
