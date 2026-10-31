import urllib.parse
import logging
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException, Response, Query
from fastapi.responses import JSONResponse, FileResponse
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
            return Response(
                content=resp.content,
                media_type="text/vtt",
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                    "Cache-Control": "public, max-age=86400"
                }
            )
    except Exception as e:
        logger.error(f"Error proxying subtitles from {url}: {e}")
        raise HTTPException(status_code=502, detail="Subtitle proxy error")

@router.get("/image-proxy")
async def get_image_proxy(url: str):
    content, media_type = await image_proxy.fetch_image(url)
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
    data = await ct_service.resolve_live_stream(channel_id, allow_drm=True)
    if not data:
        raise HTTPException(status_code=404, detail="Live stream not found")

    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", f"127.0.0.1:{settings.PORT}"))
    base_url = f"{forwarded_proto}://{forwarded_host}"

    if data.get("is_drm") and data.get("dash_url"):
        session_id = drm_session_manager.create_session(
            source_url=data["dash_url"],
            user_agent=settings.USER_AGENT,
            base_url=base_url
        )
        return {
            "channel_id": channel_id,
            "title": data.get("title", ""),
            "is_drm": True,
            "manifest_type": "mpd",
            "url": f"/api/drm/{session_id}/manifest.mpd",
            "hls_url": data.get("hls_url"),
            "license_url": "https://ivys-wvproxy.o2tv.cz/license?access_token=public",
            "qualities": data.get("qualities", []),
            "audio_tracks": data.get("audio_tracks", [])
        }

    return data

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
