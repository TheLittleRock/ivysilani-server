import hashlib
import logging
from pathlib import Path
from typing import Optional, Tuple
import urllib.parse
import httpx

from app.core.config import settings

logger = logging.getLogger("image_proxy")
IMAGE_CACHE_DIR = settings.DATA_DIR / "cache" / "images"
IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

class ImageProxyService:
    def __init__(self):
        self.headers = {
            "User-Agent": settings.USER_AGENT,
            "Referer": "https://www.ceskatelevize.cz/",
            "Origin": "https://www.ceskatelevize.cz",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
        }

    def get_cache_path(self, url: str) -> Path:
        url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
        parsed = urllib.parse.urlparse(url)
        suffix = Path(parsed.path).suffix.lower()
        if suffix not in [".jpg", ".jpeg", ".png", ".webp", ".svg"]:
            suffix = ".jpg"
        return IMAGE_CACHE_DIR / f"{url_hash}{suffix}"

    async def fetch_image(self, url: str) -> Tuple[Optional[bytes], str]:
        """Stáhne obrázek z ČT CDN s patřičnými Referer hlavičkami a uloží do diskové cache."""
        if not url:
            return None, "image/jpeg"

        cache_path = self.get_cache_path(url)
        if cache_path.exists() and cache_path.stat().st_size > 0:
            try:
                content = cache_path.read_bytes()
                media_type = self._get_media_type(cache_path.suffix)
                return content, media_type
            except Exception as e:
                logger.warning(f"Error reading cached image {cache_path}: {e}")

        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    content = resp.content
                    media_type = resp.headers.get("content-type", self._get_media_type(cache_path.suffix))
                    # Uložit do cache
                    try:
                        cache_path.write_bytes(content)
                    except Exception as e:
                        logger.warning(f"Error writing image cache: {e}")
                    return content, media_type
                else:
                    logger.warning(f"Failed to fetch image {url}: status {resp.status_code}")
        except Exception as e:
            logger.error(f"Error fetching image {url}: {e}")

        return None, "image/jpeg"

    def _get_media_type(self, suffix: str) -> str:
        s = suffix.lower()
        if s in [".jpg", ".jpeg"]:
            return "image/jpeg"
        if s == ".png":
            return "image/png"
        if s == ".webp":
            return "image/webp"
        if s == ".svg":
            return "image/svg+xml"
        return "image/jpeg"

    def build_proxy_url(self, base_url: str, raw_url: Optional[str]) -> str:
        """Převede externí URL z ČT CDN na URL lokálního Image Proxy endpointu."""
        if not raw_url:
            return f"{base_url}/static/logos/ct1.png"
        if raw_url.startswith("/static/"):
            return f"{base_url}{raw_url}"
        if not raw_url.startswith("http"):
            return f"{base_url}/static/logos/ct1.png"
        
        encoded = urllib.parse.quote(raw_url, safe="")
        return f"{base_url}/api/image-proxy?url={encoded}"

image_proxy = ImageProxyService()
