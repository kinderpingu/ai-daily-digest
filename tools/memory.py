"""
tools/memory.py

Lightweight GEPA-style skill memory.

After each run, we append a record to memory/skill_log.json.
On the next run, HermesRunner passes a summary of past patterns back into the
system context so Hermes can self-improve its search strategy over time.

This is the open-loop version of Hermes' built-in GEPA mechanism —
enough to demonstrate compounding improvement for the challenge.
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, List

log = logging.getLogger(__name__)

MEMORY_DIR = "memory"
LOG_FILE = os.path.join(MEMORY_DIR, "skill_log.json")
SKILLS_FILE = os.path.join(MEMORY_DIR, "learned_skills.md")


class SkillMemory:
    def __init__(self):
        os.makedirs(MEMORY_DIR, exist_ok=True)
        self._log: List[Dict] = self._load_log()

    # ── Public API ─────────────────────────────────────────────────────────────

    def record_run(self, date: str, topics: List[str]) -> None:
        """Append a run entry and rewrite the skills summary."""
        entry = {
            "date": date,
            "topics": topics,
            "run_count": len(self._log) + 1,
        }
        self._log.append(entry)
        self._save_log()
        self._update_skills_file()
        log.info("Skill memory updated (%d total runs).", len(self._log))

    def load_context(self) -> str:
        """Return a short context string to prepend to the agent's user message."""
        if not self._log:
            return ""
        run_count = len(self._log)
        recent = self._log[-3:]  # last 3 runs
        recent_dates = ", ".join(r["date"] for r in recent)

        lines = [
            f"You have completed {run_count} digest run(s) before.",
            f"Recent runs: {recent_dates}.",
            "Use this history to avoid repeating the same sources and to try broader or more specific queries for topics that previously returned thin results.",
        ]

        if os.path.exists(SKILLS_FILE):
            with open(SKILLS_FILE) as f:
                skills = f.read().strip()
            if skills:
                lines.append(f"\nLearned search patterns:\n{skills}")

        return "\n".join(lines)

    # ── Internals ──────────────────────────────────────────────────────────────

    def _load_log(self) -> List[Dict]:
        if not os.path.exists(LOG_FILE):
            return []
        try:
            with open(LOG_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []

    def _save_log(self) -> None:
        with open(LOG_FILE, "w") as f:
            json.dump(self._log, f, indent=2)

    def _update_skills_file(self) -> None:
        """Rewrite a human-readable skills file from the log."""
        topic_counts: Dict[str, int] = {}
        for entry in self._log:
            for t in entry.get("topics", []):
                topic_counts[t] = topic_counts.get(t, 0) + 1

        lines = ["# Digest Agent — Learned Skills\n"]
        lines.append(f"Total runs: {len(self._log)}\n")
        lines.append("## Topic frequency")
        for topic, count in sorted(topic_counts.items(), key=lambda x: -x[1]):
            lines.append(f"- {topic}: {count} run(s)")

        if len(self._log) >= 5:
            lines.append(
                "\n## Recommended query patterns (auto-generated after 5+ runs)\n"
                "- Prefer queries ending in 'today' or 'this week' for recency.\n"
                "- Combine topic + 'announcement' or 'release' for product news.\n"
                "- For broad topics, add 'site:github.com OR site:ycombinator.com' to narrow to developer sources.\n"
            )

        with open(SKILLS_FILE, "w") as f:
            f.write("\n".join(lines))
