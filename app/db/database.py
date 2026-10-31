import sqlite3
import time
import secrets
from pathlib import Path
from contextlib import contextmanager
from app.core.config import settings
from app.core.security import get_password_hash

DB_PATH = settings.DATA_DIR / "ivysilani.db"

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def _add_column_if_not_exists(cursor, table: str, column: str, col_def: str):
    cursor.execute(f"PRAGMA table_info({table});")
    cols = [row[1] for row in cursor.fetchall()]
    if column not in cols:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def};")

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()

        # 1. Tabulka uživatelů
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            user_token TEXT UNIQUE,
            is_admin INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            exp_date INTEGER,
            max_connections INTEGER DEFAULT 2,
            created_at INTEGER,
            last_active INTEGER
        );
        """)
        _add_column_if_not_exists(cursor, "users", "user_token", "TEXT")

        # 2. Tabulka pořadů (katalog VOD - filmy i seriály)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS shows (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            slug TEXT,
            description TEXT,
            image_url TEXT,
            poster_url TEXT,
            backdrop_url TEXT,
            logo_url TEXT,
            genre TEXT,
            year TEXT,
            show_type TEXT DEFAULT 'series',
            is_playable INTEGER DEFAULT 1,
            total_episodes INTEGER DEFAULT 0,
            updated_at INTEGER
        );
        """)
        _add_column_if_not_exists(cursor, "shows", "poster_url", "TEXT")
        _add_column_if_not_exists(cursor, "shows", "backdrop_url", "TEXT")
        _add_column_if_not_exists(cursor, "shows", "logo_url", "TEXT")
        _add_column_if_not_exists(cursor, "shows", "show_type", "TEXT DEFAULT 'series'")
        _add_column_if_not_exists(cursor, "shows", "is_playable", "INTEGER DEFAULT 1")
        _add_column_if_not_exists(cursor, "shows", "tmdb_id", "TEXT")
        _add_column_if_not_exists(cursor, "shows", "imdb_id", "TEXT")
        _add_column_if_not_exists(cursor, "shows", "tmdb_poster", "TEXT")
        _add_column_if_not_exists(cursor, "shows", "tmdb_backdrop", "TEXT")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_shows_genre ON shows(genre);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_shows_type ON shows(show_type);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_shows_playable ON shows(is_playable);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_shows_tmdb_id ON shows(tmdb_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_shows_imdb_id ON shows(imdb_id);")

        # 3. Tabulka epizod
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            id TEXT PRIMARY KEY,
            show_id TEXT,
            idec TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            image_url TEXT,
            duration INTEGER DEFAULT 0,
            season INTEGER DEFAULT 1,
            episode_num INTEGER DEFAULT 1,
            broadcast_date TEXT,
            is_playable INTEGER DEFAULT 1,
            is_drm INTEGER DEFAULT 0,
            FOREIGN KEY (show_id) REFERENCES shows(id) ON DELETE CASCADE
        );
        """)
        _add_column_if_not_exists(cursor, "episodes", "is_playable", "INTEGER DEFAULT 1")
        _add_column_if_not_exists(cursor, "episodes", "is_drm", "INTEGER DEFAULT 0")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_episodes_show_id ON episodes(show_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_episodes_idec ON episodes(idec);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_episodes_season ON episodes(season);")

        # 4. Tabulka úloh stahování
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS downloads (
            id TEXT PRIMARY KEY,
            idec TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            progress REAL DEFAULT 0.0,
            speed TEXT DEFAULT '',
            eta TEXT DEFAULT '',
            filepath TEXT DEFAULT '',
            filesize INTEGER DEFAULT 0,
            error_message TEXT DEFAULT '',
            created_at INTEGER,
            updated_at INTEGER
        );
        """)

        # 5. Tabulka nastavení aplikace
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """)
        cursor.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('tmdb_api_key', ?)", ("2f453df93e1dd76ca1e176029a0f9baf",))

        # Vytvoření výchozího administrátora, pokud ještě neexistuje
        cursor.execute("SELECT id, user_token FROM users WHERE username = ?", (settings.DEFAULT_ADMIN_USER,))
        admin = cursor.fetchone()
        if not admin:
            now = int(time.time())
            pwd_hash = get_password_hash(settings.DEFAULT_ADMIN_PASS)
            token = secrets.token_hex(16)
            cursor.execute("""
            INSERT INTO users (username, password_hash, user_token, is_admin, is_active, max_connections, created_at, last_active)
            VALUES (?, ?, ?, 1, 1, 10, ?, ?)
            """, (settings.DEFAULT_ADMIN_USER, pwd_hash, token, now, now))
        elif not admin["user_token"]:
            token = secrets.token_hex(16)
            cursor.execute("UPDATE users SET user_token = ? WHERE id = ?", (token, admin["id"]))

        # Zajištění tokenů pro všechny existující uživatele
        cursor.execute("SELECT id FROM users WHERE user_token IS NULL OR user_token = ''")
        for u in cursor.fetchall():
            cursor.execute("UPDATE users SET user_token = ? WHERE id = ?", (secrets.token_hex(16), u["id"]))
