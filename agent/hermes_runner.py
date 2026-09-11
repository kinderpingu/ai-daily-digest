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
import urllib.parse
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from config.settings import Settings
from tools.web_search import web_search
from tools.web_fetch import web_fetch
from tools.memory import SkillMemory

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """Sei un analista editoriale AI e prepari una newsletter quotidiana in italiano.

Il tuo compito è produrre un briefing chiaro, verificabile e leggibile da smartphone.

Lavora così:
1. Pianifica ricerche mirate sulle notizie AI più recenti.
2. Usa `web_search` per trovare articoli pertinenti.
3. Usa `web_fetch` sulle fonti più promettenti e privilegia il campo `source_url` restituito dal tool.
4. Sintetizza i risultati in Markdown con titolo, data, sintesi esecutiva, sezioni per categoria, trend trasversali e 3–5 sviluppi da monitorare.

Regole:
- Scrivi tutto in italiano, con tono professionale e conciso.
- Non usare tabelle Markdown: su smartphone sono difficili da leggere.
- Per ogni notizia usa questo formato: `### ⭐⭐⭐⭐⭐ Titolo`, seguito da **Cosa è successo**, **Perché è importante**, **Impatto** e **Fonte**.
- Usa Markdown normale: non inserire backslash davanti a `|`, `-`, `*` o altri caratteri.
- Cita solo URL originali degli articoli o fonti primarie; non citare URL `news.google.com` se hai un `source_url`.
- Distingui chiaramente fatti, analisi, rumor e speculazioni.
- Deduplica articoli che descrivono lo stesso evento.
- Concentrati solo su modelli/LLM, agenti, ricerca, AI generativa, coding, open source, Big Tech, startup, funding/M&A, robotica, hardware, strumenti e regolamentazione AI.
- Se i risultati sono scarsi, amplia la query e riprova.
- Non inventare notizie, dettagli o URL.
- Termina con il marcatore esatto: <<<DIGEST_COMPLETE>>>
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
        max_iterations = self.settings.max_iterations
        search_count = 0
        fetch_count = 0
        seen_urls = set()

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

                    if fn_name == "web_search":
                        search_count += 1
                        result = (
                            {"error": "Search budget exhausted; synthesize from collected sources."}
                            if search_count > self.settings.max_searches
                            else await self._dispatch_tool(fn_name, fn_args)
                        )
                    elif fn_name == "web_fetch":
                        url = fn_args.get("url", "")
                        canonical = self._canonical_url(url)
                        fetch_count += 1
                        if canonical in seen_urls:
                            result = {"url": url, "skipped": "duplicate source"}
                        elif fetch_count > self.settings.max_fetches:
                            result = {"url": url, "skipped": "fetch budget exhausted"}
                        else:
                            seen_urls.add(canonical)
                            result = await self._dispatch_tool(fn_name, fn_args)
                    else:
                        result = await self._dispatch_tool(fn_name, fn_args)
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result),
                    })

                messages.extend(tool_results)

        log.error("Reached max iterations without a complete digest.")
        return None

    @staticmethod
    def _canonical_url(url: str) -> str:
        parsed = urllib.parse.urlsplit(url.strip())
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        query = [(k, v) for k, v in query if not k.lower().startswith(("utm_", "oc_", "ref"))]
        return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), urllib.parse.urlencode(query), ""))

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
