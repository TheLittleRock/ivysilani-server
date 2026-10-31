import sqlite3
import time
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

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        
        # 1. Tabulka uživatelů
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            exp_date INTEGER,
            max_connections INTEGER DEFAULT 2,
            created_at INTEGER,
            last_active INTEGER
        );
        """)
        
        # 2. Tabulka pořadů (katalog VOD)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS shows (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            slug TEXT,
            description TEXT,
            image_url TEXT,
            genre TEXT,
            year TEXT,
            total_episodes INTEGER DEFAULT 0,
            updated_at INTEGER
        );
        """)
        
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
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_episodes_show_id ON episodes(show_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_episodes_idec ON episodes(idec);")

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
        
        # Vytvoření výchozího administrátora, pokud ještě neexistuje
        cursor.execute("SELECT id FROM users WHERE username = ?", (settings.DEFAULT_ADMIN_USER,))
        admin = cursor.fetchone()
        if not admin:
            now = int(time.time())
            pwd_hash = get_password_hash(settings.DEFAULT_ADMIN_PASS)
            cursor.execute("""
            INSERT INTO users (username, password_hash, is_admin, is_active, max_connections, created_at, last_active)
            VALUES (?, ?, 1, 1, 10, ?, ?)
            """, (settings.DEFAULT_ADMIN_USER, pwd_hash, now, now))
