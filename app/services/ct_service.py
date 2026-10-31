import re
import time
import json
import logging
from typing import Dict, Any, List, Optional
import httpx
from bs4 import BeautifulSoup

from app.core.config import settings

logger = logging.getLogger("ct_service")

# Definice 14 živých kanálů ČT
LIVE_CHANNELS = {
    "CH_1": {
        "id": "CH_1",
        "name": "ČT1",
        "num": 1,
        "category": "Česká televize",
        "logo": "/static/logos/ct1.svg",
        "epg_id": "ct1.cz",
        "description": "Hlavní program České televize – rodinná televize, seriály, zábava, zprávy."
    },
    "CH_2": {
        "id": "CH_2",
        "name": "ČT2",
        "num": 2,
        "category": "Česká televize",
        "logo": "/static/logos/ct2.svg",
        "epg_id": "ct2.cz",
        "description": "Dokumenty, příroda, historie, kvalitní filmová tvorba a publicistika."
    },
    "CH_24": {
        "id": "CH_24",
        "name": "ČT24",
        "num": 3,
        "category": "Česká televize",
        "logo": "/static/logos/ct24.svg",
        "epg_id": "ct24.cz",
        "description": "Nepřetržité 24hodinové zpravodajství a aktuální publicistika."
    },
    "CH_4": {
        "id": "CH_4",
        "name": "ČT sport",
        "num": 4,
        "category": "Česká televize",
        "logo": "/static/logos/ctsport.svg",
        "epg_id": "ctsport.cz",
        "description": "Český a mezinárodní sport, přímé přenosy a sportovní magazíny."
    },
    "CH_5": {
        "id": "CH_5",
        "name": "ČT :D",
        "num": 5,
        "category": "Česká televize",
        "logo": "/static/logos/ctd.svg",
        "epg_id": "ctd.cz",
        "description": "Dětský kanál Déčko pro děti od 4 do 12 let. Pohádky, vzdělávání a animované filmy."
    },
    "CH_6": {
        "id": "CH_6",
        "name": "ČT art",
        "num": 6,
        "category": "Česká televize",
        "logo": "/static/logos/ctart.svg",
        "epg_id": "ctart.cz",
        "description": "Kulturní a umělecký kanál ČT – divadlo, hudba, výtvarné umění a filmy."
    },
    "CH_25": {
        "id": "CH_25",
        "name": "ČT sport Plus 1",
        "num": 25,
        "category": "ČT sport Plus",
        "logo": "/static/logos/ctsportplus.svg",
        "epg_id": "ctsportplus1.cz",
        "description": "Internetový sportovní přenos ČT sport Plus 1."
    },
    "CH_26": {
        "id": "CH_26",
        "name": "ČT sport Plus 2",
        "num": 26,
        "category": "ČT sport Plus",
        "logo": "/static/logos/ctsportplus.svg",
        "epg_id": "ctsportplus2.cz",
        "description": "Internetový sportovní přenos ČT sport Plus 2."
    },
    "CH_27": {
        "id": "CH_27",
        "name": "ČT sport Plus 3",
        "num": 27,
        "category": "ČT sport Plus",
        "logo": "/static/logos/ctsportplus.svg",
        "epg_id": "ctsportplus3.cz",
        "description": "Internetový sportovní přenos ČT sport Plus 3."
    },
    "CH_28": {
        "id": "CH_28",
        "name": "ČT sport Plus 4",
        "num": 28,
        "category": "ČT sport Plus",
        "logo": "/static/logos/ctsportplus.svg",
        "epg_id": "ctsportplus4.cz",
        "description": "Internetový sportovní přenos ČT sport Plus 4."
    },
    "CH_29": {
        "id": "CH_29",
        "name": "ČT sport Plus 5",
        "num": 29,
        "category": "ČT sport Plus",
        "logo": "/static/logos/ctsportplus.svg",
        "epg_id": "ctsportplus5.cz",
        "description": "Internetový sportovní přenos ČT sport Plus 5."
    },
    "CH_30": {
        "id": "CH_30",
        "name": "ČT sport Plus 6",
        "num": 30,
        "category": "ČT sport Plus",
        "logo": "/static/logos/ctsportplus.svg",
        "epg_id": "ctsportplus6.cz",
        "description": "Internetový sportovní přenos ČT sport Plus 6."
    },
    "CH_31": {
        "id": "CH_31",
        "name": "ČT sport Plus 7",
        "num": 31,
        "category": "ČT sport Plus",
        "logo": "/static/logos/ctsportplus.svg",
        "epg_id": "ctsportplus7.cz",
        "description": "Internetový sportovní přenos ČT sport Plus 7."
    },
    "CH_32": {
        "id": "CH_32",
        "name": "ČT sport Plus 8",
        "num": 32,
        "category": "ČT sport Plus",
        "logo": "/static/logos/ctsportplus.svg",
        "epg_id": "ctsportplus8.cz",
        "description": "Internetový sportovní přenos ČT sport Plus 8."
    }
}

class CTService:
    def __init__(self):
        self._cache = {}
        self._headers = {
            "User-Agent": settings.USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "cs,en;q=0.9",
            "Referer": "https://www.ceskatelevize.cz/"
        }

    def get_channels_list(self) -> List[Dict[str, Any]]:
        return list(LIVE_CHANNELS.values())

    def get_channel(self, channel_id: str) -> Optional[Dict[str, Any]]:
        return LIVE_CHANNELS.get(channel_id.upper())

    async def resolve_live_stream(self, channel_id: str, allow_drm: bool = True) -> Optional[Dict[str, Any]]:
        """Získá přímou stream URL pro živé vysílání (DASH s Widevine DRM a HLS)."""
        ch_key = channel_id.upper()
        if ch_key not in LIVE_CHANNELS:
            return None

        cached = self._cache.get(f"live_{ch_key}")
        if cached and cached["expiry"] > time.time():
            return cached["data"]

        hls_url = f"https://api.ceskatelevize.cz/video/v1/playlist-live/v1/stream-data/channel/{ch_key}?canPlayDrm=false&quality=web&streamType=hls"
        dash_url = f"https://api.ceskatelevize.cz/video/v1/playlist-live/v1/stream-data/channel/{ch_key}?canPlayDrm=true&quality=web&streamType=dash"

        try:
            async with httpx.AsyncClient(headers=self._headers, timeout=10.0) as client:
                # Paralelní nebo sekvenční dotaz na HLS a DASH
                hls_resp = await client.get(hls_url)
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
                    "channel_id": ch_key,
                    "title": hls_data.get("title") or dash_data.get("title") or LIVE_CHANNELS[ch_key]["name"],
                    "url": dash_main if (allow_drm and dash_main) else (hls_main or dash_main),
                    "hls_url": hls_main,
                    "dash_url": dash_main,
                    "timeshift_url": timeshift_url,
                    "is_drm": is_drm,
                    "manifest_type": "mpd" if (allow_drm and dash_main) else "hls",
                    "qualities": dash_data.get("availableQualities") or hls_data.get("availableQualities", []),
                    "audio_tracks": dash_data.get("audioTracks") or hls_data.get("audioTracks", [])
                }
                self._cache[f"live_{ch_key}"] = {
                    "data": result,
                    "expiry": time.time() + 1800  # 30 minut
                }
                return result
        except Exception as e:
            logger.error(f"Error resolving live stream for {ch_key}: {e}")
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
                    for it in items:
                        ch_id = it.get("id")
                        if ch_id:
                            result[ch_id] = {
                                "current": it.get("current") or {},
                                "next": it.get("next") or {}
                            }
        except Exception as e:
            logger.warning(f"Error fetching live EPG from ČT: {e}")

        self._cache["live_epg_now"] = {
            "data": result,
            "expiry": time.time() + 60  # Cache 1 minutu
        }
        return result

    async def resolve_vod_stream(self, idec: str, allow_drm: bool = True) -> Optional[Dict[str, Any]]:
        """Získá stream pro daný IDEC pořadu. Nejprve zkusí HLS bez DRM."""
        cached = self._cache.get(f"vod_{idec}")
        if cached and cached["expiry"] > time.time():
            return cached["data"]

        # 1. Zkusíme HLS bez DRM
        hls_url = f"https://api.ceskatelevize.cz/video/v1/playlist-vod/v1/stream-data/media/external/{idec}?canPlayDrm=false&quality=web&streamType=hls&origin=ivysilani"
        try:
            async with httpx.AsyncClient(headers=self._headers, timeout=10.0) as client:
                resp = await client.get(hls_url)
                if resp.status_code == 200:
                    data = resp.json()
                    streams = data.get("streams", [])
                    if streams and "url" in streams[0]:
                        result = {
                            "idec": idec,
                            "title": data.get("title", ""),
                            "url": streams[0]["url"],
                            "is_drm": False,
                            "manifest_type": "hls",
                            "subtitles": streams[0].get("subtitles", [])
                        }
                        self._cache[f"vod_{idec}"] = {"data": result, "expiry": time.time() + 1800}
                        return result
        except Exception as e:
            logger.warning(f"HLS vod resolve failed for {idec}, attempting DASH: {e}")

        if not allow_drm:
            return None

        # 2. Pokud HLS nevyšlo nebo vyžaduje DRM, zkusíme DASH Widevine
        dash_url = f"https://api.ceskatelevize.cz/video/v1/playlist-vod/v1/stream-data/media/external/{idec}?canPlayDrm=true&quality=web&streamType=dash&origin=ivysilani&usePlayability=true"
        try:
            async with httpx.AsyncClient(headers=self._headers, timeout=10.0) as client:
                resp = await client.get(dash_url)
                if resp.status_code == 200:
                    data = resp.json()
                    streams = data.get("streams", [])
                    if streams and "url" in streams[0]:
                        raw_dash_url = streams[0]["url"]
                        result = {
                            "idec": idec,
                            "title": data.get("title", ""),
                            "url": raw_dash_url,
                            "is_drm": True,
                            "manifest_type": "mpd",
                            "license_key": "https://ivys-wvproxy.o2tv.cz/license?access_token=public|Origin=https%3A%2F%2Fwww.ceskatelevize.cz&Referer=https%3A%2F%2Fwww.ceskatelevize.cz%2F|R{SSM}|",
                            "subtitles": streams[0].get("subtitles", [])
                        }
                        self._cache[f"vod_{idec}"] = {"data": result, "expiry": time.time() + 1800}
                        return result
        except Exception as e:
            logger.error(f"DASH vod resolve failed for {idec}: {e}")

        return None

    async def scrape_show_metadata(self, slug_or_id_or_url: str) -> Optional[Dict[str, Any]]:
        """Stáhne a zparsuje informace o pořadu a jeho epizodách z webu ČT."""
        # Extrakce slug / showId
        clean_input = slug_or_id_or_url.strip()
        m = re.search(r"/porady/([0-9a-zA-Z_\-]+)/?", clean_input)
        slug = m.group(1) if m else clean_input.strip("/")

        url = f"https://www.ceskatelevize.cz/porady/{slug}/"
        try:
            async with httpx.AsyncClient(headers={"User-Agent": settings.USER_AGENT}, follow_redirects=True, timeout=12.0) as client:
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
                    # Může to být přímo stránka epizody
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
                title = prog.get("title", "")
                description = prog.get("description") or prog.get("shortDescription") or ""
                
                # Zpracování obrázku
                images = prog.get("images", {})
                image_url = ""
                if isinstance(images, dict):
                    image_url = images.get("card") or images.get("hero", {}).get("desktop") or ""
                if not image_url and "previewImage" in prog:
                    image_url = prog["previewImage"]

                # Žánr a rok
                genres = [g["title"] for g in prog.get("flatGenres", []) if isinstance(g, dict) and "title" in g]
                genre = genres[0] if genres else "Archiv"
                year = str(prog.get("year") or "")

                # Epizody
                episodes = []
                # Nejnovější epizoda z actionButtonu
                action_btn = prog.get("actionButton")
                if action_btn and action_btn.get("idec"):
                    episodes.append({
                        "id": str(action_btn["idec"]),
                        "idec": str(action_btn["idec"]),
                        "title": action_btn.get("text") or "Přehrát pořad",
                        "description": description,
                        "image_url": image_url,
                        "season": 1,
                        "episode_num": 1
                    })
                elif prog.get("idec"):
                    episodes.append({
                        "id": str(prog["idec"]),
                        "idec": str(prog["idec"]),
                        "title": title,
                        "description": description,
                        "image_url": image_url,
                        "season": 1,
                        "episode_num": 1
                    })

                return {
                    "id": show_id,
                    "title": title,
                    "slug": slug,
                    "description": description,
                    "image_url": image_url,
                    "genre": genre,
                    "year": year,
                    "episodes": episodes
                }
        except Exception as e:
            logger.error(f"Error scraping show {slug}: {e}")
            return None

    async def search_shows_online(self, query: str) -> List[Dict[str, Any]]:
        """Vyhledá pořady na iVysílání parsováním vyhledávací stránky."""
        if not query or len(query.strip()) < 2:
            return []

        url = f"https://www.ceskatelevize.cz/ivysilani/hledani/?keyword={query.strip()}"
        results = []
        try:
            async with httpx.AsyncClient(headers={"User-Agent": settings.USER_AGENT}, follow_redirects=True, timeout=10.0) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return []

                soup = BeautifulSoup(resp.text, "html.parser")
                found_links = set()
                for a in soup.find_all("a", href=re.compile(r"^/porady/")):
                    href = a.get("href")
                    if href in found_links or "cast/" in href:
                        continue
                    found_links.add(href)

                    # Název a obrázek
                    title_elem = a.find(["h3", "h4", "div", "span"])
                    title = title_elem.get_text(strip=True) if title_elem else a.get_text(strip=True)
                    img_elem = a.find("img")
                    img_src = img_elem.get("src") if img_elem else ""

                    # Zjistit slug a případný idec
                    parts = href.strip("/").split("/")
                    show_slug = parts[1] if len(parts) > 1 else ""
                    idec = parts[2] if len(parts) > 2 and parts[2].isdigit() else ""

                    if show_slug:
                        results.append({
                            "title": title or show_slug,
                            "slug": show_slug,
                            "url": f"https://www.ceskatelevize.cz{href}",
                            "image_url": img_src,
                            "idec": idec
                        })
                return results
        except Exception as e:
            logger.error(f"Error searching online for '{query}': {e}")
            return []

ct_service = CTService()
