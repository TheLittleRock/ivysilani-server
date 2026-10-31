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
        "version": "1.3.0",
        "name": "Česká televize (iVysílání)",
        "description": "Kompletní filmový a seriálový archiv České televize (iVysílání) s českým dabingem a titulky.",
        "logo": f"{base_url}/static/logos/ct1.png",
        "background": f"{base_url}/static/logos/ct1.png",
        "resources": ["catalog", "meta", "stream"],
        "types": ["series", "movie"],
        "idPrefixes": ["ct_", "tt", "tmdb:"],
        "catalogs": [
            {
                "type": "series",
                "id": "ct_series",
                "name": "iVysílání: Seriály",
                "extra": [
                    {
                        "name": "genre",
                        "options": [
                            "Přehled", "České", "Krimi", "Komedie", "Zahraniční", "Rodinné",
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
                            "Přehled", "České", "Krimi", "Komedie", "Zahraniční", "Pohádky",
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

    # 2. Epizoda pořadu přímo podle IDEC
    if id_clean.startswith("ct_ep_"):
        idec = id_clean.replace("ct_ep_", "")
        stream_url = f"{base_url}/movie/{u_name}/{u_pass}/{idec}.m3u8"
        
        # Zjištění titulků
        subs = []
        try:
            vod_info = await ct_service.resolve_vod_stream(idec, allow_drm=True)
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
            logger.debug(f"Subtitles resolve failed for {idec}: {e}")

        stream_obj = {
            "name": "Česká televize (iVysílání)",
            "title": "[iVysílání] 1080p HLS",
            "url": stream_url
        }
        if subs:
            stream_obj["subtitles"] = subs

        streams.append(stream_obj)
        return cors_response({"streams": streams})

    # 3. Pořad přímo podle ČT show_id (film nebo seriál: ct_show_{id}:{season}:{episode})
    if id_clean.startswith("ct_show_"):
        raw_id = id_clean.replace("ct_show_", "")
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
            stream_url = f"{base_url}/movie/{u_name}/{u_pass}/{idec}.m3u8"
            
            subs = []
            try:
                vod_info = await ct_service.resolve_vod_stream(idec, allow_drm=True)
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
                logger.debug(f"Subtitles resolve failed for {idec}: {e}")

            show_title = show["title"] if show else target_ep.get("title", "iVysílání")
            ep_title = target_ep.get("title") or show_title
            label = f"[iVysílání] {show_title} - S{season_num:02d}E{ep_num:02d} (1080p HLS)" if has_ep_params else f"[iVysílání] {show_title} (1080p HLS)"

            stream_obj = {
                "name": "Česká televize (iVysílání)",
                "title": label,
                "url": stream_url
            }
            if subs:
                stream_obj["subtitles"] = subs

            streams.append(stream_obj)
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
                stream_url = f"{base_url}/movie/{u_name}/{u_pass}/{idec}.m3u8"
                subs = []
                try:
                    vod_info = await ct_service.resolve_vod_stream(idec, allow_drm=True)
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
                    logger.debug(f"Subtitles resolve failed for {idec}: {e}")

                title_label = f"[iVysílání] {show['title']} (1080p HLS)"
                if show.get("show_type") != "movie":
                    title_label = f"[iVysílání] {show['title']} - S{season_num:02d}E{ep_num:02d} (1080p HLS)"

                stream_obj = {
                    "name": "Česká televize (iVysílání)",
                    "title": title_label,
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
