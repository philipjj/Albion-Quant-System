"""
Logging configuration using loguru.
Provides structured, colorful logging with file rotation.
"""

import sys
from loguru import logger
from app.core.config import settings, PROJECT_ROOT

# Remove default handler
logger.remove()

# Console handler with rich formatting
logger.add(
    sys.stderr,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    ),
    level=settings.log_level,
    colorize=True,
)

# File handler with rotation
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

logger.add(
    LOG_DIR / "albion_quant_{time:YYYY-MM-DD}.log",
    rotation="10 MB",
    retention="7 days",
    compression="zip",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
)

# Export
log = logger
