import re
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.db import crud
from app.services.ct_service import ct_service, LIVE_CHANNELS

router = APIRouter(prefix="/stremio")

def get_base_url(request: Request) -> str:
    if settings.BASE_URL:
        return settings.BASE_URL.rstrip('/')
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", f"127.0.0.1:{settings.PORT}"))
    return f"{forwarded_proto}://{forwarded_host}"

def cors_response(data: dict) -> JSONResponse:
    return JSONResponse(
        content=data,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS"
        }
    )

@router.options("/{full_path:path}")
async def stremio_options(full_path: str):
    return cors_response({})

@router.get("/manifest.json")
async def stremio_manifest(request: Request):
    base_url = get_base_url(request)
    manifest = {
        "id": "cz.thelittlerock.ivysilani",
        "version": "1.1.0",
        "name": "Česká televize (iVysílání)",
        "description": "Oficiální kanály živého vysílání (ČT1, ČT2, ČT24, ČT sport...) a kompletní archiv iVysílání.",
        "logo": f"{base_url}/static/logos/ct1.svg",
        "background": f"{base_url}/static/logos/ct1.svg",
        "resources": ["catalog", "meta", "stream"],
        "types": ["tv", "series", "movie"],
        "idPrefixes": ["ct_"],
        "catalogs": [
            {
                "type": "tv",
                "id": "ct_live",
                "name": "ČT Živé vysílání"
            },
            {
                "type": "series",
                "id": "ct_series",
                "name": "iVysílání: Seriály",
                "extra": [
                    {"name": "genre", "options": ["Krimi", "Drama", "Komedie", "Historický", "Klasika"]},
                    {"name": "search"},
                    {"name": "skip"}
                ]
            },
            {
                "type": "movie",
                "id": "ct_movies",
                "name": "iVysílání: Filmy",
                "extra": [
                    {"name": "genre", "options": ["Drama", "Komedie", "Pohádka", "Historický", "Thriller"]},
                    {"name": "search"},
                    {"name": "skip"}
                ]
            },
            {
                "type": "series",
                "id": "ct_documentaries",
                "name": "iVysílání: Dokumenty",
                "extra": [
                    {"name": "search"},
                    {"name": "skip"}
                ]
            },
            {
                "type": "series",
                "id": "ct_kids",
                "name": "iVysílání: Pro děti",
                "extra": [
                    {"name": "search"},
                    {"name": "skip"}
                ]
            }
        ]
    }
    return cors_response(manifest)

# Helper to parse extra path parameters (e.g. /genre=Krimi/skip=20)
def parse_extra(extra_path: Optional[str]) -> dict:
    extra = {}
    if not extra_path:
        return extra
    parts = extra_path.split("/")
    for p in parts:
        if "=" in p:
            k, v = p.split("=", 1)
            extra[k] = v.replace(".json", "")
    return extra

@router.get("/catalog/{type}/{id}.json")
@router.get("/catalog/{type}/{id}/{extra:path}")
async def stremio_catalog(request: Request, type: str, id: str, extra: Optional[str] = None):
    base_url = get_base_url(request)
    params = parse_extra(extra)
    
    # Query parameters fallback
    genre = params.get("genre") or request.query_params.get("genre")
    search = params.get("search") or request.query_params.get("search")
    skip_str = params.get("skip") or request.query_params.get("skip", "0")
    try:
        skip = int(skip_str)
    except ValueError:
        skip = 0

    metas = []

    # 1. Živé vysílání
    if id == "ct_live":
        for s_id, ch_code in [
            (1, "CH_1"), (2, "CH_2"), (3, "CH_24"), (4, "CH_4"),
            (5, "CH_5"), (6, "CH_6"), (25, "CH_25"), (26, "CH_26"),
            (27, "CH_27"), (28, "CH_28"), (29, "CH_29"), (30, "CH_30"),
            (31, "CH_31"), (32, "CH_32")
        ]:
            ch = LIVE_CHANNELS.get(ch_code)
            if ch:
                logo_url = ch["logo"]
                if logo_url.startswith("/"):
                    logo_url = f"{base_url}{logo_url}"
                metas.append({
                    "id": f"ct_live_{ch_code}",
                    "type": "tv",
                    "name": ch["name"],
                    "poster": logo_url,
                    "background": logo_url,
                    "description": ch["description"],
                    "genres": [ch["category"]]
                })
        return cors_response({"metas": metas})

    # 2. Katalog pořadů a filmů
    genre_filter = genre
    if id == "ct_movies" and not genre_filter:
        genre_filter = "Film"
    elif id == "ct_series" and not genre_filter:
        genre_filter = "Seriál"
    elif id == "ct_documentaries":
        genre_filter = "Dokument"
    elif id == "ct_kids":
        genre_filter = "Pro děti"

    shows = crud.list_shows(genre=genre_filter, search=search, limit=60, offset=skip)
    for s in shows:
        img = s.get("image_url") or f"{base_url}/static/logos/ct1.svg"
        genres_list = [g.strip() for g in s.get("genre", "").split(",") if g.strip()]
        metas.append({
            "id": f"ct_show_{s['id']}",
            "type": type,
            "name": s["title"],
            "poster": img,
            "background": img,
            "description": s.get("description", ""),
            "releaseInfo": str(s.get("year") or ""),
            "genres": genres_list or ["iVysílání"]
        })

    return cors_response({"metas": metas})

@router.get("/meta/{type}/{id}.json")
async def stremio_meta(request: Request, type: str, id: str):
    base_url = get_base_url(request)
    id_clean = id.replace(".json", "")

    # Živý kanál
    if id_clean.startswith("ct_live_"):
        ch_code = id_clean.replace("ct_live_", "")
        ch = LIVE_CHANNELS.get(ch_code)
        if not ch:
            raise HTTPException(status_code=404, detail="Kanál nenalezen")
        logo_url = ch["logo"]
        if logo_url.startswith("/"):
            logo_url = f"{base_url}{logo_url}"
        meta = {
            "id": id_clean,
            "type": "tv",
            "name": ch["name"],
            "poster": logo_url,
            "background": logo_url,
            "description": ch["description"],
            "genres": [ch["category"]]
        }
        return cors_response({"meta": meta})

    # Pořad z iVysílání
    if id_clean.startswith("ct_show_"):
        show_id = id_clean.replace("ct_show_", "")
        show = crud.get_show_by_id(show_id)
        if not show:
            raise HTTPException(status_code=404, detail="Pořad nenalezen")

        episodes = crud.get_episodes_by_show(show_id)
        img = show.get("image_url") or f"{base_url}/static/logos/ct1.svg"
        genres_list = [g.strip() for g in show.get("genre", "").split(",") if g.strip()]

        videos = []
        for ep in episodes:
            videos.append({
                "id": f"ct_ep_{ep['idec']}",
                "title": ep.get("title") or show["title"],
                "season": ep.get("season", 1),
                "episode": ep.get("episode_num", 1),
                "overview": ep.get("description", show.get("description", "")),
                "thumbnail": ep.get("image_url") or img
            })

        meta = {
            "id": id_clean,
            "type": type,
            "name": show["title"],
            "poster": img,
            "background": img,
            "description": show.get("description", ""),
            "releaseInfo": str(show.get("year") or ""),
            "genres": genres_list or ["iVysílání"],
            "videos": videos
        }
        return cors_response({"meta": meta})

    raise HTTPException(status_code=404, detail="Položka nenalezena")

@router.get("/stream/{type}/{id}.json")
async def stremio_stream(request: Request, type: str, id: str):
    base_url = get_base_url(request)
    id_clean = id.replace(".json", "")

    # Získání uživatele pro streamovací URL (použijeme admin nebo prvního uživatele)
    user = crud.get_user_by_username("admin")
    u_name = user["username"] if user else "admin"
    # Xtream codes heslo
    u_pass = settings.DEFAULT_ADMIN_PASSWORD

    streams = []

    # 1. Živý stream
    if id_clean.startswith("ct_live_"):
        ch_code = id_clean.replace("ct_live_", "")
        # Mapování kódu na číslo streamu
        from app.api.xtream import CHANNEL_ID_TO_STREAM_ID
        s_id = CHANNEL_ID_TO_STREAM_ID.get(ch_code, 1)
        ch = LIVE_CHANNELS.get(ch_code, {})
        stream_url = f"{base_url}/live/{u_name}/{u_pass}/{s_id}.m3u8"
        streams.append({
            "name": "iVysílání Server",
            "title": f"{ch.get('name', 'ČT')} (1080p HLS)",
            "url": stream_url
        })
        return cors_response({"streams": streams})

    # 2. Epizoda pořadu podle IDEC
    if id_clean.startswith("ct_ep_"):
        idec = id_clean.replace("ct_ep_", "")
        stream_url = f"{base_url}/movie/{u_name}/{u_pass}/{idec}.m3u8"
        streams.append({
            "name": "iVysílání Server",
            "title": "ČT iVysílání (1080p HLS)",
            "url": stream_url
        })
        return cors_response({"streams": streams})

    # 3. Pořad přímo (pokud přehrávač předal id pořadu)
    if id_clean.startswith("ct_show_"):
        show_id = id_clean.replace("ct_show_", "")
        episodes = crud.get_episodes_by_show(show_id)
        if episodes:
            idec = episodes[0]["idec"]
            stream_url = f"{base_url}/movie/{u_name}/{u_pass}/{idec}.m3u8"
            streams.append({
                "name": "iVysílání Server",
                "title": f"Epizoda 1 (1080p HLS)",
                "url": stream_url
            })
            return cors_response({"streams": streams})

    return cors_response({"streams": []})
