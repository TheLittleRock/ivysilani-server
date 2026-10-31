import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="allow")

    HOST: str = "0.0.0.0"
    PORT: int = 5002
    DEBUG: bool = False
    
    # Paths
    DATA_DIR: Path = Path("./data")
    DOWNLOAD_DIR: Path = Path("./downloads")
    
    # Streaming: "redirect" (HTTP 302 na ČT CDN) nebo "proxy" (server sám stahuje a posílá)
    STREAM_MODE: str = "redirect"
    
    # Veřejná URL (např. https://tv.mojedomena.cz) pro generování playlistů za reverse proxy
    # Pokud není zadána, detekuje se dynamicky z hlaviček X-Forwarded-Host / Host
    BASE_URL: Optional[str] = None
    
    # Výchozí administrátor
    DEFAULT_ADMIN_USER: str = "admin"
    DEFAULT_ADMIN_PASSWORD: str = "admin"
    DEFAULT_ADMIN_PASS: str = "admin"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "ivysilani-secret-key-change-in-production-123456")
    
    # Interval indexace katalogu archivu v hodinách
    CRAWL_INTERVAL_HOURS: int = 24
    
    # User Agent pro ČT API
    USER_AGENT: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/112.0"

settings = Settings()

# Ujistit se, že adresáře existují
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
