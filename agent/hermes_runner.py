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

Copertura editoriale obbligatoria:
- Prima di selezionare le notizie, fai una ricognizione equilibrata su queste aree: nuovi modelli e release; ricerca e safety; prodotti e agenti; open source; chip, infrastruttura e robotica; startup, finanziamenti e acquisizioni; regolamentazione e impatto geopolitico.
- Cerca esplicitamente sviluppi provenienti da ecosistemi diversi: OpenAI, Anthropic, Google DeepMind, Meta, Microsoft, xAI, Mistral, Cohere, Hugging Face, Alibaba/Qwen, DeepSeek, Moonshot/Kimi, Baidu, NVIDIA, AMD, aziende europee e startup emergenti. L'elenco è una guida, non un elenco di notizie da inventare.
- Considera una notizia solo se è recente, verificabile e con impatto concreto. Una notizia di un'azienda meno nota ma importante deve prevalere su una notizia marginale di una Big Tech.
- Non lasciare che un singolo soggetto domini il digest: salvo eventi eccezionali, massimo due notizie sullo stesso protagonista e almeno cinque protagonisti distinti quando le fonti lo consentono.
- Cerca prima le notizie principali del giorno e poi approfondisci le migliori; non trasformare il digest in un riepilogo di una sola azienda.
- Nei risultati RSS usa `publisher` e `published_at` per valutare autorevolezza e attualità prima di chiamare `web_fetch`.

Lingua obbligatoria:
- Il digest finale, compresi titoli, sintesi, analisi e descrizioni, deve essere scritto esclusivamente in italiano.
- Puoi usare query di ricerca in inglese, ma devi tradurre sempre il risultato finale in italiano.

Regole:
- Scrivi tutto in italiano, con tono professionale e conciso.
- Non usare tabelle Markdown: su smartphone sono difficili da leggere.
- Per ogni notizia usa questo formato: `### ⭐⭐⭐⭐⭐ Titolo`, seguito da **Cosa è successo**, **Perché è importante**, **Impatto** e **Fonte**.
- Usa Markdown normale: non inserire backslash davanti a `|`, `-`, `*` o altri caratteri.
- Cita solo URL originali degli articoli o fonti primarie; non citare URL `news.google.com` se hai un `source_url`.
- Distingui chiaramente fatti, analisi, rumor e speculazioni.
- Deduplica articoli che descrivono lo stesso evento.
- Concentrati solo su modelli/LLM, agenti, ricerca, AI generativa, coding, open source, Big Tech, startup, funding/M&A, robotica, hardware, strumenti e regolamentazione AI.
- Se i risultati sono scarsi, amplia la query e riprova includendo organizzazioni e aree ancora non coperte.
- Limita la ricerca a poche query mirate per categoria: dopo aver raccolto fonti sufficienti, smetti di cercare e scrivi il digest.
- Se una fonte non si apre o restituisce un errore, ignorala e passa alla successiva: non riprovare lo stesso URL.
- Devi arrivare sempre alla sintesi finale entro il limite di iterazioni; non continuare la ricerca indefinitamente.
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
            f"La data odierna è {today}.\n\n"
            f"Cerca e scrivi un digest quotidiano per questi ambiti: {topics_str}.\n\n"
            f"Seleziona fino a {self.settings.max_articles_per_topic} notizie per ambito.\n\n"
            "Prepara una rassegna globale ed equilibrata dell'intelligenza artificiale, non un riepilogo centrato su OpenAI. "
            "Copri più aree e organizzazioni indipendenti, includendo quando sono rilevanti i nuovi modelli fuori dagli Stati Uniti, "
            "per esempio Kimi, Qwen, DeepSeek o Mistral. Dai priorità a impatto e attendibilità, non al numero di articoli.\n\n"
            "Scrivi il risultato finale esclusivamente in italiano.\n\n"
            + (f"Note delle esecuzioni precedenti: usa queste informazioni per migliorare la ricerca:\n{skill_context}\n\n" if skill_context else "")
            + "Inizia ora la ricerca."
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
                    # Tool-oriented model responses may legally contain
                    # content=None. Treat that as an empty final response
                    # instead of crashing while checking the completion marker.
                    content = msg.get("content") or ""
                    if not isinstance(content, str):
                        content = str(content)
                    if "<<<DIGEST_COMPLETE>>>" in content:
                        digest = content.replace("<<<DIGEST_COMPLETE>>>", "").strip()
                        self._save_and_learn(digest, today)
                        return digest
                    # Hermes finished but forgot the marker — return anyway
                    if content.strip():
                        self._save_and_learn(content.strip(), today)
                        return content.strip()
                    log.warning("Hermes stopped with empty content; asking it to continue.")
                    messages.append({
                        "role": "user",
                        "content": (
                            "La risposta precedente era vuota. Continua il lavoro e produci il digest "
                            "completo esclusivamente in italiano, oppure prosegui la ricerca se mancano fonti."
                        ),
                    })
                    continue

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

        # If the model used all iterations on research/tool calls, give it one
        # final tool-free turn to synthesize what it already collected. This
        # prevents one bad RSS/redirect URL from turning an otherwise useful
        # run into a failed pipeline.
        log.warning("Reached max iterations; requesting final synthesis.")
        final_messages = [
            *messages,
            {
                "role": "user",
                "content": (
                    "Interrompi subito la ricerca. Usa esclusivamente le fonti e i risultati già raccolti "
                    "per scrivere ora il digest completo esclusivamente in italiano, rispettando il formato richiesto. "
                    "Se una fonte è incompleta, omettila invece di inventare dati. "
                    "Termina con <<<DIGEST_COMPLETE>>>."
                ),
            },
        ]
        final_payload = {
            "model": self.settings.model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *final_messages],
            "temperature": 0.3,
            "max_tokens": 4096,
        }
        try:
            # The research client is already closed here because the loop has
            # finished; use a dedicated client for the final synthesis call.
            async with httpx.AsyncClient(timeout=120) as final_client:
                final_resp = await final_client.post(
                    OPENROUTER_URL,
                    headers=self.headers,
                    json=final_payload,
                )
                final_resp.raise_for_status()
                final_data = final_resp.json()
                final_content = final_data["choices"][0]["message"].get("content", "")
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            log.error("Final synthesis failed: %s", exc)
            return None

        if final_content and final_content.strip():
            digest = final_content.replace("<<<DIGEST_COMPLETE>>>", "").strip()
            self._save_and_learn(digest, today)
            return digest

        log.error("Final synthesis returned empty content.")
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
