import time
from typing import Optional
from fastapi import APIRouter, Request, Response, Form, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.core.config import settings
from app.core.security import verify_password
from app.db import crud
from app.services.ct_service import ct_service, LIVE_CHANNELS
from app.services.downloader import download_manager
from app.services.archive_crawler import archive_crawler

router = APIRouter()
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

def get_current_user(request: Request) -> Optional[dict]:
    username = request.cookies.get("ivys_user")
    token = request.cookies.get("ivys_token")
    if not username or not token:
        return None
    user = crud.get_user_by_username(username)
    if not user or not user["is_active"]:
        return None
    return user

def is_using_default_password(user: Optional[dict]) -> bool:
    if not user:
        return False
    return verify_password("admin", user.get("password_hash", ""))

def require_admin(request: Request) -> dict:
    user = get_current_user(request)
    if not user or not user.get("is_admin"):
        raise HTTPException(status_code=303, headers={"Location": "/login?error=Vyžadováno+přihlášení+administrátora"})
    return user

def get_base_url(request: Request) -> str:
    if settings.BASE_URL:
        return settings.BASE_URL.rstrip('/')
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", f"127.0.0.1:{settings.PORT}"))
    return f"{forwarded_proto}://{forwarded_host}"

@router.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    channels = list(LIVE_CHANNELS.values())
    live_epg = await ct_service.get_live_epg_now()

    return templates.TemplateResponse(request=request, name="index.html", context={
        "user": user,
        "is_default_password": is_using_default_password(user),
        "channels": channels,
        "live_epg": live_epg,
        "active_tab": "live"
    })

@router.get("/archive", response_class=HTMLResponse)
async def archive_page(
    request: Request,
    genre: Optional[str] = Query("all"),
    q: Optional[str] = Query(None),
    page: int = Query(1)
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    limit = 24
    offset = (page - 1) * limit
    shows = crud.list_shows(genre=genre, search=q, limit=limit, offset=offset)
    total_shows = crud.count_shows(genre=genre, search=q)

    # Pokud uživatel vyhledává a máme málo výsledků, prohledáme přímo GraphQL ČT
    if q and q.strip() and len(shows) < 6 and page == 1:
        try:
            external_results = await ct_service.search_shows_graphql(q.strip(), limit=15)
            seen_ids = {s["id"] for s in shows}
            for res in external_results:
                sidp = res.get("sidp")
                if sidp and sidp not in seen_ids:
                    show_meta = await ct_service.scrape_show_metadata(sidp)
                    if show_meta:
                        shows.append(show_meta)
                        seen_ids.add(sidp)
            total_shows = max(total_shows, len(shows))
        except Exception as e:
            logger.warning(f"GraphQL search error in archive_page: {e}")

    total_pages = max(1, (total_shows + limit - 1) // limit)
    genres = crud.list_genres()

    return templates.TemplateResponse(request=request, name="archive.html", context={
        "user": user,
        "is_default_password": is_using_default_password(user),
        "shows": shows,
        "genres": genres,
        "current_genre": genre,
        "search_query": q or "",
        "page": page,
        "total_pages": total_pages,
        "total_shows": total_shows,
        "active_tab": "archive"
    })

@router.get("/show/{show_id}", response_class=HTMLResponse)
async def show_detail_page(request: Request, show_id: str):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    show = crud.get_show_by_id(show_id)
    if not show or (show.get("show_type") == "series" and len(crud.get_episodes_by_show(show_id)) <= 1):
        # Načteme kompletní metadata a epizody z ČT
        scraped = await ct_service.scrape_show_metadata(show_id)
        if scraped:
            show = crud.get_show_by_id(show_id) or scraped
            
    if not show:
        raise HTTPException(status_code=404, detail="Pořad nebyl nalezen")

    episodes = crud.get_episodes_by_show(show_id)
    
    # Rozdělení epizod podle sérií
    seasons = {}
    for ep in episodes:
        s_num = ep.get("season", 1) or 1
        if s_num not in seasons:
            seasons[s_num] = []
        seasons[s_num].append(ep)
    
    sorted_seasons = sorted(seasons.keys())

    return templates.TemplateResponse(request=request, name="show_detail.html", context={
        "user": user,
        "is_default_password": is_using_default_password(user),
        "show": show,
        "episodes": episodes,
        "seasons": seasons,
        "sorted_seasons": sorted_seasons,
        "active_tab": "archive"
    })

@router.get("/downloads", response_class=HTMLResponse)
async def downloads_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    tasks = crud.list_download_tasks()
    return templates.TemplateResponse(request=request, name="downloads.html", context={
        "user": user,
        "is_default_password": is_using_default_password(user),
        "tasks": tasks,
        "active_tab": "downloads"
    })

@router.post("/api/downloads/add")
async def add_download_api(request: Request, idec: str = Form(...), title: str = Form(...)):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Nepřihlášen")
    
    # Okamžitá kontrola zda pořad nevyžaduje Widevine DRM
    stream_check = await ct_service.resolve_vod_stream(idec, allow_drm=True)
    if stream_check and stream_check.get("is_drm"):
        return JSONResponse(
            status_code=400,
            content={"status": "error", "detail": "Tento pořad je chráněn Widevine DRM a nelze jej stáhnout jako prostý MP4 soubor."}
        )

    task_id = await download_manager.add_download(idec, title)
    return {"status": "ok", "task_id": task_id}

@router.delete("/api/downloads/{task_id}")
async def delete_download_api(request: Request, task_id: str):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Nepřihlášen")
    task = crud.get_download_task(task_id)
    if task and task.get("filepath") and Path(task["filepath"]).exists():
        try:
            Path(task["filepath"]).unlink()
        except Exception:
            pass
    download_manager.cancel_download(task_id)
    crud.delete_download_task(task_id)
    return {"status": "ok"}

@router.get("/downloads/file/{task_id}")
async def play_downloaded_file(request: Request, task_id: str):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Nepřihlášen")
    task = crud.get_download_task(task_id)
    if not task or not task.get("filepath") or not Path(task["filepath"]).exists():
        raise HTTPException(status_code=404, detail="Soubor nenalezen")
    return FileResponse(task["filepath"], media_type="video/mp4", filename=Path(task["filepath"]).name)

@router.get("/xtream", response_class=HTMLResponse)
async def xtream_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    base_url = get_base_url(request)
    users = crud.list_users() if user.get("is_admin") else [user]
    first_user = users[0] if users else None
    sample_user = first_user["username"] if first_user else "admin"

    return templates.TemplateResponse(request=request, name="xtream.html", context={
        "user": user,
        "is_default_password": is_using_default_password(user),
        "base_url": base_url,
        "sample_user": sample_user,
        "active_tab": "xtream"
    })

@router.get("/stremio", response_class=HTMLResponse)
async def stremio_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    base_url = get_base_url(request)
    user_token = user.get("user_token")
    if user_token:
        manifest_url = f"{base_url}/stremio/{user_token}/manifest.json"
    else:
        manifest_url = f"{base_url}/stremio/manifest.json"
    stremio_link = f"stremio://{manifest_url.split('://')[-1]}"

    return templates.TemplateResponse(request=request, name="stremio.html", context={
        "user": user,
        "is_default_password": is_using_default_password(user),
        "base_url": base_url,
        "manifest_url": manifest_url,
        "stremio_link": stremio_link,
        "active_tab": "stremio"
    })

@router.get("/admin", response_class=HTMLResponse)
async def admin_page(
    request: Request,
    error: Optional[str] = None,
    success: Optional[str] = None
):
    user = get_current_user(request)
    if not user or not user.get("is_admin"):
        return RedirectResponse(url="/login?error=Vyžadováno+přihlášení+administrátora", status_code=303)

    users = crud.list_users()
    crawler_stats = archive_crawler.stats
    total_shows = crud.count_shows()

    return templates.TemplateResponse(request=request, name="admin.html", context={
        "user": user,
        "is_default_password": is_using_default_password(user),
        "users": users,
        "crawler_stats": crawler_stats,
        "total_shows": total_shows,
        "error": error,
        "success": success,
        "active_tab": "admin"
    })

@router.post("/admin/change-password")
async def admin_change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...)
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    if not verify_password(current_password, user["password_hash"]):
        return RedirectResponse(url="/admin?error=Současné+heslo+není+správné#change-password", status_code=303)

    if new_password != confirm_password:
        return RedirectResponse(url="/admin?error=Nová+hesla+se+neshodují#change-password", status_code=303)

    if len(new_password) < 4:
        return RedirectResponse(url="/admin?error=Nové+heslo+musí+mít+alespoň+4+znaky#change-password", status_code=303)

    crud.update_user(user_id=user["id"], password=new_password)
    return RedirectResponse(url="/admin?success=Heslo+bylo+úspěšně+změněno#change-password", status_code=303)

@router.post("/admin/crawl-catalog")
async def admin_crawl_catalog(request: Request):
    user = get_current_user(request)
    if not user or not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Nedostatečná oprávnění")
    started = archive_crawler.start_background_crawl(max_pages_per_category=5)
    return {"status": "started" if started else "already_running"}

@router.get("/admin/crawl-status")
async def admin_crawl_status(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Nepřihlášen")
    return {
        **archive_crawler.stats,
        "total_shows_in_db": crud.count_shows()
    }

@router.post("/admin/users/create")
async def admin_create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    is_admin: bool = Form(False),
    max_connections: int = Form(2)
):
    require_admin(request)
    crud.create_user(username=username, password=password, is_admin=is_admin, max_connections=max_connections)
    return RedirectResponse(url="/admin", status_code=303)

@router.post("/admin/users/{user_id}/delete")
async def admin_delete_user(request: Request, user_id: int):
    require_admin(request)
    crud.delete_user(user_id)
    return RedirectResponse(url="/admin", status_code=303)

@router.post("/admin/index-show")
async def admin_index_show(request: Request, url: str = Form(...)):
    user = get_current_user(request)
    if not user or not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Nedostatečná oprávnění")
    success = await archive_crawler.index_show(url)
    return {"status": "ok" if success else "error"}

@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    error: Optional[str] = None,
    next: Optional[str] = None
):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={
        "error": error,
        "next": next or "/"
    })

@router.post("/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: Optional[str] = Form("/")
):
    user = crud.authenticate_user(username, password)
    if not user:
        return templates.TemplateResponse(request=request, name="login.html", context={
            "error": "Neplatné uživatelské jméno nebo heslo",
            "next": next or "/"
        }, status_code=401)

    redirect_url = next if (next and next.startswith("/") and not next.startswith("//")) else "/"
    response = RedirectResponse(url=redirect_url, status_code=303)
    response.set_cookie(key="ivys_user", value=user["username"], max_age=86400 * 30, httponly=True)
    response.set_cookie(key="ivys_token", value="active", max_age=86400 * 30, httponly=True)
    return response

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("ivys_user")
    response.delete_cookie("ivys_token")
    return response
