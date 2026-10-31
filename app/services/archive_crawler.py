import asyncio
import logging
import json
import time
from typing import List, Dict, Any, Optional, Tuple
import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.services.ct_service import ct_service
from app.db import crud

logger = logging.getLogger("archive_crawler")

# Všechny podkategorie Seriálů podle webu iVysílání
SERIES_SUBCATEGORIES: List[Tuple[str, str, str]] = [
    ("4785-ceske", "České", "3976-serialy"),
    ("3983-krimi", "Krimi", "3976-serialy"),
    ("3985-komedie", "Komedie", "3976-serialy"),
    ("4002-zahranicni", "Zahraniční", "3976-serialy"),
    ("3990-rodinne", "Rodinné", "3976-serialy"),
    ("3992-psychologicke", "Psychologické", "3976-serialy"),
    ("3979-historicke", "Historické", "3976-serialy"),
    ("3999-klasicke", "Klasika", "3976-serialy"),
    ("3993-thrillery", "Thrillery", "3976-serialy"),
    ("4337-literarni-adaptace", "Literární adaptace", "3976-serialy"),
    ("4928-studentske", "Studentské", "3976-serialy"),
]

# Všechny podkategorie Filmů podle webu iVysílání
MOVIE_SUBCATEGORIES: List[Tuple[str, str, str]] = [
    ("4720-ceske", "České", "3947-filmy"),
    ("3958-krimi", "Krimi", "3947-filmy"),
    ("3957-komedie", "Komedie", "3947-filmy"),
    ("3969-zahranicni", "Zahraniční", "3947-filmy"),
    ("3961-pohadky", "Pohádky", "3947-filmy"),
    ("3962-psychologicke", "Psychologické", "3947-filmy"),
    ("3954-historicke", "Historické", "3947-filmy"),
    ("3963-rodinne", "Rodinné", "3947-filmy"),
    ("3971-klasicke", "Klasika", "3947-filmy"),
    ("3951-dramata", "Drama", "3947-filmy"),
    ("3960-romanticke", "Romantické", "3947-filmy"),
    ("3949-zivotopisne", "Životopisné", "3947-filmy"),
    ("3967-thrillery", "Thriller", "3947-filmy"),
    ("3948-animovane", "Animované", "3947-filmy"),
    ("4336-literarni-adaptace", "Literární adaptace", "3947-filmy"),
    ("3973-valecne", "Válečné", "3947-filmy"),
    ("4802-studentske", "Studentské", "3947-filmy"),
]

# Další hlavní kategorie
OTHER_CATEGORIES: List[Tuple[str, str, Optional[str]]] = [
    ("4003-dokumenty", "Dokumenty", None),
    ("4124-zpravodajstvi", "Zpravodajství", None),
    ("4068-zabava", "Zábava", None),
    ("4118-pro-deti", "Pro děti", None),
    ("4079-historie", "Historie", None),
    ("4029-kultura", "Kultura", None),
]

# Zvlášť vyžádané stěžejní pořady
SPECIAL_SHOWS: List[str] = [
    "1097181328-udalosti",
    "10393496397-udalosti-za-okamzik-a-pocasi",
    "12701251153-stardance",
    "13478071605-oktopus",
    "10195164142-vypravej",
]

class ArchiveCrawler:
    def __init__(self):
        self._is_running = False
        self.stats = {
            "is_crawling": False,
            "indexed_shows": 0,
            "current_category": "",
            "start_time": 0,
            "last_error": None
        }

    async def index_show(self, slug_or_url: str) -> bool:
        """Stáhne podrobná metadata pořadu a uloží ho včetně všech epizod do SQLite databáze.
        Pokud pořad již není na iVysílání přehratelný (expirovaná práva), vymaže ho z databáze.
        """
        try:
            show_data = await ct_service.scrape_show_metadata(slug_or_url)
            if not show_data:
                return False

            show_id = show_data["id"]
            is_playable = show_data.get("is_playable", True)

            # Pokud již pořad není přehratelný, smažeme ho z databáze
            if not is_playable:
                crud.delete_show(show_id)
                logger.info(f"Pořad {show_data['title']} již není přehratelný na iVysílání - odstraněn z DB.")
                return False

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
                is_playable=True,
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

            logger.info(f"Pořad doindexován: {show_data['title']} ({len(show_data.get('episodes', []))} epizod)")
            return True
        except Exception as e:
            logger.error(f"Chyba při indexaci pořadu {slug_or_url}: {e}")
            return False

    async def crawl_category(
        self,
        subcat_slug: str,
        cat_name: str,
        parent_slug: Optional[str] = None,
        max_pages: int = 5,
        seen_shows: Optional[set] = None
    ) -> int:
        """Projde katalog dané (pod)kategorie přes SSR Next.js data a uloží nalezené pořady."""
        if seen_shows is None:
            seen_shows = set()

        headers = {
            "User-Agent": settings.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://www.ceskatelevize.cz/"
        }
        shows_added = 0
        series_to_index = []

        async with httpx.AsyncClient(headers=headers, timeout=15.0, follow_redirects=True) as client:
            for page in range(1, max_pages + 1):
                # Podkategorie nemají v URL /katalog/, hlavní kategorie ano
                if parent_slug:
                    url = f"https://www.ceskatelevize.cz/ivysilani/kategorie/{parent_slug}/{subcat_slug}/?page={page}"
                else:
                    url = f"https://www.ceskatelevize.cz/ivysilani/kategorie/{subcat_slug}/katalog/"
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
                        if show_id in seen_shows:
                            continue
                        seen_shows.add(show_id)

                        title = item.get("title")
                        slug = item.get("slug") or show_id
                        desc = item.get("shortDescription") or ""
                        images = item.get("images") or {}
                        img_url = images.get("i480") or images.get("i300") or images.get("i220") or ""
                        poster_url = images.get("poster") or images.get("poster2x") or img_url
                        backdrop_url = images.get("desktop") or images.get("hero") or img_url
                        logo_url = images.get("logo") or ""

                        card_genres = item.get("genresForCard", [])
                        genre_names = [g.get("title") for g in card_genres if g.get("title")]
                        genre = ", ".join(genre_names) if genre_names else cat_name

                        raw_show_type = (item.get("showType") or "").lower()
                        if parent_slug == "3976-serialy":
                            show_type = "series"
                        elif parent_slug == "3947-filmy":
                            show_type = "movie"
                        else:
                            show_type = "movie" if ("film" in raw_show_type or "film" in subcat_slug) else "series"

                        is_playable = bool(item.get("playable", True))
                        if not is_playable:
                            crud.delete_show(show_id)
                            continue

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
                            is_playable=True,
                            total_episodes=1
                        )

                        btn = item.get("actionButton") or {}
                        default_idec = btn.get("idec")

                        if show_type == "movie":
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
                                    is_playable=True,
                                    is_drm=False
                                )
                        else:
                            # Seriál zařadíme do fronty pro plné doindexování všech sérií a dílů
                            series_to_index.append(slug or show_id)

                        shows_added += 1

                    total_count = pf.get("totalCount", 0)
                    if page * len(items) >= total_count:
                        break

                    await asyncio.sleep(0.3)
                except Exception as e:
                    logger.warning(f"Chyba při crawlování {subcat_slug} str. {page}: {e}")
                    break

        # Asynchronně doindexujeme seriály přes GraphQL s omezovačem souběžnosti
        if series_to_index:
            sem = asyncio.Semaphore(4)
            async def index_worker(s_slug):
                async with sem:
                    try:
                        await self.index_show(s_slug)
                    except Exception as err:
                        logger.warning(f"Chyba při hloubkové indexaci seriálu {s_slug}: {err}")
                    await asyncio.sleep(0.1)

            await asyncio.gather(*(index_worker(s) for s in series_to_index))

        return shows_added

    async def crawl_entire_catalog(self, max_pages_per_category: int = 5) -> int:
        """Spustí plné projití všech kategorií a podkategorií na iVysílání."""
        if self.stats["is_crawling"]:
            logger.info("Crawler již běží.")
            return 0

        self.stats["is_crawling"] = True
        self.stats["indexed_shows"] = 0
        self.stats["start_time"] = int(time.time())
        total_indexed = 0
        seen_shows = set()

        logger.info("Zahajuji hloubkovou indexaci celého katalogu iVysílání (všechny kategorie i podkategorie)...")
        try:
            # 1. Seriály (11 podkategorií)
            for sub_slug, sub_name, parent in SERIES_SUBCATEGORIES:
                self.stats["current_category"] = f"Seriály: {sub_name}"
                logger.info(f"Indexuji podkategorii seriálů: {sub_name} ({sub_slug})...")
                count = await self.crawl_category(sub_slug, sub_name, parent_slug=parent, max_pages=max_pages_per_category, seen_shows=seen_shows)
                total_indexed += count
                self.stats["indexed_shows"] = total_indexed

            # 2. Filmy (17 podkategorií)
            for sub_slug, sub_name, parent in MOVIE_SUBCATEGORIES:
                self.stats["current_category"] = f"Filmy: {sub_name}"
                logger.info(f"Indexuji podkategorii filmů: {sub_name} ({sub_slug})...")
                count = await self.crawl_category(sub_slug, sub_name, parent_slug=parent, max_pages=max_pages_per_category, seen_shows=seen_shows)
                total_indexed += count
                self.stats["indexed_shows"] = total_indexed

            # 3. Ostatní kategorie
            for cat_slug, cat_name, parent in OTHER_CATEGORIES:
                self.stats["current_category"] = cat_name
                logger.info(f"Indexuji kategorii: {cat_name} ({cat_slug})...")
                count = await self.crawl_category(cat_slug, cat_name, parent_slug=parent, max_pages=max_pages_per_category, seen_shows=seen_shows)
                total_indexed += count
                self.stats["indexed_shows"] = total_indexed

            # 4. Speciální stěžejní pořady (Události, StarDance, OKTOPUS, Vyprávěj)
            self.stats["current_category"] = "Speciální pořady"
            for spec_slug in SPECIAL_SHOWS:
                logger.info(f"Garantovaná indexace stěžejního pořadu: {spec_slug}...")
                await self.index_show(spec_slug)

            logger.info(f"Kompletní indexace iVysílání dokončena! Celkem v katalogu: {total_indexed} pořadů.")
            crud.set_setting("last_crawl_info", json.dumps({
                "timestamp": int(time.time()),
                "duration_seconds": int(time.time()) - self.stats["start_time"],
                "total_indexed": total_indexed,
                "status": "success"
            }))
        except Exception as e:
            logger.error(f"Kritická chyba při indexaci: {e}")
            self.stats["last_error"] = str(e)
            crud.set_setting("last_crawl_info", json.dumps({
                "timestamp": int(time.time()),
                "error": str(e),
                "status": "error"
            }))
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

    def start_background_tmdb_enrichment(self) -> bool:
        """Spustí TMDB obohacení katalogu na pozadí."""
        asyncio.create_task(self.enrich_all_shows_tmdb())
        return True

    async def enrich_all_shows_tmdb(self):
        """Obohatí všechny pořady v databázi o TMDB metadata na pozadí."""
        from app.services.tmdb_service import tmdb_service
        shows = crud.list_shows(limit=5000)
        enriched_count = 0
        for s in shows:
            if not s.get("tmdb_id"):
                try:
                    res = await tmdb_service.enrich_show_metadata(s)
                    if res:
                        enriched_count += 1
                    await asyncio.sleep(0.15)
                except Exception:
                    pass
        logger.info(f"TMDB enrichment dokončeno: obohaceno {enriched_count} pořadů.")
        return enriched_count

    async def run_periodic_crawler(self):
        """Spouští se při startu a poté v pravidelných intervalech (např. 24h)."""
        logger.info("Spouštím počáteční crawler katalogu iVysílání...")
        await self.crawl_entire_catalog(max_pages_per_category=3)

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
