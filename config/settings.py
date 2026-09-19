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
    model: str = "openrouter/free"

    # ── Topics to research ─────────────────────────────────────────────────────
    topics: List[str] = field(default_factory=lambda: [
        "global AI news and frontier model releases",
        "AI research, safety, regulation and business",
        "open source AI, chips, robotics and developer tools",
    ])

    # ── Email ──────────────────────────────────────────────────────────────────
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""          # use an App Password for Gmail
    email_from: str = ""
    email_to: str = ""
    email_subject_prefix: str = "📰 Daily Digest"
    resend_api_key: str = ""
    resend_from: str = "onboarding@resend.dev"

    # ── Output ─────────────────────────────────────────────────────────────────
    save_markdown: bool = True       # also write digest to output/
    max_articles_per_topic: int = 3  # how many stories to surface per topic
    max_iterations: int = 16
    max_searches: int = 12
    max_fetches: int = 18
    delivery_mode: str = "artifact"
    memory_dir: str = "memory"
    timezone: str = "Europe/Rome"


def load_settings() -> Settings:
    topics_raw = os.getenv("DIGEST_TOPICS", "")
    topics = [t.strip() for t in topics_raw.split(",") if t.strip()] or [
        "global AI news and frontier model releases",
        "AI research, safety, regulation and business",
        "open source AI, chips, robotics and developer tools",
    ]

    return Settings(
        openrouter_api_key=os.environ["OPENROUTER_API_KEY"],
        model=os.getenv("OPENROUTER_MODEL", os.getenv("HERMES_MODEL", "openrouter/free")),
        topics=topics,
        smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_user=os.getenv("SMTP_USER", ""),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        email_from=os.getenv("EMAIL_FROM", os.getenv("SMTP_USER", "")),
        email_to=os.getenv("EMAIL_TO", ""),
        email_subject_prefix=os.getenv("EMAIL_SUBJECT_PREFIX", "📰 Daily Digest"),
        resend_api_key=os.getenv("RESEND_API_KEY", ""),
        resend_from=os.getenv("RESEND_FROM", "onboarding@resend.dev"),
        save_markdown=os.getenv("SAVE_MARKDOWN", "true").lower() == "true",
        max_articles_per_topic=int(os.getenv("MAX_ARTICLES_PER_TOPIC", "3")),
        max_iterations=int(os.getenv("MAX_ITERATIONS", "16")),
        max_searches=int(os.getenv("MAX_SEARCHES", "12")),
        max_fetches=int(os.getenv("MAX_FETCHES", "18")),
        delivery_mode=os.getenv("DELIVERY_MODE", "artifact").lower(),
        memory_dir=os.getenv("MEMORY_DIR", "memory"),
        timezone=os.getenv("TIMEZONE", "Europe/Rome"),
    )
