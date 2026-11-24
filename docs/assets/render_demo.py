"""Render docs/assets/demo.svg: an animated terminal replay of the real demo output.

Run from the repository root after changing the demo:  python docs/assets/render_demo.py
"""

from __future__ import annotations

import html
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).with_name("demo.svg")
WIDTH, LINE_H, TOP, LEFT, WRAP = 1000, 21, 64, 24, 100
STEP, PAUSE, HOLD = 0.32, 0.9, 6.0  # seconds per line, extra pause before a numbered step, end hold


def demo_lines() -> list[str]:
    out = subprocess.run([sys.executable, "examples/three_agents.py", "--yes"], cwd=ROOT, check=True,
                         capture_output=True, text=True).stdout
    lines = []
    for raw in out.rstrip().splitlines():
        indent = len(raw) - len(raw.lstrip())
        wrapped = textwrap.wrap(raw.strip(), WRAP - indent) or [""]
        lines += [" " * indent + wrapped[0]] + [" " * (indent + 3) + w for w in wrapped[1:]]
    return lines


def css_class(line: str) -> str:
    s = line.strip()
    if s[:2].rstrip(")").isdigit() and s[1:2] == ")":
        return "step"
    if s.startswith("[ONAY"):
        return "ok"
    if s.startswith(("teslim", "---")):
        return "dim"
    return "out" if line.startswith("   ") else "step"


def render(lines: list[str]) -> str:
    lines = ["$ python examples/three_agents.py --yes"] + lines
    times, t = [], 0.4
    for line in lines:
        if css_class(line) == "step":
            t += PAUSE
        times.append(t)
        t += STEP
    total = t + HOLD
    height = TOP + LINE_H * len(lines) + 24
    rows, frames = [], []
    for i, (line, start) in enumerate(zip(lines, times)):
        p = start / total * 100
        frames.append(f"@keyframes k{i}{{0%,{p:.2f}%{{opacity:0}}{p + 0.4:.2f}%,97%{{opacity:1}}100%{{opacity:0}}}}")
        cls = "cmd" if i == 0 else css_class(line)
        y = TOP + LINE_H * i
        rows.append(f'<text class="l {cls}" x="{LEFT}" y="{y}" xml:space="preserve" '
                    f'style="animation:k{i} {total:.1f}s linear infinite">{html.escape(line)}</text>')
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" width="{WIDTH}" height="{height}" role="img" aria-label="Terminal recording of the Elçi three-agent demo">
<style>
  .bg{{fill:#0D1117}} .bar{{fill:#161B22}}
  text{{font-family:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:14px;fill:#C9D1D9}}
  .cmd{{fill:#F2A541;font-weight:700}} .step{{fill:#E6EDF3;font-weight:700}} .ok{{fill:#3FB950}} .dim{{fill:#8B949E}} .out{{fill:#C9D1D9}}
  .title{{font-family:Inter,-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;font-size:13px;fill:#8B949E}}
  @media (prefers-reduced-motion: reduce){{.l{{animation:none!important;opacity:1}}}}
  {chr(10).join("  " + f for f in frames)}
</style>
<rect class="bg" width="{WIDTH}" height="{height}" rx="14"/>
<path class="bar" d="M0 14 a14 14 0 0 1 14 -14 h{WIDTH - 28} a14 14 0 0 1 14 14 v22 h-{WIDTH} z"/>
<circle cx="22" cy="18" r="6" fill="#FF5F57"/><circle cx="42" cy="18" r="6" fill="#FEBC2E"/><circle cx="62" cy="18" r="6" fill="#28C840"/>
<text class="title" x="{WIDTH / 2}" y="23" text-anchor="middle">elçi · three agents, one person</text>
{chr(10).join(rows)}
</svg>
"""


if __name__ == "__main__":
    OUT.write_text(render(demo_lines()), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
