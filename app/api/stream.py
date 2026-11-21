import re
import urllib.parse
import logging
from typing import Optional
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException, Response, Query
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
import httpx
from app.services.ct_service import ct_service
from app.services.drm_proxy import drm_session_manager
from app.services.image_proxy import image_proxy
from app.core.config import settings

logger = logging.getLogger("stream_api")

router = APIRouter(prefix="/api")

@router.api_route("/subtitles", methods=["GET", "HEAD"])
async def proxy_subtitles(url: str = Query(...)):
    """Stáhne a přepošle WebVTT titulky z CDN České televize s CORS hlavičkou."""
    if not url.startswith("http://") and not url.startswith("https://"):
        raise HTTPException(status_code=400, detail="Invalid subtitle URL")
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="Failed to fetch subtitles from origin")
            
            vtt_text = resp.text
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
    quality: Optional[str] = Query(None)
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
            forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
            forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", f"127.0.0.1:{settings.PORT}"))
            base_url = f"{forwarded_proto}://{forwarded_host}"

            has_subtitles = bool(data.get("subtitles"))
            sub_line = f'#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="Čeština",DEFAULT=YES,AUTOSELECT=YES,LANGUAGE="cs",URI="{base_url}/api/hls/subtitles/{idec}.m3u8"'

            lines = master_text.splitlines()
            out_lines = []
            sub_injected = False
            skip_next_stream = False

            for line in lines:
                if line.startswith("#EXT-X-MEDIA:TYPE=AUDIO"):
                    out_lines.append(line)
                    if has_subtitles and not sub_injected:
                        out_lines.append(sub_line)
                        sub_injected = True
                elif line.startswith("#EXT-X-STREAM-INF:"):
                    bw_match = re.search(r"BANDWIDTH=(\d+)", line)
                    bw = int(bw_match.group(1)) if bw_match else 0
                    keep = True
                    if quality == "1080p" and bw < 5000000:
                        keep = False
                    elif quality == "720p" and not (2500000 <= bw <= 4500000):
                        keep = False
                    elif quality == "576p" and not (1500000 <= bw <= 2500000):
                        keep = False

                    if keep:
                        if has_subtitles and 'SUBTITLES=' not in line:
                            line += ',SUBTITLES="subs"'
                        out_lines.append(line)
                        skip_next_stream = False
                    else:
                        skip_next_stream = True
                elif skip_next_stream:
                    skip_next_stream = False
                else:
                    out_lines.append(line)

            # Fallback pokud filtr kvality nic nezanechal
            if not any(l.startswith("#EXT-X-STREAM-INF:") for l in out_lines):
                out_lines = []
                for line in lines:
                    if line.startswith("#EXT-X-MEDIA:TYPE=AUDIO"):
                        out_lines.append(line)
                        if has_subtitles and not sub_injected:
                            out_lines.append(sub_line)
                            sub_injected = True
                    elif line.startswith("#EXT-X-STREAM-INF:"):
                        if has_subtitles and 'SUBTITLES=' not in line:
                            line += ',SUBTITLES="subs"'
                        out_lines.append(line)
                    else:
                        out_lines.append(line)

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
    """Vrátí HLS WebVTT subtitle playlist pro IPTV přehrávače (TiviMate/VLC)."""
    data = await ct_service.resolve_vod_stream(idec, allow_drm=False)
    if not data or not data.get("subtitles"):
        raise HTTPException(status_code=404, detail="Subtitles not available")

    vtt_url = data["subtitles"][0]["url"]
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", f"127.0.0.1:{settings.PORT}"))
    base_url = f"{forwarded_proto}://{forwarded_host}"
    proxy_sub_url = f"{base_url}/api/subtitles?url={urllib.parse.quote(vtt_url, safe='')}"

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
