"""
Daily Digest Agent — powered by Hermes Agent + OpenRouter
Run:  python main.py
Cron: 0 7 * * * cd /path/to/digest-agent && python main.py
"""

import asyncio
import logging
from datetime import datetime
from agent.hermes_runner import HermesRunner
from agent.email_sender import send_digest_email
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
    today = datetime.now().strftime("%A, %B %d %Y")

    log.info("=== Daily Digest Agent starting — %s ===", today)

    runner = HermesRunner(settings)
    digest = await runner.run(today)

    if digest:
        send_digest_email(digest, today, settings)
        log.info("Digest sent successfully.")
    else:
        log.error("Hermes returned an empty digest — check digest.log for details.")


if __name__ == "__main__":
    asyncio.run(main())
