import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.database import init_db
from app.services.downloader import download_manager
from app.services.archive_crawler import archive_crawler
from app.api.web import router as web_router
from app.api.xtream import router as xtream_router
from app.api.stream import router as stream_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ivysilani")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Inicializace databáze...")
    init_db()
    
    logger.info("Spouštění správce stahování...")
    await download_manager.start()
    
    logger.info("Spouštění indexeru archivu na pozadí...")
    crawler_task = asyncio.create_task(archive_crawler.run_periodic_crawler())
    
    yield
    
    logger.info("Ukončování služeb...")
    crawler_task.cancel()
    await download_manager.stop()

app = FastAPI(
    title="iVysílání Server",
    description="Moderní webová aplikace a Xtream Codes IPTV / VOD server pro Českou televizi a iVysílání",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware pro klientské přehrávače a widgety
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Statické soubory
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Registrace routerů
app.include_router(stream_router)
app.include_router(xtream_router)
app.include_router(web_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=False)
