from fastapi import APIRouter, Request, HTTPException, Response
from fastapi.responses import JSONResponse, Response
from app.services.ct_service import ct_service
from app.services.drm_proxy import drm_session_manager
from app.core.config import settings

router = APIRouter(prefix="/api")

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

    # Pokud pořad vyžaduje DRM, vytvoříme lokální DRM proxy relaci
    if data.get("is_drm"):
        forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", f"127.0.0.1:{settings.PORT}"))
        base_url = f"{forwarded_proto}://{forwarded_host}"

        session_id = drm_session_manager.create_session(
            source_url=data["url"],
            user_agent=settings.USER_AGENT,
            base_url=base_url
        )
        return {
            "idec": idec,
            "title": data.get("title", ""),
            "is_drm": True,
            "manifest_type": "mpd",
            "url": f"/api/drm/{session_id}/manifest.mpd",
            "license_url": "https://ivys-wvproxy.o2tv.cz/license?access_token=public",
            "subtitles": data.get("subtitles", [])
        }

    return data

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
