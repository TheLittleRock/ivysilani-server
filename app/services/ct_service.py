import time
import re
import json
import logging
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Optional, Any, Tuple
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

ROMAN_NUMERALS = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7,
    "viii": 8, "ix": 9, "x": 10, "xi": 11, "xii": 12, "xiii": 13,
    "xiv": 14, "xv": 15, "xvi": 16, "xvii": 17, "xviii": 18, "xix": 19, "xx": 20
}

def clean_episode_title(raw_title: str) -> Tuple[Optional[int], str]:
    """Extrahuje číslo epizody z prefixu (např. '1/13 Ztracený případ' -> (1, 'Ztracený případ'))."""
    if not raw_title:
        return None, ""
    clean = raw_title.replace("\xa0", " ").strip()
    m = re.match(r"^(\d+)/\d+\s+(.+)$", clean)
    if m:
        return int(m.group(1)), m.group(2).strip()
    return None, clean

def parse_season_number(season_title: str, ep_title: str = "", default: int = 1) -> int:
    """Extrahuje číslo řady z popisku např. 'I. řada', 'StarDance XIV (2026)', 'Osudy', 'Filmy o seriálu'."""
    s = (season_title or "").replace("\xa0", " ").strip().lower()
    t = (ep_title or "").replace("\xa0", " ").strip().lower()

    # 1. Speciály a bonusové materiály -> Série 0
    if any(b in s or b in t for b in ["film o ", "filmy o ", "bonus", "kolem dokola", "videochat", "speciál", "tiskov", "zákulis", "tour"]):
        return 0
    # 2. Vyprávěj Osudy -> Série 6
    if "osudy" in s or "osudy" in t:
        return 6
    # 3. Číselné označení: '1. řada', '2. série'
    m_num = re.search(r"(\d+)\.\s*(?:řada|série)", s)
    if m_num:
        return int(m_num.group(1))
    # 4. Římské číslice: 'I. řada', 'IV. řada'
    m_roman = re.search(r"\b([ivx]+)\.\s*(?:řada|série)", s)
    if m_roman and m_roman.group(1) in ROMAN_NUMERALS:
        return ROMAN_NUMERALS[m_roman.group(1)]
    # 5. StarDance: 'StarDance XIV'
    m_sd = re.search(r"stardance\s+([ivx]+)", s) or re.search(r"stardance\s+([ivx]+)", t)
    if m_sd and m_sd.group(1) in ROMAN_NUMERALS:
        return ROMAN_NUMERALS[m_sd.group(1)]
    # 6. Rok v závorce: '(2026)'
    m_yr = re.search(r"\((\d{4})\)", s)
    if m_yr:
        return int(m_yr.group(1))

    # 7. Odstraníme formáty stopáže a počtu dílů jako '42× 26 minut', '21× 52 minut', '14 dílů'
    s_clean = re.sub(r"\d+\s*[×x]\s*\d+\s*minut\w*", " ", s)
    s_clean = re.sub(r"\d+\s*[×x]", " ", s_clean)
    s_clean = re.sub(r"\d+\s*(?:minut\w*|min\b|díl\w*|epizod\w*|část\w*)", " ", s_clean)

    # Základní fallback - pouze pro platná čísla sérií (1 až 30)
    m_basic = re.search(r"\b(\d+)\b", s_clean)
    if m_basic:
        val = int(m_basic.group(1))
        if 1 <= val <= 30:
            return val

    return default

def parse_episode_number(title: str, default: Optional[int] = 1) -> Optional[int]:
    """Extrahuje číslo dílu z názvu např. '1/26 Od začátku', 'Díl 5' apod."""
    if not title:
        return default
    num, _ = clean_episode_title(title)
    if num is not None:
        return num
    m_exp = re.search(r"\b(?:díl|epizoda|část)\s*(\d+)\b", title, re.IGNORECASE)
    if m_exp:
        return int(m_exp.group(1))
    m_start = re.match(r"^(\d+)\.\s+", title.strip())
    if m_start:
        return int(m_start.group(1))
    return default

CZECH_MONTHS = {
    'ledna': 1, 'leden': 1, 'února': 2, 'únor': 2, 'března': 3, 'březen': 3,
    'dubna': 4, 'duben': 4, 'května': 5, 'květen': 5, 'června': 6, 'červen': 6,
    'července': 7, 'červenec': 7, 'srpna': 8, 'srpen': 8, 'září': 9,
    'října': 10, 'říjen': 10, 'listopadu': 11, 'listopad': 11, 'prosince': 12, 'prosinec': 12
}

def parse_periodical_date(title: str, idec: str = "", dt_str: str = "") -> Tuple[int, int, str]:
    """Extrahuje rok (jako sérii), pořadí/den v roce (jako díl) a formátované datum pro denní a periodické pořady."""
    year = datetime.now().year
    month = 1
    day = 1
    clean = (title or "").replace("\xa0", " ").strip()

    if dt_str:
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            return dt.year, dt.timetuple().tm_yday, f"{dt.day}. {dt.month}. {dt.year}"
        except Exception:
            pass

    m = re.search(r"(\d{1,2})\.\s*([a-záčďéěíňóřšťúůýž]+)(?:\s+(\d{4}))?", clean, re.IGNORECASE)
    if m:
        day = int(m.group(1))
        m_str = m.group(2).lower()
        month = CZECH_MONTHS.get(m_str, 1)
        if m.group(3):
            year = int(m.group(3))
        elif idec and len(idec) >= 3 and idec[:3].isdigit():
            y2 = int(idec[1:3])
            year = 2000 + y2 if y2 < 70 else 1900 + y2
        else:
            year = datetime.now().year
    elif idec and len(idec) >= 3 and idec[:3].isdigit():
        y2 = int(idec[1:3])
        year = 2000 + y2 if y2 < 70 else 1900 + y2

    try:
        dt = datetime(year, month, day)
        yday = dt.timetuple().tm_yday
    except Exception:
        yday = 1

    return year, yday, f"{day}. {month}. {year}"

class CTService:
    def __init__(self):
        self._headers = {
            "User-Agent": settings.USER_AGENT,
            "Origin": "https://www.ceskatelevize.cz",
            "Referer": "https://www.ceskatelevize.cz/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "cs,en;q=0.9"
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
        """Získá aktuální manifest živého vysílání (čistý nešifrovaný 1080p HLS stream bez DRM hlášek, s volitelným DASH)."""
        norm_key = CHANNEL_KEY_MAP.get(ch_key.lower(), ch_key)
        cached = self._cache.get(f"live_{norm_key}")
        if cached and cached["expiry"] > time.time():
            raw = cached["raw"]
        else:
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

                    if not hls_main and not dash_main and not timeshift_url:
                        return None

                    is_drm = False
                    if (dash_data.get("streamUrls", {}).get("encryption") == "wv" or 
                        "drmOnly=true" in (dash_main or "") or 
                        dash_data.get("streamUrls", {}).get("drmOnly") is True):
                        is_drm = True

                    raw = {
                        "norm_key": norm_key,
                        "title": hls_data.get("title") or dash_data.get("title") or LIVE_CHANNELS.get(norm_key, {}).get("name", "ČT"),
                        "hls_main": hls_main,
                        "dash_main": dash_main,
                        "timeshift_url": timeshift_url,
                        "is_drm": is_drm,
                        "qualities": hls_data.get("availableQualities") or dash_data.get("availableQualities", []),
                        "audio_tracks": hls_data.get("audioTracks") or dash_data.get("audioTracks", []),
                        "subtitles": self._extract_subtitles(hls_data.get("subtitles") or dash_data.get("subtitles", []))
                    }
                    self._cache[f"live_{norm_key}"] = {
                        "raw": raw,
                        "expiry": time.time() + 300  # Obnova CDN tokenu každých 5 minut
                    }
            except Exception as e:
                logger.error(f"Error resolving live stream for {norm_key}: {e}")
                return None

        # Dynamický sliding timeshift window (posledních 60 sekund) zaručuje čistý stream bez červené DRM hlášky
        timeshift_url = raw.get("timeshift_url")
        hls_main = raw.get("hls_main")
        dash_main = raw.get("dash_main")
        is_drm = raw.get("is_drm", False)

        clean_hls = None
        if timeshift_url:
            clean_hls = f"{timeshift_url}&start={int(time.time()) - 60}&duration=14400"

        # Pokud je na stanici aktivní DRM (např. StarDance, zahraniční filmy), na hls_main ČT vysílá
        # varovnou statickou smyčku "Pořad nelze přehrát v tomto prohlížeči". Timeshift endpoint
        # naproti tomu poskytuje plně nešifrovaný čistý 1080p stream s titulky i vícejazyčným audiem.
        effective_hls = (clean_hls if is_drm else hls_main) or clean_hls or hls_main

        if allow_drm and is_drm and dash_main:
            chosen_url = dash_main
            m_type = "mpd"
        else:
            chosen_url = effective_hls or dash_main
            m_type = "hls" if effective_hls else "mpd"

        return {
            "channel_id": raw["norm_key"],
            "title": raw["title"],
            "url": chosen_url,
            "hls_url": effective_hls,
            "dash_url": dash_main,
            "timeshift_url": timeshift_url,
            "is_drm": is_drm,
            "manifest_type": m_type,
            "qualities": raw["qualities"],
            "audio_tracks": raw["audio_tracks"],
            "subtitles": raw["subtitles"]
        }

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
        offset: int = 0,
        order_by: str = "oldest"
    ) -> List[Dict[str, Any]]:
        """Získá reálné epizody pro daný pořad z ČT GraphQL query GetEpisodes."""
        url = "https://api.ceskatelevize.cz/graphql/"
        params = {"client": "iVysilaniWeb", "version": "1.131.1", "use-new-playability": "true"}
        query = """
        query GetEpisodes($id: String!, $seasonId: String, $limit: PaginationAmount!, $offset: Int!, $orderBy: EpisodeOrderByType, $keyword: String, $onlyPlayable: Boolean) {
          programme(legacySidpOrIdp: $id) {
            id
            episodes(seasonId: $seasonId, limit: $limit, offset: $offset, orderBy: $orderBy, keyword: $keyword, onlyPlayable: $onlyPlayable) {
              totalCount
              items {
                id
                title
                idec
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
            "id": str(programme_id),
            "seasonId": season_id,
            "limit": limit,
            "offset": offset,
            "orderBy": order_by,
            "onlyPlayable": only_playable
        }
        try:
            async with httpx.AsyncClient(headers=self._headers, timeout=12.0) as client:
                r = await client.post(url, params=params, json={"query": query, "variables": variables})
                if r.status_code == 200:
                    data = r.json()
                    programme_data = (data.get("data") or {}).get("programme") or {}
                    episodes_obj = programme_data.get("episodes") or {}
                    items = episodes_obj.get("items") or []
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
              images {
                card
                cardPortrait
                poster
              }
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

    async def get_homepage_blocks(self) -> List[Dict[str, Any]]:
        """Získá aktuální doporučené sekce a pořady z hlavní stránky iVysílání přes GraphQL."""
        url = "https://api.ceskatelevize.cz/graphql/"
        params = {"client": "iVysilaniWeb", "version": "1.131.1"}
        query = """
        query {
          homepage(deviceType: \"website\") {
            rows {
              title
              slug
              disabled
              assets {
                totalCount
                items {
                  __typename
                  ... on ShowCard {
                    id
                    code
                    title
                    description
                    images {
                      card
                      cardPortrait
                    }
                    programme {
                      id
                      showType
                    }
                  }
                }
              }
            }
          }
        }
        """
        try:
            async with httpx.AsyncClient(headers=self._headers, timeout=10.0) as client:
                r = await client.post(url, params=params, json={"query": query})
                if r.status_code == 200:
                    data = r.json()
                    rows = data.get("data", {}).get("homepage", {}).get("rows", [])
                    result_rows = []
                    for row in rows:
                        title = (row.get("title") or "").replace("\xa0", " ").strip()
                        slug = row.get("slug") or ""
                        items = row.get("assets", {}).get("items", [])
                        valid_items = []
                        for it in items:
                            if it.get("title") and it.get("id"):
                                raw_p = (it.get("images") or {}).get("cardPortrait")
                                portrait = raw_p if raw_p and "fallbackImages" not in raw_p else None
                                prog = it.get("programme") or {}
                                canon_id = str(prog.get("id")) if prog.get("id") else str(it.get("id"))
                                valid_items.append({
                                    "id": canon_id,
                                    "asset_id": str(it.get("id")),
                                    "code": it.get("code") or "",
                                    "title": it.get("title").replace("\xa0", " ").strip(),
                                    "description": it.get("description") or "",
                                    "card_url": (it.get("images") or {}).get("card") or "",
                                    "poster_url": portrait or (it.get("images") or {}).get("card") or "",
                                    "show_type": prog.get("showType") or it.get("show_type") or "series"
                                })
                        if valid_items:
                            result_rows.append({
                                "title": title,
                                "slug": slug,
                                "items": valid_items
                            })
                    return result_rows
        except Exception as e:
            logger.warning(f"Error fetching homepage blocks: {e}")
        return []

    async def scrape_show_metadata(self, slug_or_id_or_url: str) -> Optional[Dict[str, Any]]:
        """Stáhne a zparsuje kompletní informace o pořadu, všech sériích a všech dílech z webu ČT."""
        clean_input = slug_or_id_or_url.strip()
        m = re.search(r"/porady/([0-9a-zA-Z_\-]+)/?", clean_input)
        slug = m.group(1) if m else clean_input.strip("/")

        url = f"https://www.ceskatelevize.cz/porady/{slug}/"
        try:
            req_headers = {
                "User-Agent": settings.USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "cs,en;q=0.9",
                "Referer": "https://www.ceskatelevize.cz/"
            }
            async with httpx.AsyncClient(headers=req_headers, follow_redirects=True, timeout=12.0) as client:
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
                apollo_state = data.get("props", {}).get("apolloState", {})
                root_query = apollo_state.get("ROOT_QUERY", {})

                # Hledání hexadecimálního programmeId pro GraphQL
                programme_id = None
                for k in root_query:
                    m_prog = re.search(r'programme\(\{"programmeId":"([a-f0-9]+)"\}\)', k)
                    if m_prog:
                        programme_id = m_prog.group(1)
                        break

                prog = page_data.get("programme")
                if not prog:
                    # Zkusíme dohledat Show z apolloState
                    for k, v in apollo_state.items():
                        if k.startswith("Show:") and isinstance(v, dict) and v.get("title"):
                            prog = {
                                "id": str(v.get("id") or slug),
                                "title": v.get("title"),
                                "slug": v.get("slug") or slug,
                                "description": v.get("shortDescription") or v.get("description") or "",
                                "year": v.get("year"),
                                "showType": v.get("showType", "series"),
                                "isPlayable": v.get("playable", True),
                                "images": v.get("images", {})
                            }
                            break

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
                if not programme_id:
                    programme_id = str(prog.get("programmeId") or show_id)

                title = prog.get("title", "")
                description = prog.get("description") or prog.get("shortDescription") or ""
                year = str(prog.get("year") or "")

                raw_type = (prog.get("showType") or "").lower()
                seasons_from_apollo = [v for k, v in apollo_state.items() if isinstance(v, dict) and v.get("__typename") == "Season"]
                seasons_list = prog.get("seasons", []) or seasons_from_apollo
                ep_previews = [v for k, v in apollo_state.items() if isinstance(v, dict) and v.get("__typename") == "EpisodePreview"]
                has_datetime_previews = any(p.get("date", {}).get("datetime") for p in ep_previews)
                has_season_series = any('řada' in (s.get('title') or '').lower() or 'stardance' in (s.get('title') or '').lower() for s in seasons_list)

                # Žánry
                genres = [g["title"] for g in prog.get("flatGenres", []) if isinstance(g, dict) and "title" in g]
                if not genres:
                    genres = [v.get("title") for k, v in apollo_state.items() if isinstance(v, dict) and v.get("__typename") in ["FlatGenre", "CardGenre"] and v.get("title")]
                genre = ", ".join(list(dict.fromkeys(genres))[:3]) if genres else "Archiv"

                # Detekce periodických / denních pořadů bez klasických řad
                is_periodical_or_daily = (
                    any(slug.startswith(x) for x in ['1097181328-udalosti', '10393496397-udalosti-za-okamzik-a-pocasi', '1097181328', '10393496397'])
                    or (has_datetime_previews and not has_season_series and any(k in genre.lower() for k in ['zpravodaj', 'publicist', 'počasí', 'magazín', 'zábav']))
                    or any(k in title.lower() for k in ['události', 'počasí', 'zprávy', 'černé ovce', 'sama doma', 'studio 6', 'toulavá kamera', 'hyde park'])
                )

                # Přesná detekce typu (seriál vs. film)
                is_series_by_genre = any(k in genre.lower() for k in ['seriál', 'cyklus', 'série', 'minisérie', 'pořad'])
                has_multiple_episodes = len(ep_previews) > 1 or len(seasons_list) > 1

                if is_periodical_or_daily or is_series_by_genre or has_multiple_episodes or len(seasons_list) > 0:
                    show_type = "series"
                elif raw_type == "movie" or ("film" in raw_type and not has_multiple_episodes):
                    show_type = "movie"
                elif len(ep_previews) <= 1 and prog.get("idec") and not is_series_by_genre:
                    show_type = "movie"
                else:
                    show_type = "series" if has_multiple_episodes else "movie"

                is_playable = bool(prog.get("isPlayable", True))

                # Extrakce obrázků různých typů
                images = prog.get("images", {})
                hero_imgs = images.get("heroWithFallback", {}) or {}
                backdrop_url = (
                    hero_imgs.get("desktop")
                    or images.get("metaImage")
                    or images.get("subpage")
                    or images.get("card2x")
                    or ""
                )

                # Nativní vertikální plakát cardPortrait (2:3) z ČT
                raw_portrait = (
                    images.get("cardPortrait")
                    or images.get("cardPortrait({\"width\":440})")
                    or images.get("cardPortrait({\"height\":660,\"width\":440})")
                )
                if not raw_portrait or "fallbackImages" in str(raw_portrait):
                    for k, v in apollo_state.items():
                        if isinstance(v, dict) and "cardPortrait" in v:
                            cand = v.get("cardPortrait")
                            if cand and isinstance(cand, str) and "fallbackImages" not in cand:
                                raw_portrait = cand
                                break

                # Zkusíme dohledat nativní vertikální plakát (cardPortrait) z GraphQL SearchShows
                if not raw_portrait or "fallbackImages" in str(raw_portrait):
                    try:
                        gql_search = await self.search_shows_graphql(title, limit=1)
                        if gql_search:
                            cand_port = (gql_search[0].get("images") or {}).get("cardPortrait")
                            if cand_port and "fallbackImages" not in cand_port:
                                raw_portrait = cand_port
                    except Exception:
                        pass

                placeholder_imgs = images.get("placeholderWithFallback", {}) or {}
                poster_url = (
                    (raw_portrait if raw_portrait and "fallbackImages" not in raw_portrait else None)
                    or images.get("poster")
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

                episodes = []
                seen_idecs = set()

                if show_type == "series" and is_periodical_or_daily:
                    # Periodický nebo denní pořad (Události, Počasí, Zprávy, Toulavá kamera, Sama doma...)
                    # 1. Zkusíme načíst nejnovější epizody z GraphQL
                    gql_items = []
                    if programme_id:
                        gql_items = await self.get_episodes_for_programme(programme_id, limit=50, order_by="lastTvBroadcast")
                        if not gql_items:
                            gql_items = await self.get_episodes_for_programme(programme_id, limit=50, order_by="newest")

                    # 2. Zpracujeme epizody z GraphQL
                    day_counts = {}
                    for item in gql_items:
                        p_idec = str(item.get("id") or "")
                        if not p_idec or p_idec in seen_idecs:
                            continue
                        seen_idecs.add(p_idec)
                        raw_ep_title = item.get("title") or title
                        season_val, yday, formatted_date = parse_periodical_date(raw_ep_title, p_idec)
                        day_counts[yday] = day_counts.get(yday, 0) + 1
                        ep_num = yday if day_counts[yday] == 1 else yday * 10 + (day_counts[yday] - 1)
                        ep_imgs = item.get("images") or {}
                        ep_img = ep_imgs.get("card") or image_url

                        episodes.append({
                            "id": f"{show_id}_{p_idec}",
                            "idec": p_idec,
                            "title": f"{formatted_date}: {raw_ep_title}",
                            "description": item.get("description") or description,
                            "image_url": ep_img,
                            "duration": item.get("duration", 0),
                            "season": season_val,
                            "episode_num": ep_num,
                            "is_playable": bool(item.get("playable", True)),
                            "is_drm": False
                        })

                    # 3. Zpracujeme také ep_previews (z apolloState), pokud ještě chybí
                    for p in ep_previews:
                        p_idec = str(p.get("id") or "")
                        if not p_idec or p_idec in seen_idecs:
                            continue
                        seen_idecs.add(p_idec)
                        dt_str = p.get("date", {}).get("datetime") or ""
                        raw_ep_title = p.get("title") or title
                        season_val, yday, formatted_date = parse_periodical_date(raw_ep_title, p_idec, dt_str=dt_str)
                        day_counts[yday] = day_counts.get(yday, 0) + 1
                        ep_num = yday if day_counts[yday] == 1 else yday * 10 + (day_counts[yday] - 1)
                        p_imgs = p.get("images") or {}
                        p_img = p_imgs.get("card({\"height\":270,\"width\":480})") or p_imgs.get("card") or image_url

                        episodes.append({
                            "id": f"{show_id}_{p_idec}",
                            "idec": p_idec,
                            "title": f"{formatted_date}: {raw_ep_title}",
                            "description": p.get("description") or description,
                            "image_url": p_img,
                            "duration": p.get("duration", 0),
                            "season": season_val,
                            "episode_num": ep_num,
                            "is_playable": bool(p.get("playable", True)),
                            "is_drm": False
                        })

                elif show_type == "series":
                    gql_episodes = []

                    # Pokud máme seznam řad (seasons_list), projdeme každou řadu zvlášť
                    if seasons_list and programme_id:
                        for s_item in seasons_list:
                            s_id = s_item.get("id")
                            s_title = s_item.get("title") or ""
                            if s_id:
                                s_eps = await self.get_episodes_for_programme(programme_id, season_id=s_id, limit=50, order_by="oldest")
                                s_num = parse_season_number(s_title, default=1)
                                for ep_item in s_eps:
                                    ep_item["_resolved_season"] = s_num
                                gql_episodes.extend(s_eps)

                    # Pokud nic nepřišlo po řadách nebo řady nebyly definovány, zkusíme bez filtru
                    if not gql_episodes and programme_id:
                        page1 = await self.get_episodes_for_programme(programme_id, limit=50, offset=0, order_by="oldest")
                        gql_episodes.extend(page1)
                        if len(page1) == 50:
                            page2 = await self.get_episodes_for_programme(programme_id, limit=50, offset=50, order_by="oldest")
                            gql_episodes.extend(page2)
                            if len(page2) == 50:
                                page3 = await self.get_episodes_for_programme(programme_id, limit=50, offset=100, order_by="oldest")
                                gql_episodes.extend(page3)

                    season_counters: Dict[int, int] = defaultdict(int)
                    for idx, ep_item in enumerate(gql_episodes, start=1):
                        ep_idec = str(ep_item.get("id") or "")
                        if not ep_idec or ep_idec in seen_idecs:
                            continue
                        seen_idecs.add(ep_idec)

                        raw_ep_title = ep_item.get("title") or f"Epizoda {idx}"
                        clean_num, clean_name = clean_episode_title(raw_ep_title)
                        ep_title = clean_name

                        ep_season_title = (ep_item.get("season") or {}).get("title", "")
                        resolved_season = ep_item.get("_resolved_season")
                        if resolved_season is not None:
                            season_num = resolved_season
                        else:
                            season_num = parse_season_number(ep_season_title, ep_title=raw_ep_title, default=1)

                        season_counters[season_num] += 1
                        fallback_num = season_counters[season_num]

                        if clean_num is not None:
                            ep_num = clean_num
                        else:
                            parsed = parse_episode_number(raw_ep_title, default=None)
                            if parsed is not None:
                                ep_num = parsed
                            elif len(ep_idec) >= 4 and ep_idec[-4:].isdigit() and 1 <= int(ep_idec[-4:]) <= 500:
                                ep_num = int(ep_idec[-4:])
                            else:
                                ep_num = fallback_num

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

                    # Pokud GraphQL nevrátil epizody, zkusíme ep_previews z Apollo state
                    if not episodes and ep_previews:
                        season_counters.clear()
                        for idx, p in enumerate(ep_previews, start=1):
                            p_idec = str(p.get("id") or "")
                            if not p_idec or p_idec in seen_idecs:
                                continue
                            seen_idecs.add(p_idec)
                            raw_ep_title = p.get("title") or f"Epizoda {idx}"
                            clean_num, clean_name = clean_episode_title(raw_ep_title)
                            ep_title = clean_name
                            ep_season_title = (p.get("season") or {}).get("title", "")
                            season_num = parse_season_number(ep_season_title, ep_title=raw_ep_title, default=1)

                            season_counters[season_num] += 1
                            fallback_num = season_counters[season_num]

                            if clean_num is not None:
                                ep_num = clean_num
                            else:
                                parsed = parse_episode_number(raw_ep_title, default=None)
                                if parsed is not None:
                                    ep_num = parsed
                                elif len(p_idec) >= 4 and p_idec[-4:].isdigit() and 1 <= int(p_idec[-4:]) <= 500:
                                    ep_num = int(p_idec[-4:])
                                else:
                                    ep_num = fallback_num

                            p_imgs = p.get("images") or {}
                            p_img = p_imgs.get("card({\"height\":270,\"width\":480})") or p_imgs.get("card") or image_url

                            episodes.append({
                                "id": f"{show_id}_{p_idec}",
                                "idec": p_idec,
                                "title": ep_title,
                                "description": p.get("description") or description,
                                "image_url": p_img,
                                "duration": p.get("duration", 0),
                                "season": season_num,
                                "episode_num": ep_num,
                                "is_playable": bool(p.get("playable", True)),
                                "is_drm": False
                            })

                    # Normalizace číslování dílů v rámci každé série:
                    # Garantuje, že epizody v každé sérii začínají od 1 a nemají duplicity
                    if episodes:
                        by_season_map: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
                        for ep in episodes:
                            by_season_map[ep["season"]].append(ep)
                        for s_num, s_eps in by_season_map.items():
                            nums = [e["episode_num"] for e in s_eps]
                            if (len(nums) > 1 and len(set(nums)) < len(nums)) or any(n <= 0 for n in nums):
                                for i, e in enumerate(s_eps, start=1):
                                    e["episode_num"] = i

                # Fallback pro film nebo pokud seriál neměl dostupné epizody přes GraphQL ani previews
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
