import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db.database import init_db
from app.db import crud

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_database():
    init_db()

def test_root_web_ui():
    response = client.get("/")
    assert response.status_code == 200
    assert "iVysílání Server" in response.text
    assert "ČT1" in response.text

def test_archive_web_ui():
    response = client.get("/archive")
    assert response.status_code == 200
    assert "Archiv" in response.text

def test_xtream_info_page():
    response = client.get("/xtream")
    assert response.status_code == 200
    assert "Xtream Codes" in response.text

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
    cat_names = [c["category_name"] for c in categories]
    assert "Česká televize" in cat_names

def test_player_api_get_live_streams():
    response = client.get("/player_api.php?username=admin&password=admin&action=get_live_streams")
    assert response.status_code == 200
    streams = response.json()
    assert isinstance(streams, list)
    assert len(streams) >= 14
    stream_names = [s["name"] for s in streams]
    assert any("ČT1" in name for name in stream_names)
    assert any("ČT24" in name for name in stream_names)

def test_get_m3u_playlist():
    response = client.get("/get.php?username=admin&password=admin&type=m3u_plus")
    assert response.status_code == 200
    assert "#EXTM3U" in response.text
    assert "tvg-id=" in response.text
    assert "ČT1" in response.text

def test_xmltv_epg():
    response = client.get("/xmltv.php?username=admin&password=admin")
    assert response.status_code == 200
    assert "<?xml" in response.text
    assert "<tv" in response.text
    assert '<channel id="ct1.cz">' in response.text
