"""
config/settings.py
Loads all configuration from environment variables (or a .env file).
"""

import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    # ── OpenRouter ─────────────────────────────────────────────────────────────
    openrouter_api_key: str = ""
    model: str = "nousresearch/hermes-3-llama-3.1-405b"

    # ── Topics to research ─────────────────────────────────────────────────────
    topics: List[str] = field(default_factory=lambda: [
        "artificial intelligence",
        "open source software",
        "developer tools",
    ])

    # ── Email ──────────────────────────────────────────────────────────────────
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""          # use an App Password for Gmail
    email_from: str = ""
    email_to: str = ""
    email_subject_prefix: str = "📰 Daily Digest"

    # ── Output ─────────────────────────────────────────────────────────────────
    save_markdown: bool = True       # also write digest to output/
    max_articles_per_topic: int = 3  # how many stories to surface per topic


def load_settings() -> Settings:
    topics_raw = os.getenv("DIGEST_TOPICS", "")
    topics = [t.strip() for t in topics_raw.split(",") if t.strip()] or [
        "artificial intelligence",
        "open source software",
        "developer tools",
    ]

    return Settings(
        openrouter_api_key=os.environ["OPENROUTER_API_KEY"],
        model=os.getenv("HERMES_MODEL", "nousresearch/hermes-3-llama-3.1-405b"),
        topics=topics,
        smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_user=os.environ["SMTP_USER"],
        smtp_password=os.environ["SMTP_PASSWORD"],
        email_from=os.getenv("EMAIL_FROM", os.environ["SMTP_USER"]),
        email_to=os.environ["EMAIL_TO"],
        email_subject_prefix=os.getenv("EMAIL_SUBJECT_PREFIX", "📰 Daily Digest"),
        save_markdown=os.getenv("SAVE_MARKDOWN", "true").lower() == "true",
        max_articles_per_topic=int(os.getenv("MAX_ARTICLES_PER_TOPIC", "3")),
    )
