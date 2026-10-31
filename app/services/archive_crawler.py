import asyncio
import logging
from typing import List
from app.services.ct_service import ct_service
from app.db import crud

logger = logging.getLogger("archive_crawler")

# Základní výběr populárních a nejžádanějších pořadů České televize pro okamžité naplnění VOD
POPULAR_SEED_SHOWS = [
    # Zpravodajství a publicistika
    "1097181328-udalosti",
    "1096898228-udalosti-komentare",
    "1126672097-otazky-vaclava-moravce",
    "10119615714-reporteri-ct",
    "1097429889-cerne-ovce",
    "1148499747-sama-doma",
    # Seriály a drama
    "10123499335-vypravej",
    "1034828308-cetnicke-humoresky",
    "10660602073-pripady-1-oddeleni",
    "13146196620-devadesatky",
    "1039525917-most",
    "12051301269-kukacky",
    "1084288000-zdivocela-zeme",
    "12630713725-docent",
    "13753232813-oktopus",
    "14332219483-smysl-pro-tumor",
    # Pohádky a pro děti
    "13901424013-krakonosovo-tajemstvi",
    "898578-krkonosska-pohadka",
    "1008489727-vecernicek",
    "1095970759-kouzelna-skolka",
    "872584-mach-a-sebestova",
    "871576-bob-a-bobek-kralici-z-klobouku",
    # Dokumenty a magazíny
    "1126949941-toulava-kamera",
    "1185936825-na-ceste",
    "10518832906-zazraky-prirody",
    "1008789767-kluci-v-akci",
    "1015050226-kocka-neni-pes",
    "1015050067-pes-neni-kocka",
    # Zábava
    "1009099593-vsechnoparty",
    "13304561085-pece-cela-zene"
]

class ArchiveCrawler:
    def __init__(self):
        self._is_running = False

    async def index_show(self, slug_or_url: str) -> bool:
        """Stáhne metadata pořadu a uloží ho do lokální SQLite databáze."""
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
                genre=show_data["genre"],
                year=show_data["year"],
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
                    episode_num=ep.get("episode_num", 1)
                )

            logger.info(f"Successfully indexed show: {show_data['title']} ({len(show_data.get('episodes', []))} episodes)")
            return True
        except Exception as e:
            logger.error(f"Error indexing show {slug_or_url}: {e}")
            return False

    async def seed_initial_catalog(self):
        """Při prvním spuštění načte základní balíček oblíbených pořadů."""
        current_count = crud.count_shows()
        if current_count > 10:
            logger.info(f"Catalog already has {current_count} shows. Skipping seed.")
            return

        logger.info("Starting initial seed of popular ČT shows into catalog...")
        for slug in POPULAR_SEED_SHOWS:
            await self.index_show(slug)
            await asyncio.sleep(0.5)  # Šetrné k ČT serverům
        logger.info("Initial catalog seed finished.")

    async def run_periodic_crawler(self):
        """Běží na pozadí a udržuje katalog aktualizovaný."""
        if self._is_running:
            return
        self._is_running = True
        try:
            # 1. Spustit initial seed
            await self.seed_initial_catalog()

            # 2. Pravidelná smyčka
            while self._is_running:
                await asyncio.sleep(3600 * 24)  # 24 hodin
                logger.info("Running periodic catalog update...")
                shows = crud.list_shows(limit=50)
                for s in shows:
                    if s.get("slug"):
                        await self.index_show(s["slug"])
                        await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            logger.info("Periodic crawler cancelled.")
        except Exception as e:
            logger.error(f"Periodic crawler error: {e}")
        finally:
            self._is_running = False

archive_crawler = ArchiveCrawler()
