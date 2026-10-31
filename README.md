# iVysílání Server 📺

> Moderní webová aplikace a Xtream Codes IPTV / VOD server pro Českou televizi a iVysílání. Umožňuje přehrávání živého vysílání všech 14 kanálů ČT, procházení a sledování archivu pořadů přímo ve webovém prohlížeči, stahování do MP4 i integraci do IPTV aplikací (TiviMate, IPTV Smarters, Kodi, VLC) přes protokol Xtream Codes a M3U/EPG.

[![Docker Image](https://github.com/TheLittleRock/ivysilani-server/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/TheLittleRock/ivysilani-server/actions/workflows/docker-publish.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

---

## 🌟 Funkce

- **Živé vysílání všech 14 kanálů ČT v plné kvalitě (1080p HLS):**
  - Hlavní kanály: ČT1, ČT2, ČT24, ČT sport, ČT :D, ČT art
  - Digitální a sportovní kanály: ČT sport Plus 1 až ČT sport Plus 8
- **Katalog a archiv iVysílání (VOD):**
  - Procházení pořadů podle žánrů, vyhledávání v archivu ČT
  - On-demand indexace i automatický crawler na pozadí
  - Podpora přímého přidání libovolného pořadu zadáním URL nebo IDEC kódu
- **Špičkové přehrávání:**
  - Moderní Web UI s Video.js přehrávačem přizpůsobeným pro tmavý režim (Tailwind CSS)
  - Podpora nechráněných HLS streamů i obsahu chráněného DRM Widevine
  - Přizpůsobený manifest proxy a pure-Python MP4 box parser pro Widevine PSSH/KID podle originální logiky
- **Xtream Codes IPTV API & M3U / EPG:**
  - Plnohodnotná podpora Xtream Codes API (`/player_api.php`) pro Live TV i VOD / Series
  - Generování M3U playlistu (`/get.php`) s logy a kategoriemi
  - Automatické generování XMLTV EPG (`/xmltv.php`) s podporou Catchup (zpětného zhlédnutí)
- **Správce stahování:**
  - Vestavěné asynchronní stahování pořadů z iVysílání do souborů MP4 pomocí `ffmpeg`
  - Živý ukazatel procentuálního průběhu stahování a přímé přehrávání/stažení z disku
- **Správa uživatelů a zabezpečení:**
  - Multi-uživatelská správa v SQLite (přihlašovací jména, bcrypt hesla, expirace účtů, limity souběžných spojení)
  - Administrační rozhraní s ochranou cookie sessions
- **Snadné nasazení:**
  - Připravený `Dockerfile` pro multi-arch (AMD64 i ARM64 např. Raspberry Pi)
  - `docker-compose.yml` připravený pro Portainer Stack i standardní Docker

---

## 👏 Poděkování a uznání (Acknowledgments)

Tento projekt vznikl z inspirace a adaptace postupů z komunitních open-source nástrojů:

1. **[waladir/plugin.video.ivysilani.cz](https://github.com/waladir/plugin.video.ivysilani.cz)** (autoři **drake127**, **brozikcz** a další přispěvatelé):
   - Architektura řešení ČT DRM (Widevine manifest adapter, manipulace s inicializačními MP4 segmenty, PSSH extrakce a integrace s ČT widevine licenčním serverem).
   - Metodika získávání playlistů a struktura kanálů ČT.
2. **[sunecz/Media-Downloader](https://github.com/sunecz/Media-Downloader)** (autor **sunecz**):
   - Inspirace pro řešení stahování HLS streamů z iVysílání a jejich remux do standardního MP4 formátu pomocí `ffmpeg`.

Velké díky původním autorům za jejich dlouholetou práci na analýze protokolů a rozhraní České televize!

---

## 🚀 Rychlý start (přímo v Pythonu)

### Požadavky
- Python 3.10+
- `ffmpeg` (nutný pro stahování pořadů do MP4)

### Postup instalace:
```bash
# 1. Klonování repozitáře
git clone https://github.com/TheLittleRock/ivysilani-server.git
cd ivysilani-server

# 2. Vytvoření a aktivace virtuálního prostředí
python3 -m venv .venv
source .venv/bin/activate

# 3. Instalace závislostí
pip install -r requirements.txt

# 4. Spuštění serveru
python3 run.py
```

Server se spustí na adrese `http://localhost:5002`.
- Výchozí přihlašovací údaje: **`admin`** / **`admin`** (heslo lze změnit v administraci).

---

## 🐳 Nasazení v Dockeru & Portaineru

### Varianta A: Docker Compose z příkazové řádky

V repozitáři je připraven soubor `docker-compose.yml`:

```yaml
version: "3.8"

services:
  ivysilani-server:
    image: ghcr.io/thelittlerock/ivysilani-server:latest
    container_name: ivysilani-server
    restart: unless-stopped
    ports:
      - "5002:5002"
    environment:
      - PORT=5002
      - STREAM_MODE=redirect       # "redirect" pro přímé přesměrování na CDN, "proxy" pro proxování streamů
      - BASE_URL=                  # Volitelně veřejná URL (např. https://tv.mojedomena.cz)
      - DEFAULT_ADMIN_USER=admin
      - DEFAULT_ADMIN_PASSWORD=admin
      - TZ=Europe/Prague
    volumes:
      - ./data:/data
      - ./downloads:/downloads
```

Spuštění kontejneru:
```bash
docker compose up -d
```

### Varianta B: Nasazení přes Portainer (Stack)

1. Přihlaste se do vašeho **Portaineru**.
2. V levém menu přejděte na **Stacks** -> klikněte na **Add stack**.
3. Zadejte název, např. `ivysilani`.
4. V editoru (Web editor) vložte obsah souboru `docker-compose.yml`.
5. Pokud používáte veřejnou doménu přes Nginx Proxy Manager, nastavte proměnnou `BASE_URL`:
   ```yaml
   - BASE_URL=https://ivysilani.vasedomena.cz
   ```
6. Klikněte na tlačítko **Deploy the stack**.

---

## 🌐 Provoz s veřejnou IP a Nginx Proxy Managerem (NPM)

Pokud chcete server provozovat bezpečně na internetu s vlastní doménou a SSL certifikátem:

### 1. Nastavení DNS a routeru:
- V DNS u svého registrátora nasměrujte A/AAAA záznam (např. `ivysilani.vasedomena.cz`) na vaši veřejnou IP adresu.
- Na vašem domácím routeru / firewallu přesměrujte porty `80` a `443` na IP adresu serveru, kde běží Nginx Proxy Manager.

### 2. Konfigurace Proxy Hostu v Nginx Proxy Manageru:
1. V NPM otevřete záložku **Hosts** -> **Proxy Hosts** -> **Add Proxy Host**.
2. **Details**:
   - **Domain Names:** `ivysilani.vasedomena.cz`
   - **Scheme:** `http`
   - **Forward Hostname / IP:** lokální IP vašeho serveru s iVysílání Serverem (např. `192.168.1.100` nebo název kontejneru v docker síti)
   - **Forward Port:** `5002`
   - Zaškrtněte:
     - ✅ **Block Common Exploits**
     - ✅ **Websockets Support**
3. **SSL**:
   - Vyberte **Request a new SSL Certificate**.
   - Zaškrtněte ✅ **Force SSL**, ✅ **HTTP/2 Support**, ✅ **HSTS Enabled**.
   - Vyplňte svůj e-mail a odsouhlaste podmínky Let's Encrypt.
4. **Advanced** (doporučené nastavení pro bezproblémový streaming a stahování velkých souborů):
   ```nginx
   # Zvýšení limitu pro upload a timeoutů pro streamování HLS
   client_max_body_size 100M;
   proxy_read_timeout 3600s;
   proxy_send_timeout 3600s;
   proxy_buffering off;
   ```
5. Klikněte na **Save**.
6. V konfiguraci `docker-compose.yml` serveru nastavte:
   ```yaml
   environment:
     - BASE_URL=https://ivysilani.vasedomena.cz
   ```
   A restartujte kontejner iVysílání serveru (`docker compose restart`).

---

## 📱 Nastavení v IPTV přehrávačích (Xtream Codes / M3U)

Propojení s přehrávači je mimořádně jednoduché. Podporovány jsou všechny aplikace kompatibilní s Xtream Codes nebo M3U.

### 1. TiviMate (Android TV / Fire TV) - Doporučeno ⭐
1. V TiviMate zvolte **Přidat playlist** -> **Xtream Codes přihlášení**.
2. Zadejte parametry:
   - **URL serveru:** `http://<IP-serveru>:5002` (nebo `https://ivysilani.vasedomena.cz`)
   - **Uživatelské jméno:** `admin` (nebo uživatel vytvořený v administraci)
   - **Heslo:** `admin`
3. Povolte VOD / Seriály pro přístup k archivu iVysílání.
4. TiviMate automaticky načte 14 živých kanálů, jejich loga i EPG program včetně zpětného zhlédnutí (Catchup).

### 2. IPTV Smarters Pro (iOS, Android, Smart TV)
1. Zvolte **Login with Xtream Codes API**.
2. Vyplňte:
   - **Any Name:** ČT iVysílání
   - **Username:** `admin`
   - **Password:** `admin`
   - **URL:** `http://<IP-serveru>:5002` (nebo `https://ivysilani.vasedomena.cz`)
3. Klikněte na **Add User**. Budete mít k dispozici Live TV i VOD sekci.

### 3. Kodi (PVR IPTV Simple Client)
- **M3U URL:**
  `http://<IP-serveru>:5002/get.php?username=admin&password=admin&type=m3u_plus`
- **EPG XMLTV URL:**
  `http://<IP-serveru>:5002/xmltv.php?username=admin&password=admin`

### 4. VLC Media Player
- Otevřete VLC -> **Média** -> **Otevřít síťový proud** (Ctrl+N).
- Vložte odkaz na M3U playlist: `http://<IP-serveru>:5002/get.php?username=admin&password=admin&type=m3u_plus`

---

## ⚙️ Přehled konfiguračních proměnných prostředí

| Proměnná | Výchozí hodnota | Popis |
| :--- | :--- | :--- |
| `PORT` | `5002` | Port, na kterém webový a IPTV server naslouchá |
| `HOST` | `0.0.0.0` | Bind adresa síťového rozhraní |
| `BASE_URL` | *(prázdné)* | Veřejná URL serveru (např. `https://tv.mojedomena.cz`) |
| `STREAM_MODE` | `redirect` | `redirect` = HTTP 302 přesměrování na CDN ČT (rychlé, minimální zátěž CPU a RAM); `proxy` = server data sám přeposílá |
| `DATA_DIR` | `./data` | Složka pro SQLite databázi a nastavení |
| `DOWNLOAD_DIR` | `./downloads` | Složka, kam se ukládají stažené MP4 soubory |
| `DEFAULT_ADMIN_USER` | `admin` | Uživatelské jméno výchozího administrátora |
| `DEFAULT_ADMIN_PASSWORD` | `admin` | Heslo výchozího administrátora |
| `CRAWL_INTERVAL_HOURS` | `24` | Interval automatické reindexace archivu iVysílání (v hodinách) |

---

## 🔒 Řešení DRM (Widevine)

Česká televize u části svého VOD archivu používá šifrování Common Encryption s ochranou Widevine Modular DRM a rotačními klíči v segmentech.

Tento server obsahuje věrně adaptovaný manifest proxy engine a pure-Python MP4 box parser (`drm_proxy.py` a `drm.py`) převzatý a upravený z osvědčeného doplňku `waladir/plugin.video.ivysilani.cz`:
1. Detekuje přítomnost šifrovaných vzorků (`seig KID`) v segmentech videa.
2. Vytváří virtuální lokální DASH MPD manifest (`/api/drm/{session_id}/manifest.mpd`).
3. Dynamicky patchuje inicializační MP4 segmenty (`init.mp4`) se správným KID a PSSH boxem.
4. Integruje Video.js přehrávač (`videojs-contrib-eme`) pro plynulé dekódování v moderních prohlížečích přes oficiální licenční proxy České televize (`https://ivys-wvproxy.o2tv.cz/license?access_token=public`).

---

## 🧪 Testy

Projekt obsahuje sadu automatizovaných testů ověřujících integritu API, scraperů, databáze a DRM logiky:

```bash
python3 -m pytest tests/ -v
```

---

## 📄 Licence

Tento projekt je šířen pod licencí **GNU General Public License v3.0 (GPL-3.0)** v souladu s licencí původního Kodi doplňku. Podrobnosti naleznete v souboru [LICENSE](LICENSE).
