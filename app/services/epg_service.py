import re
import time
import asyncio
import logging
import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Dict, Any, List, Optional
import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.services.ct_service import LIVE_CHANNELS, ct_service
from app.db import crud

logger = logging.getLogger("epg_service")

# Mapování tříd ČT HTML na standardní identifikátory v XMLTV a M3U
CHANNEL_BLOCK_MAP = {
    "programmeBlockChannel1": "ct1.cz",
    "programmeBlockChannel2": "ct2.cz",
    "programmeBlockChannel24": "ct24.cz",
    "programmeBlockChannel4": "ctsport.cz",
    "programmeBlockChannelD": "ctd.cz",
    "programmeBlockChannelArt": "ctart.cz",
    "programmeBlockChannelSportPlus": "ctsportplus1.cz"
}

_cached_epg_xml: Optional[str] = None
_cached_epg_time: float = 0.0

async def scrape_ct_schedule_for_date(target_date: datetime.date, client: httpx.AsyncClient) -> int:
    """Stáhne a uloží oficiální televizní program ČT pro zadané datum."""
    date_str = target_date.strftime("%d.%m.%Y")
    url = f"https://www.ceskatelevize.cz/tv-program/{date_str}/"
    logger.debug(f"Stahuji TV program ČT pro datum: {date_str}...")

    try:
        resp = await client.get(url)
        if resp.status_code != 200:
            logger.warning(f"Nelze stáhnout TV program pro {date_str}: status {resp.status_code}")
            return 0

        soup = BeautifulSoup(resp.text, "html.parser")
        total_saved = 0
        tz_prague = ZoneInfo("Europe/Prague")

        for block in soup.find_all(class_="programmeBlock"):
            classes = block.get("class", [])
            matched_channel = None
            for c in classes:
                if c in CHANNEL_BLOCK_MAP:
                    matched_channel = CHANNEL_BLOCK_MAP[c]
                    break
            if not matched_channel:
                continue

            raw_items = []
            for item in block.find_all("li", class_="programme"):
                time_span = item.find(class_="progTime")
                if not time_span:
                    continue
                time_str = time_span.text.strip()
                title_a = item.find("a", class_="progTitle")
                if not title_a:
                    continue
                title = title_a.text.strip()
                href = title_a.get("href", "")

                idec_m = re.search(r'/(\d{10,15})/?$', href) or re.search(r'idec=\"?(\d{10,15})\"?', str(title_a))
                idec = idec_m.group(1) if idec_m else ""

                desc_p = item.find("p", class_="progDesc") or item.find("div", class_="progInfo")
                desc = desc_p.text.strip().replace(title, "").strip() if desc_p else ""
                has_video = "has-video" in item.get("class", [])

                raw_items.append({
                    "time_str": time_str,
                    "title": title,
                    "idec": idec,
                    "desc": desc,
                    "has_video": has_video
                })

            # Výpočet start_ts a end_ts
            for idx, prog in enumerate(raw_items):
                try:
                    parts = prog["time_str"].split(":")
                    hour, minute = int(parts[0]), int(parts[1])
                except Exception:
                    continue

                # Pořady vysílané po půlnoci (před 05:00) patří kalendářně na další den
                prog_day = target_date + datetime.timedelta(days=1) if hour < 5 else target_date
                start_dt = datetime.datetime(prog_day.year, prog_day.month, prog_day.day, hour, minute, tzinfo=tz_prague)
                start_ts = int(start_dt.timestamp())

                # Konec je začátek dalšího pořadu, nebo +30 minut pro poslední
                if idx + 1 < len(raw_items):
                    try:
                        n_parts = raw_items[idx + 1]["time_str"].split(":")
                        n_h, n_m = int(n_parts[0]), int(n_parts[1])
                        n_day = target_date + datetime.timedelta(days=1) if n_h < 5 else target_date
                        end_dt = datetime.datetime(n_day.year, n_day.month, n_day.day, n_h, n_m, tzinfo=tz_prague)
                        if end_dt <= start_dt:
                            end_dt = start_dt + datetime.timedelta(minutes=30)
                    except Exception:
                        end_dt = start_dt + datetime.timedelta(minutes=30)
                else:
                    end_dt = start_dt + datetime.timedelta(minutes=30)

                end_ts = int(end_dt.timestamp())
                prog_id = f"{matched_channel}_{start_ts}"

                crud.upsert_epg_programme(
                    prog_id=prog_id,
                    channel_id=matched_channel,
                    date_str=date_str,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    start_time=prog["time_str"],
                    title=prog["title"],
                    description=prog["desc"],
                    idec=prog["idec"],
                    has_video=prog["has_video"]
                )
                total_saved += 1

        return total_saved
    except Exception as e:
        logger.error(f"Chyba při scrapování programu ČT pro {date_str}: {e}")
        return 0

async def update_external_epg():
    """Periodicky aktualizuje TV program ČT z webu ceskatelevize.cz pro předchozích 7 dní i následujících 7 dní."""
    global _cached_epg_xml, _cached_epg_time
    logger.info("Spouštím aktualizaci TV programu a EPG z oficiálního webu České televize...")

    headers = {
        "User-Agent": settings.USER_AGENT,
        "Referer": "https://www.ceskatelevize.cz/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    try:
        now_dt = datetime.datetime.now(ZoneInfo("Europe/Prague")).date()
        total_progs = 0

        async with httpx.AsyncClient(headers=headers, timeout=20.0, follow_redirects=True) as client:
            # Stahujeme program: -7 dní (pro Catchup) až +7 dní (pro EPG dopředu)
            for day_offset in range(-7, 8):
                day = now_dt + datetime.timedelta(days=day_offset)
                saved = await scrape_ct_schedule_for_date(day, client)
                total_progs += saved
                await asyncio.sleep(0.2)

        # Pročištění EPG staršího než 14 dní
        cutoff_ts = int(time.time()) - (14 * 86400)
        crud.clear_old_epg(cutoff_ts)

        # Regenerace XMLTV cache
        _cached_epg_xml = None
        generate_xmltv_epg(settings.BASE_URL or "https://ct.thelittlerock.cz")
        logger.info(f"EPG ČT úspěšně aktualizováno! Uloženo {total_progs} programových položek.")
    except Exception as e:
        logger.error(f"Chyba při běhu EPG aktualizátoru: {e}")

async def run_periodic_epg():
    """Běží nepřetržitě na pozadí a obnovuje TV program ČT každých 6 hodin."""
    while True:
        try:
            await update_external_epg()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Chyba v periodickém EPG runneru: {e}")
        await asyncio.sleep(21600)  # Každých 6 hodin

def generate_xmltv_epg(base_url: str) -> str:
    """Vygeneruje standardní XMLTV EPG pro všech 14 kanálů ČT z aktuální SQLite databáze."""
    global _cached_epg_xml, _cached_epg_time
    epg_file = settings.DATA_DIR / "ct_epg_cache.xml"

    # Vrátit z paměti, pokud je čerstvá (< 2 hodiny)
    if _cached_epg_xml and (time.time() - _cached_epg_time < 7200):
        return _cached_epg_xml

    tz_prague = ZoneInfo("Europe/Prague")
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<tv generator-info-name="iVysilani-Server" generator-info-url="{base_url}">'
    ]

    # 1. Definice všech 14 kanálů s lokálními logy
    for ch_id, ch in LIVE_CHANNELS.items():
        logo_url = ch["logo"]
        if logo_url.startswith("/"):
            logo_url = f"{base_url}{logo_url}"

        lines.append(f'  <channel id="{ch["epg_id"]}">')
        lines.append(f'    <display-name>{ch["name"]}</display-name>')
        lines.append(f'    <icon src="{logo_url}" />')
        lines.append('  </channel>')

    # 2. Načtení všech programů z SQLite databáze
    with crud.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT channel_id, start_ts, end_ts, title, description, idec, has_video
        FROM epg_programmes
        ORDER BY start_ts ASC
        """)
        progs = cursor.fetchall()

    for p in progs:
        start_dt = datetime.datetime.fromtimestamp(p["start_ts"], tz=tz_prague)
        end_dt = datetime.datetime.fromtimestamp(p["end_ts"], tz=tz_prague)
        start_xml = start_dt.strftime("%Y%m%d%H%M%S %z")
        stop_xml = end_dt.strftime("%Y%m%d%H%M%S %z")

        title_clean = p["title"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        desc_clean = p["description"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") if p["description"] else ""

        lines.append(f'  <programme channel="{p["channel_id"]}" start="{start_xml}" stop="{stop_xml}">')
        lines.append(f'    <title lang="cs">{title_clean}</title>')
        if desc_clean:
            lines.append(f'    <desc lang="cs">{desc_clean}</desc>')
        lines.append('  </programme>')

    lines.append('</tv>')
    full_xml = "\n".join(lines)

    try:
        epg_file.write_text(full_xml, encoding="utf-8")
    except Exception as e:
        logger.warning(f"Nelze zapsat EPG do cache souboru: {e}")

    _cached_epg_xml = full_xml
    _cached_epg_time = time.time()
    return full_xml
