# Changelog

Všechny významné změny v projektu **iVysílání Server** jsou dokumentovány v tomto souboru.

Formát vychází z [Keep a Changelog](https://keepachangelog.com/cs/1.0.0/) a projekt dodržuje [Sémantické verzování](https://semver.org/spec/v2.0.0.html).

---

## [2.2.3] - 2026-11-22

### Opraveno (Fixed)
- **Korektní číslování epizod v Xtream Codes VOD a scraperu (Per-Season Episode Numbering):**
  - Vyřešena chyba, kdy crawler čísloval epizody se shifted indexy (např. u animovaného seriálu *Čtyřlístek* začínala 1. série dílem `04` a 2. série dílem `11`).
  - **Příčina:**
    1. U seriálů, jejichž epizody nemají v názvu číslo dílu (např. *Kamarádi z Třeskoprsk*), scraper použil globální čítač `idx` běžící přes všechny série najednou. Speciály (Série 90) dostaly díly 1..3, 1. série díly 4..10 a 2. série díly 11..16.
    2. Xtream Codes API (`get_series_info`) tyto posunuté indexy předávalo přímo crawleru.
  - **Řešení:**
    1. V `app/services/ct_service.py` (`scrape_show_metadata`) implementován nezávislý čítač epizod pro každou sérii (`season_counters[season_num]`), bezpečné parsování z IDEC a finální normalizační průchod, který garantuje sekvenci 1..N v každé sérii.
    2. V `app/api/xtream.py` (`get_series_info`) přidána automatická normalizační vrstva: pokud epizody v libovolné sérii nezačínají od 1 nebo obsahují mezery/duplicity, jsou automaticky srovnány na 1..N.
    3. Opraveno bezpečné procházení GraphQL odpovědi v `get_episodes_for_programme` (zamezení `AttributeError: 'NoneType' object has no attribute 'get'`).
    4. Rozšířeno vyhledávání v `app/db/crud.py` (`get_episode_by_id_or_idec`) pro spolehlivou obsluhu filmů i dílů bez ohledu na formát ID.
- **Garance doručení titulků do Crawleru a HLS přehrávačů:**
  - V `app/api/stream.py` (`get_hls_master_playlist`) upraveno vkládání titulků: pokud pořad nabízí titulky, jsou případné původní CDN odkazy vždy nahrazeny naší vyčištěnou proxy stopou `/api/hls/subtitles/{idec}.m3u8` s posunem +1.8s a X-TIMESTAMP-MAP.
  - V crawleru na serveru vyčištěna knihovna od dříve stažených poškozených souborů z ranních hodin (kdy ještě nebyl nasazen HLS subtitle fix).

---

## [2.2.2] - 2026-11-22

### Opraveno (Fixed)
- **Kompletní oprava stahování titulků v Crawleru (RFC 8216 HLS Master Playlist & Subtitle M3U8):**
  - Vyřešena chyba stahovače (`xtream-gui-linux`): `výhrady: zdroj nabízel titulky, v souboru žádné nejsou` (`[mux] skládám slepené stopy: 1 obraz, 1 zvuk, 0 titulky`).
  - **Příčina:**
    1. Hlubokým reverzním inženýrstvím Go binárky `xtream-gui-linux` (symboly `runHLSFallbackSmart`, `isDirectVTT`, `parseMaster`) bylo zjištěno, že pokud `#EXT-X-MEDIA:TYPE=SUBTITLES` obsahuje přímou URL končící na `.vtt`, funkce `isDirectVTT` vrátí `true`, což způsobí okamžitý skok přes prefetch smyčku a vynechání registrace stopy pro finální muxování.
    2. Crawler vyžaduje HLS subtitle playlist (`.m3u8`), uvnitř kterého segment končí na `.vtt` (ověřeno funkcí `playlistLooksLikeSegmentedVTT`).
    3. Původní master playlist měl prokládané tagy `#EXT-X-MEDIA:TYPE=AUDIO` a `#EXT-X-STREAM-INF:`. Go parser v `parseMaster` zahazuje variantu, pokud za `#EXT-X-STREAM-INF:` bezprostředně nenásleduje video URL, ale další `#EXT-X-MEDIA` tag.
  - **Řešení:**
    1. V `app/api/stream.py` upraven `get_hls_master_playlist`: podle RFC 8216 jsou nyní na začátku master playlistu seřazeny všechny audio a titulkové `#EXT-X-MEDIA` tagy, následované jednotlivými `#EXT-X-STREAM-INF:` tagy (každý s atributem `SUBTITLES="subs"` a bezprostředně následující video URL).
    2. Tag titulků `#EXT-X-MEDIA:TYPE=SUBTITLES` v master playlistu vždy odkazuje na `/api/hls/subtitles/{idec}.m3u8`.
    3. HLS subtitle playlist `/api/hls/subtitles/{idec}.m3u8` poskytuje segment `/api/subtitles/{idec}.vtt`, což v crawleru aktivuje detekci `playlistLooksLikeSegmentedVTT`, stažení segmentu `0.vtt`, spojení do `joined.vtt` a korektní muxování do výsledného MP4 (`Stream #0:2: Subtitle: mov_text`).
    4. Přidán HTTP access log middleware v `app/main.py` pro okamžitou diagnostiku a přehled všech požadavků z crawleru a klientů.

---

## [2.2.1] - 2026-11-22

### Opraveno (Fixed)
- **Titulky při stahování v Crawleru (Direct WebVTT & HLS Segment VTT Fix):**
  - Vyřešena chyba stahovače (`xtream-gui-linux`): `výhrady: zdroj nabízel titulky, v souboru žádné nejsou` (`[mux] 1 titulkových stop se nepodařilo spojit, do filmu se nedostaly`).
  - **Příčina:** Crawler ve svém interním stahovacím engine (`internal/download`) provádí kontrolu přípon segmentů pomocí `playlistLooksLikeSegmentedVTT` a `isDirectVTT`. Dosavadní segmentový odkaz v M3U8 byl `/api/subtitles?url=...` (bez přípony v cestě URL), což vedlo k detekci `looksVTT = false` a vyprázdnění seznamu segmentů k fúzi.
  - **Řešení:**
    1. Vytvořen dedikovaný endpoint `/api/subtitles/{idec}.vtt`, který přímo stahuje, zpožďuje (+1.8s) a vrací WebVTT titulky pro daný pořad s korektní příponou `.vtt`.
    2. V HLS WebVTT playlistu `/api/hls/subtitles/{idec}.m3u8` nyní segment odkazuje na `/api/subtitles/{idec}.vtt`.
    3. Pro klienty typu Crawler (`xtream-tui`, `xtream-gui` nebo dotazy přes parametr `xtream=1`) vkládá master playlist do tagu `#EXT-X-MEDIA:TYPE=SUBTITLES` přímý odkaz `URI="/api/subtitles/{idec}.vtt"`, což v crawleru aktivuje nativní větev `isDirectVTT` (přímé stažení `single.vtt` bez jakéhokoliv selhání spojování a bez nutnosti serializace).
    4. Běžné přehrávače (VLC, TiviMate, ExoPlayer) nadále dostávají standardní HLS Media Playlist `/api/hls/subtitles/{idec}.m3u8`.
    5. Titulky se nyní při stahování bezchybně vkládají do MP4 kontejneru (`Stream #0:2: Subtitle: mov_text`).

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
