import re
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import xml.etree.ElementTree as ET
from pathlib import Path
import httpx

from app.core.config import settings
from app.services.ct_service import LIVE_CHANNELS, ct_service

logger = logging.getLogger("epg_service")

# Mapování ID kanálů z externího XMLTV na naše standardní tvg-id
CT_EPG_MAP = {
    "ČT1.cz": "ct1.cz",
    "ČT2.cz": "ct2.cz",
    "ČT24.cz": "ct24.cz",
    "ČT.sport.cz": "ctsport.cz",
    "ČT.:D.cz": "ctd.cz",
    "ČT.art.cz": "ctart.cz"
}

_cached_epg_xml: Optional[str] = None
_cached_epg_time: float = 0.0

async def update_external_epg():
    """Stáhne a zpracuje aktuální XMLTV EPG pro české kanály."""
    global _cached_epg_xml, _cached_epg_time
    epg_file = settings.DATA_DIR / "ct_epg_cache.xml"

    # Kontrola stáří souboru na disku (aktualizace 1x za 12 hodin)
    if epg_file.exists() and (time.time() - epg_file.stat().st_mtime < 43200):
        try:
            _cached_epg_xml = epg_file.read_text(encoding="utf-8")
            _cached_epg_time = epg_file.stat().st_mtime
            logger.info("Načteno EPG z lokální cache disku.")
            return
        except Exception as e:
            logger.warning(f"Chyba při čtení lokální EPG cache: {e}")

    url = "https://epg.lat/files/cz.xml.gz"
    logger.info("Stahuji aktuální XMLTV data z epg.lat...")
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                raw_text = resp.text
                # Vyfiltrovat programové bloky pouze pro kanály ČT
                pattern = r'(<programme[^>]+channel=\"(' + '|'.join(re.escape(k) for k in CT_EPG_MAP.keys()) + r')\"[^>]*>.*?</programme>)'
                programmes = re.findall(pattern, raw_text, re.DOTALL)
                
                # Nahradit názvy kanálů našimi standardními identifikátory
                filtered_blocks = []
                for prog_text, orig_ch in programmes:
                    new_ch = CT_EPG_MAP.get(orig_ch, orig_ch)
                    # Nahradit channel="ČT1.cz" -> channel="ct1.cz"
                    block = re.sub(r'channel=\"[^\"]+\"', f'channel="{new_ch}"', prog_text, count=1)
                    filtered_blocks.append(block)

                extracted_xml = "\n".join(filtered_blocks)
                epg_file.write_text(extracted_xml, encoding="utf-8")
                _cached_epg_xml = extracted_xml
                _cached_epg_time = time.time()
                logger.info(f"EPG úspěšně aktualizováno. Uloženo {len(filtered_blocks)} pořadů ČT.")
    except Exception as e:
        logger.error(f"Chyba při stahování externího EPG: {e}")

def generate_xmltv_epg(base_url: str) -> str:
    """Vygeneruje standardní XMLTV EPG pro všech 14 kanálů ČT."""
    global _cached_epg_xml
    
    # 1. Hlavička XMLTV
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<tv generator-info-name="iVysilani-Server" generator-info-url="{base_url}">'
    ]

    # 2. Definice všech 14 kanálů s lokálními logy
    for ch_id, ch in LIVE_CHANNELS.items():
        logo_url = ch["logo"]
        if logo_url.startswith("/"):
            logo_url = f"{base_url}{logo_url}"
        
        lines.append(f'  <channel id="{ch["epg_id"]}">')
        lines.append(f'    <display-name>{ch["name"]}</display-name>')
        lines.append(f'    <icon src="{logo_url}" />')
        lines.append('  </channel>')

    # 3. Pokud máme reálná EPG data, vložíme je
    if _cached_epg_xml:
        lines.append(_cached_epg_xml)
    else:
        # Fallback bloky, pokud ještě nebyla stažena externí data
        now = datetime.now(timezone.utc)
        for ch_id, ch in LIVE_CHANNELS.items():
            for hour_offset in range(-12, 12, 2):
                start_dt = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=hour_offset)
                stop_dt = start_dt + timedelta(hours=2)
                start_str = start_dt.strftime("%Y%m%d%H%M%S +0000")
                stop_str = stop_dt.strftime("%Y%m%d%H%M%S +0000")
                title = f"Vysílání {ch['name']} ({start_dt.strftime('%H:%M')})"
                lines.append(f'  <programme start="{start_str}" stop="{stop_str}" channel="{ch["epg_id"]}">')
                lines.append(f'    <title lang="cs">{title}</title>')
                lines.append(f'    <desc lang="cs">{ch["description"]}</desc>')
                lines.append('  </programme>')

    # 4. Uzavření dokumentu
    lines.append('</tv>')
    return "\n".join(lines)
