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
    assert any(c["id"] == "ct_live" for c in catalogs)
    assert any(c["id"] == "ct_series" for c in catalogs)

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
    assert "ct_live" in catalog_ids
    assert "ct_series" in catalog_ids
    assert "ct_movies" in catalog_ids
    assert "ct_entertainment" in catalog_ids
    assert "ct_documentaries" in catalog_ids
    assert "ct_kids" in catalog_ids

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
    assert any(c["category_name"] == "Seriály" for c in cats)

    # 2. get_series
    resp_s = client.get("/player_api.php?username=admin&password=admin&action=get_series")
    assert resp_s.status_code == 200
    series = resp_s.json()
    assert isinstance(series, list)

    # 3. timeshift endpoint check
    ts_resp = client.get("/streaming/timeshift.php?username=admin&password=admin&stream=1", follow_redirects=False)
    assert ts_resp.status_code in [302, 200]

def test_image_proxy_endpoint():
    resp = client.get("/api/image-proxy?url=https://www.ceskatelevize.cz/favicon.ico")
    assert resp.status_code == 200

