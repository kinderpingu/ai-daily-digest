"""
Daily Digest Agent — powered by Hermes Agent + OpenRouter
Run:  python main.py
Cron: 0 7 * * * cd /path/to/digest-agent && python main.py
"""

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from agent.hermes_runner import HermesRunner
from agent.email_sender import send_report
from config.settings import load_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("digest.log",encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


async def main():
    settings = load_settings()
    try:
        now = datetime.now(ZoneInfo(settings.timezone))
    except Exception:
        log.warning("Invalid TIMEZONE=%s; falling back to UTC", settings.timezone)
        now = datetime.now(ZoneInfo("UTC"))
    today = now.strftime("%A, %B %d %Y")

    log.info("=== Daily Digest Agent starting — %s ===", today)

    runner = HermesRunner(settings)
    digest = await runner.run(today)

    if digest:
        send_report(digest, today, settings)
        log.info("Digest delivered using %s mode.", settings.delivery_mode)
    else:
        log.error("Hermes returned an empty digest — check digest.log for details.")
        raise RuntimeError("Hermes returned an empty digest")


if __name__ == "__main__":
    asyncio.run(main())
