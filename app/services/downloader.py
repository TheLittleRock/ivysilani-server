import os
import asyncio
import uuid
import re
import time
import logging
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.db import crud
from app.services.ct_service import ct_service

logger = logging.getLogger("downloader")

class DownloadManager:
    def __init__(self):
        self._active_processes = {}
        self._queue = asyncio.Queue()
        self._worker_task = None

    async def start(self):
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self):
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
        for task_id, proc in list(self._active_processes.items()):
            try:
                proc.terminate()
            except Exception:
                pass
        self._active_processes.clear()

    async def add_download(self, idec: str, title: str) -> str:
        task_id = uuid.uuid4().hex
        clean_title = re.sub(r'[\\/*?:"<>|]', "", title).strip() or f"porad_{idec}"
        crud.create_download_task(task_id, idec, clean_title)
        await self._queue.put(task_id)
        return task_id

    async def _worker_loop(self):
        logger.info("Download manager worker started.")
        while True:
            try:
                task_id = await self._queue.get()
                await self._process_download(task_id)
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in download worker loop: {e}")
                await asyncio.sleep(2)

    async def _process_download(self, task_id: str):
        task = crud.get_download_task(task_id)
        if not task:
            return

        idec = task["idec"]
        title = task["title"]
        logger.info(f"Starting download for task {task_id}: {title} (IDEC: {idec})")

        crud.update_download_task(task_id, status="downloading", progress=0.0)

        # 1. Získat HLS stream URL (s automatickým unencrypted HbbTV fallbackem)
        stream_data = await ct_service.resolve_vod_stream(idec, allow_drm=True)
        if not stream_data or not stream_data.get("url"):
            crud.update_download_task(
                task_id,
                status="failed",
                error_message="Pořad není dostupný v archivu ČT (práva vypršela nebo stream nelze načíst)."
            )
            return

        stream_url = stream_data["url"]

        # 2. Inteligentní formátování názvu a cesty podle standardu Plex/Jellyfin
        ep = crud.get_episode_by_idec(idec)
        show = crud.get_show_by_id(ep["show_id"]) if (ep and ep.get("show_id")) else None

        settings.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

        if show and show.get("show_type") == "series" and ep:
            safe_show = re.sub(r'[\\/*?:"<>|]', "", show["title"]).strip()
            safe_ep = re.sub(r'[\\/*?:"<>|]', "", ep["title"]).strip()
            season_num = ep.get("season", 1) or 1
            ep_num = ep.get("episode_num", 1) or 1
            
            show_dir = settings.DOWNLOAD_DIR / safe_show
            show_dir.mkdir(parents=True, exist_ok=True)
            output_filename = f"{safe_show} - S{season_num:02d}E{ep_num:02d} - {safe_ep}.mp4"
            output_filepath = show_dir / output_filename
        else:
            safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()
            year_str = f" ({show['year']})" if (show and show.get("year")) else ""
            output_filename = f"{safe_title}{year_str}.mp4"
            output_filepath = settings.DOWNLOAD_DIR / output_filename

        # 3. Spustit ffmpeg pro stažení HLS do MP4
        headers_str = f"User-Agent: {settings.USER_AGENT}\r\nReferer: https://www.ceskatelevize.cz/\r\nOrigin: https://www.ceskatelevize.cz\r\n"
        cmd = [
            "ffmpeg",
            "-y",
            "-headers", headers_str,
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-i", stream_url,
            "-c", "copy",
            "-movflags", "+faststart",
            str(output_filepath)
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            self._active_processes[task_id] = process

            # Sledování průběhu stahování, rychlosti a ETA
            duration = 0.0
            time_pattern = re.compile(r'time=(\d+):(\d+):(\d+\.\d+)')
            duration_pattern = re.compile(r'Duration: (\d+):(\d+):(\d+\.\d+)')
            speed_pattern = re.compile(r'speed=\s*([\d\.]+)x')
            size_pattern = re.compile(r'size=\s*(\d+)kB')
            stderr_lines = []
            last_update = time.time()

            while True:
                line = await process.stderr.readline()
                if not line:
                    break
                line_str = line.decode('utf-8', errors='ignore')
                stderr_lines.append(line_str.strip())
                if len(stderr_lines) > 25:
                    stderr_lines.pop(0)

                if not duration:
                    dur_match = duration_pattern.search(line_str)
                    if dur_match:
                        h, m, s = dur_match.groups()
                        duration = int(h) * 3600 + int(m) * 60 + float(s)

                now = time.time()
                # Aktualizace stavu každých 1.5 sekundy
                if now - last_update >= 1.5:
                    last_update = now
                    current_time = 0.0
                    time_match = time_pattern.search(line_str)
                    if time_match:
                        h, m, s = time_match.groups()
                        current_time = int(h) * 3600 + int(m) * 60 + float(s)

                    pct = 0.0
                    if duration > 0 and current_time > 0:
                        pct = min(99.0, round((current_time / duration) * 100, 1))

                    speed_str = ""
                    speed_match = speed_pattern.search(line_str)
                    if speed_match:
                        speed_val = speed_match.group(1)
                        speed_str = f"{speed_val}x"

                    current_size = 0
                    size_match = size_pattern.search(line_str)
                    if size_match:
                        current_size = int(size_match.group(1)) * 1024

                    eta_str = ""
                    if duration > 0 and current_time > 0 and speed_match:
                        try:
                            sp_float = float(speed_match.group(1))
                            if sp_float > 0:
                                rem_sec = int((duration - current_time) / sp_float)
                                m, s = divmod(rem_sec, 60)
                                eta_str = f"{m}m {s}s"
                        except Exception:
                            pass

                    crud.update_download_task(
                        task_id,
                        progress=pct,
                        speed=speed_str,
                        eta=eta_str,
                        filesize=current_size,
                        filepath=str(output_filepath)
                    )

            await process.wait()
            self._active_processes.pop(task_id, None)

            if process.returncode == 0 and output_filepath.exists() and output_filepath.stat().st_size > 0:
                filesize = output_filepath.stat().st_size
                crud.update_download_task(
                    task_id,
                    status="completed",
                    progress=100.0,
                    speed="",
                    eta="",
                    filepath=str(output_filepath),
                    filesize=filesize
                )
                logger.info(f"Download finished: {output_filepath} ({filesize} bytes)")
            else:
                last_err = "; ".join([l for l in stderr_lines[-3:] if l]) or f"kód {process.returncode}"
                crud.update_download_task(
                    task_id,
                    status="failed",
                    error_message=f"FFmpeg chyba ({last_err})"
                )
        except asyncio.CancelledError:
            if task_id in self._active_processes:
                self._active_processes[task_id].terminate()
            crud.update_download_task(task_id, status="cancelled")
        except Exception as e:
            logger.error(f"Download task {task_id} failed: {e}")
            crud.update_download_task(task_id, status="failed", error_message=str(e))

    def cancel_download(self, task_id: str):
        if task_id in self._active_processes:
            try:
                self._active_processes[task_id].terminate()
            except Exception:
                pass
            self._active_processes.pop(task_id, None)
        crud.update_download_task(task_id, status="cancelled")

download_manager = DownloadManager()
