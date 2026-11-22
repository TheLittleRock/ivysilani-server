# Changelog

Všechny významné změny v projektu **iVysílání Server** jsou dokumentovány v tomto souboru.

Formát vychází z [Keep a Changelog](https://keepachangelog.com/cs/1.0.0/) a projekt dodržuje [Sémantické verzování](https://semver.org/spec/v2.0.0.html).

---

## [2.2.0] - 2026-11-22

### Opraveno (Fixed)
- **Xtream Series Season Reporting (Oprava Season 0 u seriálů v Crawleru):**
  - Vyřešena chyba, kdy stahovač (Crawler / `xtream-gui-linux`) ukládal všechny epizody seriálů jako `S00` (např. `Čtyřlístek.S00E11.mp4`).
  - V odpovědi akce `get_series_info` v `player_api.php` chybělo v objektu každé epizody i ve vnořeném `info` pole `season`, což v Go unmarshaleru ponechávalo celočíselnou proměnnou `ep.Season` na výchozí nule.
  - Doplněna explicitní pole `season`, `season_num` a `season_number` (jako `int`) přímo do každé epizody i do objektu `info`, včetně správného číslování speciálů (`season = 0`).
- **Jemné doladění synchronizace titulků (+1.8s Audio/Video Sync):**
  - Posun WebVTT titulků byl zkalibrován z `2.5s` na `1.8s`, čímž bylo odstraněno drobné zpoždění (zlomek sekundy za mluveným slovem). Titulky se nyní zobrazují přesně ve chvíli, kdy postava promluví.
  - Přidána možnost dynamické konfigurace posunu titulků přes databázi `app_settings` (`subtitle_offset_seconds`) a nové administrační rozhraní (`/admin#subtitles-settings`).
- **Oprava rozpadlého horního navigačního panelu:**
  - Upraven layout a zkráceny popisky navigačních položek (přidáno `whitespace-nowrap shrink-0` a přepnutí responzivního breakpointu na `lg:`). Tlačítka se již nezalamují do dvou řádků ani na menších monitorech a noteboocích (1024–1366 px).
- **Moderní tmavé scrollbary pro celou aplikaci:**
  - Odstraněny nevzhledné nativní bílé posuvníky prohlížeče se šipkami v seznamu televizních stanic, výběru dnů v programu a v seznamu EPG.
  - Zavedeny stylové tenké poloprůhledné posuvníky (`.custom-scrollbar` a globální `::-webkit-scrollbar` / `scrollbar-width: thin`) ladící s tmavým designem aplikace.
  - Lišta s výběrem dnů TV programu byla přesunuta na samostatný plnošířkový řádek pro pohodlné procházení.
- **Xtream Codes VOD/Series ID Typecast (Go Client Compatibility):**
  - Opravena kritická chyba `json: cannot unmarshal string into Go struct field VodStream.stream_id of type int`, která způsobovala `HTTP 502 Bad Gateway` v Go klientech (např. `xtream-gui-linux` / crawler).
  - Všechna `stream_id` a `series_id` v `get_vod_streams`, `get_series`, `get_vod_info` i `get_series_info` jsou nyní přetypována na celočíselný `int` přes bezpečnou funkci `to_int_id()`.
- **Nativní GZip komprese odpovědí:**
  - Do FastAPI přidán `GZipMiddleware(minimum_size=1000)`. Odpovědi katalogů s tisíci položkami se komprimují z ~570 KB na ~45 KB, což zabraňuje přetečení vyrovnávací paměti (buffer overflow) v OpenResty / Nginx Proxy Manageru.
- **Odstranění DRM ze živého vysílání (StarDance, licence ČT):**
  - Implementováno automatické rozpoznání šifrovaného DASH/HLS živého streamu (`wv` / `drmOnly=true`). Server automaticky přesměruje požadavek na plovoucí unencrypted timeshift okno (`allow_drm=False`), čímž eliminuje varovné DRM hlášky v přehrávači.
- **Timeshift a Catch-up přímé endpointy:**
  - Doplněny cesty `/timeshift/{user}/{pass}/{duration}/{start}/{stream_filename}` a `/timeshift/{token}/{duration}/{start}/{stream_filename}`.
  - Vylepšen regex parser časových razítek pro podporu formátů `YYYY-MM-DD:HH-MM`, `YYYYMMDDHHMMSS`, `YYYYMMDDHHMM` a Unix timestamps.
- **Responzivní navigace na mobilních zařízeních:**
  - Opraveno mobilní menu v `base.html` – záložky Živě, Archiv, Stahování, IPTV, Stremio a Administrace jsou nyní plně přístupné i z malých obrazovek.
- **Normalizace slugů u seriálů:**
  - Opraveno parsování `series_id` s textovými příponami (např. `13478071605-oktopus` -> `13478071605`), aby se správně dohledávaly všechny díly v databázi.

### Přidáno (Added)
- **Centralizované verzování:**
  - Modul `app/version.py` s funkcí `get_version_info()`.
  - Nový endpoint `GET /api/version` poskytující JSON s verzí, git commitem a verzemi jednotlivých rozhraní.
  - Zobrazení verze v hlavičce a patičce webového rozhraní a v administraci (`v2.2.0`).
- **Integrace doplňku pro StreamCube:**
  - Plnohodnotná podpora StreamCube SDK v1 (`/streamcube/manifest.json`, podpora živého vysílání, VOD katalogů a M3U exportu).
- **Enrichment vertikálních plakátů (2:3 Canvas Padding):**
  - Napojení na GraphQL `cardPortrait` z CDN České televize s automatickým canvas paddingem do poměru 2:3 a TMDB fallbacks pro ideální zobrazení ve Stremio, TiviMate a crawleru.
- **AI Handover Dokumentace:**
  - Vytvořen soubor `AGENT_HANDOVER.md` pro kompletní a bezeztrátové předání kontextu mezi AI agenty.

---

## [2.1.0] - 2026-11-21

### Přidáno (Added)
- **Kompletní EPG & Catchup scraper:**
  - Automatické stahování oficiálního TV programu České televize pro 14 stanic na 14 dní dopředu i dozadu z `ceskatelevize.cz`.
  - Generování XMLTV EPG na `/xmltv.php` s mapováním kanálů a vysílacích časů.
  - Implementace timeshift streamu na `/streaming/timeshift.php` pro TiviMate a IPTV přehrávače.
- **Stremio Addon katalogy:**
  - Implementovány podkategorie seriálů i filmů (Krimi, Komedie, České, Zahraniční, Dokumenty, Pohádky atd.).
  - Filtrování streamů – Stremio manifest striktně odděluje VOD od Live TV.
- **Rychlý live polling stahování:**
  - Zkrácen polling interval správce stahování na 1.5s pro okamžitou odezvu a ukládání souborů v Plex formátu.

### Opraveno (Fixed)
- **HbbTV DRM Fallback:**
  - Vyřešeno přehrávání pořadů vyžadujících Widevine DRM (např. Bod obnovy) přes unencrypted 1080p HbbTV HLS stream.
- **CORS u titulků a volba zvukové stopy:**
  - Opravena CORS hlavička u WebVTT titulků a přidána podpora vícejazyčných stop v Shaka Playeru.

---

## [2.0.0] - 2026-11-01

### Změněno (Changed)
- **Kompletní přepis architektury na FastAPI a SQLite:**
  - Nahrazení starých PHP/skriptovacích komponent jednotnou FastAPI backend architekturou v Pythonu.
  - Kontejnerizace do Dockeru a nasazení přes GitHub Actions na produkční server `koleje`.
  - Zavedení rotujícího loggeru do `data/logs/ivysilani.log` (10 MB, 5 rotací).
- **Xtream Codes server:**
  - Implementace rozhraní `player_api.php`, `/live/`, `/movie/` a `/series/`.
- **Stremio v2 Addon:**
  - Vytvoření doplňku kompatibilního se specifikací Stremio v2.

---

## [1.0.0] - 2026-10-31

### Přidáno (Added)
- Počáteční verze iVysílání Serveru.
- Základní webový přehrávač pro živé kanály ČT1, ČT2, ČT24, ČT sport, ČT :D a ČT art.
- Scraper archivu a stahovač streamů.
