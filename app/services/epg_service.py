import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
import xml.etree.ElementTree as ET

from app.services.ct_service import LIVE_CHANNELS

def generate_xmltv_epg(base_url: str) -> str:
    """Vygeneruje standardní XMLTV EPG pro všech 14 kanálů ČT."""
    root = ET.Element("tv", {
        "generator-info-name": "iVysilani-Server",
        "generator-info-url": base_url
    })

    # 1. Kanály
    for ch_id, ch in LIVE_CHANNELS.items():
        channel_el = ET.SubElement(root, "channel", {"id": ch["epg_id"]})
        name_el = ET.SubElement(channel_el, "display-name")
        name_el.text = ch["name"]
        icon_el = ET.SubElement(channel_el, "icon", {"src": ch["logo"]})

    # 2. Programové položky (pro dnešek a včerejšek)
    now = datetime.now(timezone.utc)
    for ch_id, ch in LIVE_CHANNELS.items():
        # Vytvoření časových slotů (orientační generování pro EPG průvodce)
        for hour_offset in range(-24, 24, 2):
            start_dt = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=hour_offset)
            stop_dt = start_dt + timedelta(hours=2)

            start_str = start_dt.strftime("%Y%m%d%H%M%S +0000")
            stop_str = stop_dt.strftime("%Y%m%d%H%M%S +0000")

            prog_el = ET.SubElement(root, "programme", {
                "start": start_str,
                "stop": stop_str,
                "channel": ch["epg_id"]
            })
            title_el = ET.SubElement(prog_el, "title", {"lang": "cs"})
            if ch_id == "CH_24":
                title_el.text = f"Zprávy ČT24 ({start_dt.strftime('%H:%M')})"
            elif ch_id == "CH_4":
                title_el.text = f"Sportovní zprávy a přenosy ({start_dt.strftime('%H:%M')})"
            else:
                title_el.text = f"Vysílání {ch['name']} ({start_dt.strftime('%H:%M')})"

            desc_el = ET.SubElement(prog_el, "desc", {"lang": "cs"})
            desc_el.text = ch["description"]

    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
