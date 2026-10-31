import re
import urllib.parse
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.db import crud
from app.services.ct_service import ct_service, LIVE_CHANNELS
from app.services.image_proxy import image_proxy
from app.api.xtream import CHANNEL_STREAM_MAP, CHANNEL_ID_TO_STREAM_ID

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

def get_user_for_token(token: Optional[str]) -> dict:
    """Najde uživatele podle tokenu, jinak vrátí výchozího administrátora."""
    if token:
        user = crud.get_user_by_token(token)
        if user:
            return user
    
    admin = crud.get_user_by_username("admin")
    if admin:
        return admin
    
    users = crud.list_users()
    if users:
        return users[0]
        
    return {
        "username": "admin",
        "user_token": settings.DEFAULT_ADMIN_PASSWORD
    }

def parse_extra(extra_path: Optional[str]) -> dict:
    extra = {}
    if not extra_path:
        return extra
    parts = extra_path.split("/")
    for p in parts:
        if "=" in p:
            k, v = p.split("=", 1)
            v = v.replace(".json", "")
            extra[k] = urllib.parse.unquote(v)
    return extra

def build_manifest(base_url: str, token: Optional[str] = None) -> dict:
    token_suffix = f"/{token}" if token else ""
    return {
        "id": "cz.thelittlerock.ivysilani",
        "version": "1.2.0",
        "name": "Česká televize (iVysílání)",
        "description": "Oficiální kanály živého vysílání (ČT1, ČT2, ČT24, ČT sport...) a kompletní archiv iVysílání.",
        "logo": f"{base_url}/static/logos/ct1.png",
        "background": f"{base_url}/static/logos/ct1.png",
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
                    {
                        "name": "genre",
                        "options": [
                            "Přehled", "Krimi", "Komedie", "České", "Zahraniční", "Rodinné",
                            "Psychologické", "Historické", "Klasika", "Thrillery", "Literární adaptace", "Studentské"
                        ]
                    },
                    {"name": "search"},
                    {"name": "skip"}
                ]
            },
            {
                "type": "movie",
                "id": "ct_movies",
                "name": "iVysílání: Filmy",
                "extra": [
                    {
                        "name": "genre",
                        "options": [
                            "Přehled", "Krimi", "Komedie", "Zahraniční", "České", "Pohádky",
                            "Psychologické", "Historické", "Rodinné", "Klasika", "Drama",
                            "Romantické", "Životopisné", "Thriller", "Animované", "Literární adaptace",
                            "Válečné", "Studentské"
                        ]
                    },
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
                "id": "ct_entertainment",
                "name": "iVysílání: Zábava",
                "extra": [
                    {
                        "name": "genre",
                        "options": [
                            "Přehled", "Talk show", "Soutěže", "Hudební", "Reality show", "Klasika"
                        ]
                    },
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

@router.options("/{full_path:path}")
async def stremio_options(full_path: str):
    return cors_response({})

# --- Manifest ---
@router.get("/manifest.json")
async def stremio_manifest_default(request: Request):
    return cors_response(build_manifest(get_base_url(request), None))

@router.get("/{token}/manifest.json")
async def stremio_manifest_token(request: Request, token: str):
    return cors_response(build_manifest(get_base_url(request), token))

# --- Catalog ---
async def handle_catalog(request: Request, type: str, id: str, token: Optional[str] = None, extra: Optional[str] = None):
    base_url = get_base_url(request)
    params = parse_extra(extra)
    
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
        for s_id, ch_code in CHANNEL_STREAM_MAP.items():
            ch = LIVE_CHANNELS.get(ch_code)
            if ch:
                logo_rel = ch.get("logo_png") or ch["logo"]
                logo_url = f"{base_url}{logo_rel}"
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

    # 2. VOD Katalogy
    genre_filter = genre if (genre and genre != "Přehled") else None
    show_type = None

    if id == "ct_series":
        show_type = "series"
    elif id == "ct_movies":
        show_type = "movie"
    elif id == "ct_documentaries":
        if not genre_filter:
            genre_filter = "Dokument"
    elif id == "ct_entertainment":
        if not genre_filter:
            genre_filter = "Zábava"
    elif id == "ct_kids":
        if not genre_filter:
            genre_filter = "Děti"

    # Hledání v lokální DB (pouze hratelné položky)
    shows = crud.list_shows(
        genre=genre_filter,
        show_type=show_type,
        only_playable=True,
        search=search,
        limit=60,
        offset=skip
    )

    # Pokud uživatel vyhledává a v lokální DB není dostatek výsledků, prohledáme přímo GraphQL ČT
    if search and len(shows) < 5:
        try:
            external_results = await ct_service.search_shows_graphql(search, limit=20)
            seen_ids = {s["id"] for s in shows}
            for res in external_results:
                sidp = res.get("sidp")
                if sidp and sidp not in seen_ids:
                    # Rychle zinicializujeme metadata pořadu na pozadí
                    show_meta = await ct_service.scrape_show_metadata(sidp)
                    if show_meta and show_meta.get("is_playable", True):
                        shows.append(show_meta)
                        seen_ids.add(sidp)
        except Exception:
            pass

    for s in shows:
        poster_raw = s.get("poster_url") or s.get("image_url")
        backdrop_raw = s.get("backdrop_url") or poster_raw
        
        poster_url = image_proxy.build_proxy_url(base_url, poster_raw)
        backdrop_url = image_proxy.build_proxy_url(base_url, backdrop_raw)

        genres_list = [g.strip() for g in s.get("genre", "").split(",") if g.strip()]
        s_type = "movie" if s.get("show_type") == "movie" else "series"

        metas.append({
            "id": f"ct_show_{s['id']}",
            "type": s_type,
            "name": s["title"],
            "poster": poster_url,
            "background": backdrop_url,
            "description": s.get("description", ""),
            "releaseInfo": str(s.get("year") or ""),
            "genres": genres_list or ["iVysílání"]
        })

    return cors_response({"metas": metas})

@router.get("/catalog/{type}/{id}.json")
@router.get("/catalog/{type}/{id}/{extra:path}")
async def stremio_catalog_default(request: Request, type: str, id: str, extra: Optional[str] = None):
    return await handle_catalog(request, type, id, token=None, extra=extra)

@router.get("/{token}/catalog/{type}/{id}.json")
@router.get("/{token}/catalog/{type}/{id}/{extra:path}")
async def stremio_catalog_token(request: Request, token: str, type: str, id: str, extra: Optional[str] = None):
    return await handle_catalog(request, type, id, token=token, extra=extra)

# --- Meta ---
async def handle_meta(request: Request, type: str, id: str, token: Optional[str] = None):
    base_url = get_base_url(request)
    id_clean = id.replace(".json", "")

    # Živý kanál
    if id_clean.startswith("ct_live_"):
        ch_code = id_clean.replace("ct_live_", "")
        ch = LIVE_CHANNELS.get(ch_code)
        if not ch:
            raise HTTPException(status_code=404, detail="Kanál nenalezen")
        logo_rel = ch.get("logo_png") or ch["logo"]
        logo_url = f"{base_url}{logo_rel}"
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
            # Pokus o on-demand scrape z ČT
            show = await ct_service.scrape_show_metadata(show_id)
            if not show:
                raise HTTPException(status_code=404, detail="Pořad nenalezen")

        episodes = crud.get_episodes_by_show(show_id)
        # Filtrujeme pouze přehratelné epizody
        playable_episodes = [ep for ep in episodes if ep.get("is_playable", 1)]

        poster_raw = show.get("poster_url") or show.get("image_url")
        backdrop_raw = show.get("backdrop_url") or poster_raw
        poster_url = image_proxy.build_proxy_url(base_url, poster_raw)
        backdrop_url = image_proxy.build_proxy_url(base_url, backdrop_raw)

        genres_list = [g.strip() for g in show.get("genre", "").split(",") if g.strip()]
        is_movie = (show.get("show_type") == "movie")

        meta = {
            "id": id_clean,
            "type": "movie" if is_movie else "series",
            "name": show["title"],
            "poster": poster_url,
            "background": backdrop_url,
            "description": show.get("description", ""),
            "releaseInfo": str(show.get("year") or ""),
            "genres": genres_list or ["iVysílání"]
        }

        if is_movie:
            if playable_episodes:
                meta["behaviorHints"] = {
                    "defaultVideoId": f"ct_ep_{playable_episodes[0]['idec']}"
                }
        else:
            videos = []
            for ep in playable_episodes:
                ep_thumb = image_proxy.build_proxy_url(
                    base_url,
                    ep.get("image_url") or poster_raw
                )
                videos.append({
                    "id": f"ct_ep_{ep['idec']}",
                    "title": ep.get("title") or show["title"],
                    "season": ep.get("season", 1),
                    "episode": ep.get("episode_num", 1),
                    "overview": ep.get("description", show.get("description", "")),
                    "thumbnail": ep_thumb,
                    "released": ep.get("air_date") or ""
                })
            meta["videos"] = videos

        return cors_response({"meta": meta})

    raise HTTPException(status_code=404, detail="Položka nenalezena")

@router.get("/meta/{type}/{id}.json")
async def stremio_meta_default(request: Request, type: str, id: str):
    return await handle_meta(request, type, id, token=None)

@router.get("/{token}/meta/{type}/{id}.json")
async def stremio_meta_token(request: Request, token: str, type: str, id: str):
    return await handle_meta(request, type, id, token=token)

# --- Stream ---
async def handle_stream(request: Request, type: str, id: str, token: Optional[str] = None):
    base_url = get_base_url(request)
    id_clean = id.replace(".json", "")

    # Získání uživatele pro streamovací URL přes user_token
    user = get_user_for_token(token)
    u_name = user["username"]
    u_pass = user.get("user_token") or settings.DEFAULT_ADMIN_PASSWORD

    streams = []

    # 1. Živý stream
    if id_clean.startswith("ct_live_"):
        ch_code = id_clean.replace("ct_live_", "")
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
        
        # Zjištění titulků
        subs = []
        try:
            vod_info = await ct_service.resolve_vod_stream(idec, allow_drm=False)
            if vod_info and vod_info.get("subtitles"):
                for s in vod_info["subtitles"]:
                    subs.append({
                        "id": s.get("lang", "cs"),
                        "url": s.get("url"),
                        "lang": "ces" if s.get("lang") in ["cs", "ces", "cze"] else s.get("lang", "ces")
                    })
        except Exception:
            pass

        stream_obj = {
            "name": "iVysílání Server",
            "title": "ČT iVysílání (1080p HLS)",
            "url": stream_url
        }
        if subs:
            stream_obj["subtitles"] = subs

        streams.append(stream_obj)
        return cors_response({"streams": streams})

    # 3. Pořad přímo (např. film)
    if id_clean.startswith("ct_show_"):
        show_id = id_clean.replace("ct_show_", "")
        episodes = crud.get_episodes_by_show(show_id)
        playable_episodes = [ep for ep in episodes if ep.get("is_playable", 1)]
        if playable_episodes:
            idec = playable_episodes[0]["idec"]
            stream_url = f"{base_url}/movie/{u_name}/{u_pass}/{idec}.m3u8"
            
            subs = []
            try:
                vod_info = await ct_service.resolve_vod_stream(idec, allow_drm=False)
                if vod_info and vod_info.get("subtitles"):
                    for s in vod_info["subtitles"]:
                        subs.append({
                            "id": s.get("lang", "cs"),
                            "url": s.get("url"),
                            "lang": "ces" if s.get("lang") in ["cs", "ces", "cze"] else s.get("lang", "ces")
                        })
            except Exception:
                pass

            stream_obj = {
                "name": "iVysílání Server",
                "title": f"{playable_episodes[0].get('title', 'Film')} (1080p HLS)",
                "url": stream_url
            }
            if subs:
                stream_obj["subtitles"] = subs

            streams.append(stream_obj)
            return cors_response({"streams": streams})

    return cors_response({"streams": []})

@router.get("/stream/{type}/{id}.json")
async def stremio_stream_default(request: Request, type: str, id: str):
    return await handle_stream(request, type, id, token=None)

@router.get("/{token}/stream/{type}/{id}.json")
async def stremio_stream_token(request: Request, token: str, type: str, id: str):
    return await handle_stream(request, type, id, token=token)
