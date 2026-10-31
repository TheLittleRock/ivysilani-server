#!/usr/bin/env python3
"""
Spouštěcí skript pro iVysílání Server.
Spouští FastAPI aplikaci pomocí ASGI serveru Uvicorn.
"""
import sys
import uvicorn
from app.core.config import settings

def main():
    print("=" * 60)
    print("  iVysílání Server - Česká televize Web & Xtream Codes IPTV")
    print(f"  Běží na: http://{settings.HOST}:{settings.PORT}")
    print(f"  Výchozí admin: {settings.DEFAULT_ADMIN_USER} / {settings.DEFAULT_ADMIN_PASSWORD}")
    print("=" * 60)
    
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        workers=1,
        log_level="info"
    )

if __name__ == "__main__":
    main()
