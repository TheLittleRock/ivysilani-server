import time
import secrets
from typing import List, Optional, Dict, Any
from app.db.database import get_db
from app.core.security import get_password_hash, verify_password

# --- Správa uživatelů ---

def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_user_by_token(token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_token = ? AND is_active = 1", (token,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def list_users() -> List[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, user_token, is_admin, is_active, exp_date, max_connections, created_at, last_active FROM users ORDER BY id ASC")
        return [dict(r) for r in cursor.fetchall()]

def create_user(username: str, password: str, is_admin: bool = False, exp_date: Optional[int] = None, max_connections: int = 2) -> Optional[int]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        if cursor.fetchone():
            return None
        now = int(time.time())
        pwd_hash = get_password_hash(password)
        token = secrets.token_hex(16)
        cursor.execute("""
        INSERT INTO users (username, password_hash, user_token, is_admin, is_active, exp_date, max_connections, created_at, last_active)
        VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
        """, (username, pwd_hash, token, 1 if is_admin else 0, exp_date, max_connections, now, now))
        return cursor.lastrowid

def update_user(user_id: int, password: Optional[str] = None, is_admin: Optional[bool] = None, is_active: Optional[bool] = None, exp_date: Optional[int] = None, max_connections: Optional[int] = None) -> bool:
    with get_db() as conn:
        cursor = conn.cursor()
        updates = []
        params = []
        if password is not None and password.strip():
            updates.append("password_hash = ?")
            params.append(get_password_hash(password))
        if is_admin is not None:
            updates.append("is_admin = ?")
            params.append(1 if is_admin else 0)
        if is_active is not None:
            updates.append("is_active = ?")
            params.append(1 if is_active else 0)
        if exp_date is not None:
            updates.append("exp_date = ?")
            params.append(exp_date)
        if max_connections is not None:
            updates.append("max_connections = ?")
            params.append(max_connections)
        if not updates:
            return True
        params.append(user_id)
        cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
        return cursor.rowcount > 0

def delete_user(user_id: int) -> bool:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return False
        if row["is_admin"]:
            cursor.execute("SELECT COUNT(*) as count FROM users WHERE is_admin = 1")
            admin_count = cursor.fetchone()["count"]
            if admin_count <= 1:
                return False
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return cursor.rowcount > 0

def update_user_activity(username: str):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET last_active = ? WHERE username = ?", (int(time.time()), username))

def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    user = get_user_by_username(username)
    if not user:
        return None
    if not user.get("is_active", 1):
        return None
    exp_date = user.get("exp_date")
    if exp_date and exp_date < int(time.time()):
        return None
    # Umožníme ověření buď klasickým heslem, nebo neměnným uživatelským tokenem
    is_valid_pwd = verify_password(password, user["password_hash"])
    is_valid_token = bool(user.get("user_token") and password == user["user_token"])
    if not (is_valid_pwd or is_valid_token):
        return None
    update_user_activity(username)
    return user

# --- Správa pořadů a epizod (VOD Katalog) ---

def upsert_show(
    show_id: str,
    title: str,
    slug: str = "",
    description: str = "",
    image_url: str = "",
    poster_url: str = "",
    backdrop_url: str = "",
    logo_url: str = "",
    genre: str = "",
    year: str = "",
    show_type: str = "series",
    is_playable: bool = True,
    total_episodes: int = 0,
    tmdb_id: Optional[str] = None,
    imdb_id: Optional[str] = None,
    tmdb_poster: Optional[str] = None,
    tmdb_backdrop: Optional[str] = None
):
    with get_db() as conn:
        cursor = conn.cursor()
        now = int(time.time())
        cursor.execute("""
        INSERT INTO shows (id, title, slug, description, image_url, poster_url, backdrop_url, logo_url, genre, year, show_type, is_playable, total_episodes, updated_at, tmdb_id, imdb_id, tmdb_poster, tmdb_backdrop)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title=excluded.title,
            slug=excluded.slug,
            description=excluded.description,
            image_url=excluded.image_url,
            poster_url=excluded.poster_url,
            backdrop_url=excluded.backdrop_url,
            logo_url=excluded.logo_url,
            genre=excluded.genre,
            year=excluded.year,
            show_type=excluded.show_type,
            is_playable=excluded.is_playable,
            total_episodes=excluded.total_episodes,
            updated_at=excluded.updated_at,
            tmdb_id=COALESCE(excluded.tmdb_id, shows.tmdb_id),
            imdb_id=COALESCE(excluded.imdb_id, shows.imdb_id),
            tmdb_poster=COALESCE(excluded.tmdb_poster, shows.tmdb_poster),
            tmdb_backdrop=COALESCE(excluded.tmdb_backdrop, shows.tmdb_backdrop)
        """, (
            show_id, title, slug, description, image_url,
            poster_url or image_url, backdrop_url or image_url, logo_url,
            genre, year, show_type, 1 if is_playable else 0, total_episodes, now,
            tmdb_id, imdb_id, tmdb_poster, tmdb_backdrop
        ))

def upsert_episode(
    ep_id: str,
    show_id: str,
    idec: str,
    title: str,
    description: str = "",
    image_url: str = "",
    duration: int = 0,
    season: int = 1,
    episode_num: int = 1,
    broadcast_date: str = "",
    is_playable: bool = True,
    is_drm: bool = False
):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO episodes (id, show_id, idec, title, description, image_url, duration, season, episode_num, broadcast_date, is_playable, is_drm)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            show_id=excluded.show_id,
            idec=excluded.idec,
            title=excluded.title,
            description=excluded.description,
            image_url=excluded.image_url,
            duration=excluded.duration,
            season=excluded.season,
            episode_num=excluded.episode_num,
            broadcast_date=excluded.broadcast_date,
            is_playable=excluded.is_playable,
            is_drm=excluded.is_drm
        """, (ep_id, show_id, idec, title, description, image_url, duration, season, episode_num, broadcast_date, 1 if is_playable else 0, 1 if is_drm else 0))

def get_setting(key: str, default: str = "") -> str:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row["value"] if row and row["value"] is not None else default

def set_setting(key: str, value: str) -> None:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

def get_show_by_imdb_id(imdb_id: str) -> Optional[Dict[str, Any]]:
    if not imdb_id:
        return None
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM shows WHERE imdb_id = ?", (imdb_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_show_by_tmdb_id(tmdb_id: str) -> Optional[Dict[str, Any]]:
    if not tmdb_id:
        return None
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM shows WHERE tmdb_id = ?", (str(tmdb_id),))
        row = cursor.fetchone()
        return dict(row) if row else None

def update_show_tmdb(show_id: str, tmdb_id: str, imdb_id: str, tmdb_poster: str = "", tmdb_backdrop: str = "") -> bool:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        UPDATE shows SET tmdb_id = ?, imdb_id = ?, tmdb_poster = ?, tmdb_backdrop = ? WHERE id = ?
        """, (tmdb_id, imdb_id, tmdb_poster, tmdb_backdrop, show_id))
        return cursor.rowcount > 0

def mark_show_playable(show_id: str, is_playable: bool):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE shows SET is_playable = ? WHERE id = ?", (1 if is_playable else 0, show_id))

def list_shows(
    genre: Optional[str] = None,
    show_type: Optional[str] = None,
    only_playable: bool = False,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> List[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM shows"
        params = []
        conditions = []

        effective_show_type = show_type
        if genre:
            g_low = genre.lower().strip()
            if g_low in ["filmy", "film"]:
                effective_show_type = "movie"
            elif g_low in ["seriály", "serialy", "seriál", "serial"]:
                effective_show_type = "series"
            elif g_low in ["dokumenty", "dokument"]:
                conditions.append("(genre LIKE '%Dokument%' OR genre LIKE '%Publicistika%')")
            elif g_low not in ["all", "vše", "vse"]:
                conditions.append("genre LIKE ?")
                params.append(f"%{genre}%")

        if effective_show_type:
            conditions.append("show_type = ?")
            params.append(effective_show_type)

        if only_playable:
            conditions.append("is_playable = 1")
        if search:
            conditions.append("(title LIKE ? OR description LIKE ?)")
            params.append(f"%{search}%")
            params.append(f"%{search}%")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY updated_at DESC, title ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor.execute(query, params)
        return [dict(r) for r in cursor.fetchall()]

def list_series(genre: Optional[str] = None, only_playable: bool = True, search: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    return list_shows(genre=genre, show_type="series", only_playable=only_playable, search=search, limit=limit, offset=offset)

def list_movies(genre: Optional[str] = None, only_playable: bool = True, search: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    return list_shows(genre=genre, show_type="movie", only_playable=only_playable, search=search, limit=limit, offset=offset)

def count_shows(
    genre: Optional[str] = None,
    show_type: Optional[str] = None,
    only_playable: bool = False,
    search: Optional[str] = None
) -> int:
    with get_db() as conn:
        cursor = conn.cursor()
        query = "SELECT COUNT(*) as cnt FROM shows"
        params = []
        conditions = []

        effective_show_type = show_type
        if genre:
            g_low = genre.lower().strip()
            if g_low in ["filmy", "film"]:
                effective_show_type = "movie"
            elif g_low in ["seriály", "serialy", "seriál", "serial"]:
                effective_show_type = "series"
            elif g_low in ["dokumenty", "dokument"]:
                conditions.append("(genre LIKE '%Dokument%' OR genre LIKE '%Publicistika%')")
            elif g_low not in ["all", "vše", "vse"]:
                conditions.append("genre LIKE ?")
                params.append(f"%{genre}%")

        if effective_show_type:
            conditions.append("show_type = ?")
            params.append(effective_show_type)

        if only_playable:
            conditions.append("is_playable = 1")
        if search:
            conditions.append("(title LIKE ? OR description LIKE ?)")
            params.append(f"%{search}%")
            params.append(f"%{search}%")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        cursor.execute(query, params)
        return cursor.fetchone()["cnt"]

def get_show_by_id(show_id: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM shows WHERE id = ?", (show_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_episodes_by_show(show_id: str, only_playable: bool = False) -> List[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        if only_playable:
            cursor.execute("SELECT * FROM episodes WHERE show_id = ? AND is_playable = 1 ORDER BY season ASC, episode_num ASC", (show_id,))
        else:
            cursor.execute("SELECT * FROM episodes WHERE show_id = ? ORDER BY season ASC, episode_num ASC", (show_id,))
        return [dict(r) for r in cursor.fetchall()]

def get_episode_by_idec(idec: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM episodes WHERE idec = ?", (idec,))
        row = cursor.fetchone()
        return dict(row) if row else None

def list_genres() -> List[str]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT genre FROM shows WHERE genre IS NOT NULL AND genre != '' ORDER BY genre ASC")
        raw_genres = [r["genre"] for r in cursor.fetchall()]
        genres_set = set()
        for rg in raw_genres:
            for part in rg.split(","):
                p = part.strip()
                if p:
                    genres_set.add(p)
        return sorted(list(genres_set))

# --- Správa stahování ---

def create_download_task(task_id: str, idec: str, title: str) -> Dict[str, Any]:
    with get_db() as conn:
        cursor = conn.cursor()
        now = int(time.time())
        cursor.execute("""
        INSERT INTO downloads (id, idec, title, status, progress, created_at, updated_at)
        VALUES (?, ?, ?, 'pending', 0.0, ?, ?)
        """, (task_id, idec, title, now, now))
        return {
            "id": task_id, "idec": idec, "title": title, "status": "pending",
            "progress": 0.0, "speed": "", "eta": "", "filepath": "", "filesize": 0, "error_message": "",
            "created_at": now, "updated_at": now
        }

def get_download_task(task_id: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM downloads WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def list_download_tasks() -> List[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM downloads ORDER BY created_at DESC")
        return [dict(r) for r in cursor.fetchall()]

def update_download_task(task_id: str, **kwargs) -> bool:
    with get_db() as conn:
        cursor = conn.cursor()
        kwargs["updated_at"] = int(time.time())
        fields = [f"{k} = ?" for k in kwargs.keys()]
        params = list(kwargs.values())
        params.append(task_id)
        cursor.execute(f"UPDATE downloads SET {', '.join(fields)} WHERE id = ?", params)
        return cursor.rowcount > 0

def delete_download_task(task_id: str) -> bool:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM downloads WHERE id = ?", (task_id,))
        return cursor.rowcount > 0
