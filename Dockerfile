FROM python:3.11-slim

LABEL org.opencontainers.image.title="iVysílání Server" \
      org.opencontainers.image.description="Webová aplikace a Xtream Codes IPTV / VOD server pro Českou televizi a iVysílání" \
      org.opencontainers.image.authors="TheLittleRock" \
      org.opencontainers.image.licenses="GPL-3.0"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=5002 \
    DATA_DIR=/data \
    DOWNLOAD_DIR=/downloads \
    STREAM_MODE=redirect \
    TZ=Europe/Prague

# Instalace ffmpeg (pro stahování HLS streamů) a curl (pro healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalace Python závislostí
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopírování zdrojových kódů
COPY app /app/app
COPY run.py /app/run.py

# Příprava adresářů pro persistentní data a stažené soubory
RUN mkdir -p /data /downloads

EXPOSE 5002

VOLUME ["/data", "/downloads"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5002/ || exit 1

CMD ["python3", "run.py"]
