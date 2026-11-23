# Changelog

Všechny významné změny v projektu **iVysílání Server** jsou dokumentovány v tomto souboru.

Formát vychází z [Keep a Changelog](https://keepachangelog.com/cs/1.0.0/) a projekt dodržuje [Sémantické verzování](https://semver.org/spec/v2.0.0.html).

---

## [2.3.4] - 2026-11-23

### Opraveno (Fixed)
- **Okamžité přehrávání ve Full HD (1080p) z M3U a Live streamů:**
  - Endpoint `/live/{token}/{stream_filename}` dynamicky přepisuje HLS master playlist živého vysílání tak, aby výchozí a primární video variantou byl 1080p stream (FHD). Tím se zcela eliminuje počáteční zpožděné přepínání z nízkého rozlišení (180p/360p) v IPTV aplikacích (TiviMate, Kodi, VLC, Televizo, OTT Navigator).
  - Všechny audio stopy (včetně prostorového zvuku a zvukového popisu) a WebVTT titulky zůstávají plně zachovány v souladu s RFC 8216.
  - Do M3U playlistu (`/get.php`) přidány vlastnosti `#KODIPROP:inputstream.adaptive.default_bandwidth=100000000`, `max_bandwidth=100000000` a `stream_selection_type=auto` pro okamžitý start v plné kvalitě v přehrávači Kodi.
  - VOD master playlist `/api/hls/master/{idec}.m3u8` nyní řadí varianty sestupně podle datového toku (1080p vždy první) a endpointy pro zpětné zhlédnutí (`/streaming/timeshift.php` i catch-up v `/live`) automaticky požadují `quality=1080p`.
- **Automatické a perzistentní zarovnání sérií a epizod podle TMDb:**
  - V `app/services/archive_crawler.py` integrováno okamžité volání `tmdb_service.enrich_show_metadata` a `tmdb_service.align_show_episodes` do metody `index_show`. Každý nově zaindexovaný nebo zaktualizovaný seriál je ihned automaticky zarovnán podle struktury TMDb přímo v SQLite databázi.
  - Po dokončení celkového indexačního cyklu `crawl_entire_catalog` se automaticky spouští hromadná kontrola a reindexace všech seriálů v katalogu.
  - Odstraněno blokující omezení `len(tmdb_seasons) <= 1` v `align_show_episodes`, které bránilo opravě pořadů s anomálními čísly řad (např. *Ať žijí rytíři!*, *Špačkovi v síti času*).
  - V `app/services/tmdb_service.py` je stav zarovnání (`is_show_aligned`) nyní trvale ukládán do tabulky `app_settings` (`aligned_{show_id}`), takže přetrvá restart serveru a kontejneru.
  - Vylepšena normalizace názvů epizod `clean_episode_title` i `normalize_title` o spolehlivější ořezávání prefixů číslování (`1/13 `, `1. `, `Díl 1: ` apod.).
  - Opravena detekce v `parse_season_number` – pravidlo pro řadu 6 u *Vyprávěj Osudy* bylo omezeno pouze na seriál *Vyprávěj*, čímž se předešlo chybnému zařazování nesouvisejících pořadů s "osudy" v názvu do 6. série.
  - Vyčištěna všechna historická anomální čísla sérií v databázi (hodnoty 31 až 1899) a provedena kompletní reindexace všech problematických seriálů (*Komisař Montalbano*, *Četnické humoresky*, *Bob a Bobek*, *Ranč U Zelené sedmy*, *Manželské etudy*, *Ať žijí rytíři!*, *Špačkovi v síti času*).

---

## [2.3.3] - 2026-11-23

### Opraveno (Fixed)
- **Oprava směrování Live TV streamů a odstranění DRM chybové obrazovky:**
  - Odstraněna chybná detekce `is_drm = "drmOnly=true" in dash_main`, která byla na kanálech ČT1, ČT2, ČT sport, ČT :D a ČT art permanentně vyhodnocována jako aktivní DRM.
  - Odstraněno chybné nahrazování živého HLS streamu 4hodinovým statickým timeshift playlistem (`duration=14400`), který obsahoval stovky historických segmentů z dřívějších pořadů s DRM varovným statickým obrazem („Pořad nelze přehrát v tomto prohlížeči. Použijte prohlížeč s podporou DRM“).
  - Obnoven nativní živý HLS feed (`contentType=live&origin=hbbtv`) pro přehrávání aktuálního vysílání v reálném čase bez zpoždění, vyrovnávací paměti z minulých pořadů a bez červené DRM hlášky.
  - Zkrácena doba mezipaměti živého vysílání v `get_live_stream` z 300s na 60s pro okamžitou reakci na střídání pořadů.

### Přidáno (Added)
- **Podpora Live TV Widevine DASH přes DRM Proxy:**
  - Do `/live/{token}/{stream_filename}` přidána podpora přípony `.mpd`. Pokud klient vyžádá formát `.mpd` (např. `/live/{token}/2.mpd`), server inicializuje live DRM proxy relaci a přesměruje na dynamický lokální MPD manifest.
  - Endpoint `/stream/live/{channel_id}` automaticky přepíná na Widevine DASH proxy v případě, že je vyžádán DRM stream nebo živý pořad vyžaduje Widevine ochranu.
  - Do Stremio doplňku přidána volitelná druhá stopa živého vysílání s Widevine DASH DRM pro klienty s nativní podporou DRM přehrávání.

---

## [2.3.2] - 2026-11-22

### Opraveno (Fixed)
- **Zachování přesného číslování dílů při neúplných sériích na iVysílání (TMDb Alignment by Name):**
  - Vyřešena chyba u seriálů, které nemají na iVysílání publikovány všechny epizody (např. *Bob a Bobek* – 3. série má z 13 epizod online pouze 7 dílů).
  - Původní normalizační logika při `min(nums) > 1` chybně přečíslovala epizody `6, 8, 9, 10, 11, 12, 13` na sekvenci `1, 2, 3, 4, 5, 6, 7`. V důsledku toho byl díl *V galerii* (epizoda 6) označen jako S03E01 (což v TMDb odpovídá dílu *Šťastní výherci*).
  - Pro seriály zarovnané podle TMDb bylo zrušeno přepisování čísel dílů. Každá epizoda si striktně zachovává své skutečné číslo a řadu podle TMDb, i když některé úvodní nebo mezilehlé díly na iVysílání chybí.
- **Oprava sloučených sérií (Komisař Montalbano):**
  - Vyřešena chyba, kdy byly úvodní řady komisaře Montalbana sloučeny do jediné 1. série (původně 10 dílů v S01).
  - Všech 37 dílů je nyní rozděleno a očíslováno do všech 15 sérií přesně podle standardu TMDb (S01: 2 díly, S02: 2 díly, S03: 2 díly, S04: 4 díly, S05: 2 díly atd.).
  - Upravena logika on-demand i dávkového přeindexování v `app/api/xtream.py` a `app/services/archive_crawler.py` – zarovnání se spouští i v případě mezer v sériích (`has_gaps`), vysokých čísel řad či nadbytku dílů v 1. sérii.
- **Oprava parsování formátů stopáže v `parse_season_number`:**
  - Formáty stopáže a počty dílů jako `42× 26 minut` nebo `21× 52 minut` z ČT webu jsou nyní odfiltrovány a nejsou chybně parsovány jako extrémní čísla sérií (např. Série 42 a 21 u *Ranče U Zelené sedmy*).

---

## [2.3.1] - 2026-11-22

### Opraveno (Fixed)
- **Synchronizace titulků (Nativní časování ČT / Odstranění zpoždění):**
  - Nastavena výchozí hodnota posunu titulků `SUBTITLE_OFFSET_SECONDS` na `0.0s`.
  - Původní umělý posun +1.8s (historicky přidávaný před zavedením MPEG-TS časové mapy `X-TIMESTAMP-MAP`) způsoboval ve stažených souborech (např. *Zorro*) cca 2sekundové zpoždění titulků za zvukem.
  - S časovým posunem 0.0s jsou titulky v dokonalé synchronizaci s nativním zvukovým doprovodem České televize.
- **Správa fronty stahování a vyčištění chybných sérií:**
  - Z fronty stahování a odesílání byly odstraněny dříve stažené položky seriálů *Komisař Montalbano* a *Molang*, které měly nesprávné číslování před TMDb zarovnáním.
  - Disková úložiště byla pročištěna, což umožňuje jejich čisté a bezchybné znovustažení se správnou strukturou sérií a epizod.
- **Sanitizace dokumentace:**
  - Kompletní pročištění repozitáře a dokumentace od zmínek o proprietárních klientských nástrojích.

---

## [2.3.0] - 2026-11-22

### Přidáno (Added)
- **TMDb zarovnání a přeindexování sérií a epizod (TMDb Season & Episode Alignment):**
  - Vyřešen zásadní problém, kdy ČT iVysílání eviduje mnohé dlouhé seriály (např. *Komisař Montalbano*, *13. komnata*, *Pan Tau*, *Dobrodružství kriminalistiky*, *Nemocnice na kraji města*) v jediné ploše 1. sérii, zatímco mezinárodní standard TMDb je člení do desítek sérií.
  - V důsledku této neshody externí stahovače po stažení dílů S01 zahazovaly všechny díly přesahující počet epizod 1. série v TMDb.
  - V `app/services/tmdb_service.py` implementována metoda `get_tv_episodes` pro načtení kompletní struktury všech sérií a dílů z TMDb API.
  - Implementováno chytré párování názvů `match_tokens` a normalizace `normalize_title` (zvládající českou flexi/skloňování, např. *Tereza Pergnerová* vs. *13. komnata Terezy Pergnerové*).
  - Přidána metoda `align_show_episodes(show_id)` pro automatické přerozdělení epizod do správných sérií a dílů přímo v databázi.
  - V `app/api/xtream.py` v endpointu `get_series_info` přidáno lazy/on-demand zarovnání: pokud je vyžádán seriál, který má v iVysílání všechny díly v 1. sérii, automaticky se na pozadí ověří a přeindexuje podle TMDb.
  - Do administrace (`admin.html`, `web.py`) přidáno tlačítko a endpoint `POST /api/admin/reindex-tmdb` pro kompletní dávkové přeindexování všech seriálů v katalogu na pozadí.
  - Vyřešeno hromadné odstranění 157 položek pořadu *13. komnata* z externí fronty stahování (`queue.json`).
- **Import oprav:**
  - V `app/services/ct_service.py` doplněn chybějící import `defaultdict` z `collections`.

---

## [2.2.3] - 2026-11-22

### Opraveno (Fixed)
- **Korektní číslování epizod v Xtream Codes VOD a scraperu (Per-Season Episode Numbering):**
  - Vyřešena chyba, kdy externí stahovací klienti číslovali epizody se shifted indexy (např. u animovaného seriálu *Čtyřlístek* začínala 1. série dílem `04` a 2. série dílem `11`).
  - **Příčina:**
    1. U seriálů, jejichž epizody nemají v názvu číslo dílu (např. *Kamarádi z Třeskoprsk*), scraper použil globální čítač `idx` běžící přes všechny série najednou. Speciály (Série 90) dostaly díly 1..3, 1. série díly 4..10 a 2. série díly 11..16.
    2. Xtream Codes API (`get_series_info`) tyto posunuté indexy předávalo přímo připojeným klientům.
  - **Řešení:**
    1. V `app/services/ct_service.py` (`scrape_show_metadata`) implementován nezávislý čítač epizod pro každou sérii (`season_counters[season_num]`), bezpečné parsování z IDEC a finální normalizační průchod, který garantuje sekvenci 1..N v každé sérii.
    2. V `app/api/xtream.py` (`get_series_info`) přidána automatická normalizační vrstva: pokud epizody v libovolné sérii nezačínají od 1 nebo obsahují mezery/duplicity, jsou automaticky srovnány na 1..N.
    3. Opraveno bezpečné procházení GraphQL odpovědi v `get_episodes_for_programme` (zamezení `AttributeError: 'NoneType' object has no attribute 'get'`).
    4. Rozšířeno vyhledávání v `app/db/crud.py` (`get_episode_by_id_or_idec`) pro spolehlivou obsluhu filmů i dílů bez ohledu na formát ID.
- **Garance doručení titulků do externích stahovačů a HLS přehrávačů:**
  - V `app/api/stream.py` (`get_hls_master_playlist`) upraveno vkládání titulků: pokud pořad nabízí titulky, jsou případné původní CDN odkazy vždy nahrazeny naší vyčištěnou proxy stopou `/api/hls/subtitles/{idec}.m3u8` s posunem a X-TIMESTAMP-MAP.
  - Ve stahovacím klientu na serveru vyčištěna knihovna od dříve stažených poškozených souborů z ranních hodin (kdy ještě nebyl nasazen HLS subtitle fix).

---

## [2.2.2] - 2026-11-22

### Opraveno (Fixed)
- **Kompletní oprava stahování titulků v externích stahovačích (RFC 8216 HLS Master Playlist & Subtitle M3U8):**
  - Vyřešena chyba stahovacích klientů: `výhrady: zdroj nabízel titulky, v souboru žádné nejsou` (`[mux] skládám slepené stopy: 1 obraz, 1 zvuk, 0 titulky`).
  - **Příčina:**
    1. Analýzou chování stahovacích HLS klientů bylo zjištěno, že pokud `#EXT-X-MEDIA:TYPE=SUBTITLES` obsahuje přímou URL končící na `.vtt`, některé Go parser enginy detekují přímý WebVTT soubor a přeskočí prefetch smyčku, což vedlo k vynechání registrace stopy pro finální muxování.
    2. Klient vyžaduje HLS subtitle playlist (`.m3u8`), uvnitř kterého segment končí na `.vtt`.
    3. Původní master playlist měl prokládané tagy `#EXT-X-MEDIA:TYPE=AUDIO` a `#EXT-X-STREAM-INF:`. Některé parsery zahazují variantu, pokud za `#EXT-X-STREAM-INF:` bezprostředně nenásleduje video URL, ale další `#EXT-X-MEDIA` tag.
  - **Řešení:**
    1. V `app/api/stream.py` upraven `get_hls_master_playlist`: podle RFC 8216 jsou nyní na začátku master playlistu seřazeny všechny audio a titulkové `#EXT-X-MEDIA` tagy, následované jednotlivými `#EXT-X-STREAM-INF:` tagy (každý s atributem `SUBTITLES="subs"` a bezprostředně následující video URL).
    2. Tag titulků `#EXT-X-MEDIA:TYPE=SUBTITLES` v master playlistu vždy odkazuje na `/api/hls/subtitles/{idec}.m3u8`.
    3. HLS subtitle playlist `/api/hls/subtitles/{idec}.m3u8` poskytuje segment `/api/subtitles/{idec}.vtt`, což v externím stahovači aktivuje správnou segmentovou detekci, stažení segmentu `0.vtt`, spojení do `joined.vtt` a korektní muxování do výsledného MP4 (`Stream #0:2: Subtitle: mov_text`).
    4. Přidán HTTP access log middleware v `app/main.py` pro okamžitou diagnostiku a přehled všech požadavků ze stahovačů a IPTV klientů.

---

## [2.2.1] - 2026-11-22

### Opraveno (Fixed)
- **Titulky při stahování v externích stahovačích (Direct WebVTT & HLS Segment VTT Fix):**
  - Vyřešena chyba stahovače: `výhrady: zdroj nabízel titulky, v souboru žádné nejsou` (`[mux] 1 titulkových stop se nepodařilo spojit, do filmu se nedostaly`).
  - **Příčina:** Někteří stahovací klienti ve svém stahovacím engine provádějí striktní kontrolu přípon segmentů. Dosavadní segmentový odkaz v M3U8 byl `/api/subtitles?url=...` (bez přípony v cestě URL), což vedlo k chybě a vyprázdnění seznamu segmentů k fúzi.
  - **Řešení:**
    1. Vytvořen dedikovaný endpoint `/api/subtitles/{idec}.vtt`, který přímo stahuje a vrací WebVTT titulky pro daný pořad s korektní příponou `.vtt`.
    2. V HLS WebVTT playlistu `/api/hls/subtitles/{idec}.m3u8` nyní segment odkazuje na `/api/subtitles/{idec}.vtt`.
    3. Pro externí klienty nebo dotazy přes parametr `xtream=1` vkládá master playlist do tagu `#EXT-X-MEDIA:TYPE=SUBTITLES` přímý odkaz `URI="/api/subtitles/{idec}.vtt"`, což aktivuje přímé stažení titulků bez selhání spojování.
    4. Běžné přehrávače (VLC, TiviMate, ExoPlayer) nadále dostávají standardní HLS Media Playlist `/api/hls/subtitles/{idec}.m3u8`.
    5. Titulky se nyní při stahování bezchybně vkládají do MP4 kontejneru (`Stream #0:2: Subtitle: mov_text`).

---

## [2.2.0] - 2026-11-22

### Opraveno (Fixed)
- **Xtream Series Season Reporting (Oprava Season 0 u seriálů v IPTV stahovačích):**
  - Vyřešena chyba, kdy stahovací klienti ukládali všechny epizody seriálů jako `S00` (např. `Čtyřlístek.S00E11.mp4`).
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
  - Opravena kritická chyba `json: cannot unmarshal string into Go struct field VodStream.stream_id of type int`, která způsobovala `HTTP 502 Bad Gateway` ve striktních typových Go klientech.
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
  - Napojení na GraphQL `cardPortrait` z CDN České televize s automatickým canvas paddingem do poměru 2:3 a TMDB fallbacks pro ideální zobrazení ve Stremio, TiviMate a externích přehrávačích.
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
