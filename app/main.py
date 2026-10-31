import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging_config import setup_logging
from app.db.database import init_db
from app.services.downloader import download_manager
from app.services.archive_crawler import archive_crawler
from app.services.epg_service import run_periodic_epg
from app.api.web import router as web_router
from app.api.xtream import router as xtream_router
from app.api.stream import router as stream_router
from app.api.stremio import router as stremio_router

setup_logging()
logger = logging.getLogger("ivysilani")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Inicializace databáze...")
    init_db()
    
    logger.info("Spouštění správce stahování...")
    await download_manager.start()
    
    logger.info("Spouštění indexeru archivu na pozadí...")
    crawler_task = asyncio.create_task(archive_crawler.run_periodic_crawler())
    
    logger.info("Spouštění stahování EPG dat na pozadí...")
    epg_task = asyncio.create_task(run_periodic_epg())
    
    yield
    
    logger.info("Ukončování služeb...")
    crawler_task.cancel()
    epg_task.cancel()
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

@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico():
    fav = STATIC_DIR / "favicon.ico"
    if fav.exists():
        return FileResponse(str(fav), media_type="image/x-icon")
    return Response(status_code=404)

# Registrace routerů
app.include_router(stream_router)
app.include_router(xtream_router)
app.include_router(stremio_router)
app.include_router(web_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=False)
