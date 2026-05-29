"""
agent/hermes_runner.py

This is the heart of the project.  It drives Hermes (via OpenRouter) through a
multi-step agentic loop:

  Plan  →  Search each topic  →  Read top stories  →  Synthesise  →  Write digest

Hermes uses tool calls for every search + fetch step, which the runner executes
locally and feeds back.  After ~15 runs the GEPA skill-memory loop in Hermes
starts self-optimising its search and synthesis strategies — giving the agent
genuine compound improvement over time.
"""

import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from config.settings import Settings
from tools.web_search import web_search
from tools.web_fetch import web_fetch
from tools.memory import SkillMemory

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """You are the Daily Digest Agent — an autonomous research assistant.

Your job is to produce a rich, readable daily briefing on the user's chosen topics.

You work by:
1. Planning which searches will surface the most relevant, recent stories.
2. Calling `web_search` to find articles (use targeted queries like "topic news today").
3. Calling `web_fetch` on the most promising URLs to get full content.
4. Synthesising findings into a structured Markdown digest with:
   - A short executive summary (3–5 sentences covering the day's biggest themes)
   - One section per topic, each with 2–3 story bullets (headline + 1-sentence insight + source URL)
   - A "Connections & Trends" section noting cross-topic patterns
   - A closing "Worth Watching" item — one thing to keep an eye on

Rules:
- Be concise but substantive.  No filler phrases.
- Cite every claim with its source URL.
- If a search returns thin results, widen the query and try again.
- Never fabricate stories or URLs.
- Finish with the exact marker: <<<DIGEST_COMPLETE>>>
"""


TOOLS: List[Dict] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for recent news and articles.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query, e.g. 'open source AI tools news today'"},
                    "num_results": {"type": "integer", "default": 5, "description": "Number of results to return (max 10)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch the text content of a URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL to fetch"},
                    "max_chars": {"type": "integer", "default": 4000, "description": "Max characters to return"},
                },
                "required": ["url"],
            },
        },
    },
]


class HermesRunner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.memory = SkillMemory()
        self.headers = {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/daily-digest-agent",
            "X-Title": "Daily Digest Agent",
        }

    async def run(self, today: str) -> Optional[str]:
        topics_str = ", ".join(self.settings.topics)
        skill_context = self.memory.load_context()

        user_message = (
            f"Today is {today}.\n\n"
            f"Research and write a daily digest for these topics: {topics_str}.\n\n"
            f"Fetch {self.settings.max_articles_per_topic} stories per topic.\n\n"
            + (f"Previous skill notes (use these to improve your approach):\n{skill_context}\n\n" if skill_context else "")
            + "Begin your research now."
        )

        messages = [{"role": "user", "content": user_message}]
        max_iterations = 20  # safety cap on tool-call loop

        async with httpx.AsyncClient(timeout=120) as client:
            for iteration in range(max_iterations):
                log.info("Hermes iteration %d/%d", iteration + 1, max_iterations)

                payload = {
                    "model": self.settings.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        *messages,
                    ],
                    "tools": TOOLS,
                    "tool_choice": "auto",
                    "temperature": 0.3,
                    "max_tokens": 4096,
                }

                try:
                    resp = await client.post(OPENROUTER_URL, headers=self.headers, json=payload)
                    resp.raise_for_status()
                except httpx.HTTPStatusError as e:
                    log.error("OpenRouter HTTP error: %s — %s", e.response.status_code, e.response.text)
                    return None

                data = resp.json()
                choice = data["choices"][0]
                msg = choice["message"]
                finish = choice.get("finish_reason", "")

                messages.append(msg)

                # ── No tool call → Hermes is done writing ──────────────────────
                if finish == "stop" or not msg.get("tool_calls"):
                    content = msg.get("content", "")
                    if "<<<DIGEST_COMPLETE>>>" in content:
                        digest = content.replace("<<<DIGEST_COMPLETE>>>", "").strip()
                        self._save_and_learn(digest, today)
                        return digest
                    # Hermes finished but forgot the marker — return anyway
                    if content.strip():
                        self._save_and_learn(content.strip(), today)
                        return content.strip()
                    log.warning("Hermes stopped with empty content.")
                    return None

                # ── Execute tool calls ─────────────────────────────────────────
                tool_results = []
                for tc in msg["tool_calls"]:
                    fn_name = tc["function"]["name"]
                    fn_args = json.loads(tc["function"]["arguments"])
                    log.info("  Tool call: %s(%s)", fn_name, list(fn_args.keys()))

                    result = await self._dispatch_tool(fn_name, fn_args)
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result),
                    })

                messages.extend(tool_results)

        log.error("Reached max iterations without a complete digest.")
        return None

    async def _dispatch_tool(self, name: str, args: Dict) -> Any:
        if name == "web_search":
            return await web_search(args["query"], args.get("num_results", 5))
        if name == "web_fetch":
            return await web_fetch(args["url"], args.get("max_chars", 4000))
        return {"error": f"Unknown tool: {name}"}

    def _save_and_learn(self, digest: str, today: str):
        """Persist the digest as Markdown and update skill memory (GEPA-style)."""
        if self.settings.save_markdown:
            slug = today.replace(" ", "_").replace(",", "")
            path = os.path.join("output", f"digest_{slug}.md")
            os.makedirs("output", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# Daily Digest - {today}\n\n{digest}\n", )
            log.info("Digest saved to %s", path)

        # Lightweight GEPA: record which topics yielded rich results
        self.memory.record_run(today, self.settings.topics)
