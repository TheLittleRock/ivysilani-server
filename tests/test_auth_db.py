import pytest
import os
import tempfile
from pathlib import Path

# Override DATA_DIR for test
temp_dir = tempfile.mkdtemp()
os.environ["DATA_DIR"] = temp_dir

from app.db.database import init_db, get_db
from app.db import crud
from app.core.security import verify_password, hash_password

def test_db_init_and_admin_seed():
    init_db()
    user = crud.get_user_by_username("admin")
    assert user is not None
    assert user["username"] == "admin"
    assert user["is_admin"] == 1
    assert verify_password("admin", user["password_hash"])

def test_user_crud():
    # Vytvoření nového uživatele
    user_id = crud.create_user(
        username="testuser",
        password="secretpassword",
        max_connections=2,
        is_admin=False
    )
    assert user_id > 0

    # Získání uživatele
    user = crud.get_user_by_username("testuser")
    assert user is not None
    assert user["username"] == "testuser"
    assert user["max_connections"] == 2
    assert user["is_admin"] == 0

    # Ověření přihlášení
    auth_user = crud.authenticate_user("testuser", "secretpassword")
    assert auth_user is not None
    assert auth_user["username"] == "testuser"

    # Neplatné heslo
    bad_auth = crud.authenticate_user("testuser", "wrongpassword")
    assert bad_auth is None

    # Smazání uživatele
    deleted = crud.delete_user(user["id"])
    assert deleted is True
    assert crud.get_user_by_username("testuser") is None

def test_show_and_episode_crud():
    # Vytvoření pořadu
    crud.upsert_show(
        show_id="test-serial",
        title="Testovací Seriál",
        slug="testovaci-serial",
        description="Popis testovacího pořadu",
        image_url="https://example.com/img.jpg",
        genre="Drama",
        year="2024"
    )

    show = crud.get_show_by_id("test-serial")
    assert show is not None
    assert show["title"] == "Testovací Seriál"

    # Vytvoření epizod
    crud.upsert_episode(
        ep_id="ep1",
        show_id="test-serial",
        idec="IDEC123",
        title="Díl 1",
        description="První epizoda",
        duration=3600,
        season=1,
        episode_num=1
    )
    crud.upsert_episode(
        ep_id="ep2",
        show_id="test-serial",
        idec="IDEC124",
        title="Díl 2",
        description="Druhá epizoda",
        duration=3500,
        season=1,
        episode_num=2
    )

    show_episodes = crud.get_episodes_by_show("test-serial")
    assert len(show_episodes) == 2
    assert show_episodes[0]["title"] == "Díl 1"

    # Hledání
    results = crud.list_shows(search="Testovací")
    assert len(results) == 1
    assert results[0]["id"] == "test-serial"
