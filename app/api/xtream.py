import time
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Request, Response, HTTPException, Query
from fastapi.responses import RedirectResponse, StreamingResponse, PlainTextResponse
import httpx

from app.core.config import settings
from app.db import crud
from app.services.ct_service import ct_service, LIVE_CHANNELS
from app.services.epg_service import generate_xmltv_epg

router = APIRouter()

def get_base_url(request: Request) -> str:
    if settings.BASE_URL:
        return settings.BASE_URL.rstrip('/')
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", f"127.0.0.1:{settings.PORT}"))
    return f"{forwarded_proto}://{forwarded_host}"

def check_auth(username: str, password: str):
    user = crud.authenticate_user(username, password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return user

# Mapping stream_id <-> channel
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
    action: Optional[str] = Query(None),
    stream_id: Optional[int] = Query(None),
    series_id: Optional[str] = Query(None),
    vod_id: Optional[str] = Query(None)
):
    # Form data fallback pro POST
    if request.method == "POST":
        form_data = await request.form()
        username = username or form_data.get("username")
        password = password or form_data.get("password")
        action = action or form_data.get("action")
        stream_id = stream_id or (int(form_data.get("stream_id")) if form_data.get("stream_id") else None)
        series_id = series_id or form_data.get("series_id")
        vod_id = vod_id or form_data.get("vod_id")

    if not username or not password:
        return {"user_info": {"auth": 0, "message": "Missing credentials"}}

    user = crud.authenticate_user(username, password)
    if not user:
        return {"user_info": {"auth": 0, "message": "Invalid username or password"}}

    base_url = get_base_url(request)
    now_ts = int(time.time())
    now_dt = datetime.fromtimestamp(now_ts, timezone.utc)

    # 1. Výchozí odpověď při přihlášení (žádná akce)
    if not action:
        exp_str = str(user.get("exp_date")) if user.get("exp_date") else None
        return {
            "user_info": {
                "username": user["username"],
                "password": password,
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
        streams = []
        for s_id, ch_code in CHANNEL_STREAM_MAP.items():
            ch = LIVE_CHANNELS[ch_code]
            cat_id = "1" if ch["category"] == "Česká televize" else "2"
            logo_url = ch["logo"]
            if logo_url.startswith("/"):
                logo_url = f"{base_url}{logo_url}"
            streams.append({
                "num": ch["num"],
                "name": ch["name"],
                "stream_type": "live",
                "stream_id": s_id,
                "stream_icon": logo_url,
                "epg_channel_id": ch["epg_id"],
                "added": str(now_ts),
                "category_id": cat_id,
                "custom_sid": "",
                "tv_archive": 1,
                "direct_source": "",
                "tv_archive_duration": 14
            })
        return streams

    # 4. VOD Kategorie
    if action == "get_vod_categories":
        genres = crud.list_genres()
        categories = [{"category_id": "all", "category_name": "Všechny pořady", "parent_id": 0}]
        for i, g in enumerate(genres, start=1):
            categories.append({"category_id": str(i), "category_name": g, "parent_id": 0})
        return categories

    # 5. VOD Seznam pořadů / filmů
    if action == "get_vod_streams":
        shows = crud.list_shows(limit=200)
        genres = crud.list_genres()
        genre_map = {g: str(i) for i, g in enumerate(genres, start=1)}

        vod_streams = []
        for idx, s in enumerate(shows, start=1):
            cat_id = genre_map.get(s["genre"], "all")
            # Pokud má pořad epizodu, použijeme její IDEC
            episodes = crud.get_episodes_by_show(s["id"])
            idec = episodes[0]["idec"] if episodes else s["id"]
            vod_streams.append({
                "num": idx,
                "name": s["title"],
                "stream_type": "movie",
                "stream_id": idec,
                "stream_icon": s["image_url"],
                "rating": "8.0",
                "rating_5based": 4.0,
                "added": str(s.get("updated_at", now_ts)),
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
        img = ep["image_url"] if ep else (show["image_url"] if show else "")
        return {
            "info": {
                "name": title,
                "title": title,
                "year": show["year"] if show else "",
                "releasedate": "",
                "genre": show["genre"] if show else "",
                "plot": desc,
                "cover_big": img,
                "movie_image": img,
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
        return [{"category_id": "1", "category_name": "Seriály a pořady ČT", "parent_id": 0}]

    if action == "get_series":
        shows = crud.list_shows(limit=200)
        series_list = []
        for idx, s in enumerate(shows, start=1):
            series_list.append({
                "num": idx,
                "name": s["title"],
                "series_id": s["id"],
                "cover": s["image_url"],
                "plot": s["description"],
                "cast": "",
                "director": "",
                "genre": s["genre"],
                "releaseDate": s["year"],
                "last_modified": str(s.get("updated_at", now_ts)),
                "rating": "8.5",
                "rating_5based": 4.2,
                "category_id": "1"
            })
        return series_list

    if action == "get_series_info":
        s_id = str(series_id)
        show = crud.get_show_by_id(s_id)
        if not show:
            return {"seasons": [], "episodes": {}}
        episodes = crud.get_episodes_by_show(s_id)

        seasons_set = set()
        episodes_by_season = {}
        for ep in episodes:
            s_num = ep.get("season", 1)
            seasons_set.add(s_num)
            if str(s_num) not in episodes_by_season:
                episodes_by_season[str(s_num)] = []
            episodes_by_season[str(s_num)].append({
                "id": ep["idec"],
                "episode_num": ep.get("episode_num", 1),
                "title": ep["title"],
                "container_extension": "m3u8",
                "info": {
                    "plot": ep.get("description", ""),
                    "duration_secs": ep.get("duration", 3600),
                    "movie_image": ep.get("image_url", show["image_url"])
                }
            })

        seasons = [{"air_date": "", "episode_count": len(episodes_by_season.get(str(sn), [])), "id": sn, "name": f"Série {sn}", "season_number": sn} for sn in sorted(seasons_set)]
        return {
            "seasons": seasons,
            "info": {
                "name": show["title"],
                "cover": show["image_url"],
                "plot": show["description"],
                "genre": show["genre"]
            },
            "episodes": episodes_by_season
        }

    return {"message": "Action not supported"}

# --- Streamovací Endpointy ---

@router.api_route("/live/{username}/{password}/{stream_filename}", methods=["GET", "HEAD"])
async def live_stream(request: Request, username: str, password: str, stream_filename: str):
    check_auth(username, password)
    # Extrakce stream_id
    stream_id_str = stream_filename.split(".")[0]
    try:
        s_id = int(stream_id_str)
        ch_code = CHANNEL_STREAM_MAP.get(s_id)
    except ValueError:
        ch_code = stream_id_str.upper()

    if not ch_code or ch_code not in LIVE_CHANNELS:
        raise HTTPException(status_code=404, detail="Channel not found")

    stream_data = await ct_service.resolve_live_stream(ch_code, allow_drm=False)
    if not stream_data or not (stream_data.get("hls_url") or stream_data.get("url")):
        raise HTTPException(status_code=503, detail="Unable to resolve live stream from ČT")

    # Pokud klient žádá timeshift (catchup)
    has_catchup = any(k in request.query_params for k in ["utc", "lutc", "timeshift", "start"])
    if has_catchup and stream_data.get("timeshift_url"):
        stream_url = stream_data["timeshift_url"]
    else:
        stream_url = stream_data.get("hls_url") or stream_data["url"]

    if settings.STREAM_MODE == "proxy":
        # Proxy mód
        client = httpx.AsyncClient(headers={"User-Agent": settings.USER_AGENT})
        req = client.build_request("GET", stream_url)
        r = await client.send(req, stream=True)
        return StreamingResponse(r.aiter_raw(), media_type="application/vnd.apple.mpegurl", background=r.aclose)

    # Výchozí rychlý 302 Redirect na ČT CDN
    return RedirectResponse(url=stream_url, status_code=302)

@router.api_route("/movie/{username}/{password}/{stream_filename}", methods=["GET", "HEAD"])
@router.api_route("/series/{username}/{password}/{stream_filename}", methods=["GET", "HEAD"])
async def vod_stream(username: str, password: str, stream_filename: str):
    check_auth(username, password)
    idec = stream_filename.split(".")[0]
    stream_data = await ct_service.resolve_vod_stream(idec)
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
    username: str = Query(...),
    password: str = Query(...),
    type: str = Query("m3u_plus")
):
    check_auth(username, password)
    base_url = get_base_url(request)

    lines = ["#EXTM3U url-tvg=\"{}/xmltv.php?username={}&password={}\"".format(base_url, username, password)]

    # 1. Živé kanály
    for s_id, ch_code in CHANNEL_STREAM_MAP.items():
        ch = LIVE_CHANNELS[ch_code]
        stream_url = f"{base_url}/live/{username}/{password}/{s_id}.m3u8"
        logo_url = ch["logo"]
        if logo_url.startswith("/"):
            logo_url = f"{base_url}{logo_url}"
        catchup_src = f"{base_url}/live/{username}/{password}/{s_id}.m3u8?utc=${{start}}&lutc=${{timestamp}}"
        lines.append(f'#EXTINF:-1 tvg-id="{ch["epg_id"]}" tvg-name="{ch["name"]}" tvg-logo="{logo_url}" group-title="{ch["category"]}" catchup="default" catchup-days="14" catchup-source="{catchup_src}",{ch["name"]}')
        # Podpora pro Kodi inputstream
        lines.append('#KODIPROP:inputstream=inputstream.adaptive')
        lines.append('#KODIPROP:inputstream.adaptive.manifest_type=hls')
        lines.append(stream_url)

    # 2. VOD pořady a epizody
    shows = crud.list_shows(limit=200)
    for s in shows:
        episodes = crud.get_episodes_by_show(s["id"])
        group = f"VOD - {s['genre']}" if s["genre"] else "VOD - iVysílání"
        for ep in episodes:
            vod_url = f"{base_url}/movie/{username}/{password}/{ep['idec']}.m3u8"
            ep_title = f"{s['title']} - {ep['title']}" if ep['title'] != s['title'] else s['title']
            lines.append(f'#EXTINF:-1 tvg-id="{ep["idec"]}" tvg-name="{ep_title}" tvg-logo="{ep["image_url"] or s["image_url"]}" group-title="{group}",{ep_title}')
            lines.append('#KODIPROP:inputstream=inputstream.adaptive')
            lines.append(vod_url)

    content = "\n".join(lines)
    return PlainTextResponse(content, media_type="application/x-mpegurl", headers={"Content-Disposition": 'attachment; filename="ivysilani.m3u"'})

@router.api_route("/xmltv.php", methods=["GET", "HEAD"])
async def get_xmltv(
    request: Request,
    username: str = Query(...),
    password: str = Query(...)
):
    check_auth(username, password)
    base_url = get_base_url(request)
    xml_content = generate_xmltv_epg(base_url)
    return Response(content=xml_content, media_type="application/xml")
