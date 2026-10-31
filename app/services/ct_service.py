import time
import re
import json
import logging
from typing import Dict, List, Optional, Any
import httpx
from bs4 import BeautifulSoup

from app.core.config import settings

logger = logging.getLogger("ct_service")

# 14 oficiálních stanic České televize
LIVE_CHANNELS = {
    "CH_1": {
        "id": "CH_1", "channel_code": "1", "name": "ČT1", "num": 1,
        "category": "Česká televize", "epg_id": "ct1.cz",
        "logo": "/static/logos/ct1.svg",
        "logo_png": "/static/logos/ct1.png",
        "poster": "/static/logos/ct1_poster.png",
        "description": "Hlavní program České televize – rodinná televize, seriály, zábava, zprávy."
    },
    "CH_2": {
        "id": "CH_2", "channel_code": "2", "name": "ČT2", "num": 2,
        "category": "Česká televize", "epg_id": "ct2.cz",
        "logo": "/static/logos/ct2.svg",
        "logo_png": "/static/logos/ct2.png",
        "poster": "/static/logos/ct2_poster.png",
        "description": "Dokumenty, příroda, historie, kvalitní filmová tvorba a publicistika."
    },
    "CH_24": {
        "id": "CH_24", "channel_code": "24", "name": "ČT24", "num": 3,
        "category": "Česká televize", "epg_id": "ct24.cz",
        "logo": "/static/logos/ct24.svg",
        "logo_png": "/static/logos/ct24.png",
        "poster": "/static/logos/ct24_poster.png",
        "description": "Nepřetržité 24hodinové zpravodajství a aktuální publicistika."
    },
    "CH_4": {
        "id": "CH_4", "channel_code": "4", "name": "ČT sport", "num": 4,
        "category": "Česká televize", "epg_id": "ctsport.cz",
        "logo": "/static/logos/ctsport.svg",
        "logo_png": "/static/logos/ctsport.png",
        "poster": "/static/logos/ctsport_poster.png",
        "description": "Český a mezinárodní sport, přímé přenosy a sportovní magazíny."
    },
    "CH_5": {
        "id": "CH_5", "channel_code": "5", "name": "ČT :D", "num": 5,
        "category": "Česká televize", "epg_id": "ctd.cz",
        "logo": "/static/logos/ctd.svg",
        "logo_png": "/static/logos/ctd.png",
        "poster": "/static/logos/ctd_poster.png",
        "description": "Dětský kanál Déčko pro děti od 4 do 12 let. Pohádky, vzdělávání a animované filmy."
    },
    "CH_6": {
        "id": "CH_6", "channel_code": "6", "name": "ČT art", "num": 6,
        "category": "Česká televize", "epg_id": "ctart.cz",
        "logo": "/static/logos/ctart.svg",
        "logo_png": "/static/logos/ctart.png",
        "poster": "/static/logos/ctart_poster.png",
        "description": "Kulturní a umělecký kanál ČT – divadlo, hudba, výtvarné umění a filmy."
    },
    "CH_25": {
        "id": "CH_25", "channel_code": "25", "name": "ČT sport Plus 1", "num": 7,
        "category": "ČT sport Plus", "epg_id": "ctsportplus1.cz",
        "logo": "/static/logos/ctsportplus.svg",
        "logo_png": "/static/logos/ctsportplus.png",
        "poster": "/static/logos/ctsportplus1_poster.png",
        "description": "Internetový sportovní přenos ČT sport Plus 1."
    },
    "CH_26": {
        "id": "CH_26", "channel_code": "26", "name": "ČT sport Plus 2", "num": 8,
        "category": "ČT sport Plus", "epg_id": "ctsportplus2.cz",
        "logo": "/static/logos/ctsportplus.svg",
        "logo_png": "/static/logos/ctsportplus.png",
        "poster": "/static/logos/ctsportplus2_poster.png",
        "description": "Internetový sportovní přenos ČT sport Plus 2."
    },
    "CH_27": {
        "id": "CH_27", "channel_code": "27", "name": "ČT sport Plus 3", "num": 9,
        "category": "ČT sport Plus", "epg_id": "ctsportplus3.cz",
        "logo": "/static/logos/ctsportplus.svg",
        "logo_png": "/static/logos/ctsportplus.png",
        "poster": "/static/logos/ctsportplus3_poster.png",
        "description": "Internetový sportovní přenos ČT sport Plus 3."
    },
    "CH_28": {
        "id": "CH_28", "channel_code": "28", "name": "ČT sport Plus 4", "num": 10,
        "category": "ČT sport Plus", "epg_id": "ctsportplus4.cz",
        "logo": "/static/logos/ctsportplus.svg",
        "logo_png": "/static/logos/ctsportplus.png",
        "poster": "/static/logos/ctsportplus4_poster.png",
        "description": "Internetový sportovní přenos ČT sport Plus 4."
    },
    "CH_29": {
        "id": "CH_29", "channel_code": "29", "name": "ČT sport Plus 5", "num": 11,
        "category": "ČT sport Plus", "epg_id": "ctsportplus5.cz",
        "logo": "/static/logos/ctsportplus.svg",
        "logo_png": "/static/logos/ctsportplus.png",
        "poster": "/static/logos/ctsportplus5_poster.png",
        "description": "Internetový sportovní přenos ČT sport Plus 5."
    },
    "CH_30": {
        "id": "CH_30", "channel_code": "30", "name": "ČT sport Plus 6", "num": 12,
        "category": "ČT sport Plus", "epg_id": "ctsportplus6.cz",
        "logo": "/static/logos/ctsportplus.svg",
        "logo_png": "/static/logos/ctsportplus.png",
        "poster": "/static/logos/ctsportplus6_poster.png",
        "description": "Internetový sportovní přenos ČT sport Plus 6."
    },
    "CH_31": {
        "id": "CH_31", "channel_code": "31", "name": "ČT sport Plus 7", "num": 13,
        "category": "ČT sport Plus", "epg_id": "ctsportplus7.cz",
        "logo": "/static/logos/ctsportplus.svg",
        "logo_png": "/static/logos/ctsportplus.png",
        "poster": "/static/logos/ctsportplus7_poster.png",
        "description": "Internetový sportovní přenos ČT sport Plus 7."
    },
    "CH_32": {
        "id": "CH_32", "channel_code": "32", "name": "ČT sport Plus 8", "num": 14,
        "category": "ČT sport Plus", "epg_id": "ctsportplus8.cz",
        "logo": "/static/logos/ctsportplus.svg",
        "logo_png": "/static/logos/ctsportplus.png",
        "poster": "/static/logos/ctsportplus8_poster.png",
        "description": "Internetový sportovní přenos ČT sport Plus 8."
    }
}

CHANNEL_KEY_MAP = {
    "ct1": "CH_1", "1": "CH_1", "ch_1": "CH_1", "CH_1": "CH_1",
    "ct2": "CH_2", "2": "CH_2", "ch_2": "CH_2", "CH_2": "CH_2",
    "ct24": "CH_24", "24": "CH_24", "ch_24": "CH_24", "CH_24": "CH_24",
    "ctsport": "CH_4", "sport": "CH_4", "4": "CH_4", "ch_4": "CH_4", "CH_4": "CH_4",
    "ctd": "CH_5", "decko": "CH_5", "5": "CH_5", "ch_5": "CH_5", "CH_5": "CH_5",
    "ctart": "CH_6", "art": "CH_6", "6": "CH_6", "ch_6": "CH_6", "CH_6": "CH_6",
    "ct3": "CH_7", "3": "CH_7", "ch_7": "CH_7", "CH_7": "CH_7",
    "ctsportplus1": "CH_25", "i25": "CH_25", "25": "CH_25", "ch_25": "CH_25", "CH_25": "CH_25",
    "ctsportplus2": "CH_26", "i26": "CH_26", "26": "CH_26", "ch_26": "CH_26", "CH_26": "CH_26",
    "ctsportplus3": "CH_27", "i27": "CH_27", "27": "CH_27", "ch_27": "CH_27", "CH_27": "CH_27",
    "ctsportplus4": "CH_28", "i28": "CH_28", "28": "CH_28", "ch_28": "CH_28", "CH_28": "CH_28",
    "ctsportplus5": "CH_29", "i29": "CH_29", "29": "CH_29", "ch_29": "CH_29", "CH_29": "CH_29",
    "ctsportplus6": "CH_30", "i30": "CH_30", "30": "CH_30", "ch_30": "CH_30", "CH_30": "CH_30",
    "ctsportplus7": "CH_31", "i31": "CH_31", "31": "CH_31", "ch_31": "CH_31", "CH_31": "CH_31",
    "ctsportplus8": "CH_32", "i32": "CH_32", "32": "CH_32", "ch_32": "CH_32", "CH_32": "CH_32",
}

def parse_season_number(title: str, default: int = 1) -> int:
    """Extrahuje číslo řady z popisku např. 'I. řada', '2. série', 'XIII. řada'."""
    if not title:
        return default
    m_num = re.search(r"\b(\d+)\b", title)
    if m_num:
        return int(m_num.group(1))
    m_roman = re.search(r"\b([IVXLC]+)\b", title.upper())
    if m_roman:
        roman_map = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
        clean = m_roman.group(1)
        total, prev = 0, 0
        for c in reversed(clean):
            val = roman_map.get(c, 0)
            if val < prev:
                total -= val
            else:
                total += val
                prev = val
        return max(1, total)
    return default

def parse_episode_number(title: str, default: int = 1) -> int:
    """Extrahuje číslo dílu z názvu např. '1/26 Od začátku', 'Díl 5' apod."""
    if not title:
        return default
    m_slash = re.search(r"^(\d+)\s*/\s*\d+", title)
    if m_slash:
        return int(m_slash.group(1))
    m_num = re.search(r"\b(?:díl|epizoda|část)?\s*(\d+)\b", title, re.IGNORECASE)
    if m_num:
        return int(m_num.group(1))
    return default

class CTService:
    def __init__(self):
        self._headers = {
            "User-Agent": settings.USER_AGENT,
            "Origin": "https://www.ceskatelevize.cz",
            "Referer": "https://www.ceskatelevize.cz/",
            "Accept": "application/json, text/plain, */*"
        }
        self._cache = {}

    def _extract_subtitles(self, raw_subs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalizuje seznam titulků a extrahuje přímý WebVTT odkaz."""
        subtitles = []
        if not raw_subs:
            return subtitles
        for s in raw_subs:
            files = s.get("files", [])
            vtt_file = next((f["url"] for f in files if f.get("format") == "vtt"), None)
            if not vtt_file and files:
                vtt_file = files[0].get("url")
            if vtt_file:
                subtitles.append({
                    "language": s.get("language", "ces"),
                    "label": "Čeština" if s.get("language") in ["ces", "cze", "cs"] else s.get("language"),
                    "url": vtt_file
                })
        return subtitles

    async def resolve_live_stream(self, ch_key: str, allow_drm: bool = True) -> Optional[Dict[str, Any]]:
        """Získá aktuální manifest živého vysílání (HbbTV unencrypted HLS s fallbackem/doplněním na DASH Widevine)."""
        norm_key = CHANNEL_KEY_MAP.get(ch_key.lower(), ch_key)
        cached = self._cache.get(f"live_{norm_key}")
        if cached and cached["expiry"] > time.time():
            return cached["data"]

        # 1. HbbTV profil - poskytuje neblokovaný, nešifrovaný 1080p HLS stream
        hbbtv_url = f"https://api.ceskatelevize.cz/video/v1/playlist-live/v1/stream-data/channel/{norm_key}?streamType=hls&origin=hbbtv&canPlayDrm=false"
        # 2. DASH Widevine stream pro prohlížeč/Shaka
        dash_url = f"https://api.ceskatelevize.cz/video/v1/playlist-live/v1/stream-data/channel/{norm_key}?canPlayDrm=true&quality=web&streamType=dash"

        try:
            async with httpx.AsyncClient(headers=self._headers, timeout=10.0) as client:
                hls_resp = await client.get(hbbtv_url)
                dash_resp = await client.get(dash_url)

                hls_data = hls_resp.json() if hls_resp.status_code == 200 else {}
                dash_data = dash_resp.json() if dash_resp.status_code == 200 else {}

                hls_main = hls_data.get("streamUrls", {}).get("main")
                timeshift_url = hls_data.get("streamUrls", {}).get("timeshift")
                dash_main = dash_data.get("streamUrls", {}).get("main")

                if not hls_main and not dash_main:
                    return None

                is_drm = False
                if dash_main and ("drmOnly=true" in dash_main or dash_data.get("streamUrls", {}).get("encryption") == "wv"):
                    is_drm = True

                result = {
                    "channel_id": norm_key,
                    "title": hls_data.get("title") or dash_data.get("title") or LIVE_CHANNELS.get(norm_key, {}).get("name", "ČT"),
                    "url": hls_main or dash_main,
                    "hls_url": hls_main,
                    "dash_url": dash_main,
                    "timeshift_url": timeshift_url,
                    "is_drm": is_drm,
                    "manifest_type": "hls" if hls_main else "mpd",
                    "qualities": hls_data.get("availableQualities") or dash_data.get("availableQualities", []),
                    "audio_tracks": hls_data.get("audioTracks") or dash_data.get("audioTracks", []),
                    "subtitles": self._extract_subtitles(hls_data.get("subtitles") or dash_data.get("subtitles", []))
                }
                self._cache[f"live_{norm_key}"] = {
                    "data": result,
                    "expiry": time.time() + 1800
                }
                return result
        except Exception as e:
            logger.error(f"Error resolving live stream for {norm_key}: {e}")
            return None

    async def get_live_epg_now(self) -> Dict[str, Dict[str, Any]]:
        """Vrátí aktuální a následující pořad pro všechny živé stanice z ČT GraphQL."""
        cached = self._cache.get("live_epg_now")
        if cached and cached["expiry"] > time.time():
            return cached["data"]

        url = "https://api.ceskatelevize.cz/graphql/"
        params = {"client": "iVysilaniWeb", "version": "1.131.1", "use-new-playability": "true"}
        query = """
        query LiveBroadcastFind {
          liveBroadcastFind {
            id
            slug
            current {
              id
              idec
              title
              description
              startsAt
              endsAt
            }
            next {
              id
              idec
              title
              description
              startsAt
              endsAt
            }
          }
        }
        """
        result = {}
        try:
            async with httpx.AsyncClient(headers=self._headers, timeout=5.0) as client:
                r = await client.post(url, params=params, json={"operationName": "LiveBroadcastFind", "variables": {}, "query": query})
                if r.status_code == 200:
                    data = r.json()
                    items = data.get("data", {}).get("liveBroadcastFind", [])
                    slug_map = {
                        "ct1": "CH_1",
                        "ct2": "CH_2",
                        "ct24": "CH_24",
                        "ct-sport": "CH_4",
                        "ct-d": "CH_5",
                        "ct-art": "CH_6",
                        "ct-sport-plus-1": "CH_25",
                        "ct-sport-plus-2": "CH_26",
                        "ct-sport-plus-3": "CH_27",
                        "ct-sport-plus-4": "CH_28",
                        "ct-sport-plus-5": "CH_29",
                        "ct-sport-plus-6": "CH_30",
                        "ct-sport-plus-7": "CH_31",
                        "ct-sport-plus-8": "CH_32"
                    }
                    for item in items:
                        slug = item.get("slug")
                        ch_key = slug_map.get(slug)
                        if ch_key:
                            result[ch_key] = {
                                "current": item.get("current"),
                                "next": item.get("next")
                            }
                    self._cache["live_epg_now"] = {"data": result, "expiry": time.time() + 60}
        except Exception as e:
            logger.warning(f"Error fetching live EPG: {e}")

        return result

    async def resolve_vod_stream(self, idec: str, allow_drm: bool = True) -> Optional[Dict[str, Any]]:
        """Získá streamovací URL pro daný IDEC kód (pořad nebo epizodu).
        Používá HLS bez DRM s automatickým HbbTV fallbackem pro unencrypted 1080p streamy
        a volitelným DASH Widevine pro přehrávače s podporou DRM.
        """
        cached = self._cache.get(f"vod_{idec}")
        if cached and cached["expiry"] > time.time():
            return cached["data"]

        hls_stream_url = None
        dash_stream_url = None
        title = ""
        raw_subs = []

        try:
            async with httpx.AsyncClient(headers=self._headers, timeout=10.0) as client:
                # 1. Zkusíme standardní webový HLS bez DRM
                web_hls_url = f"https://api.ceskatelevize.cz/video/v1/playlist-vod/v1/stream-data/media/external/{idec}?canPlayDrm=false&quality=web&streamType=hls&origin=ivysilani"
                try:
                    resp = await client.get(web_hls_url)
                    if resp.status_code == 200:
                        data = resp.json()
                        streams = data.get("streams", [])
                        if streams and "url" in streams[0]:
                            hls_stream_url = streams[0]["url"]
                            title = data.get("title", "")
                            raw_subs = streams[0].get("subtitles", []) or data.get("subtitles", [])
                except Exception as e:
                    logger.debug(f"Web HLS resolve failed for {idec}: {e}")

                # 2. Pokud webové HLS selhalo (DRM omezení na webu jako u Bodu obnovy), zkusíme HbbTV profil (unencrypted 1080p HLS)
                if not hls_stream_url:
                    hbbtv_url = f"https://api.ceskatelevize.cz/video/v1/playlist-vod/v1/stream-data/media/external/{idec}?canPlayDrm=false&streamType=hls&origin=hbbtv"
                    try:
                        resp_hbbtv = await client.get(hbbtv_url)
                        if resp_hbbtv.status_code == 200:
                            data_hbbtv = resp_hbbtv.json()
                            streams_hbbtv = data_hbbtv.get("streams", [])
                            if streams_hbbtv and "url" in streams_hbbtv[0]:
                                hls_stream_url = streams_hbbtv[0]["url"]
                                if not title:
                                    title = data_hbbtv.get("title", "")
                                if not raw_subs:
                                    raw_subs = streams_hbbtv[0].get("subtitles", []) or data_hbbtv.get("subtitles", [])
                    except Exception as e:
                        logger.debug(f"HbbTV HLS resolve failed for {idec}: {e}")

                # 3. Získáme také DASH Widevine, pokud je vyžadováno nebo pro web přehrávač
                if allow_drm or not hls_stream_url:
                    dash_api_url = f"https://api.ceskatelevize.cz/video/v1/playlist-vod/v1/stream-data/media/external/{idec}?canPlayDrm=true&quality=web&streamType=dash&origin=ivysilani&usePlayability=true"
                    try:
                        resp_dash = await client.get(dash_api_url)
                        if resp_dash.status_code == 200:
                            data_dash = resp_dash.json()
                            streams_dash = data_dash.get("streams", [])
                            if streams_dash and "url" in streams_dash[0]:
                                dash_stream_url = streams_dash[0]["url"]
                                if not title:
                                    title = data_dash.get("title", "")
                                if not raw_subs:
                                    raw_subs = streams_dash[0].get("subtitles", []) or data_dash.get("subtitles", [])
                    except Exception as e:
                        logger.debug(f"DASH resolve failed for {idec}: {e}")

        except Exception as e:
            logger.warning(f"Error fetching VOD streams for {idec}: {e}")

        if not hls_stream_url and not dash_stream_url:
            return None

        # Preferujeme unencrypted HLS (funguje ve Stremio, TiviMate, VLC, Downloaderu i prohlížeči)
        preferred_url = hls_stream_url or dash_stream_url
        is_drm = bool(not hls_stream_url and dash_stream_url)

        result = {
            "idec": idec,
            "title": title,
            "url": preferred_url,
            "hls_url": hls_stream_url,
            "dash_url": dash_stream_url,
            "is_drm": is_drm,
            "manifest_type": "hls" if hls_stream_url else "mpd",
            "license_key": "https://ivys-wvproxy.o2tv.cz/license?access_token=public|Origin=https%3A%2F%2Fwww.ceskatelevize.cz&Referer=https%3A%2F%2Fwww.ceskatelevize.cz%2F|R{SSM}|",
            "subtitles": self._extract_subtitles(raw_subs),
            "raw_subtitles": raw_subs
        }
        self._cache[f"vod_{idec}"] = {"data": result, "expiry": time.time() + 1800}
        return result

    async def get_episodes_for_programme(
        self,
        programme_id: str,
        season_id: Optional[str] = None,
        only_playable: bool = False,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Získá reálné epizody pro daný pořad z ČT GraphQL query GetEpisodes."""
        url = "https://api.ceskatelevize.cz/graphql/"
        params = {"client": "iVysilaniWeb", "version": "1.131.1", "use-new-playability": "true"}
        query = """
        query GetEpisodes($programmeId: String!, $seasonId: String, $limit: PaginationAmount!, $offset: Int!, $orderBy: EpisodeOrderByType!, $keyword: String, $onlyPlayable: Boolean) {
          programme(programmeId: $programmeId) {
            id
            episodes(seasonId: $seasonId, limit: $limit, offset: $offset, orderBy: $orderBy, keyword: $keyword, onlyPlayable: $onlyPlayable) {
              totalCount
              items {
                id
                title
                description
                duration
                season { id title }
                cardLabels { topLeft center bottomRight }
                images { card(width: 480, height: 270) }
                playable
              }
            }
          }
        }
        """
        variables = {
            "programmeId": programme_id,
            "seasonId": season_id,
            "limit": limit,
            "offset": offset,
            "orderBy": "oldest",
            "onlyPlayable": only_playable
        }
        try:
            async with httpx.AsyncClient(headers=self._headers, timeout=12.0) as client:
                r = await client.post(url, params=params, json={"query": query, "variables": variables})
                if r.status_code == 200:
                    data = r.json()
                    episodes_obj = data.get("data", {}).get("programme", {}).get("episodes", {})
                    items = episodes_obj.get("items", [])
                    return items
        except Exception as e:
            logger.warning(f"Error fetching GraphQL episodes for programme {programme_id}: {e}")
        return []

    async def search_shows_graphql(self, keyword: str, limit: int = 30, only_playable: bool = False) -> List[Dict[str, Any]]:
        """Vyhledá pořady přímo v ČT GraphQL API přes SearchShows."""
        if not keyword or len(keyword.strip()) < 2:
            return []

        url = "https://api.ceskatelevize.cz/graphql/"
        params = {"client": "iVysilaniWeb", "version": "1.131.1", "use-new-playability": "true"}
        query = """
        query SearchShows($limit: PaginationAmount!, $offset: Int!, $search: String!, $onlyPlayable: Boolean) {
          searchShows(limit: $limit, offset: $offset, keyword: $search, onlyPlayable: $onlyPlayable) {
            totalCount
            items {
              code
              id
              description
              genres { id title }
              imageUrl(width: 480, height: 270)
              sidp
              title
              playable
              cardLabels { topLeft center }
            }
          }
        }
        """
        variables = {
            "limit": limit,
            "offset": 0,
            "search": keyword.strip(),
            "onlyPlayable": only_playable
        }
        try:
            async with httpx.AsyncClient(headers=self._headers, timeout=10.0) as client:
                r = await client.post(url, params=params, json={"query": query, "variables": variables})
                if r.status_code == 200:
                    data = r.json()
                    items = data.get("data", {}).get("searchShows", {}).get("items", [])
                    return items
        except Exception as e:
            logger.warning(f"GraphQL SearchShows failed: {e}")
        return []

    async def scrape_show_metadata(self, slug_or_id_or_url: str) -> Optional[Dict[str, Any]]:
        """Stáhne a zparsuje kompletní informace o pořadu, všech sériích a všech dílech z webu ČT."""
        clean_input = slug_or_id_or_url.strip()
        m = re.search(r"/porady/([0-9a-zA-Z_\-]+)/?", clean_input)
        slug = m.group(1) if m else clean_input.strip("/")

        url = f"https://www.ceskatelevize.cz/porady/{slug}/"
        try:
            async with httpx.AsyncClient(headers={"User-Agent": settings.USER_AGENT}, follow_redirects=True, timeout=12.0) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    # Zkusíme vyhledat přes GraphQL, pokud slug nefungoval přímo
                    clean_kw = re.sub(r'^\d+-?', '', slug).replace('-', ' ').strip() or slug
                    search_res = await self.search_shows_graphql(clean_kw, limit=1)
                    if not search_res and clean_kw != slug:
                        search_res = await self.search_shows_graphql(slug, limit=1)
                    if search_res:
                        item = search_res[0]
                        full_slug = f"{item['id']}-{item['code']}"
                        url = f"https://www.ceskatelevize.cz/porady/{full_slug}/"
                        resp = await client.get(url)
                    if resp.status_code != 200:
                        logger.warning(f"Failed to fetch show page {url}: {resp.status_code}")
                        return None

                match = re.search(r'<script id="__NEXT_DATA__" type="application/json">([^<]+)</script>', resp.text)
                if not match:
                    return None

                data = json.loads(match.group(1))
                page_data = data.get("props", {}).get("pageProps", {}).get("data", {})
                prog = page_data.get("programme")
                if not prog:
                    ep_data = page_data.get("episode")
                    if ep_data:
                        show_info = ep_data.get("show", {})
                        prog = {
                            "id": show_info.get("id") or slug,
                            "title": show_info.get("title") or ep_data.get("title"),
                            "slug": show_info.get("slug") or slug,
                            "description": ep_data.get("description"),
                            "idec": ep_data.get("idec"),
                            "images": ep_data.get("images", {})
                        }
                    else:
                        return None

                show_id = str(prog.get("id") or slug)
                programme_id = str(prog.get("programmeId") or show_id)
                title = prog.get("title", "")
                description = prog.get("description") or prog.get("shortDescription") or ""
                year = str(prog.get("year") or "")

                raw_type = prog.get("showType", "")
                seasons_list = prog.get("seasons", [])
                show_type = "movie" if raw_type == "movie" or (not seasons_list and prog.get("idec")) else "series"
                is_playable = bool(prog.get("isPlayable", True))

                # Extrahe obrázků různých typů
                images = prog.get("images", {})
                hero_imgs = images.get("heroWithFallback", {}) or {}
                backdrop_url = (
                    hero_imgs.get("desktop")
                    or images.get("metaImage")
                    or images.get("subpage")
                    or images.get("card2x")
                    or ""
                )
                placeholder_imgs = images.get("placeholderWithFallback", {}) or {}
                poster_url = (
                    images.get("poster")
                    or images.get("poster2x")
                    or placeholder_imgs.get("placeholderMobile")
                    or images.get("card")
                    or backdrop_url
                )
                logo_url = (
                    images.get("logo")
                    or images.get("logo2x")
                    or images.get("logoInverted")
                    or ""
                )
                image_url = images.get("card") or backdrop_url or poster_url

                # Žánry
                genres = [g["title"] for g in prog.get("flatGenres", []) if isinstance(g, dict) and "title" in g]
                genre = ", ".join(genres) if genres else "Archiv"

                episodes = []

                if show_type == "series":
                    # Pro seriál načteme všechny reálné epizody přes GraphQL GetEpisodes
                    # 1. Zkusíme načíst celou sérii bez season filtru (až 100 dílů)
                    gql_episodes = await self.get_episodes_for_programme(programme_id, limit=50, offset=0)
                    if len(gql_episodes) == 50:
                        # Druhá stránka pro dlouhé seriály
                        page2 = await self.get_episodes_for_programme(programme_id, limit=50, offset=50)
                        gql_episodes.extend(page2)
                        if len(page2) == 50:
                            page3 = await self.get_episodes_for_programme(programme_id, limit=50, offset=100)
                            gql_episodes.extend(page3)

                    # Pokud bez season filtru nic nepřišlo a máme seasons_list, zkusíme jednotlivé řady
                    if not gql_episodes and seasons_list:
                        for s_item in seasons_list:
                            s_id = s_item.get("id")
                            if s_id:
                                s_eps = await self.get_episodes_for_programme(programme_id, season_id=s_id, limit=50)
                                gql_episodes.extend(s_eps)

                    for idx, ep_item in enumerate(gql_episodes, start=1):
                        ep_idec = str(ep_item.get("id") or "")
                        ep_title = ep_item.get("title") or f"Epizoda {idx}"
                        ep_season_title = (ep_item.get("season") or {}).get("title", "")
                        season_num = parse_season_number(ep_season_title, default=1)
                        ep_num = parse_episode_number(ep_title, default=idx)
                        ep_imgs = ep_item.get("images") or {}
                        ep_img = ep_imgs.get("card") or image_url

                        episodes.append({
                            "id": f"{show_id}_{ep_idec}",
                            "idec": ep_idec,
                            "title": ep_title,
                            "description": ep_item.get("description") or description,
                            "image_url": ep_img,
                            "duration": ep_item.get("duration", 0),
                            "season": season_num,
                            "episode_num": ep_num,
                            "is_playable": bool(ep_item.get("playable", True)),
                            "is_drm": False
                        })

                # Fallback pro film nebo pokud seriál neměl dostupné epizody přes GraphQL
                if not episodes:
                    idec = str(prog.get("idec") or (prog.get("actionButton") or {}).get("idec") or "")
                    if idec:
                        episodes.append({
                            "id": f"{show_id}_{idec}",
                            "idec": idec,
                            "title": title,
                            "description": description,
                            "image_url": image_url,
                            "duration": prog.get("duration", 0),
                            "season": 1,
                            "episode_num": 1,
                            "is_playable": is_playable,
                            "is_drm": False
                        })

                return {
                    "id": show_id,
                    "programme_id": programme_id,
                    "title": title,
                    "slug": slug,
                    "description": description,
                    "image_url": image_url,
                    "poster_url": poster_url,
                    "backdrop_url": backdrop_url,
                    "logo_url": logo_url,
                    "genre": genre,
                    "year": year,
                    "show_type": show_type,
                    "is_playable": is_playable,
                    "total_episodes": len(episodes),
                    "episodes": episodes
                }
        except Exception as e:
            logger.error(f"Error scraping show {slug}: {e}")
            return None

ct_service = CTService()
