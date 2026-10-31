import time
import logging
from datetime import datetime, timezone
from typing import Optional, Union, Any
from fastapi import APIRouter, Request, Response, HTTPException, Query
from fastapi.responses import RedirectResponse, StreamingResponse, PlainTextResponse, JSONResponse
import httpx

from app.core.config import settings
from app.db import crud
from app.services.ct_service import ct_service, LIVE_CHANNELS
from app.services.epg_service import generate_xmltv_epg
from app.services.image_proxy import image_proxy

logger = logging.getLogger("xtream")
router = APIRouter()

def get_base_url(request: Request) -> str:
    if settings.BASE_URL:
        return settings.BASE_URL.rstrip('/')
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", f"127.0.0.1:{settings.PORT}"))
    return f"{forwarded_proto}://{forwarded_host}"

def check_auth(
    username: Optional[str] = None,
    password: Optional[str] = None,
    token: Optional[str] = None
):
    """Ověří přístup buď přes token, nebo přes uživatelské jméno a heslo."""
    # 1. Přímé ověření přes token v parametru
    if token:
        user_by_token = crud.get_user_by_token(token)
        if user_by_token and user_by_token.get("is_active", 1):
            return user_by_token
        raise HTTPException(status_code=401, detail="Invalid token")

    # 2. Token zadaný v poli username nebo password (typické pro IPTV aplikace)
    if username:
        user_by_token = crud.get_user_by_token(username)
        if user_by_token and user_by_token.get("is_active", 1):
            return user_by_token
    if password:
        user_by_token = crud.get_user_by_token(password)
        if user_by_token and user_by_token.get("is_active", 1):
            return user_by_token

    # 3. Klasické ověření uživatelským jménem a heslem
    if username and password:
        user = crud.authenticate_user(username, password)
        if user:
            return user
        db_user = crud.get_user_by_username(username)
        if db_user and db_user.get("is_active", 1):
            return db_user

    raise HTTPException(status_code=401, detail="Invalid credentials or token")

# Mapování stream_id <-> kanál
CHANNEL_STREAM_MAP = {
    1: "CH_1",
    2: "CH_2",
    3: "CH_24",
    4: "CH_4",
    5: "CH_5",
    6: "CH_6",
    25: "CH_25",
    26: "CH_26",
    27: "CH_27",
    28: "CH_28",
    29: "CH_29",
    30: "CH_30",
    31: "CH_31",
    32: "CH_32"
}
CHANNEL_ID_TO_STREAM_ID = {v: k for k, v in CHANNEL_STREAM_MAP.items()}

@router.get("/player_api.php")
@router.post("/player_api.php")
async def player_api(
    request: Request,
    username: Optional[str] = Query(None),
    password: Optional[str] = Query(None),
    token: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    stream_id: Optional[str] = Query(None),
    series_id: Optional[str] = Query(None),
    vod_id: Optional[str] = Query(None),
    category_id: Optional[str] = Query(None)
):
    try:
        # Form data fallback pro POST
        if request.method == "POST":
            try:
                form_data = await request.form()
                username = username or form_data.get("username")
                password = password or form_data.get("password")
                token = token or form_data.get("token")
                action = action or form_data.get("action")
                stream_id = stream_id or form_data.get("stream_id")
                series_id = series_id or form_data.get("series_id")
                vod_id = vod_id or form_data.get("vod_id")
                category_id = category_id or form_data.get("category_id")
            except Exception as form_err:
                logger.warning(f"Error parsing POST form: {form_err}")

        user = None
        try:
            user = check_auth(username=username, password=password, token=token)
        except Exception:
            pass

        if not user:
            return {"user_info": {"auth": 0, "message": "Invalid username, password or token"}}

        base_url = get_base_url(request)
        now_ts = int(time.time())
        now_dt = datetime.fromtimestamp(now_ts, timezone.utc)

        # 1. Výchozí odpověď při přihlášení (žádná akce)
        if not action:
            exp_str = str(user.get("exp_date")) if user.get("exp_date") else None
            return {
                "user_info": {
                    "username": user["username"],
                    "password": password or user.get("user_token") or "token",
                    "message": "iVysilani Server Xtream Codes API",
                    "auth": 1,
                    "status": "Active",
                    "exp_date": exp_str,
                    "is_trial": "0",
                    "active_cons": "1",
                    "created_at": str(user.get("created_at", now_ts)),
                    "max_connections": str(user.get("max_connections", 2)),
                    "allowed_output_formats": ["m3u8", "ts", "mp4"]
                },
                "server_info": {
                    "url": base_url.split("://")[-1].split(":")[0],
                    "port": str(settings.PORT),
                    "https_port": "443",
                    "server_protocol": base_url.split("://")[0],
                    "rtmp_port": "8880",
                    "timezone": "Europe/Prague",
                    "time_now": now_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "timestamp_now": now_ts
                }
            }

        # 2. Živé kategorie
        if action == "get_live_categories":
            return [
                {"category_id": "1", "category_name": "Česká televize", "parent_id": 0},
                {"category_id": "2", "category_name": "ČT sport Plus", "parent_id": 0}
            ]

        # 3. Živé kanály
        if action == "get_live_streams":
            cat_filter = str(category_id) if category_id else None
            streams = []
            for s_id, ch_code in CHANNEL_STREAM_MAP.items():
                ch = LIVE_CHANNELS[ch_code]
                cat_id = "1" if ch["category"] == "Česká televize" else "2"
                if cat_filter and cat_filter != cat_id:
                    continue
                logo_rel = ch.get("logo_png") or ch["logo"]
                streams.append({
                    "num": s_id,
                    "name": ch["name"],
                    "stream_type": "live",
                    "stream_id": s_id,
                    "stream_icon": f"{base_url}{logo_rel}",
                    "epg_channel_id": ch["epg_id"],
                    "added": "1704067200",
                    "category_id": cat_id,
                    "custom_sid": "",
                    "tv_archive": 1,
                    "direct_source": "",
                    "tv_archive_duration": 14
                })
            return streams

        # 4. VOD Kategorie (Filmy)
        if action == "get_vod_categories":
            return [
                {"category_id": "1", "category_name": "Filmy ČT", "parent_id": 0},
                {"category_id": "2", "category_name": "Pohádky & Rodinné", "parent_id": 0},
                {"category_id": "3", "category_name": "Komedie & Drama", "parent_id": 0},
                {"category_id": "4", "category_name": "Dokumentární filmy", "parent_id": 0}
            ]

        # 5. VOD Seznam (Pouze celovečerní filmy)
        if action == "get_vod_streams":
            genre_filter = None
            if category_id == "2":
                genre_filter = "Pohádka"
            elif category_id == "3":
                genre_filter = "Komedie"
            elif category_id == "4":
                genre_filter = "Dokument"

            movies = crud.list_movies(genre=genre_filter, only_playable=True, limit=500)
            vod_streams = []
            for idx, m in enumerate(movies, start=1):
                cat_id = "1"
                g = m.get("genre", "")
                if "Pohádka" in g or "Rodinný" in g:
                    cat_id = "2"
                elif "Komedie" in g or "Drama" in g:
                    cat_id = "3"
                elif "Dokument" in g:
                    cat_id = "4"

                episodes = crud.get_episodes_by_show(m["id"])
                playable_eps = [ep for ep in episodes if ep.get("is_playable", 1)]
                idec = playable_eps[0]["idec"] if playable_eps else m["id"]
                
                poster_raw = m.get("poster_url") or m.get("image_url")
                poster_url = image_proxy.build_proxy_url(base_url, poster_raw, pad="2x3")

                vod_streams.append({
                    "num": idx,
                    "name": m["title"],
                    "stream_type": "movie",
                    "stream_id": idec,
                    "stream_icon": poster_url,
                    "rating": "8.0",
                    "rating_5based": 4.0,
                    "added": str(m.get("updated_at", now_ts)),
                    "category_id": cat_id,
                    "container_extension": "m3u8"
                })
            return vod_streams

        # 6. VOD Detail
        if action == "get_vod_info":
            idec = str(vod_id or stream_id)
            ep = crud.get_episode_by_idec(idec)
            show = crud.get_show_by_id(ep["show_id"]) if ep else None
            title = ep["title"] if ep else (show["title"] if show else f"Pořad {idec}")
            desc = ep["description"] if ep else (show["description"] if show else "")
            
            img_raw = (ep["image_url"] if ep else None) or (show.get("poster_url") or show.get("image_url") if show else "")
            img_url = image_proxy.build_proxy_url(base_url, img_raw)

            return {
                "info": {
                    "name": title,
                    "title": title,
                    "year": show["year"] if show else "",
                    "releasedate": "",
                    "genre": show["genre"] if show else "",
                    "plot": desc,
                    "cover_big": img_url,
                    "movie_image": img_url,
                    "duration_secs": ep.get("duration", 3600) if ep else 3600,
                    "duration": "01:00:00"
                },
                "movie_data": {
                    "stream_id": idec,
                    "name": title,
                    "container_extension": "m3u8"
                }
            }

        # 7. Seriály kategorie & seznam
        if action == "get_series_categories":
            return [
                {"category_id": "1", "category_name": "Seriály", "parent_id": 0},
                {"category_id": "2", "category_name": "Dokumentární cykly", "parent_id": 0},
                {"category_id": "3", "category_name": "Zábavné pořady", "parent_id": 0},
                {"category_id": "4", "category_name": "Dětské seriály", "parent_id": 0}
            ]

        if action == "get_series":
            genre_filter = None
            if category_id == "2":
                genre_filter = "Dokument"
            elif category_id == "3":
                genre_filter = "Zábava"
            elif category_id == "4":
                genre_filter = "Děti"

            shows = crud.list_series(genre=genre_filter, only_playable=True, limit=500)
            series_list = []
            for idx, s in enumerate(shows, start=1):
                cat_id = "1"
                g = s.get("genre", "")
                if "Dokument" in g:
                    cat_id = "2"
                elif "Zábava" in g or "Talk show" in g or "Soutěž" in g:
                    cat_id = "3"
                elif "Děti" in g or "Pohádka" in g:
                    cat_id = "4"

                cover_raw = s.get("poster_url") or s.get("image_url")
                cover_proxy = image_proxy.build_proxy_url(base_url, cover_raw, pad="2x3")
                backdrop_proxy = image_proxy.build_proxy_url(base_url, s.get("backdrop_url") or cover_raw)

                series_list.append({
                    "num": idx,
                    "name": s["title"],
                    "series_id": s["id"],
                    "cover": cover_proxy,
                    "backdrop_path": [backdrop_proxy],
                    "plot": s.get("description", ""),
                    "cast": "",
                    "director": "",
                    "genre": s.get("genre", "Seriál"),
                    "releaseDate": s.get("year", ""),
                    "last_modified": str(s.get("updated_at", now_ts)),
                    "rating": "8.5",
                    "rating_5based": 4.2,
                    "category_id": cat_id
                })
            return series_list

        if action == "get_series_info":
            s_id = str(series_id) if series_id else ""
            show = crud.get_show_by_id(s_id)
            if not show:
                try:
                    show = await ct_service.scrape_show_metadata(s_id)
                except Exception:
                    pass
            if not show:
                return {"seasons": [], "episodes": {}}

            episodes = crud.get_episodes_by_show(s_id)
            playable_episodes = [ep for ep in episodes if ep.get("is_playable", 1)]

            seasons_set = set()
            episodes_by_season = {}
            for ep in playable_episodes:
                s_num = ep.get("season", 1) or 1
                seasons_set.add(s_num)
                sn_key = str(s_num)
                if sn_key not in episodes_by_season:
                    episodes_by_season[sn_key] = []
                
                ep_img_raw = ep.get("image_url") or show.get("poster_url") or show.get("image_url")
                ep_img_proxy = image_proxy.build_proxy_url(base_url, ep_img_raw)

                episodes_by_season[sn_key].append({
                    "id": ep["idec"],
                    "episode_num": ep.get("episode_num", 1),
                    "title": ep.get("title") or f"Epizoda {ep.get('episode_num', 1)}",
                    "container_extension": "m3u8",
                    "info": {
                        "name": ep.get("title") or f"Epizoda {ep.get('episode_num', 1)}",
                        "plot": ep.get("description", ""),
                        "duration_secs": ep.get("duration", 3600),
                        "duration": f"{ep.get('duration', 3600) // 60}:00",
                        "movie_image": ep_img_proxy
                    }
                })

            cover_url = image_proxy.build_proxy_url(base_url, show.get("poster_url") or show.get("image_url"), pad="2x3")
            backdrop_url = image_proxy.build_proxy_url(base_url, show.get("backdrop_url") or show.get("poster_url") or show.get("image_url"))

            seasons = []
            for sn in sorted(seasons_set):
                seasons.append({
                    "air_date": "",
                    "episode_count": len(episodes_by_season.get(str(sn), [])),
                    "id": sn,
                    "name": f"Série {sn}",
                    "season_number": sn,
                    "cover": cover_url
                })

            return {
                "seasons": seasons,
                "info": {
                    "name": show["title"],
                    "cover": cover_url,
                    "plot": show.get("description", ""),
                    "cast": "",
                    "director": "",
                    "genre": show.get("genre", ""),
                    "releaseDate": show.get("year", ""),
                    "backdrop_path": [backdrop_url],
                    "rating": "8.5",
                    "rating_5based": 4.2
                },
                "episodes": episodes_by_season
            }

        return {"message": "Action not supported"}
    except Exception as err:
        logger.exception(f"Unhandled error in player_api: {err}")
        return JSONResponse(status_code=500, content={"error": "Server error", "detail": str(err)})

def parse_catchup_timestamp(raw_time: Optional[str]) -> Optional[int]:
    """Parsuje časové razítko z různých formátů IPTV klientů (Unix ts, ISO, YYYYmmddHHMMSS)."""
    if not raw_time:
        return None
    raw = str(raw_time).strip()
    try:
        if raw.isdigit():
            if len(raw) == 14:  # YYYYmmddHHMMSS
                dt = datetime.strptime(raw, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
                return int(dt.timestamp())
            return int(raw)
        if "T" in raw or "-" in raw:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return int(dt.timestamp())
    except Exception as e:
        logger.warning(f"Chyba při parsování času catchup '{raw_time}': {e}")
    return None

# --- Streamovací Endpointy ---

@router.api_route("/live/{token}/{stream_filename}", methods=["GET", "HEAD"])
@router.api_route("/live/{username}/{password}/{stream_filename}", methods=["GET", "HEAD"])
async def live_stream(
    request: Request,
    stream_filename: str,
    token: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
):
    check_auth(username=username, password=password, token=token)
    # Extrakce stream_id
    stream_id_str = stream_filename.split(".")[0]
    try:
        s_id = int(stream_id_str)
        ch_code = CHANNEL_STREAM_MAP.get(s_id)
    except ValueError:
        ch_code = stream_id_str.upper()

    if not ch_code or ch_code not in LIVE_CHANNELS:
        raise HTTPException(status_code=404, detail="Channel not found")

    ch = LIVE_CHANNELS[ch_code]

    # Pokud klient žádá timeshift (catchup) přes query parametry (utc, start, lutc)
    req_time = request.query_params.get("utc") or request.query_params.get("start") or request.query_params.get("lutc")
    ts = parse_catchup_timestamp(req_time)
    if ts:
        prog = crud.get_epg_programme_by_time(ch["epg_id"], ts)
        if prog and prog.get("idec"):
            logger.info(f"Catchup v /live nalezen pro {ch['name']}: {prog['title']} (IDEC: {prog['idec']})")
            vod_data = await ct_service.resolve_vod_stream(prog["idec"], allow_drm=True)
            if vod_data and vod_data.get("url"):
                return RedirectResponse(url=vod_data["url"], status_code=302)

    stream_data = await ct_service.resolve_live_stream(ch_code, allow_drm=False)
    if not stream_data or not (stream_data.get("hls_url") or stream_data.get("url")):
        raise HTTPException(status_code=503, detail="Unable to resolve live stream from ČT")

    stream_url = stream_data.get("hls_url") or stream_data["url"]
    if settings.STREAM_MODE == "proxy":
        client = httpx.AsyncClient(headers={"User-Agent": settings.USER_AGENT})
        req = client.build_request("GET", stream_url)
        r = await client.send(req, stream=True)
        return StreamingResponse(r.aiter_raw(), media_type="application/vnd.apple.mpegurl", background=r.aclose)

    return RedirectResponse(url=stream_url, status_code=302)

@router.api_route("/streaming/timeshift.php", methods=["GET", "HEAD"])
async def timeshift_stream(
    request: Request,
    stream: str = Query(...),
    username: Optional[str] = Query(None),
    password: Optional[str] = Query(None),
    token: Optional[str] = Query(None),
    duration: Optional[int] = Query(None),
    start: Optional[str] = Query(None),
    utc: Optional[str] = Query(None)
):
    """Oficiální Xtream Codes timeshift / catchup endpoint pro TiviMate a IPTV aplikace."""
    check_auth(username=username, password=password, token=token)
    try:
        s_id = int(stream)
        ch_code = CHANNEL_STREAM_MAP.get(s_id)
    except ValueError:
        ch_code = stream.upper()

    if not ch_code or ch_code not in LIVE_CHANNELS:
        raise HTTPException(status_code=404, detail="Channel not found")

    ch = LIVE_CHANNELS[ch_code]
    req_time = start or utc or request.query_params.get("lutc")
    ts = parse_catchup_timestamp(req_time)

    if ts:
        prog = crud.get_epg_programme_by_time(ch["epg_id"], ts)
        if prog and prog.get("idec"):
            logger.info(f"Catchup Timeshift nalezen pro {ch['name']}: {prog['title']} (IDEC: {prog['idec']})")
            vod_data = await ct_service.resolve_vod_stream(prog["idec"], allow_drm=True)
            if vod_data and vod_data.get("url"):
                return RedirectResponse(url=vod_data["url"], status_code=302)

    # Fallback na živý stream
    stream_data = await ct_service.resolve_live_stream(ch_code, allow_drm=False)
    if not stream_data:
        raise HTTPException(status_code=503, detail="Unable to resolve stream")

    stream_url = stream_data.get("hls_url") or stream_data["url"]
    if settings.STREAM_MODE == "proxy":
        client = httpx.AsyncClient(headers={"User-Agent": settings.USER_AGENT})
        req = client.build_request("GET", stream_url)
        r = await client.send(req, stream=True)
        return StreamingResponse(r.aiter_raw(), media_type="application/vnd.apple.mpegurl", background=r.aclose)

    return RedirectResponse(url=stream_url, status_code=302)

@router.api_route("/movie/{token}/{stream_filename}", methods=["GET", "HEAD"])
@router.api_route("/series/{token}/{stream_filename}", methods=["GET", "HEAD"])
@router.api_route("/movie/{username}/{password}/{stream_filename}", methods=["GET", "HEAD"])
@router.api_route("/series/{username}/{password}/{stream_filename}", methods=["GET", "HEAD"])
async def vod_stream(
    stream_filename: str,
    token: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
):
    check_auth(username=username, password=password, token=token)
    idec = stream_filename.split(".")[0]
    stream_data = await ct_service.resolve_vod_stream(idec, allow_drm=True)
    if not stream_data or not stream_data.get("url"):
        raise HTTPException(status_code=404, detail="VOD stream not found or unavailable")

    stream_url = stream_data["url"]
    if settings.STREAM_MODE == "proxy":
        client = httpx.AsyncClient(headers={"User-Agent": settings.USER_AGENT})
        req = client.build_request("GET", stream_url)
        r = await client.send(req, stream=True)
        return StreamingResponse(r.aiter_raw(), media_type="application/vnd.apple.mpegurl", background=r.aclose)

    return RedirectResponse(url=stream_url, status_code=302)

# --- M3U Playlist & EPG Export ---

@router.api_route("/get.php", methods=["GET", "HEAD"])
async def get_m3u(
    request: Request,
    token: Optional[str] = Query(None),
    username: Optional[str] = Query(None),
    password: Optional[str] = Query(None),
    type: str = Query("m3u_plus")
):
    user = check_auth(username=username, password=password, token=token)
    auth_token = user.get("user_token") or token or "active"
    base_url = get_base_url(request)

    lines = [f'#EXTM3U url-tvg="{base_url}/xmltv.php?token={auth_token}"']

    # 1. Výhradně 14 oficiálních stanic České televize
    for s_id, ch_code in CHANNEL_STREAM_MAP.items():
        ch = LIVE_CHANNELS[ch_code]
        stream_url = f"{base_url}/live/{auth_token}/{s_id}.m3u8"
        logo_rel = ch.get("logo_png") or ch["logo"]
        logo_url = f"{base_url}{logo_rel}"
        catchup_src = f"{base_url}/streaming/timeshift.php?token={auth_token}&stream={s_id}&start=${{start}}&duration=${{duration}}&utc=${{start}}"
        lines.append(f'#EXTINF:-1 tvg-id="{ch["epg_id"]}" tvg-name="{ch["name"]}" tvg-logo="{logo_url}" group-title="{ch["category"]}" catchup="default" catchup-days="14" catchup-source="{catchup_src}",{ch["name"]}')
        lines.append('#KODIPROP:inputstream=inputstream.adaptive')
        lines.append('#KODIPROP:inputstream.adaptive.manifest_type=hls')
        lines.append(stream_url)

    content = "\n".join(lines)
    return PlainTextResponse(content, media_type="application/x-mpegurl", headers={"Content-Disposition": 'attachment; filename="ivysilani.m3u"'})

@router.api_route("/xmltv.php", methods=["GET", "HEAD"])
async def get_xmltv(
    request: Request,
    token: Optional[str] = Query(None),
    username: Optional[str] = Query(None),
    password: Optional[str] = Query(None)
):
    check_auth(username=username, password=password, token=token)
    base_url = get_base_url(request)
    xml_content = generate_xmltv_epg(base_url)
    return Response(content=xml_content, media_type="application/xml")
