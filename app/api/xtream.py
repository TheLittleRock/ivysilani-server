import time
import logging
import base64
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional, Union, Any
from fastapi import APIRouter, Request, Response, HTTPException, Query
from fastapi.responses import RedirectResponse, StreamingResponse, PlainTextResponse, JSONResponse
import httpx

from app.core.config import settings
from app.version import __version__
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

    # 3. Klasické ověření uživatelským jménem a heslem (nebo tokenem v heslu)
    if username and password:
        user = crud.authenticate_user(username, password)
        if user:
            return user
        db_user = crud.get_user_by_username(username)
        if db_user and (db_user.get("user_token") == password or password == settings.DEFAULT_ADMIN_PASSWORD):
            return db_user

    raise HTTPException(status_code=401, detail="Invalid credentials or token")

XTREAM_VOD_CATEGORIES = [
    {"category_id": "1", "category_name": "České filmy", "genre_key": "České"},
    {"category_id": "2", "category_name": "Krimi", "genre_key": "Krimi"},
    {"category_id": "3", "category_name": "Komedie", "genre_key": "Komedie"},
    {"category_id": "4", "category_name": "Zahraniční", "genre_key": "Zahraniční"},
    {"category_id": "5", "category_name": "Pohádky", "genre_key": "Pohádky"},
    {"category_id": "6", "category_name": "Psychologické", "genre_key": "Psychologické"},
    {"category_id": "7", "category_name": "Historické", "genre_key": "Historické"},
    {"category_id": "8", "category_name": "Rodinné", "genre_key": "Rodinné"},
    {"category_id": "9", "category_name": "Klasika", "genre_key": "Klasika"},
    {"category_id": "10", "category_name": "Drama", "genre_key": "Drama"},
    {"category_id": "11", "category_name": "Romantické", "genre_key": "Romantické"},
    {"category_id": "12", "category_name": "Životopisné", "genre_key": "Životopisné"},
    {"category_id": "13", "category_name": "Thriller", "genre_key": "Thriller"},
    {"category_id": "14", "category_name": "Animované", "genre_key": "Animované"},
    {"category_id": "15", "category_name": "Literární adaptace", "genre_key": "Literární adaptace"},
    {"category_id": "16", "category_name": "Válečné", "genre_key": "Válečné"},
    {"category_id": "17", "category_name": "Studentské", "genre_key": "Studentské"},
    {"category_id": "18", "category_name": "Dokumentární filmy", "genre_key": "Dokument"}
]

XTREAM_SERIES_CATEGORIES = [
    {"category_id": "1", "category_name": "České seriály", "genre_key": "České"},
    {"category_id": "2", "category_name": "Krimi seriály", "genre_key": "Krimi"},
    {"category_id": "3", "category_name": "Komedie", "genre_key": "Komedie"},
    {"category_id": "4", "category_name": "Zahraniční seriály", "genre_key": "Zahraniční"},
    {"category_id": "5", "category_name": "Rodinné", "genre_key": "Rodinné"},
    {"category_id": "6", "category_name": "Psychologické", "genre_key": "Psychologické"},
    {"category_id": "7", "category_name": "Historické", "genre_key": "Historické"},
    {"category_id": "8", "category_name": "Klasika", "genre_key": "Klasika"},
    {"category_id": "9", "category_name": "Thrillery", "genre_key": "Thrillery"},
    {"category_id": "10", "category_name": "Literární adaptace", "genre_key": "Literární adaptace"},
    {"category_id": "11", "category_name": "Studentské", "genre_key": "Studentské"},
    {"category_id": "12", "category_name": "Dokumentární cykly", "genre_key": "Dokument"},
    {"category_id": "13", "category_name": "Zábava & Soutěže", "genre_key": "Zábava"},
    {"category_id": "14", "category_name": "Pro děti & Večerníček", "genre_key": "Děti"},
    {"category_id": "15", "category_name": "Zpravodajství & Publicistika", "genre_key": "Zpravodaj"}
]

VOD_STEM_MAP = {
    "18": ["dokument", "publicist"],
    "14": ["animov"],
    "5":  ["pohád"],
    "2":  ["krimi", "detektiv"],
    "3":  ["komed"],
    "13": ["thriller"],
    "16": ["váleč", "válk"],
    "17": ["student", "famu"],
    "7":  ["histor"],
    "12": ["životopis", "biograf"],
    "11": ["romant"],
    "6":  ["psycholog"],
    "8":  ["rodin"],
    "9":  ["klasik"],
    "10": ["drama"],
    "4":  ["zahranič"],
    "1":  ["česk"],
}

SERIES_STEM_MAP = {
    "15": ["zpravodaj", "politika", "zprávy", "události", "počasí"],
    "14": ["dět", "večerníč", "animov", "pohád"],
    "13": ["zábav", "talk show", "soutěž", "hudeb", "reality"],
    "12": ["dokument", "publicist", "příroda", "věda"],
    "11": ["student", "famu"],
    "2":  ["krimi", "detektiv"],
    "3":  ["komed"],
    "9":  ["thriller"],
    "7":  ["histor"],
    "6":  ["psycholog"],
    "5":  ["rodin"],
    "8":  ["klasik"],
    "4":  ["zahranič"],
    "1":  ["česk"],
}

def resolve_vod_category_id(genre_str: str) -> str:
    g = (genre_str or "").lower()
    for cat_id, stems in VOD_STEM_MAP.items():
        if any(s in g for s in stems):
            return cat_id
    return "1"

def resolve_series_category_id(genre_str: str) -> str:
    g = (genre_str or "").lower()
    for cat_id, stems in SERIES_STEM_MAP.items():
        if any(s in g for s in stems):
            return cat_id
    return "1"

def to_int_id(val: Any, fallback: int = 1) -> int:
    try:
        s = str(val).split("-")[0].split("_")[0]
        return int(s)
    except (ValueError, TypeError):
        return fallback

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

@router.api_route("/player_api.php", methods=["GET", "POST", "HEAD"])
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
        tz_prague = ZoneInfo("Europe/Prague")
        now_dt_prague = datetime.fromtimestamp(now_ts, tz_prague)

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
                    "time_now": now_dt_prague.strftime("%Y-%m-%d %H:%M:%S"),
                    "timestamp_now": now_ts,
                    "version": __version__
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

        # 3b. EPG pro kanály (Xtream get_simple_data_table / get_epg / get_short_epg)
        if action in ["get_simple_data_table", "get_epg", "get_short_epg"]:
            stream_id_req = request.query_params.get("stream_id") or stream_id
            if not stream_id_req:
                return {"epg_listings": []}
            try:
                s_id = int(stream_id_req)
                ch_code = CHANNEL_STREAM_MAP.get(s_id)
            except ValueError:
                ch_code = str(stream_id_req).upper()

            if not ch_code or ch_code not in LIVE_CHANNELS:
                return {"epg_listings": []}

            ch = LIVE_CHANNELS[ch_code]
            epg_id = ch["epg_id"]

            limit_val = 10 if action == "get_short_epg" else None
            req_limit = request.query_params.get("limit")
            if req_limit:
                try:
                    limit_val = int(req_limit)
                except ValueError:
                    pass

            with crud.get_db() as conn:
                cursor = conn.cursor()
                min_ts = now_ts - (14 * 86400)
                if limit_val:
                    cursor.execute("""
                    SELECT * FROM epg_programmes
                    WHERE channel_id = ? AND end_ts >= ?
                    ORDER BY start_ts ASC LIMIT ?
                    """, (epg_id, now_ts - 3600, limit_val))
                else:
                    cursor.execute("""
                    SELECT * FROM epg_programmes
                    WHERE channel_id = ? AND start_ts >= ?
                    ORDER BY start_ts ASC
                    """, (epg_id, min_ts))
                progs = cursor.fetchall()

            epg_listings = []
            for p in progs:
                start_dt = datetime.fromtimestamp(p["start_ts"], tz_prague)
                end_dt = datetime.fromtimestamp(p["end_ts"], tz_prague)
                t_b64 = base64.b64encode((p["title"] or "").encode("utf-8")).decode("utf-8")
                d_b64 = base64.b64encode((p["description"] or "").encode("utf-8")).decode("utf-8")
                now_playing = 1 if (p["start_ts"] <= now_ts <= p["end_ts"]) else 0
                has_archive = 1 if (now_ts - p["start_ts"] <= 14 * 86400) else 0

                epg_listings.append({
                    "id": p["id"],
                    "epg_id": p["channel_id"],
                    "title": t_b64,
                    "lang": "cs",
                    "start": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "end": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "description": d_b64,
                    "channel_id": str(stream_id_req),
                    "start_timestamp": str(p["start_ts"]),
                    "stop_timestamp": str(p["end_ts"]),
                    "now_playing": now_playing,
                    "has_archive": has_archive
                })

            return {"epg_listings": epg_listings}

        # 4. VOD Kategorie (Filmy)
        if action == "get_vod_categories":
            return [
                {"category_id": c["category_id"], "category_name": c["category_name"], "parent_id": 0}
                for c in XTREAM_VOD_CATEGORIES
            ]

        # 5. VOD Seznam (Pouze celovečerní filmy - optimalizovaný jeden dotaz bez 502 limitu)
        if action == "get_vod_streams":
            genre_filter = None
            if category_id:
                for c in XTREAM_VOD_CATEGORIES:
                    if str(c["category_id"]) == str(category_id):
                        genre_filter = c["genre_key"]
                        break

            movies = crud.list_playable_movies_with_idec(genre=genre_filter)
            vod_streams = []
            for idx, m in enumerate(movies, start=1):
                cat_id = resolve_vod_category_id(m.get("genre", ""))
                idec = m.get("idec") or m["id"]
                poster_raw = m.get("tmdb_poster") or m.get("poster_url") or m.get("image_url")
                poster_url = image_proxy.build_proxy_url(base_url, poster_raw, pad="2x3")

                vod_streams.append({
                    "num": idx,
                    "name": m["title"],
                    "stream_type": "movie",
                    "stream_id": to_int_id(idec, idx),
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
            ep = crud.get_episode_by_id_or_idec(idec)
            show = crud.get_show_by_id(idec) if not ep else crud.get_show_by_id(ep["show_id"])
            if not ep and show:
                eps = crud.get_episodes_by_show(show["id"])
                if eps:
                    ep = eps[0]
                    idec = ep["idec"]

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
                    "stream_id": to_int_id(idec, 1),
                    "name": title,
                    "container_extension": "m3u8"
                }
            }

        # 7. Seriály kategorie & seznam
        if action == "get_series_categories":
            return [
                {"category_id": c["category_id"], "category_name": c["category_name"], "parent_id": 0}
                for c in XTREAM_SERIES_CATEGORIES
            ]

        if action == "get_series":
            genre_filter = None
            if category_id:
                for c in XTREAM_SERIES_CATEGORIES:
                    if str(c["category_id"]) == str(category_id):
                        genre_filter = c["genre_key"]
                        break

            shows = crud.list_series(genre=genre_filter, only_playable=True, limit=None)
            series_list = []
            for idx, s in enumerate(shows, start=1):
                cat_id = resolve_series_category_id(s.get("genre", ""))
                cover_raw = s.get("tmdb_poster") or s.get("poster_url") or s.get("image_url")
                cover_proxy = image_proxy.build_proxy_url(base_url, cover_raw, pad="2x3")
                backdrop_proxy = image_proxy.build_proxy_url(base_url, s.get("tmdb_backdrop") or s.get("backdrop_url") or cover_raw)

                series_list.append({
                    "num": idx,
                    "name": s["title"],
                    "series_id": to_int_id(s["id"], idx),
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
            s_id_clean = s_id.split("-")[0]
            show = crud.get_show_by_id(s_id) or crud.get_show_by_id(s_id_clean)
            if not show:
                try:
                    show = await ct_service.scrape_show_metadata(s_id) or await ct_service.scrape_show_metadata(s_id_clean)
                except Exception:
                    pass
            if not show:
                return {"seasons": [], "episodes": {}}

            actual_id = show.get("id") or s_id_clean
            episodes = crud.get_episodes_by_show(actual_id)
            if not episodes and actual_id != s_id:
                episodes = crud.get_episodes_by_show(s_id)
            playable_episodes = [ep for ep in episodes if ep.get("is_playable", 1)]

            # Automatické dohledání a rozdělení do sérií podle TMDB (pokud má pořad v iVysílání jen 1 sérii)
            existing_seasons = set(ep.get("season", 1) for ep in episodes)
            if len(existing_seasons) <= 1 and len(playable_episodes) >= 4:
                try:
                    from app.services.tmdb_service import tmdb_service
                    align_res = await tmdb_service.align_show_episodes(actual_id, show.get("tmdb_id"))
                    if align_res.get("status") == "ok" and align_res.get("matched", 0) > 0:
                        episodes = crud.get_episodes_by_show(actual_id)
                        if not episodes and actual_id != s_id:
                            episodes = crud.get_episodes_by_show(s_id)
                        playable_episodes = [ep for ep in episodes if ep.get("is_playable", 1)]
                except Exception as e:
                    logger.debug(f"On-demand TMDB alignment skipped for {actual_id}: {e}")

            seasons_set = set()
            episodes_by_season = {}
            for ep in playable_episodes:
                raw_sn = ep.get("season")
                if raw_sn is not None:
                    try:
                        s_num = int(raw_sn)
                    except (ValueError, TypeError):
                        s_num = 1
                else:
                    s_num = 1

                raw_ep_num = ep.get("episode_num")
                if raw_ep_num is not None:
                    try:
                        ep_num = int(raw_ep_num)
                    except (ValueError, TypeError):
                        ep_num = 1
                else:
                    ep_num = 1

                seasons_set.add(s_num)
                sn_key = str(s_num)
                if sn_key not in episodes_by_season:
                    episodes_by_season[sn_key] = []
                
                ep_img_raw = ep.get("image_url") or show.get("poster_url") or show.get("image_url")
                ep_img_proxy = image_proxy.build_proxy_url(base_url, ep_img_raw)
                ep_title = ep.get("title") or f"Epizoda {ep_num}"
                ep_id_int = to_int_id(ep["idec"], ep_num)

                episodes_by_season[sn_key].append({
                    "id": ep_id_int,
                    "episode_num": ep_num,
                    "title": ep_title,
                    "container_extension": "m3u8",
                    "season": s_num,
                    "season_num": s_num,
                    "season_number": s_num,
                    "info": {
                        "name": ep_title,
                        "season": s_num,
                        "season_num": s_num,
                        "season_number": s_num,
                        "episode_num": ep_num,
                        "plot": ep.get("description", ""),
                        "duration_secs": ep.get("duration", 3600),
                        "duration": f"{ep.get('duration', 3600) // 60}:00",
                        "movie_image": ep_img_proxy
                    },
                    "custom_sid": "",
                    "added": str(now_ts),
                    "direct_source": ""
                })

            # Normalizace episode_num v rámci každé série pro Xtream Codes:
            # Zabraňuje posunu čísel dílů napříč sériemi (např. Čtyřlístek S01 4..10 -> 1..7, S02 11..16 -> 1..6)
            for sn_key, s_eps in episodes_by_season.items():
                if not s_eps:
                    continue
                s_eps.sort(key=lambda x: (x.get("episode_num", 0), str(x.get("id", ""))))
                nums = [e["episode_num"] for e in s_eps]
                if min(nums, default=1) > 1 or len(set(nums)) < len(nums):
                    for i, e in enumerate(s_eps, start=1):
                        e["episode_num"] = i
                        if "info" in e and isinstance(e["info"], dict):
                            e["info"]["episode_num"] = i

            cover_url = image_proxy.build_proxy_url(base_url, show.get("poster_url") or show.get("image_url"), pad="2x3")
            backdrop_url = image_proxy.build_proxy_url(base_url, show.get("backdrop_url") or show.get("poster_url") or show.get("image_url"))

            seasons = []
            for sn in sorted(seasons_set):
                seasons.append({
                    "air_date": "",
                    "episode_count": len(episodes_by_season.get(str(sn), [])),
                    "id": sn,
                    "name": f"Série {sn}" if sn > 0 else "Speciály",
                    "season_number": sn,
                    "cover": cover_url,
                    "cover_big": cover_url
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
    """Parsuje časové razítko z různých formátů IPTV klientů (Unix ts, ISO, YYYYmmddHHMMSS, YYYY-MM-DD:HH-MM)."""
    if not raw_time:
        return None
    raw = str(raw_time).strip()
    if not raw or raw.startswith("${"):
        return None
    tz_prague = ZoneInfo("Europe/Prague")
    try:
        # Čistá čísla (Unix ts nebo formáty YYYYMMDDHHMMSS / YYYYMMDDHHMM)
        if raw.isdigit():
            val = int(raw)
            if len(raw) == 14:  # YYYYmmddHHMMSS
                dt = datetime.strptime(raw, "%Y%m%d%H%M%S").replace(tzinfo=tz_prague)
                return int(dt.timestamp())
            if len(raw) == 12:  # YYYYmmddHHMM
                dt = datetime.strptime(raw, "%Y%m%d%H%M").replace(tzinfo=tz_prague)
                return int(dt.timestamp())
            if val > 100_000_000_000:  # Milisekundy
                return val // 1000
            return val

        # TiviMate / XC timeshift formát: YYYY-MM-DD:HH-MM nebo YYYY-MM-DD:HH-MM-SS nebo s mezerou
        import re
        m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})[: ](\d{1,2})[-:](\d{1,2})(?:[-:](\d{1,2}))?$", raw)
        if m:
            y, mo, d, h, mi, s = m.groups()
            dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0), tzinfo=tz_prague)
            return int(dt.timestamp())

        # ISO formáty
        if "T" in raw or "-" in raw:
            iso_str = raw.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz_prague)
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
            forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
            forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", f"127.0.0.1:{settings.PORT}"))
            base_url = f"{forwarded_proto}://{forwarded_host}"
            return RedirectResponse(url=f"{base_url}/api/hls/master/{prog['idec']}.m3u8", status_code=302)

        # Fallback na ČT unencrypted HbbTV timeshift stream
        stream_data = await ct_service.resolve_live_stream(ch_code, allow_drm=False)
        if stream_data and stream_data.get("timeshift_url"):
            ts_url = stream_data["timeshift_url"]
            join_char = "&" if "?" in ts_url else "?"
            return RedirectResponse(url=f"{ts_url}{join_char}start={ts}&duration=3600", status_code=302)

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
    duration: Optional[str] = Query(None),
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

    # Bezpečný výpočet délky
    dur_secs = 3600
    if duration and not duration.startswith("${"):
        try:
            dur_val = int(float(duration))
            if dur_val > 0:
                dur_secs = dur_val * 60 if dur_val < 300 else dur_val
        except Exception:
            dur_secs = 3600

    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", f"127.0.0.1:{settings.PORT}"))
    base_url = f"{forwarded_proto}://{forwarded_host}"

    if ts:
        prog = crud.get_epg_programme_by_time(ch["epg_id"], ts)
        if prog and prog.get("idec"):
            logger.info(f"Catchup Timeshift nalezen pro {ch['name']}: {prog['title']} (IDEC: {prog['idec']})")
            return RedirectResponse(url=f"{base_url}/api/hls/master/{prog['idec']}.m3u8", status_code=302)

    # Fallback na ČT živý / timeshift HLS stream
    stream_data = await ct_service.resolve_live_stream(ch_code, allow_drm=False)
    if not stream_data:
        raise HTTPException(status_code=503, detail="Unable to resolve stream")

    stream_url = stream_data.get("timeshift_url") or stream_data.get("hls_url") or stream_data["url"]
    if ts and "timeshift" in stream_url:
        join_char = "&" if "?" in stream_url else "?"
        stream_url += f"{join_char}start={ts}&duration={dur_secs}"

    return RedirectResponse(url=stream_url, status_code=302)

@router.api_route("/timeshift/{username}/{password}/{duration}/{start}/{stream_filename}", methods=["GET", "HEAD"])
@router.api_route("/timeshift/{token}/{duration}/{start}/{stream_filename}", methods=["GET", "HEAD"])
async def timeshift_direct_stream(
    request: Request,
    stream_filename: str,
    duration: str,
    start: str,
    token: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
):
    """Přímý Xtream Codes Timeshift/Catch-up endpoint pro IPTVnator, TiviMate a další přehrávače."""
    check_auth(username=username, password=password, token=token)
    stream_id_str = stream_filename.split(".")[0]
    try:
        s_id = int(stream_id_str)
        ch_code = CHANNEL_STREAM_MAP.get(s_id)
    except ValueError:
        ch_code = stream_id_str.upper()

    if not ch_code or ch_code not in LIVE_CHANNELS:
        raise HTTPException(status_code=404, detail="Channel not found")

    ch = LIVE_CHANNELS[ch_code]
    ts = parse_catchup_timestamp(start)
    if not ts:
        logger.warning(f"Timeshift start time could not be parsed: {start}")
        ts = int(time.time()) - 3600

    dur_secs = 3600
    try:
        dur_val = int(float(duration))
        if dur_val > 0:
            dur_secs = dur_val * 60 if dur_val < 300 else dur_val
    except Exception:
        dur_secs = 3600

    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", f"127.0.0.1:{settings.PORT}"))
    base_url = f"{forwarded_proto}://{forwarded_host}"

    # 1. Look up EPG programme by time for VOD playback
    prog = crud.get_epg_programme_by_time(ch["epg_id"], ts)
    if prog and prog.get("idec"):
        logger.info(f"Timeshift direct VOD match found for {ch['name']}: {prog['title']} (IDEC: {prog['idec']})")
        return RedirectResponse(url=f"{base_url}/api/hls/master/{prog['idec']}.m3u8", status_code=302)

    # 2. Fallback na ČT unencrypted HbbTV timeshift stream
    stream_data = await ct_service.resolve_live_stream(ch_code, allow_drm=False)
    if not stream_data or not stream_data.get("timeshift_url"):
        raise HTTPException(status_code=503, detail="Timeshift stream not available")

    ts_url = stream_data["timeshift_url"]
    join_char = "&" if "?" in ts_url else "?"
    return RedirectResponse(url=f"{ts_url}{join_char}start={ts}&duration={dur_secs}", status_code=302)

@router.api_route("/movie/{token}/{stream_filename}", methods=["GET", "HEAD"])
@router.api_route("/series/{token}/{stream_filename}", methods=["GET", "HEAD"])
@router.api_route("/movie/{username}/{password}/{stream_filename}", methods=["GET", "HEAD"])
@router.api_route("/series/{username}/{password}/{stream_filename}", methods=["GET", "HEAD"])
async def vod_stream(
    request: Request,
    stream_filename: str,
    token: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    quality: Optional[str] = Query(None)
):
    check_auth(username=username, password=password, token=token)
    idec = stream_filename.split(".")[0]
    
    # Ověříme, zda idec není show_id nebo episode_id
    ep = crud.get_episode_by_id_or_idec(idec)
    if ep:
        idec = ep["idec"]
    else:
        show = crud.get_show_by_id(idec)
        if show:
            eps = crud.get_episodes_by_show(show["id"])
            if eps:
                idec = eps[0]["idec"]

    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", f"127.0.0.1:{settings.PORT}"))
    base_url = f"{forwarded_proto}://{forwarded_host}"

    master_url = f"{base_url}/api/hls/master/{idec}.m3u8?xtream=1"
    if quality:
        master_url += f"&quality={quality}"
    return RedirectResponse(url=master_url, status_code=302)

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
