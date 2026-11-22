import re
import urllib.parse
import logging
from typing import Optional
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException, Response, Query
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
import httpx
from app.db import crud
from app.services.ct_service import ct_service
from app.services.drm_proxy import drm_session_manager
from app.services.image_proxy import image_proxy
from app.core.config import settings

logger = logging.getLogger("stream_api")

router = APIRouter(prefix="/api")

def shift_vtt_timestamps(vtt_text: str, offset_seconds: float = 1.8) -> str:
    """Posune všechny časové značky ve WebVTT o zadaný počet sekund.
    Kladná hodnota posouvá titulky dopředu v čase (zpožďuje jejich zobrazení,
    pokud se zobrazují moc brzy).
    """
    def parse_time(t_str: str) -> float:
        t_str = t_str.strip().replace(",", ".")
        parts = t_str.split(":")
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        return float(parts[0])

    def format_time(seconds: float) -> str:
        if seconds < 0:
            seconds = 0.0
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = seconds % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}"

    pattern = re.compile(r"((?:\d{2}:)?\d{2}:\d{2}[\.,]\d{3})\s+-->\s+((?:\d{2}:)?\d{2}:\d{2}[\.,]\d{3})")

    def replacer(match):
        start_str, end_str = match.group(1), match.group(2)
        start_sec = parse_time(start_str) + offset_seconds
        end_sec = parse_time(end_str) + offset_seconds
        return f"{format_time(start_sec)} --> {format_time(end_sec)}"

    return pattern.sub(replacer, vtt_text)

@router.api_route("/subtitles", methods=["GET", "HEAD"])
async def proxy_subtitles(url: str = Query(...), offset: Optional[float] = Query(None)):
    """Stáhne a přepošle WebVTT titulky z CDN České televize s CORS hlavičkou
    a automatickým vyrovnáním časového posunu (defaultně +2.5s zpoždění pro dokonalou synchronizaci s videem).
    """
    if not url.startswith("http://") and not url.startswith("https://"):
        raise HTTPException(status_code=400, detail="Invalid subtitle URL")
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="Failed to fetch subtitles from origin")
            
            vtt_text = resp.text

            # Časový posun titulků: ČT WebVTT soubory mívají náskok vůči webovému VOD videu
            if offset is not None:
                use_offset = offset
            else:
                db_offset = crud.get_setting("subtitle_offset_seconds", "")
                if db_offset:
                    try:
                        use_offset = float(db_offset)
                    except ValueError:
                        use_offset = settings.SUBTITLE_OFFSET_SECONDS
                else:
                    use_offset = settings.SUBTITLE_OFFSET_SECONDS

            if use_offset != 0:
                vtt_text = shift_vtt_timestamps(vtt_text, use_offset)

            # Injekce X-TIMESTAMP-MAP pro HLS přehrávače (VLC, ExoPlayer, TiviMate),
            # aby titulky byly korektně synchronizovány s MPEGTS časovou osou videa
            if "X-TIMESTAMP-MAP" not in vtt_text and vtt_text.startswith("WEBVTT"):
                lines = vtt_text.splitlines()
                lines.insert(1, "X-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:0")
                vtt_text = "\n".join(lines)

            return Response(
                content=vtt_text.encode("utf-8"),
                media_type="text/vtt; charset=utf-8",
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                    "Cache-Control": "public, max-age=86400"
                }
            )
    except Exception as e:
        logger.error(f"Error proxying subtitles from {url}: {e}")
        raise HTTPException(status_code=502, detail="Subtitle proxy error")

@router.api_route("/subtitles/{idec}.vtt", methods=["GET", "HEAD"])
async def get_vtt_subtitles_by_idec(request: Request, idec: str, offset: Optional[float] = Query(None)):
    """Poskytuje WebVTT titulky přímo podle IDEC epizody/filmu.
    Umožňuje přímé stažení titulků v crawleru (xtream-gui) i přehrávačích bez potřeby M3U8 obálky.
    """
    data = await ct_service.resolve_vod_stream(idec, allow_drm=False)
    if not data or not data.get("subtitles"):
        raise HTTPException(status_code=404, detail="Subtitles not available")
    vtt_url = data["subtitles"][0]["url"]
    return await proxy_subtitles(url=vtt_url, offset=offset)

@router.api_route("/subtitles/track.vtt", methods=["GET", "HEAD"])
async def proxy_subtitles_vtt(url: str = Query(...), offset: Optional[float] = Query(None)):
    """Proxy WebVTT titulků s URL končící na .vtt pro kompatibilitu s HLS segmenty."""
    return await proxy_subtitles(url=url, offset=offset)

@router.api_route("/image-proxy", methods=["GET", "HEAD"])
async def get_image_proxy(url: str, pad: Optional[str] = Query(None)):
    content, media_type = await image_proxy.fetch_image(url, pad=pad)
    if not content:
        fallback = Path("app/static/logos/ct1.png")
        if fallback.exists():
            return FileResponse(str(fallback), media_type="image/png")
        raise HTTPException(status_code=404, detail="Image not found")
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=604800, immutable"}
    )


@router.get("/stream/live/{channel_id}")
async def get_live_stream_info(request: Request, channel_id: str):
    data = await ct_service.resolve_live_stream(channel_id, allow_drm=False)
    if not data:
        raise HTTPException(status_code=404, detail="Live stream not found")

    hls_url = data.get("hls_url") or data.get("url")
    return {
        "channel_id": channel_id,
        "title": data.get("title", ""),
        "is_drm": False,
        "manifest_type": "hls",
        "url": hls_url,
        "hls_url": hls_url,
        "qualities": data.get("qualities", []),
        "audio_tracks": data.get("audio_tracks", []),
        "subtitles": data.get("subtitles", [])
    }

@router.api_route("/hls/master/{idec}.m3u8", methods=["GET", "HEAD"])
async def get_hls_master_playlist(
    request: Request,
    idec: str,
    quality: Optional[str] = Query(None),
    xtream: Optional[int] = Query(None)
):
    """Dynamicky přepíše HLS master playlist: vloží české titulky a volitelně vyfiltruje požadovanou kvalitu."""
    data = await ct_service.resolve_vod_stream(idec, allow_drm=False)
    if not data or not data.get("hls_url"):
        raise HTTPException(status_code=404, detail="HLS stream not available")

    hls_master_url = data["hls_url"]
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(hls_master_url)
            if resp.status_code != 200:
                return RedirectResponse(url=hls_master_url, status_code=302)

            master_text = resp.text
            base_url = settings.BASE_URL.rstrip('/') if settings.BASE_URL else None
            if not base_url:
                forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
                forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", f"127.0.0.1:{settings.PORT}"))
                base_url = f"{forwarded_proto}://{forwarded_host}"

            has_subtitles = bool(data.get("subtitles"))
            sub_uri = f"{base_url}/api/hls/subtitles/{idec}.m3u8"
            sub_line = f'#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="Čeština",DEFAULT=YES,AUTOSELECT=YES,LANGUAGE="cs",URI="{sub_uri}"'

            lines = [l.strip() for l in master_text.splitlines() if l.strip()]
            headers = []
            audios = []
            subtitles = []
            variants = []

            i = 0
            while i < len(lines):
                line = lines[i]
                if line.startswith("#EXTM3U") or line.startswith("#EXT-X-VERSION"):
                    headers.append(line)
                    i += 1
                elif line.startswith("#EXT-X-MEDIA:TYPE=AUDIO"):
                    audios.append(line)
                    i += 1
                elif line.startswith("#EXT-X-MEDIA:TYPE=SUBTITLES"):
                    subtitles.append(line)
                    i += 1
                elif line.startswith("#EXT-X-STREAM-INF:"):
                    inf_line = line
                    uri_line = lines[i+1] if i + 1 < len(lines) else ""
                    i += 2
                    bw_match = re.search(r"BANDWIDTH=(\d+)", inf_line)
                    bw = int(bw_match.group(1)) if bw_match else 0
                    variants.append((inf_line, uri_line, bw))
                else:
                    i += 1

            # Injekce českých titulků pokud v master playlistu chybí
            if has_subtitles and not subtitles:
                subtitles.append(sub_line)

            # Volitelná filtrace podle kvality
            selected_variants = []
            for inf_line, uri_line, bw in variants:
                keep = True
                if quality == "1080p" and bw < 5000000:
                    keep = False
                elif quality == "720p" and not (2500000 <= bw <= 4500000):
                    keep = False
                elif quality == "576p" and not (1500000 <= bw <= 2500000):
                    keep = False

                if keep:
                    selected_variants.append((inf_line, uri_line, bw))

            if not selected_variants:
                selected_variants = variants

            # Sestavení čistého master playlistu podle RFC 8216
            out_lines = []
            out_lines.extend(headers)
            out_lines.extend(audios)
            out_lines.extend(subtitles)

            for inf_line, uri_line, _ in selected_variants:
                if (has_subtitles or subtitles) and 'SUBTITLES=' not in inf_line:
                    inf_line += ',SUBTITLES="subs"'
                out_lines.append(inf_line)
                out_lines.append(uri_line)

            return Response(
                content="\n".join(out_lines),
                media_type="application/vnd.apple.mpegurl",
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                    "Cache-Control": "public, max-age=1800"
                }
            )
    except Exception as e:
        logger.warning(f"Error rewriting HLS master playlist for {idec}: {e}")
        return RedirectResponse(url=hls_master_url, status_code=302)

@router.api_route("/hls/subtitles/{idec}.m3u8", methods=["GET", "HEAD"])
async def get_hls_subtitle_playlist(request: Request, idec: str):
    """Vrátí HLS WebVTT subtitle playlist pro IPTV přehrávače (TiviMate/VLC) a crawler."""
    data = await ct_service.resolve_vod_stream(idec, allow_drm=False)
    if not data or not data.get("subtitles"):
        raise HTTPException(status_code=404, detail="Subtitles not available")

    base_url = settings.BASE_URL.rstrip('/') if settings.BASE_URL else None
    if not base_url:
        forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", f"127.0.0.1:{settings.PORT}"))
        base_url = f"{forwarded_proto}://{forwarded_host}"
    proxy_sub_url = f"{base_url}/api/subtitles/{idec}.vtt"

    hls_vtt = f"""#EXTM3U
#EXT-X-TARGETDURATION:7200
#EXT-X-VERSION:3
#EXT-X-MEDIA-SEQUENCE:0
#EXTINF:7200.0,
{proxy_sub_url}
#EXT-X-ENDLIST
"""
    return Response(
        content=hls_vtt,
        media_type="application/vnd.apple.mpegurl",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Cache-Control": "public, max-age=86400"
        }
    )

@router.get("/stream/vod/{idec}")
async def get_vod_stream_info(request: Request, idec: str):
    data = await ct_service.resolve_vod_stream(idec, allow_drm=True)
    if not data:
        raise HTTPException(status_code=404, detail="VOD stream not found")

    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", f"127.0.0.1:{settings.PORT}"))
    base_url = f"{forwarded_proto}://{forwarded_host}"

    # Obalení titulků přes lokální CORS proxy
    proxied_subtitles = []
    for s in data.get("subtitles", []):
        sub_raw = s.get("url", "")
        if sub_raw:
            proxied_subtitles.append({
                "language": s.get("language", "ces"),
                "label": s.get("label", "Čeština"),
                "url": f"{base_url}/api/subtitles?url={urllib.parse.quote(sub_raw, safe='')}"
            })

    # Pokud pořad vyžaduje DRM a nemá unencrypted HLS, vytvoříme lokální DRM proxy relaci
    if data.get("is_drm") and data.get("dash_url"):
        session_id = drm_session_manager.create_session(
            source_url=data["dash_url"],
            user_agent=settings.USER_AGENT,
            base_url=base_url
        )
        return {
            "idec": idec,
            "title": data.get("title", ""),
            "is_drm": True,
            "manifest_type": "mpd",
            "url": f"/api/drm/{session_id}/manifest.mpd",
            "hls_url": data.get("hls_url"),
            "license_url": "https://ivys-wvproxy.o2tv.cz/license?access_token=public",
            "subtitles": proxied_subtitles
        }

    res = dict(data)
    res["subtitles"] = proxied_subtitles
    return res

@router.get("/drm/{session_id}/manifest.mpd")
async def get_drm_manifest(session_id: str):
    try:
        adapter = drm_session_manager.get_adapter(session_id)
        content = adapter.manifest()
        return Response(content=content, media_type="application/dash+xml")
    except KeyError:
        raise HTTPException(status_code=404, detail="DRM session expired or not found")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"DRM adapter error: {str(e)}")

@router.get("/drm/{session_id}/init/{init_id}.mp4")
async def get_drm_init(session_id: str, init_id: str):
    try:
        adapter = drm_session_manager.get_adapter(session_id)
        content = adapter.initialization(init_id)
        return Response(content=content, media_type="video/mp4")
    except KeyError:
        raise HTTPException(status_code=404, detail="DRM init segment expired or not found")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"DRM init segment error: {str(e)}")
