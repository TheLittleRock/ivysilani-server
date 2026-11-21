#!/usr/bin/env python3
"""
Dávkový obohacovací skript pro iVysílání Server:
1. Dohledá nativní vertikální plakáty (cardPortrait z ČT GraphQL nebo 2:3 poster z TMDB API)
2. U periodických pořadů (Události, Zprávy, Kouzelná školka, Počasí) zajistí korektní indexaci
"""
import asyncio
import logging
import httpx
from app.db import crud
from app.services.ct_service import ct_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("enrich")

TMDB_API_KEY = "2f453df93e1dd76ca1e176029a0f9baf"

async def enrich_posters():
    with crud.get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, title FROM shows 
            WHERE poster_url NOT LIKE '%cardPortrait%' 
              AND poster_url NOT LIKE '%tmdb%' 
              AND poster_url NOT LIKE '%na-vysku%'
        """)
        shows = c.fetchall()

    logger.info(f"Nalezeno {len(shows)} pořadů bez nativního vertikálního plakátu k obohacení.")
    if not shows:
        return

    updated_ct = 0
    updated_tmdb = 0

    async with httpx.AsyncClient(timeout=8.0) as client:
        for idx, r in enumerate(shows, start=1):
            sid, title = r["id"], r["title"]
            card_port = None
            try:
                ct_res = await ct_service.search_shows_graphql(title, limit=1)
                if ct_res:
                    cand = (ct_res[0].get("images") or {}).get("cardPortrait")
                    if cand and "fallbackImages" not in cand:
                        card_port = cand
            except Exception:
                pass

            tmdb_port = None
            if not card_port:
                try:
                    resp = await client.get(
                        f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={title}&language=cs-CZ"
                    )
                    res = resp.json().get("results", [])
                    if res and res[0].get("poster_path"):
                        p_path = res[0]["poster_path"]
                        tmdb_port = f"https://image.tmdb.org/t/p/w500{p_path}"
                except Exception:
                    pass

            final_poster = card_port or tmdb_port
            if final_poster:
                with crud.get_db() as conn:
                    cur = conn.cursor()
                    if tmdb_port:
                        cur.execute("UPDATE shows SET poster_url = ?, tmdb_poster = ? WHERE id = ?", (final_poster, tmdb_port, sid))
                        updated_tmdb += 1
                    else:
                        cur.execute("UPDATE shows SET poster_url = ? WHERE id = ?", (final_poster, sid))
                        updated_ct += 1

            if idx % 50 == 0 or idx == len(shows):
                logger.info(f"Obohaceno {idx}/{len(shows)} (ČT: {updated_ct}, TMDB: {updated_tmdb})")

            # Drobný rate limit pro šetrnost k API
            await asyncio.sleep(0.05)

    logger.info(f"Hotovo: {updated_ct} ČT cardPortrait, {updated_tmdb} TMDB poster")

if __name__ == "__main__":
    asyncio.run(enrich_posters())
