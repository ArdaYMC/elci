"""Find agents already on this computer, so ``elci init`` can offer them. Nothing is exposed by itself.

Looks at (read only):

* Claude Code projects listed in ``~/.claude.json``: each folder is a candidate agent, described by
  the first line of its ``CLAUDE.md``. Its MCP setup is per folder, so each project can speak as a
  different Elçi agent.
* Claude Code subagents in ``~/.claude/agents/*.md`` and ``<project>/.claude/agents/*.md``.
* Claude Desktop, if its config file exists.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Candidate:
    name: str  # suggested Elçi agent name
    kind: str  # claude-code-project | claude-code-subagent | claude-desktop
    description: str
    path: str | None = None  # project folder, when there is one

    @property
    def mcp_command(self) -> str:
        add = f"claude mcp add elci -e ELCI_AGENT={self.name} -- elci-mcp"
        if self.kind == "claude-code-project" and self.path:
            return f'cd "{self.path}" && {add}'
        if self.kind == "claude-desktop":
            return f'add "elci-mcp" with env ELCI_AGENT={self.name} to claude_desktop_config.json'
        return add


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:40] or "agent"


def _first_line(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip().lstrip("#").strip()
            if line and not line.startswith("---"):
                return line[:100]
    except OSError:
        pass
    return ""


def _frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    m = re.match(r"---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            out[key.strip()] = value.strip().strip("\"'")
    return out


def _subagents(folder: Path, owner: str | None) -> list[Candidate]:
    found = []
    for md in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        meta = _frontmatter(md)
        name = meta.get("name") or md.stem
        where = f" (in {owner})" if owner else ""
        found.append(Candidate(slug(name), "claude-code-subagent", (meta.get("description") or "")[:100] + where))
    return found


def _desktop_config(home: Path) -> Path:
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "Claude" / "claude_desktop_config.json"
    return home / ".config" / "Claude" / "claude_desktop_config.json"


def find_local_agents(home: Path | None = None) -> list[Candidate]:
    home = home or Path.home()
    found: list[Candidate] = []
    try:
        projects = json.loads((home / ".claude.json").read_text(encoding="utf-8")).get("projects", {})
    except (OSError, ValueError):
        projects = {}
    for raw in sorted(projects):
        folder = Path(raw)
        if not folder.is_dir() or folder == home:
            continue
        found.append(Candidate(slug(folder.name), "claude-code-project",
                               _first_line(folder / "CLAUDE.md") or "Claude Code project", str(folder)))
        found += _subagents(folder / ".claude" / "agents", folder.name)
    found += _subagents(home / ".claude" / "agents", None)
    if _desktop_config(home).is_file():
        found.append(Candidate("desktop", "claude-desktop", "Claude Desktop app"))
    unique, seen = [], set()
    for c in found:
        if c.name not in seen:
            seen.add(c.name)
            unique.append(c)
    return unique
