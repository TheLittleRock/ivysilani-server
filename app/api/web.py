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

def require_admin(request: Request) -> dict:
    user = get_current_user(request)
    if not user or not user.get("is_admin"):
        raise HTTPException(status_code=303, headers={"Location": "/login"})
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
    channels = list(LIVE_CHANNELS.values())
    return templates.TemplateResponse(request=request, name="index.html", context={
        "user": user,
        "channels": channels,
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
    limit = 24
    offset = (page - 1) * limit
    shows = crud.list_shows(genre=genre, search=q, limit=limit, offset=offset)
    total_shows = crud.count_shows(genre=genre, search=q)
    total_pages = max(1, (total_shows + limit - 1) // limit)
    genres = crud.list_genres()

    return templates.TemplateResponse(request=request, name="archive.html", context={
        "user": user,
        "shows": shows,
        "genres": genres,
        "current_genre": genre,
        "search_query": q or "",
        "page": page,
        "total_pages": total_pages,
        "active_tab": "archive"
    })

@router.get("/show/{show_id}", response_class=HTMLResponse)
async def show_detail_page(request: Request, show_id: str):
    user = get_current_user(request)
    show = crud.get_show_by_id(show_id)
    if not show:
        # Zkusíme doindexovat on-demand
        success = await archive_crawler.index_show(show_id)
        if success:
            show = crud.get_show_by_id(show_id)
    if not show:
        raise HTTPException(status_code=404, detail="Pořad nebyl nalezen")

    episodes = crud.get_episodes_by_show(show_id)
    return templates.TemplateResponse(request=request, name="show_detail.html", context={
        "user": user,
        "show": show,
        "episodes": episodes,
        "active_tab": "archive"
    })

@router.get("/downloads", response_class=HTMLResponse)
async def downloads_page(request: Request):
    user = get_current_user(request)
    tasks = crud.list_download_tasks()
    return templates.TemplateResponse(request=request, name="downloads.html", context={
        "user": user,
        "tasks": tasks,
        "active_tab": "downloads"
    })

@router.post("/api/downloads/add")
async def add_download_api(idec: str = Form(...), title: str = Form(...)):
    task_id = await download_manager.add_download(idec, title)
    return {"status": "ok", "task_id": task_id}

@router.delete("/api/downloads/{task_id}")
async def delete_download_api(task_id: str):
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
async def play_downloaded_file(task_id: str):
    task = crud.get_download_task(task_id)
    if not task or not task.get("filepath") or not Path(task["filepath"]).exists():
        raise HTTPException(status_code=404, detail="Soubor nenalezen")
    return FileResponse(task["filepath"], media_type="video/mp4", filename=Path(task["filepath"]).name)

@router.get("/xtream", response_class=HTMLResponse)
async def xtream_page(request: Request):
    user = get_current_user(request)
    base_url = get_base_url(request)
    users = crud.list_users() if (user and user.get("is_admin")) else ([user] if user else [])
    
    first_user = users[0] if users else None
    sample_user = first_user["username"] if first_user else "admin"
    
    return templates.TemplateResponse(request=request, name="xtream.html", context={
        "user": user,
        "base_url": base_url,
        "sample_user": sample_user,
        "active_tab": "xtream"
    })

@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    user = get_current_user(request)
    if not user or not user.get("is_admin"):
        return RedirectResponse(url="/login?error=Vyžadováno přihlášení administrátora")
    users = crud.list_users()
    return templates.TemplateResponse(request=request, name="admin.html", context={
        "user": user,
        "users": users,
        "active_tab": "admin"
    })

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
    success = await archive_crawler.index_show(url)
    return {"status": "ok" if success else "error"}

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: Optional[str] = None):
    return templates.TemplateResponse(request=request, name="login.html", context={
        "error": error
    })

@router.post("/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    user = crud.authenticate_user(username, password)
    if not user:
        return templates.TemplateResponse(request=request, name="login.html", context={
            "error": "Neplatné uživatelské jméno nebo heslo"
        }, status_code=401)

    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="ivys_user", value=user["username"], max_age=86400 * 30, httponly=True)
    response.set_cookie(key="ivys_token", value="active", max_age=86400 * 30, httponly=True)
    return response

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("ivys_user")
    response.delete_cookie("ivys_token")
    return response
