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

        # 1. Získat HLS stream URL (bez DRM)
        stream_data = await ct_service.resolve_vod_stream(idec, allow_drm=False)
        if not stream_data or not stream_data.get("url"):
            # Zjistíme, zda je pořad chráněn DRM nebo zcela nedostupný
            drm_check = await ct_service.resolve_vod_stream(idec, allow_drm=True)
            if drm_check and drm_check.get("is_drm"):
                crud.update_download_task(
                    task_id,
                    status="failed",
                    error_message="Pořad je chráněn šifrováním Widevine DRM a nelze jej stáhnout jako prostý MP4 soubor."
                )
            else:
                crud.update_download_task(
                    task_id,
                    status="failed",
                    error_message="Pořad není dostupný v archivu ČT (práva vypršela nebo stream nelze načíst)."
                )
            return

        stream_url = stream_data["url"]
        output_filename = f"{title}_{idec}.mp4"
        output_filepath = settings.DOWNLOAD_DIR / output_filename

        # 2. Spustit ffmpeg pro stažení HLS do MP4 bez problematického aac_adtstoasc filtru
        headers_str = f"User-Agent: {settings.USER_AGENT}\r\nReferer: https://www.ceskatelevize.cz/\r\nOrigin: https://www.ceskatelevize.cz\r\n"
        cmd = [
            "ffmpeg",
            "-y",
            "-headers", headers_str,
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

            # Sledování průběhu stahování a ukládání posledních řádků stderr pro případ chyby
            duration = 0.0
            time_pattern = re.compile(r'time=(\d+):(\d+):(\d+\.\d+)')
            duration_pattern = re.compile(r'Duration: (\d+):(\d+):(\d+\.\d+)')
            stderr_lines = []

            while True:
                line = await process.stderr.readline()
                if not line:
                    break
                line_str = line.decode('utf-8', errors='ignore')
                stderr_lines.append(line_str.strip())
                if len(stderr_lines) > 30:
                    stderr_lines.pop(0)

                if not duration:
                    dur_match = duration_pattern.search(line_str)
                    if dur_match:
                        h, m, s = dur_match.groups()
                        duration = int(h) * 3600 + int(m) * 60 + float(s)

                time_match = time_pattern.search(line_str)
                if time_match and duration > 0:
                    h, m, s = time_match.groups()
                    current_time = int(h) * 3600 + int(m) * 60 + float(s)
                    pct = min(99.0, round((current_time / duration) * 100, 1))
                    crud.update_download_task(task_id, progress=pct)

            await process.wait()
            self._active_processes.pop(task_id, None)

            if process.returncode == 0 and output_filepath.exists() and output_filepath.stat().st_size > 0:
                filesize = output_filepath.stat().st_size
                crud.update_download_task(
                    task_id,
                    status="completed",
                    progress=100.0,
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
