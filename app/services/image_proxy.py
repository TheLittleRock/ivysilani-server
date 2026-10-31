import hashlib
import io
import logging
from pathlib import Path
from typing import Optional, Tuple
import urllib.parse
import httpx
from PIL import Image

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

    def get_cache_path(self, url: str, pad: Optional[str] = None) -> Path:
        cache_key = f"{url}_pad_{pad}" if pad else url
        url_hash = hashlib.md5(cache_key.encode("utf-8")).hexdigest()
        if pad:
            return IMAGE_CACHE_DIR / f"{url_hash}.jpg"
        parsed = urllib.parse.urlparse(url)
        suffix = Path(parsed.path).suffix.lower()
        if suffix not in [".jpg", ".jpeg", ".png", ".webp", ".svg"]:
            suffix = ".jpg"
        return IMAGE_CACHE_DIR / f"{url_hash}{suffix}"

    async def fetch_image(self, url: str, pad: Optional[str] = None) -> Tuple[Optional[bytes], str]:
        """Stáhne obrázek z ČT CDN s patřičnými Referer hlavičkami a uloží do diskové cache.
        Pokud je zadán pad='2x3', obrázek vycentruje a doplní letterbox do poměru 2:3 bez ořezu.
        """
        if not url:
            return None, "image/jpeg"

        cache_path = self.get_cache_path(url, pad=pad)
        if cache_path.exists() and cache_path.stat().st_size > 0:
            try:
                content = cache_path.read_bytes()
                media_type = self._get_media_type(cache_path.suffix)
                return content, media_type
            except Exception as e:
                logger.warning(f"Error reading cached image {cache_path}: {e}")

        # Pokud chceme padding 2:3, nejprve získáme surový originál (bez paddingu)
        if pad == "2x3":
            raw_content, _ = await self.fetch_image(url, pad=None)
            if not raw_content:
                return None, "image/jpeg"

            try:
                with Image.open(io.BytesIO(raw_content)) as img:
                    img = img.convert("RGB")
                    orig_w, orig_h = img.size
                    target_w, target_h = 600, 900
                    scale = min(target_w / orig_w, target_h / orig_h)
                    new_w = max(1, int(orig_w * scale))
                    new_h = max(1, int(orig_h * scale))
                    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

                    # Vzorkování barvy pozadí z okrajů originálního obrázku
                    edge_pixels = []
                    step_x = max(1, orig_w // 50)
                    step_y = max(1, orig_h // 50)
                    for x in range(0, orig_w, step_x):
                        edge_pixels.append(img.getpixel((x, 0)))
                        edge_pixels.append(img.getpixel((x, orig_h - 1)))
                    for y in range(0, orig_h, step_y):
                        edge_pixels.append(img.getpixel((0, y)))
                        edge_pixels.append(img.getpixel((orig_w - 1, y)))

                    if edge_pixels:
                        avg_r = int(sum(p[0] for p in edge_pixels) / len(edge_pixels))
                        avg_g = int(sum(p[1] for p in edge_pixels) / len(edge_pixels))
                        avg_b = int(sum(p[2] for p in edge_pixels) / len(edge_pixels))
                        # Mírné ztmavení pro přirozený kontrast s plakátem
                        bg_color = (max(0, int(avg_r * 0.85)), max(0, int(avg_g * 0.85)), max(0, int(avg_b * 0.85)))
                    else:
                        bg_color = (15, 23, 42)

                    canvas = Image.new("RGB", (target_w, target_h), color=bg_color)
                    paste_x = (target_w - new_w) // 2
                    paste_y = (target_h - new_h) // 2
                    canvas.paste(resized, (paste_x, paste_y))

                    buf = io.BytesIO()
                    canvas.save(buf, format="JPEG", quality=90, optimize=True)
                    padded_bytes = buf.getvalue()
                    try:
                        cache_path.write_bytes(padded_bytes)
                    except Exception as e:
                        logger.warning(f"Error writing padded image cache: {e}")
                    return padded_bytes, "image/jpeg"
            except Exception as e:
                logger.error(f"Error applying 2:3 padding to image {url}: {e}")
                return raw_content, "image/jpeg"

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

    def build_proxy_url(self, base_url: str, raw_url: Optional[str], pad: Optional[str] = None) -> str:
        """Převede externí URL z ČT CDN na URL lokálního Image Proxy endpointu."""
        if not raw_url:
            return f"{base_url}/static/logos/ct1.png"
        if raw_url.startswith("/static/"):
            return f"{base_url}{raw_url}"
        if not raw_url.startswith("http"):
            return f"{base_url}/static/logos/ct1.png"
        
        encoded = urllib.parse.quote(raw_url, safe="")
        proxy_url = f"{base_url}/api/image-proxy?url={encoded}"
        if pad:
            proxy_url += f"&pad={pad}"
        return proxy_url

image_proxy = ImageProxyService()
