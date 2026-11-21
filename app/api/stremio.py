import re
import urllib.parse
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.db import crud
from app.services.ct_service import ct_service, clean_episode_title, LIVE_CHANNELS
from app.services.image_proxy import image_proxy
from app.services.tmdb_service import tmdb_service
from app.api.xtream import CHANNEL_STREAM_MAP, CHANNEL_ID_TO_STREAM_ID

router = APIRouter()

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

def build_manifest(base_url: str, token: Optional[str] = None, is_streamcube: bool = False) -> dict:
    token_suffix = f"/{token}" if token else ""
    auth_token = token or "active"

    catalogs = []
    # Live TV pouze pro StreamCube (uživatel si nepřeje živé vysílání ve Stremio doplňku)
    if is_streamcube:
        catalogs.append({
            "type": "tv",
            "id": "ct_live",
            "name": "Česká televize: Živé vysílání"
        })

    # Seriály a filmy
    catalogs.extend([
        {
            "type": "series",
            "id": "ct_featured",
            "name": "iVysílání: Doporučujeme (Seriály)",
            "genres": [
                "Vše", "Nejsledovanější", "Doporučujeme", "Ty nejlepší zahraniční seriály",
                "Novinky České televize", "Filmové tipy", "Dokumenty České televize",
                "Napínavé kriminální případy", "Vyrobila Česká televize"
            ],
            "extra": [
                {
                    "name": "genre",
                    "options": [
                        "Vše", "Nejsledovanější", "Doporučujeme", "Ty nejlepší zahraniční seriály",
                        "Novinky České televize", "Filmové tipy", "Dokumenty České televize",
                        "Napínavé kriminální případy", "Vyrobila Česká televize"
                    ]
                },
                {"name": "search"},
                {"name": "skip"}
            ]
        },
        {
            "type": "series",
            "id": "ct_series",
            "name": "iVysílání: Všechny seriály",
            "genres": [
                "Vše", "České", "Krimi", "Komedie", "Zahraniční", "Rodinné",
                "Psychologické", "Historické", "Klasika", "Thrillery", "Literární adaptace", "Studentské"
            ],
            "extra": [
                {
                    "name": "genre",
                    "options": [
                        "Vše", "České", "Krimi", "Komedie", "Zahraniční", "Rodinné",
                        "Psychologické", "Historické", "Klasika", "Thrillery", "Literární adaptace", "Studentské"
                    ]
                },
                {"name": "search"},
                {"name": "skip"}
            ]
        },
        {
            "type": "movie",
            "id": "ct_featured_movie",
            "name": "iVysílání: Doporučujeme (Filmy)",
            "genres": [
                "Vše", "Filmové tipy", "iVysílání doporučuje", "Nejsledovanější", "Klasika"
            ],
            "extra": [
                {
                    "name": "genre",
                    "options": ["Vše", "Filmové tipy", "iVysílání doporučuje", "Nejsledovanější", "Klasika"]
                },
                {"name": "search"},
                {"name": "skip"}
            ]
        },
        {
            "type": "movie",
            "id": "ct_movies",
            "name": "iVysílání: Všechny filmy",
            "genres": [
                "Vše", "České", "Krimi", "Komedie", "Zahraniční", "Pohádky",
                "Psychologické", "Historické", "Rodinné", "Klasika", "Drama",
                "Romantické", "Životopisné", "Thriller", "Animované", "Literární adaptace",
                "Válečné", "Studentské"
            ],
            "extra": [
                {
                    "name": "genre",
                    "options": [
                        "Vše", "České", "Krimi", "Komedie", "Zahraniční", "Pohádky",
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
            "type": "movie",
            "id": "ct_movies_czech",
            "name": "iVysílání: České filmy",
            "extra": [{"name": "search"}, {"name": "skip"}]
        },
        {
            "type": "movie",
            "id": "ct_movies_foreign",
            "name": "iVysílání: Zahraniční filmy",
            "extra": [{"name": "search"}, {"name": "skip"}]
        },
        {
            "type": "movie",
            "id": "ct_movies_pohadky",
            "name": "iVysílání: Pohádky",
            "extra": [{"name": "search"}, {"name": "skip"}]
        },
        {
            "type": "movie",
            "id": "ct_movies_doc",
            "name": "iVysílání: Dokumentární filmy",
            "extra": [{"name": "search"}, {"name": "skip"}]
        },
        {
            "type": "series",
            "id": "ct_documentaries",
            "name": "iVysílání: Dokumenty",
            "genres": ["Vše", "Příroda", "Historie", "Věda", "Lidé a společnost"],
            "extra": [
                {"name": "genre", "options": ["Vše", "Příroda", "Historie", "Věda", "Lidé a společnost"]},
                {"name": "search"},
                {"name": "skip"}
            ]
        },
        {
            "type": "series",
            "id": "ct_entertainment",
            "name": "iVysílání: Zábava",
            "genres": ["Vše", "Talk show", "Soutěže", "Komedie", "Hudební"],
            "extra": [
                {
                    "name": "genre",
                    "options": ["Vše", "Talk show", "Soutěže", "Komedie", "Hudební"]
                },
                {"name": "search"},
                {"name": "skip"}
            ]
        },
        {
            "type": "series",
            "id": "ct_kids",
            "name": "iVysílání: Pro děti",
            "genres": ["Vše", "Večerníček", "Pohádky", "Animované", "Pro nejmenší"],
            "extra": [
                {"name": "genre", "options": ["Vše", "Večerníček", "Pohádky", "Animované", "Pro nejmenší"]},
                {"name": "search"},
                {"name": "skip"}
            ]
        }
    ])

    manifest = {
        "id": "cz.thelittlerock.ivysilani.streamcube" if is_streamcube else "cz.thelittlerock.ivysilani",
        "version": "1.3.2",
        "name": "Česká televize (StreamCube)" if is_streamcube else "Česká televize (iVysílání)",
        "description": "Kompletní filmový a seriálový archiv České televize (iVysílání), živé vysílání 14 stanic ČT s EPG a IPTV podporou." if is_streamcube else "Kompletní filmový a seriálový archiv České televize (iVysílání) s českým dabingem a titulky.",
        "logo": f"{base_url}/static/logos/ct1.png",
        "background": f"{base_url}/static/logos/ct1.png",
        "resources": ["catalog", "meta", "stream", "subtitles"],
        "types": ["series", "movie", "tv", "iptv", "stream"] if is_streamcube else ["series", "movie"],
        "idPrefixes": ["ct_", "tt", "tmdb:"],
        "catalogs": catalogs
    }

    if is_streamcube:
        manifest["streamcube"] = {
            "manifestVersion": 1,
            "addonType": "stream",
            "capabilities": ["stream", "iptv", "epg"],
            "minAppVersion": "2.0.0",
            "iptv": {
                "m3u": f"{base_url}/get.php?token={auth_token}",
                "epg": f"{base_url}/xmltv.php?token={auth_token}"
            }
        }

    return manifest

@router.options("/{full_path:path}")
async def stremio_options(full_path: str):
    return cors_response({})

# --- Manifest ---
@router.get("/manifest.json")
async def stremio_manifest_default(request: Request):
    is_streamcube = "/streamcube" in str(request.url.path)
    return cors_response(build_manifest(get_base_url(request), None, is_streamcube=is_streamcube))

@router.get("/{token}/manifest.json")
async def stremio_manifest_token(request: Request, token: str):
    is_streamcube = "/streamcube" in str(request.url.path)
    return cors_response(build_manifest(get_base_url(request), token, is_streamcube=is_streamcube))


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
                poster_rel = ch.get("poster") or ch.get("logo_png") or ch["logo"]
                poster_url = f"{base_url}{poster_rel}"
                logo_rel = ch.get("logo_png") or ch["logo"]
                logo_url = f"{base_url}{logo_rel}"
                metas.append({
                    "id": f"ct_live_{ch_code}",
                    "type": "tv",
                    "name": ch["name"],
                    "poster": poster_url,
                    "background": logo_url,
                    "description": ch["description"],
                    "genres": [ch["category"]]
                })
        return cors_response({"metas": metas})

    # 2. VOD Katalogy
    genre_filter = genre if (genre and genre not in ["Přehled", "Vše", "vse", "all"]) else None
    show_type = None

    if id == "ct_featured":
        # Doporučené bloky z hlavní stránky iVysílání
        hp_blocks = crud.get_homepage_blocks()
        matching_items = []
        for blk in hp_blocks:
            b_title = blk.get("title", "")
            if not genre_filter or genre_filter.lower() in b_title.lower():
                matching_items.extend(blk.get("items", []))

        shows = []
        seen_show_ids = set()
        for it in matching_items:
            it_id = it.get("id")
            if it_id and it_id not in seen_show_ids:
                seen_show_ids.add(it_id)
                db_s = crud.get_show_by_id(it_id)
                if db_s:
                    shows.append(db_s)
                else:
                    shows.append({
                        "id": it_id,
                        "title": it.get("title", ""),
                        "description": it.get("description", ""),
                        "image_url": it.get("card_url", ""),
                        "poster_url": it.get("poster_url", ""),
                        "backdrop_url": it.get("card_url", ""),
                        "genre": genre_filter or "Doporučujeme",
                        "show_type": it.get("show_type", "series"),
                        "year": ""
                    })
    elif id == "ct_series":
        show_type = "series"
        shows = crud.list_shows(genre=genre_filter, show_type=show_type, only_playable=True, search=search, limit=60, offset=skip)
    elif id == "ct_featured_movie":
        hp_blocks = crud.get_homepage_blocks()
        matching_items = []
        for blk in hp_blocks:
            b_title = blk.get("title", "")
            if genre_filter and genre_filter.lower() in b_title.lower():
                matching_items.extend(blk.get("items", []))
            elif not genre_filter and any(w in b_title.lower() for w in ["film", "doporuč", "sledovan", "hit"]):
                matching_items.extend(blk.get("items", []))

        shows = []
        seen_show_ids = set()
        for it in matching_items:
            it_id = it.get("id")
            if it_id and it_id not in seen_show_ids:
                seen_show_ids.add(it_id)
                db_s = crud.get_show_by_id(it_id)
                if db_s and db_s.get("show_type") == "movie":
                    shows.append(db_s)
                elif not db_s and it.get("show_type") == "movie":
                    shows.append({
                        "id": it_id,
                        "title": it.get("title", ""),
                        "description": it.get("description", ""),
                        "image_url": it.get("card_url", ""),
                        "poster_url": it.get("poster_url", ""),
                        "backdrop_url": it.get("card_url", ""),
                        "genre": genre_filter or "Filmové tipy",
                        "show_type": "movie",
                        "year": ""
                    })
        if not shows:
            shows = crud.list_shows(show_type="movie", only_playable=True, limit=60, offset=skip)
    elif id == "ct_movies":
        show_type = "movie"
        shows = crud.list_shows(genre=genre_filter, show_type=show_type, only_playable=True, search=search, limit=60, offset=skip)
    elif id == "ct_movies_czech":
        shows = crud.list_shows(genre="České", show_type="movie", only_playable=True, search=search, limit=60, offset=skip)
    elif id == "ct_movies_foreign":
        shows = crud.list_shows(genre="Zahraniční", show_type="movie", only_playable=True, search=search, limit=60, offset=skip)
    elif id == "ct_movies_pohadky":
        shows = crud.list_shows(genre="Pohádky", show_type="movie", only_playable=True, search=search, limit=60, offset=skip)
    elif id == "ct_movies_doc":
        shows = crud.list_shows(genre="Dokument", show_type="movie", only_playable=True, search=search, limit=60, offset=skip)
    elif id == "ct_documentaries":
        if not genre_filter:
            genre_filter = "Dokument"
        shows = crud.list_shows(genre=genre_filter, only_playable=True, search=search, limit=60, offset=skip)
    elif id == "ct_entertainment":
        if not genre_filter:
            genre_filter = "Zábava"
        shows = crud.list_shows(genre=genre_filter, only_playable=True, search=search, limit=60, offset=skip)
    elif id == "ct_kids":
        if not genre_filter:
            genre_filter = "Děti"
        shows = crud.list_shows(genre=genre_filter, only_playable=True, search=search, limit=60, offset=skip)
    else:
        shows = crud.list_shows(genre=genre_filter, only_playable=True, search=search, limit=60, offset=skip)

    # Rychlé vyhledávání přes GraphQL bez blokování HTTP dotazy
    if search and len(shows) < 5:
        try:
            external_results = await ct_service.search_shows_graphql(search, limit=20)
            seen_ids = {str(s["id"]) for s in shows}
            for res in external_results:
                sidp = str(res.get("id") or res.get("sidp") or "")
                if sidp and sidp not in seen_ids:
                    seen_ids.add(sidp)
                    imgs = res.get("images") or {}
                    raw_port = imgs.get("cardPortrait")
                    port_url = raw_port if raw_port and "fallbackImages" not in raw_port else imgs.get("card")
                    shows.append({
                        "id": sidp,
                        "title": res.get("title") or "",
                        "description": res.get("description") or "",
                        "image_url": imgs.get("card") or "",
                        "poster_url": port_url or "",
                        "backdrop_url": imgs.get("card") or "",
                        "genre": ", ".join([g.get("title") for g in res.get("genres", []) if g.get("title")]),
                        "show_type": "series" if any("seriál" in (g.get("title") or "").lower() for g in res.get("genres", [])) else "movie",
                        "year": ""
                    })
                    # Hloubkovou indexaci spustíme asynchronně na pozadí
                    import asyncio
                    asyncio.create_task(ct_service.scrape_show_metadata(sidp))
        except Exception:
            pass

    for s in shows:
        poster_url = s.get("tmdb_poster")
        if not poster_url:
            poster_raw = s.get("poster_url") or s.get("image_url")
            poster_url = image_proxy.build_proxy_url(base_url, poster_raw, pad="2x3")

        backdrop_url = s.get("tmdb_backdrop")
        if not backdrop_url:
            backdrop_raw = s.get("backdrop_url") or s.get("image_url")
            backdrop_url = image_proxy.build_proxy_url(base_url, backdrop_raw)

        genres_list = [g.strip() for g in s.get("genre", "").split(",") if g.strip()]
        s_type = "movie" if s.get("show_type") == "movie" else "series"

        item = {
            "id": f"ct_show_{s['id']}",
            "type": s_type,
            "name": s["title"],
            "poster": poster_url,
            "background": backdrop_url,
            "description": s.get("description", ""),
            "releaseInfo": str(s.get("year") or ""),
            "genres": genres_list or ["iVysílání"]
        }
        if s_type == "movie" and s.get("imdb_id"):
            item["imdb_id"] = s["imdb_id"]
        metas.append(item)

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

    # 1. Živý kanál
    if id_clean.startswith("ct_live_"):
        ch_code = id_clean.replace("ct_live_", "")
        ch = LIVE_CHANNELS.get(ch_code)
        if not ch:
            raise HTTPException(status_code=404, detail="Kanál nenalezen")
        poster_rel = ch.get("poster") or ch.get("logo_png") or ch["logo"]
        poster_url = f"{base_url}{poster_rel}"
        logo_rel = ch.get("logo_png") or ch["logo"]
        logo_url = f"{base_url}{logo_rel}"
        meta = {
            "id": id_clean,
            "type": "tv",
            "name": ch["name"],
            "poster": poster_url,
            "background": logo_url,
            "description": ch["description"],
            "genres": [ch["category"]]
        }
        return cors_response({"meta": meta})

    # 2. Pořad z iVysílání nebo Cinemeta (IMDb / TMDB)
    show = None
    if id_clean.startswith("ct_show_"):
        show_id = id_clean.replace("ct_show_", "")
        show = crud.get_show_by_id(show_id)
        if not show:
            show = await ct_service.scrape_show_metadata(show_id)
    elif id_clean.startswith("tt"):
        show = crud.get_show_by_imdb_id(id_clean)
        if not show:
            tmdb_info = await tmdb_service.get_by_imdb_id(id_clean)
            if tmdb_info and tmdb_info.get("title"):
                candidates = crud.list_shows(search=tmdb_info["title"], limit=1)
                if candidates:
                    show = candidates[0]
                    crud.update_show_tmdb(show["id"], tmdb_info["tmdb_id"], id_clean, tmdb_info.get("poster_url", "") or "", tmdb_info.get("backdrop_url", "") or "")
    elif id_clean.startswith("tmdb:"):
        raw_tmdb = id_clean.replace("tmdb:", "")
        show = crud.get_show_by_tmdb_id(raw_tmdb)

    if show:
        episodes = crud.get_episodes_by_show(show["id"])
        # Pokud seriál nemá žádné epizody, doindexujeme je
        if not episodes and show.get("id"):
            try:
                from app.services.archive_crawler import archive_crawler
                await archive_crawler.index_show(show["id"])
                episodes = crud.get_episodes_by_show(show["id"])
            except Exception:
                pass

        playable_episodes = [ep for ep in episodes if ep.get("is_playable", 1)]

        poster_url = show.get("tmdb_poster")
        if not poster_url:
            poster_raw = show.get("poster_url") or show.get("image_url")
            poster_url = image_proxy.build_proxy_url(base_url, poster_raw, pad="2x3")

        backdrop_url = show.get("tmdb_backdrop")
        if not backdrop_url:
            backdrop_raw = show.get("backdrop_url") or show.get("image_url")
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
        if is_movie and show.get("imdb_id"):
            meta["imdb_id"] = show["imdb_id"]

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
                    ep.get("image_url") or show.get("image_url")
                )
                _, clean_name = clean_episode_title(ep.get("title") or "")
                ep_clean_title = clean_name or ep.get("title") or show["title"]

                videos.append({
                    "id": f"{id_clean}:{ep.get('season', 1)}:{ep.get('episode_num', 1)}",
                    "title": ep_clean_title,
                    "season": ep.get("season", 1),
                    "episode": ep.get("episode_num", 1),
                    "overview": ep.get("description", show.get("description", "")),
                    "thumbnail": ep_thumb,
                    "released": ep.get("broadcast_date") or ""
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
            "name": "Česká televize (iVysílání)",
            "title": f"[ČT] {ch.get('name', 'ČT')} (1080p HLS)",
            "url": stream_url
        })
        return cors_response({"streams": streams})

    async def build_stremio_stream_list(idec_code: str, title_label: str) -> list:
        subs = []
        try:
            vod_info = await ct_service.resolve_vod_stream(idec_code, allow_drm=False)
            if vod_info and vod_info.get("subtitles"):
                for s in vod_info["subtitles"]:
                    raw_sub = s.get("url", "")
                    if raw_sub:
                        subs.append({
                            "id": s.get("language", "ces"),
                            "url": f"{base_url}/api/subtitles?url={urllib.parse.quote(raw_sub, safe='')}",
                            "lang": "ces" if s.get("language") in ["cs", "ces", "cze"] else s.get("language", "ces")
                        })
        except Exception as e:
            logger.debug(f"Subtitles resolve failed for {idec_code}: {e}")

        qualities = [
            ("Adaptivní Auto", "", "až 1080p Full HD • Auto adaptivní"),
            ("1080p Full HD", "1080p", "1080p Full HD (6.3 Mbps)"),
            ("720p HD", "720p", "720p HD (3.7 Mbps)"),
            ("576p SD", "576p", "576p SD (2.2 Mbps)")
        ]
        res_streams = []
        for q_name, q_val, q_desc in qualities:
            q_param = f"?quality={q_val}" if q_val else ""
            stream_url = f"{base_url}/movie/{u_name}/{u_pass}/{idec_code}.m3u8{q_param}"
            s_obj = {
                "name": f"[iVysílání] {q_name}",
                "title": f"{title_label}\n{q_desc} • ČT HLS",
                "url": stream_url
            }
            if subs:
                s_obj["subtitles"] = subs
            res_streams.append(s_obj)
        return res_streams

    # 2. Epizoda pořadu přímo podle IDEC
    if id_clean.startswith("ct_ep_"):
        idec = id_clean.replace("ct_ep_", "")
        streams = await build_stremio_stream_list(idec, "[iVysílání] Pořad ČT")
        return cors_response({"streams": streams})

    # 3. Pořad přímo podle ČT show_id (film nebo seriál: ct_show_{id}:{season}:{episode} nebo ct_{id}:{season}:{episode})
    if id_clean.startswith("ct_show_") or (id_clean.startswith("ct_") and not id_clean.startswith("ct_ep_")):
        raw_id = id_clean.replace("ct_show_", "")
        if raw_id.startswith("ct_"):
            raw_id = raw_id[3:]
        parts = raw_id.split(":")
        show_id = parts[0]
        has_ep_params = len(parts) > 1
        season_num = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
        ep_num = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1

        show = crud.get_show_by_id(show_id)
        episodes = crud.get_episodes_by_show(show_id)
        if not episodes and show_id:
            try:
                from app.services.archive_crawler import archive_crawler
                await archive_crawler.index_show(show_id)
                episodes = crud.get_episodes_by_show(show_id)
            except Exception:
                pass

        playable_episodes = [ep for ep in episodes if ep.get("is_playable", 1)]
        if playable_episodes:
            target_ep = None
            if has_ep_params and (not show or show.get("show_type") != "movie"):
                # 1. Přesná shoda série a epizody
                for ep in playable_episodes:
                    if ep.get("season") == season_num and ep.get("episode_num") == ep_num:
                        target_ep = ep
                        break
                # 2. Shoda indexu v rámci série
                if not target_ep:
                    s_eps = [ep for ep in playable_episodes if ep.get("season") == season_num]
                    if s_eps and 0 <= ep_num - 1 < len(s_eps):
                        target_ep = s_eps[ep_num - 1]
                # 3. Fallback na první
                if not target_ep:
                    target_ep = playable_episodes[0]
            else:
                target_ep = playable_episodes[0]

            idec = target_ep["idec"]
            show_title = show["title"] if show else target_ep.get("title", "iVysílání")
            ep_title = target_ep.get("title") or show_title
            label = f"[iVysílání] {show_title} - S{season_num:02d}E{ep_num:02d}" if has_ep_params else f"[iVysílání] {show_title}"
            streams = await build_stremio_stream_list(idec, label)
            return cors_response({"streams": streams})

    # 4. IMDb ID (tt...) nebo TMDB ID (tmdb:...) ze Stremio Cinemeta katalogu
    if id_clean.startswith("tt") or id_clean.startswith("tmdb:"):
        parts = id_clean.split(":")
        main_id = parts[0]
        season_num = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
        ep_num = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1

        show = None
        if main_id.startswith("tt"):
            show = crud.get_show_by_imdb_id(main_id)
            if not show:
                tmdb_info = await tmdb_service.get_by_imdb_id(main_id)
                if tmdb_info and tmdb_info.get("title"):
                    candidates = crud.list_shows(search=tmdb_info["title"], limit=1)
                    if candidates:
                        show = candidates[0]
                        crud.update_show_tmdb(show["id"], tmdb_info["tmdb_id"], main_id, tmdb_info.get("poster_url", "") or "", tmdb_info.get("backdrop_url", "") or "")
        elif main_id.startswith("tmdb:"):
            raw_tmdb = main_id.replace("tmdb:", "")
            show = crud.get_show_by_tmdb_id(raw_tmdb)

        if show:
            # Speciální mapování pro Vyprávěj: Season 0 ep 7–15 -> Season 6 (Osudy)
            if str(show.get("id")) == "10195164142":
                if season_num == 0 and 7 <= ep_num <= 15:
                    season_num = 6
                    ep_num = ep_num - 6

            episodes = crud.get_episodes_by_show(show["id"], only_playable=True)
            if not episodes and show.get("id"):
                try:
                    from app.services.archive_crawler import archive_crawler
                    await archive_crawler.index_show(show["id"])
                    episodes = crud.get_episodes_by_show(show["id"], only_playable=True)
                except Exception:
                    pass

            target_ep = None
            if show.get("show_type") == "movie" and episodes:
                target_ep = episodes[0]
            else:
                for ep in episodes:
                    if ep.get("season") == season_num and ep.get("episode_num") == ep_num:
                        target_ep = ep
                        break
                if not target_ep:
                    s_eps = [ep for ep in episodes if ep.get("season") == season_num]
                    if s_eps and 0 <= ep_num - 1 < len(s_eps):
                        target_ep = s_eps[ep_num - 1]
                if not target_ep and episodes:
                    target_ep = episodes[0]

            if target_ep:
                idec = target_ep["idec"]
                title_label = f"[iVysílání] {show['title']}"
                if show.get("show_type") != "movie":
                    title_label = f"[iVysílání] {show['title']} - S{season_num:02d}E{ep_num:02d}"
                streams = await build_stremio_stream_list(idec, title_label)
                return cors_response({"streams": streams})

    return cors_response({"streams": []})

@router.get("/stream/{type}/{id}.json")
async def stremio_stream_default(request: Request, type: str, id: str):
    return await handle_stream(request, type, id, token=None)

@router.get("/{token}/stream/{type}/{id}.json")
async def stremio_stream_token(request: Request, token: str, type: str, id: str):
    return await handle_stream(request, type, id, token=token)

# --- Subtitles ---
async def handle_subtitles(request: Request, type: str, id: str, token: Optional[str] = None, extra: Optional[str] = None):
    base_url = get_base_url(request)
    id_clean = id.replace(".json", "")
    
    idec = None
    if id_clean.startswith("ct_ep_"):
        idec = id_clean.replace("ct_ep_", "")
    elif id_clean.startswith("ct_show_") or (id_clean.startswith("ct_") and not id_clean.startswith("ct_live_")):
        raw_id = id_clean.replace("ct_show_", "")
        if raw_id.startswith("ct_"):
            raw_id = raw_id[3:]
        parts = raw_id.split(":")
        show_id = parts[0]
        has_ep_params = len(parts) > 1
        season_num = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
        ep_num = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1

        episodes = crud.get_episodes_by_show(show_id)
        playable_episodes = [ep for ep in episodes if ep.get("is_playable", 1)]
        if playable_episodes:
            target_ep = None
            if has_ep_params:
                for ep in playable_episodes:
                    if ep.get("season") == season_num and ep.get("episode_num") == ep_num:
                        target_ep = ep
                        break
                if not target_ep:
                    s_eps = [ep for ep in playable_episodes if ep.get("season") == season_num]
                    if s_eps and 0 <= ep_num - 1 < len(s_eps):
                        target_ep = s_eps[ep_num - 1]
                if not target_ep:
                    target_ep = playable_episodes[0]
            else:
                target_ep = playable_episodes[0]
            if target_ep:
                idec = target_ep["idec"]
    elif id_clean.startswith("tt") or id_clean.startswith("tmdb:"):
        parts = id_clean.split(":")
        main_id = parts[0]
        season_num = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
        ep_num = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1

        show = None
        if main_id.startswith("tt"):
            show = crud.get_show_by_imdb_id(main_id)
        elif main_id.startswith("tmdb:"):
            show = crud.get_show_by_tmdb_id(main_id.replace("tmdb:", ""))

        if show:
            episodes = crud.get_episodes_by_show(show["id"], only_playable=True)
            if episodes:
                if show.get("show_type") == "movie":
                    idec = episodes[0]["idec"]
                else:
                    for ep in episodes:
                        if ep.get("season") == season_num and ep.get("episode_num") == ep_num:
                            idec = ep["idec"]
                            break
                    if not idec:
                        idec = episodes[0]["idec"]

    subtitles = []
    if idec:
        try:
            vod_info = await ct_service.resolve_vod_stream(idec, allow_drm=False)
            if vod_info and vod_info.get("subtitles"):
                for idx, s in enumerate(vod_info["subtitles"], start=1):
                    raw_sub = s.get("url", "")
                    if raw_sub:
                        subtitles.append({
                            "id": f"cze_{idx}",
                            "url": f"{base_url}/api/subtitles?url={urllib.parse.quote(raw_sub, safe='')}",
                            "lang": "cze"
                        })
        except Exception as e:
            logger.debug(f"Subtitles fetch failed for {idec}: {e}")

    return cors_response({"subtitles": subtitles})

@router.get("/subtitles/{type}/{id}.json")
@router.get("/subtitles/{type}/{id}/{extra:path}")
async def stremio_subtitles_default(request: Request, type: str, id: str, extra: Optional[str] = None):
    return await handle_subtitles(request, type, id, token=None, extra=extra)

@router.get("/{token}/subtitles/{type}/{id}.json")
@router.get("/{token}/subtitles/{type}/{id}/{extra:path}")
async def stremio_subtitles_token(request: Request, token: str, type: str, id: str, extra: Optional[str] = None):
    return await handle_subtitles(request, type, id, token=token, extra=extra)
