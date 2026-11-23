import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db.database import init_db
from app.db import crud

client = TestClient(app)
AUTH_COOKIES = {"ivys_user": "admin", "ivys_token": "active"}

@pytest.fixture(autouse=True)
def setup_database():
    init_db()

def test_unauthenticated_redirect():
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"

def test_root_web_ui_authenticated():
    response = client.get("/", cookies=AUTH_COOKIES)
    assert response.status_code == 200
    assert "iVysílání" in response.text
    assert "ČT1" in response.text

def test_archive_web_ui_authenticated():
    response = client.get("/archive", cookies=AUTH_COOKIES)
    assert response.status_code == 200
    assert "Katalog a archiv" in response.text

def test_xtream_info_page():
    response = client.get("/xtream", cookies=AUTH_COOKIES)
    assert response.status_code == 200
    assert "Xtream Codes" in response.text

def test_stremio_info_page():
    response = client.get("/stremio", cookies=AUTH_COOKIES)
    assert response.status_code == 200
    assert "Stremio" in response.text

def test_player_api_unauthorized():
    response = client.get("/player_api.php?username=baduser&password=badpass")
    assert response.status_code == 200
    data = response.json()
    assert "user_info" in data
    assert data["user_info"]["auth"] == 0

def test_player_api_auth_success():
    response = client.get("/player_api.php?username=admin&password=admin")
    assert response.status_code == 200
    data = response.json()
    assert "user_info" in data
    assert data["user_info"]["auth"] == 1
    assert data["user_info"]["username"] == "admin"
    assert "server_info" in data

def test_player_api_get_live_categories():
    response = client.get("/player_api.php?username=admin&password=admin&action=get_live_categories")
    assert response.status_code == 200
    categories = response.json()
    assert isinstance(categories, list)
    assert len(categories) > 0

def test_player_api_get_live_streams():
    response = client.get("/player_api.php?username=admin&password=admin&action=get_live_streams")
    assert response.status_code == 200
    streams = response.json()
    assert isinstance(streams, list)
    assert len(streams) >= 14
    ch1 = next((s for s in streams if s["stream_id"] == 1), None)
    assert ch1 is not None
    assert ch1["name"] == "ČT1"
    assert "/static/logos/ct1.png" in ch1["stream_icon"]

def test_get_m3u_playlist():
    response = client.get("/get.php?username=admin&password=admin&type=m3u_plus")
    assert response.status_code == 200
    assert "#EXTM3U" in response.text
    assert "ČT1" in response.text
    assert "catchup=\"default\"" in response.text
    assert "catchup-days=\"14\"" in response.text
    assert "/static/logos/ct1.png" in response.text

def test_get_m3u_playlist_token():
    from app.db import crud
    user = crud.get_user_by_username("admin")
    token = user.get("user_token")
    response = client.get(f"/get.php?token={token}&type=m3u_plus")
    assert response.status_code == 200
    assert "#EXTM3U" in response.text
    assert f"/live/{token}/1.m3u8" in response.text
    assert f"xmltv.php?token={token}" in response.text
    # Overime, ze M3U playlist obsahuje presne 14 zivych stanic CT bez nahodnych VOD poradu
    extinf_lines = [l for l in response.text.splitlines() if l.startswith("#EXTINF:")]
    assert len(extinf_lines) == 14

def test_xmltv_epg():
    response = client.get("/xmltv.php?username=admin&password=admin")
    assert response.status_code == 200
    assert "<?xml" in response.text
    assert "<tv" in response.text
    assert 'id="ct1.cz"' in response.text or 'id="CH_1"' in response.text

def test_stremio_manifest():
    response = client.get("/stremio/manifest.json")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "cz.thelittlerock.ivysilani"
    assert "iVysílání" in data["name"]
    catalogs = data["catalogs"]
    # Zive vysilani je vyrazeno ze Stremio doplňku dle zadani
    assert not any(c["id"] == "ct_live" for c in catalogs)
    assert any(c["id"] == "ct_series" for c in catalogs)
    assert any(c["id"] == "ct_movies" for c in catalogs)

def test_stremio_live_catalog():
    response = client.get("/stremio/catalog/tv/ct_live.json")
    assert response.status_code == 200
    data = response.json()
    assert "metas" in data
    assert len(data["metas"]) >= 14
    ct1 = next((m for m in data["metas"] if m["id"] == "ct_live_CH_1"), None)
    assert ct1 is not None
    assert ct1["name"] == "ČT1"

def test_stremio_live_meta():
    response = client.get("/stremio/meta/tv/ct_live_CH_1.json")
    assert response.status_code == 200
    data = response.json()
    assert "meta" in data
    assert data["meta"]["id"] == "ct_live_CH_1"
    assert data["meta"]["name"] == "ČT1"

def test_stremio_live_stream():
    response = client.get("/stremio/stream/tv/ct_live_CH_1.json")
    assert response.status_code == 200
    data = response.json()
    assert "streams" in data
    assert len(data["streams"]) > 0
    assert "url" in data["streams"][0]

def test_stremio_tokenized_manifest_and_catalogs():
    from app.db import crud
    user = crud.get_user_by_username("admin")
    token = user.get("user_token")
    assert token is not None

    # Test tokenized manifest
    response = client.get(f"/stremio/{token}/manifest.json")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "cz.thelittlerock.ivysilani"
    assert "/static/logos/ct1.png" in data["logo"]
    catalogs = data["catalogs"]
    catalog_ids = [c["id"] for c in catalogs]
    assert "ct_live" not in catalog_ids
    assert "ct_series" in catalog_ids
    assert "ct_movies" in catalog_ids

    # Test tokenized stream
    stream_resp = client.get(f"/stremio/{token}/stream/tv/ct_live_CH_1.json")
    assert stream_resp.status_code == 200
    st_data = stream_resp.json()
    assert "streams" in st_data
    assert len(st_data["streams"]) > 0
    assert token in st_data["streams"][0]["url"]

def test_xtream_series_api():
    # 1. get_series_categories
    resp = client.get("/player_api.php?username=admin&password=admin&action=get_series_categories")
    assert resp.status_code == 200
    cats = resp.json()
    assert isinstance(cats, list)
    assert any("seriál" in c["category_name"].lower() for c in cats)

    # 2. get_series
    resp_s = client.get("/player_api.php?username=admin&password=admin&action=get_series")
    assert resp_s.status_code == 200
    series = resp_s.json()
    assert isinstance(series, list)

    # 3. get_series_info (ověření struktury sérií a epizod pro kompatibilitu se stahovači a přehrávači)
    crud.upsert_show(
        show_id="999888777",
        title="Testovací Seriál",
        show_type="series"
    )
    crud.upsert_episode(
        ep_id="999888777_s1e1",
        show_id="999888777",
        idec="11111",
        title="Díl 1 S1",
        season=1,
        episode_num=1
    )
    crud.upsert_episode(
        ep_id="999888777_s2e1",
        show_id="999888777",
        idec="22222",
        title="Díl 1 S2",
        season=2,
        episode_num=1
    )
    info_resp = client.get("/player_api.php?username=admin&password=admin&action=get_series_info&series_id=999888777")
    assert info_resp.status_code == 200
    info_data = info_resp.json()
    assert "seasons" in info_data
    assert "episodes" in info_data
    
    # Ověříme, že v seasons jsou obě série se správnými season_number
    s_numbers = [s["season_number"] for s in info_data["seasons"]]
    assert 1 in s_numbers
    assert 2 in s_numbers

    # Ověříme, že každá epizoda má explicitní season a info.season jako int (prevence S00 chyby)
    ep_s1 = info_data["episodes"]["1"][0]
    assert ep_s1["season"] == 1
    assert ep_s1["season_number"] == 1
    assert ep_s1["info"]["season"] == 1
    assert ep_s1["episode_num"] == 1

    ep_s2 = info_data["episodes"]["2"][0]
    assert ep_s2["season"] == 2
    assert ep_s2["season_number"] == 2
    assert ep_s2["info"]["season"] == 2
    assert ep_s2["episode_num"] == 1

    # 4. timeshift endpoint check
    ts_resp = client.get("/streaming/timeshift.php?username=admin&password=admin&stream=1", follow_redirects=False)
    assert ts_resp.status_code in [302, 200]

def test_image_proxy_endpoint():
    resp = client.get("/api/image-proxy?url=https://www.ceskatelevize.cz/favicon.ico")
    assert resp.status_code == 200

def test_subtitle_proxy_endpoint():
    # CORS headers and proxying
    resp = client.get("/api/subtitles?url=https://www.ceskatelevize.cz/favicon.ico")
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "*"

def test_admin_subtitle_settings():
    # Test uložení posunu titulků přes admin UI
    resp = client.post(
        "/admin/settings/subtitles",
        data={"subtitle_offset_seconds": "1.8"},
        cookies=AUTH_COOKIES,
        follow_redirects=False
    )
    assert resp.status_code == 303
    assert crud.get_setting("subtitle_offset_seconds") == "1.8"

def test_downloads_list_api():
    resp = client.get("/api/downloads/list", cookies=AUTH_COOKIES)
    assert resp.status_code == 200
    data = resp.json()
    assert "tasks" in data
    assert isinstance(data["tasks"], list)

def test_stremio_tmdb_id_pairing():
    # Insert a show with TMDB / IMDb IDs
    crud.upsert_show(
        show_id="12155281075",
        title="Bod obnovy",
        description="Sci-fi thriller",
        show_type="movie",
        tmdb_id="1071815",
        imdb_id="tt9362492",
        tmdb_poster="https://image.tmdb.org/t/p/w500/test.jpg"
    )
    crud.upsert_episode(
        ep_id="21951212035",
        show_id="12155281075",
        title="Bod obnovy",
        idec="21951212035"
    )
    
    # Check meta resolution via IMDb ID
    meta_resp = client.get("/stremio/meta/movie/tt9362492.json")
    assert meta_resp.status_code == 200
    meta_data = meta_resp.json()
    assert "meta" in meta_data
    assert meta_data["meta"]["name"] == "Bod obnovy"
    assert meta_data["meta"]["id"] == "tt9362492"
    assert "poster" in meta_data["meta"]

def test_series_episode_numbering_normalization():
    # Test that shifted episode numbers (e.g. S01 starting at 4, S02 starting at 11)
    # are normalized to 1..N per season in get_series_info
    crud.upsert_show(
        show_id="test_series_shifted",
        title="Test Shifted Series",
        show_type="series"
    )
    # Season 1 with shifted numbers (4, 5, 6)
    crud.upsert_episode(ep_id="ep_s1_4", show_id="test_series_shifted", title="Díl 4", idec="90001", season=1, episode_num=4)
    crud.upsert_episode(ep_id="ep_s1_5", show_id="test_series_shifted", title="Díl 5", idec="90002", season=1, episode_num=5)
    crud.upsert_episode(ep_id="ep_s1_6", show_id="test_series_shifted", title="Díl 6", idec="90003", season=1, episode_num=6)

    # Season 2 with shifted numbers (11, 12)
    crud.upsert_episode(ep_id="ep_s2_11", show_id="test_series_shifted", title="Díl 11", idec="90011", season=2, episode_num=11)
    crud.upsert_episode(ep_id="ep_s2_12", show_id="test_series_shifted", title="Díl 12", idec="90012", season=2, episode_num=12)

    resp = client.get("/player_api.php?username=admin&password=admin&action=get_series_info&series_id=test_series_shifted")
    assert resp.status_code == 200
    data = resp.json()
    episodes = data["episodes"]

    # Season 1 should be normalized to 1, 2, 3
    s1_nums = [e["episode_num"] for e in episodes["1"]]
    assert s1_nums == [1, 2, 3]

    # Season 2 should be normalized to 1, 2
    s2_nums = [e["episode_num"] for e in episodes["2"]]
    assert s2_nums == [1, 2]

@pytest.mark.asyncio
async def test_tmdb_episode_matching_and_alignment(monkeypatch):
    from app.services.tmdb_service import tmdb_service

    # Mock get_tv_episodes to return multi-season structure like Montalbano
    async def mock_get_tv_episodes(tmdb_id):
        return [
            {"season": 1, "episode": 1, "name": "Zloděj školních svačin", "norm_name": tmdb_service.normalize_title("Zloděj školních svačin")},
            {"season": 1, "episode": 2, "name": "Hlas houslí", "norm_name": tmdb_service.normalize_title("Hlas houslí")},
            {"season": 2, "episode": 1, "name": "Tvar vody", "norm_name": tmdb_service.normalize_title("Tvar vody")},
            {"season": 2, "episode": 2, "name": "Hliněný pes", "norm_name": tmdb_service.normalize_title("Hliněný pes")},
        ]

    monkeypatch.setattr(tmdb_service, "get_tv_episodes", mock_get_tv_episodes)

    crud.upsert_show(show_id="montalbano_test", title="Komisař Montalbano", show_type="series", tmdb_id="37290")
    # All episodes initially in season 1
    crud.upsert_episode(ep_id="m1", show_id="montalbano_test", title="Tvar vody", idec="101", season=1, episode_num=1)
    crud.upsert_episode(ep_id="m2", show_id="montalbano_test", title="Hliněný pes", idec="102", season=1, episode_num=2)
    crud.upsert_episode(ep_id="m3", show_id="montalbano_test", title="Zloděj školních svačin", idec="103", season=1, episode_num=3)
    crud.upsert_episode(ep_id="m4", show_id="montalbano_test", title="Hlas houslí", idec="104", season=1, episode_num=4)

    res = await tmdb_service.align_show_episodes("montalbano_test", "37290")
    assert res["status"] == "ok"
    assert res["matched"] == 4

    ep_tvar = crud.get_episode_by_id("m1")
    assert ep_tvar["season"] == 2
    assert ep_tvar["episode_num"] == 1

    ep_zlodej = crud.get_episode_by_id("m3")
    assert ep_zlodej["season"] == 1
    assert ep_zlodej["episode_num"] == 1

@pytest.mark.asyncio
async def test_on_demand_series_info_aligns_season_gaps():
    from unittest.mock import patch
    from app.services.tmdb_service import tmdb_service
    crud.upsert_show(show_id="montalbano_gap_test", title="Komisař Montalbano", show_type="series", tmdb_id="37290")
    # Season 1 has S1 & S2 episodes, and Season 5 already exists (gap: missing S2, S3, S4)
    crud.upsert_episode(ep_id="mg1", show_id="montalbano_gap_test", title="Tvar vody", idec="1011", season=1, episode_num=1)
    crud.upsert_episode(ep_id="mg2", show_id="montalbano_gap_test", title="Hliněný pes", idec="1012", season=1, episode_num=2)
    crud.upsert_episode(ep_id="mg3", show_id="montalbano_gap_test", title="Zloděj školních svačin", idec="1013", season=1, episode_num=3)
    crud.upsert_episode(ep_id="mg4", show_id="montalbano_gap_test", title="Hlas houslí", idec="1014", season=1, episode_num=4)
    crud.upsert_episode(ep_id="mg5", show_id="montalbano_gap_test", title="Bod zlomu", idec="1015", season=5, episode_num=1)

    with patch.object(tmdb_service, "get_tv_episodes", return_value=[
        {"season": 1, "episode": 1, "name": "Zloděj školních svačin", "norm_name": "zlodej skolnich svacin"},
        {"season": 1, "episode": 2, "name": "Hlas houslí", "norm_name": "hlas housli"},
        {"season": 2, "episode": 1, "name": "Tvar vody", "norm_name": "tvar vody"},
        {"season": 2, "episode": 2, "name": "Hliněný pes", "norm_name": "hlineny pes"},
        {"season": 5, "episode": 1, "name": "Bod zlomu", "norm_name": "bod zlomu"}
    ]):
        resp = client.get("/player_api.php?username=admin&password=admin&action=get_series_info&series_id=montalbano_gap_test")
        assert resp.status_code == 200
        data = resp.json()
        seasons = [s["season_number"] for s in data["seasons"]]
        assert 1 in seasons
        assert 2 in seasons
        assert 5 in seasons
        eps_s2 = data["episodes"]["2"]
        assert len(eps_s2) == 2
        assert eps_s2[0]["title"] == "Tvar vody"

@pytest.mark.asyncio
async def test_series_info_preserves_tmdb_episode_numbers_when_episodes_missing():
    crud.upsert_show(show_id="bob_bobek_test", title="Bob a Bobek", show_type="series", tmdb_id="70198")
    # Only episodes 6, 8, 9, 10, 11, 12, 13 are playable (1-5 and 7 missing)
    crud.upsert_episode(ep_id="bb_6", show_id="bob_bobek_test", title="V galerii", idec="20006", season=3, episode_num=6)
    crud.upsert_episode(ep_id="bb_8", show_id="bob_bobek_test", title="V lázních", idec="20008", season=3, episode_num=8)
    crud.upsert_episode(ep_id="bb_9", show_id="bob_bobek_test", title="Na pouti", idec="20009", season=3, episode_num=9)
    crud.upsert_episode(ep_id="bb_10", show_id="bob_bobek_test", title="Při povodni", idec="20010", season=3, episode_num=10)
    crud.upsert_episode(ep_id="bb_11", show_id="bob_bobek_test", title="Ve službách vědy", idec="20011", season=3, episode_num=11)
    crud.upsert_episode(ep_id="bb_12", show_id="bob_bobek_test", title="Návštěva z vesmíru", idec="20012", season=3, episode_num=12)
    crud.upsert_episode(ep_id="bb_13", show_id="bob_bobek_test", title="Na ostrově", idec="20013", season=3, episode_num=13)

    resp = client.get("/player_api.php?username=admin&password=admin&action=get_series_info&series_id=bob_bobek_test")
    assert resp.status_code == 200
    data = resp.json()
    s3_eps = data["episodes"]["3"]
    assert len(s3_eps) == 7
    ep_nums = [e["episode_num"] for e in s3_eps]
    assert ep_nums == [6, 8, 9, 10, 11, 12, 13]
    assert s3_eps[0]["title"] == "V galerii"
    assert s3_eps[0]["episode_num"] == 6
    assert s3_eps[0]["info"]["episode_num"] == 6

def test_live_stream_m3u8_and_mpd_endpoints():
    user = crud.get_user_by_username("admin")
    token = user["user_token"]

    # 1. Standard HLS stream (.m3u8) vrací přímo přepsaný master playlist s 1080p FHD (případně 302 fallback)
    resp_hls = client.get(f"/live/{token}/2.m3u8", follow_redirects=False)
    assert resp_hls.status_code in [200, 302]
    if resp_hls.status_code == 200:
        assert "application/vnd.apple.mpegurl" in resp_hls.headers["content-type"]
        assert "1920x1080" in resp_hls.text
    else:
        assert "contentType=live" in resp_hls.headers["location"]

    # 2. DASH DRM stream (.mpd) redirects to proxied DRM manifest
    resp_mpd = client.get(f"/live/{token}/2.mpd", follow_redirects=False)
    assert resp_mpd.status_code == 302
    assert "/api/drm/" in resp_mpd.headers["location"]
    assert resp_mpd.headers["location"].endswith("/manifest.mpd")

@pytest.mark.asyncio
async def test_align_show_episodes_fixes_bogus_seasons_with_single_tmdb_season():
    from unittest.mock import patch
    from app.services.tmdb_service import tmdb_service
    crud.upsert_show(show_id="rytiri_test", title="Ať žijí rytíři!", show_type="series", tmdb_id="293395")
    # Bogus seasons 14 and 7 from ČT duration tabs
    crud.upsert_episode(ep_id="r1", show_id="rytiri_test", title="1. Loučení", idec="201", season=14, episode_num=1)
    crud.upsert_episode(ep_id="r2", show_id="rytiri_test", title="2. Pán tvrze", idec="202", season=14, episode_num=2)
    crud.upsert_episode(ep_id="r3", show_id="rytiri_test", title="Královský posel", idec="203", season=7, episode_num=1)

    with patch.object(tmdb_service, "get_tv_episodes", return_value=[
        {"season": 1, "episode": 1, "name": "Loučení", "norm_name": "louceni"},
        {"season": 1, "episode": 2, "name": "Pán tvrze", "norm_name": "pan tvrze"},
        {"season": 1, "episode": 3, "name": "Královský posel", "norm_name": "kralovsky posel"}
    ]):
        res = await tmdb_service.align_show_episodes("rytiri_test", "293395")
        assert res["status"] == "ok"
        assert res["matched"] == 3

        ep1 = crud.get_episode_by_id("r1")
        assert ep1["season"] == 1
        assert ep1["episode_num"] == 1

        ep2 = crud.get_episode_by_id("r2")
        assert ep2["season"] == 1
        assert ep2["episode_num"] == 2

        ep3 = crud.get_episode_by_id("r3")
        assert ep3["season"] == 1
        assert ep3["episode_num"] == 3







