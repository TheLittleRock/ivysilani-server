import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from app.core.config import settings

def setup_logging():
    """Nakonfiguruje rotující logování do souboru a konzole."""
    log_dir = settings.DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "ivysilani.log"

    log_format = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
    formatter = logging.Formatter(log_format)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Pokud již handlery existují, nezdvojujeme
    if not any(isinstance(h, RotatingFileHandler) for h in root_logger.handlers):
        # Souborový handler (max 10 MB, 5 záloh)
        file_handler = RotatingFileHandler(
            filename=str(log_file),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)
        root_logger.addHandler(file_handler)

    # Console handler
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler) for h in root_logger.handlers):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO)
        root_logger.addHandler(console_handler)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.INFO)

    logging.info(f"Logovací subsystém aktivován. Soubor: {log_file}")
