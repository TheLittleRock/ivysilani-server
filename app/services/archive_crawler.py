import asyncio
import logging
import json
from typing import List, Dict, Any, Optional
import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.services.ct_service import ct_service
from app.db import crud

logger = logging.getLogger("archive_crawler")

# 14 hlavních kategorií iVysílání
IVYSILANI_CATEGORIES = [
    ("3976-serialy", "Seriály"),
    ("3947-filmy", "Filmy"),
    ("4003-dokumenty", "Dokumenty"),
    ("4029-kultura", "Kultura"),
    ("4068-zabava", "Zábava"),
    ("4079-historie", "Historie"),
    ("4118-pro-deti", "Pro děti"),
    ("4124-zpravodajstvi", "Zpravodajství"),
    ("4106-priroda", "Příroda"),
    ("4093-spolecnost", "Společnost"),
    ("4055-rady-a-recepty", "Rady a recepty"),
    ("4142-sport", "Sport"),
    ("4191-spiritualita", "Spiritualita"),
    ("4732-archiv", "Archiv"),
]

class ArchiveCrawler:
    def __init__(self):
        self._is_running = False
        self.stats = {
            "is_crawling": False,
            "indexed_shows": 0,
            "current_category": "",
            "last_error": None
        }

    async def index_show(self, slug_or_url: str) -> bool:
        """Stáhne podrobná metadata pořadu a uloží ho včetně všech epizod do SQLite databáze."""
        try:
            show_data = await ct_service.scrape_show_metadata(slug_or_url)
            if not show_data:
                return False

            show_id = show_data["id"]
            crud.upsert_show(
                show_id=show_id,
                title=show_data["title"],
                slug=show_data["slug"],
                description=show_data["description"],
                image_url=show_data["image_url"],
                poster_url=show_data.get("poster_url", ""),
                backdrop_url=show_data.get("backdrop_url", ""),
                logo_url=show_data.get("logo_url", ""),
                genre=show_data["genre"],
                year=show_data["year"],
                show_type=show_data.get("show_type", "series"),
                is_playable=show_data.get("is_playable", True),
                total_episodes=len(show_data.get("episodes", []))
            )

            for ep in show_data.get("episodes", []):
                ep_id = f"{show_id}_{ep['idec']}"
                crud.upsert_episode(
                    ep_id=ep_id,
                    show_id=show_id,
                    idec=str(ep["idec"]),
                    title=ep["title"],
                    description=ep.get("description", show_data["description"]),
                    image_url=ep.get("image_url", show_data["image_url"]),
                    duration=ep.get("duration", 0),
                    season=ep.get("season", 1),
                    episode_num=ep.get("episode_num", 1),
                    is_playable=ep.get("is_playable", True),
                    is_drm=ep.get("is_drm", False)
                )

            logger.info(f"Pořad úspěšně doindexován: {show_data['title']} ({len(show_data.get('episodes', []))} epizod)")
            return True
        except Exception as e:
            logger.error(f"Chyba při indexaci pořadu {slug_or_url}: {e}")
            return False
        except Exception as e:
            logger.error(f"Chyba při indexaci pořadu {slug_or_url}: {e}")
            return False

    async def crawl_category(self, cat_slug: str, cat_name: str, max_pages: int = 5) -> int:
        """Projde katalog dané kategorie přes SSR Next.js data a uloží nalezené pořady."""
        headers = {
            "User-Agent": settings.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://www.ceskatelevize.cz/"
        }
        shows_added = 0
        async with httpx.AsyncClient(headers=headers, timeout=15.0, follow_redirects=True) as client:
            for page in range(1, max_pages + 1):
                url = f"https://www.ceskatelevize.cz/ivysilani/kategorie/{cat_slug}/katalog/"
                if page > 1:
                    url += f"?page={page}"

                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        break

                    soup = BeautifulSoup(resp.text, "html.parser")
                    tag = soup.find("script", id="__NEXT_DATA__")
                    if not tag or not tag.string:
                        break

                    data = json.loads(tag.string)
                    cat_data = data.get("props", {}).get("pageProps", {}).get("data", {}).get("category", {})
                    pf = cat_data.get("programmeFind", {})
                    items = pf.get("items", [])
                    if not items:
                        break

                    for item in items:
                        show_id = str(item.get("id"))
                        title = item.get("title")
                        slug = item.get("slug") or show_id
                        desc = item.get("shortDescription") or ""
                        images = item.get("images") or {}
                        img_url = images.get("i480") or images.get("i300") or images.get("i220") or ""
                        poster_url = images.get("poster") or images.get("poster2x") or img_url
                        backdrop_url = images.get("desktop") or images.get("hero") or img_url
                        logo_url = images.get("logo") or ""

                        # Žánry
                        card_genres = item.get("genresForCard", [])
                        genre_names = [g.get("title") for g in card_genres if g.get("title")]
                        genre = ", ".join(genre_names) if genre_names else cat_name

                        raw_show_type = (item.get("showType") or "").lower()
                        show_type = "movie" if ("film" in raw_show_type or "film" in cat_slug) else "series"
                        is_playable = bool(item.get("playable", True))

                        crud.upsert_show(
                            show_id=show_id,
                            title=title,
                            slug=slug,
                            description=desc,
                            image_url=img_url,
                            poster_url=poster_url,
                            backdrop_url=backdrop_url,
                            logo_url=logo_url,
                            genre=genre,
                            year=str(item.get("year") or ""),
                            show_type=show_type,
                            is_playable=is_playable,
                            total_episodes=1
                        )

                        # Pokud má pořad výchozí epizodu (IDEC)
                        btn = item.get("actionButton") or {}
                        default_idec = btn.get("idec")
                        if default_idec:
                            crud.upsert_episode(
                                ep_id=f"{show_id}_{default_idec}",
                                show_id=show_id,
                                idec=str(default_idec),
                                title=title,
                                description=desc,
                                image_url=img_url,
                                duration=0,
                                season=1,
                                episode_num=1,
                                is_playable=is_playable,
                                is_drm=False
                            )

                        shows_added += 1

                    # Pokud jsme dosáhli konce
                    total_count = pf.get("totalCount", 0)
                    if page * len(items) >= total_count:
                        break

                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.warning(f"Chyba při crawlování {cat_slug} str. {page}: {e}")
                    break

        return shows_added

    async def crawl_entire_catalog(self, max_pages_per_category: int = 5) -> int:
        """Spustí plné projití všech kategorií na iVysílání."""
        if self.stats["is_crawling"]:
            logger.info("Crawler již běží.")
            return 0

        self.stats["is_crawling"] = True
        self.stats["indexed_shows"] = 0
        total_indexed = 0

        logger.info("Zahajuji hloubkovou indexaci celého katalogu iVysílání...")
        try:
            for cat_slug, cat_name in IVYSILANI_CATEGORIES:
                self.stats["current_category"] = cat_name
                logger.info(f"Indexuji kategorii: {cat_name} ({cat_slug})...")
                count = await self.crawl_category(cat_slug, cat_name, max_pages=max_pages_per_category)
                total_indexed += count
                self.stats["indexed_shows"] = total_indexed
                logger.info(f"Kategorie {cat_name} dokončena: +{count} pořadů.")

            logger.info(f"Celá indexace iVysílání dokončena! Celkem nalezeno {total_indexed} záznamů.")
        except Exception as e:
            logger.error(f"Kritická chyba při indexaci: {e}")
            self.stats["last_error"] = str(e)
        finally:
            self.stats["is_crawling"] = False
            self.stats["current_category"] = ""

        return total_indexed

    def start_background_crawl(self, max_pages_per_category: int = 5) -> bool:
        """Spustí indexaci na pozadí jako asynchronní úlohu."""
        if self.stats["is_crawling"]:
            return False
        asyncio.create_task(self.crawl_entire_catalog(max_pages_per_category=max_pages_per_category))
        return True

    async def run_periodic_crawler(self):
        """Spouští se při startu a poté v pravidelných intervalech (např. 24h)."""
        logger.info("Spouštím počáteční crawler katalogu iVysílání...")
        await self.crawl_entire_catalog(max_pages_per_category=4)

        while True:
            try:
                await asyncio.sleep(settings.CRAWL_INTERVAL_HOURS * 3600)
                logger.info("Pravidelná aktualizace katalogu iVysílání...")
                await self.crawl_entire_catalog(max_pages_per_category=3)
            except asyncio.CancelledError:
                logger.info("Pravidelný crawler byl zastaven.")
                break
            except Exception as e:
                logger.error(f"Chyba v periodickém crawleru: {e}")

archive_crawler = ArchiveCrawler()
