# ruff: noqa: E501  (inline CSS and HTML read better unwrapped)
"""Render technical_report.md to a whitepaper-style PDF with a headless Chromium browser (Edge or Chrome).

Usage: python scripts/report_pdf.py [--out rosetta-flow_Report.pdf]
Needs markdown-it-py and latex2mathml (pip install markdown-it-py latex2mathml) and a Chromium-based browser. Fonts: Inter and JetBrains Mono
from web/node_modules when installed (npm ci in web/), Neue Haas Grotesk Display for headings when installed on the
system; otherwise system fallbacks.
"""

from __future__ import annotations

import argparse
import html as htmllib
import re
import shutil
import subprocess
import sys
from pathlib import Path

import latex2mathml.converter
from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "web" / "node_modules" / "@fontsource-variable"


def font_faces() -> str:
    # brand font (Neue Haas Grotesk Display) for headings and body; Inter only where it is not installed
    faces = []
    for family in ("Display", "Body"):
        for weight, style, name in ((400, "normal", "Roman"), (400, "italic", "RomanItalic"), (500, "normal", "Mediu"),
                                    (600, "normal", "Mediu"), (700, "normal", "Bold")):
            faces.append(f"@font-face{{font-family:'{family}';font-weight:{weight};font-style:{style};"
                         f"src:local('NeueHaasDisplay-{name}'),local('Inter')}}")
    for family, rel in (("Inter", "inter/files/inter-latin-wght-normal.woff2"),
                        ("Inter", "inter/files/inter-latin-ext-wght-normal.woff2"),
                        ("Mono", "jetbrains-mono/files/jetbrains-mono-latin-wght-normal.woff2")):
        f = FONTS / rel
        if f.exists():
            faces.append(f"@font-face{{font-family:'{family}';font-weight:100 900;src:url('{f.as_uri()}') format('woff2')}}")
    return "\n".join(faces)


CSS = """
@page { size: A4; margin: 15mm 16mm 16mm 16mm;
  @bottom-left { content: "rosetta-flow  ·  Technical report  ·  Hack Apertus 2026"; font: 7pt 'Body', 'Segoe UI', sans-serif; color: #8a8f98; }
  @bottom-right { content: counter(page) " / " counter(pages); font: 7pt 'Body', 'Segoe UI', sans-serif; color: #8a8f98; } }
:root { --ink: #16181d; --muted: #5d636e; --rule: #d9dce1; --hair: #eceef1; --accent: #4a6a00; --tint: #f3f8e1; }
html { font-size: 8.85pt; }
body { font-family: 'Body', 'Inter', 'Segoe UI', Arial, sans-serif; color: var(--ink); line-height: 1.39; margin: 0; letter-spacing: 0.012em; font-variant-ligatures: none; font-feature-settings: "liga" 0, "clig" 0;
  font-feature-settings: "tnum" 0, "cv11" 1; -webkit-font-smoothing: antialiased; }
p { margin: 0 0 0.5em 0; text-align: justify; hyphens: auto; orphans: 3; widows: 3; }
strong { font-weight: 600; }
a { color: var(--accent); text-decoration: none; overflow-wrap: anywhere; }
ul, ol { margin: 0.1em 0 0.6em 0; padding-left: 1.15em; }
li { margin: 0.18em 0; text-align: justify; hyphens: auto; }
li::marker { color: var(--accent); }
code { font-family: 'Mono', Consolas, monospace; font-size: 0.84em; background: #f3f4f6; border-radius: 3px; padding: 0.05em 0.3em; overflow-wrap: anywhere; }

/* title block */
.title { margin: 0 0 1.1em 0; padding-bottom: 0.9em; border-bottom: 1.2px solid var(--ink); }
.eyebrow { font: 600 7.4pt 'Body', sans-serif; letter-spacing: 0.14em; text-transform: uppercase; color: var(--muted); margin-bottom: 0.9em; }
.brand { display: flex; align-items: center; gap: 12px; }
.mark { width: 34px; height: 34px; border-radius: 9px; background: #ff5fa6; display: grid; place-items: center; }
.mark img { width: 23px; height: 23px; }
.brand h1 { font-family: 'Display', 'Body', sans-serif; font-weight: 500; font-size: 27pt; letter-spacing: -0.01em; margin: 0; line-height: 1; }
.subtitle { font-family: 'Display', 'Body', sans-serif; font-weight: 400; font-size: 13.5pt; color: #2b2f36; margin: 0.55em 0 0.9em 0; line-height: 1.25; }
.meta { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.45em 1.6em; font-size: 7.9pt; }
.meta div { min-width: 0; }
.meta b { display: block; font-weight: 600; font-size: 6.6pt; letter-spacing: 0.12em; text-transform: uppercase; color: var(--muted); margin-bottom: 0.1em; }
.meta span { overflow-wrap: anywhere; }

/* headings */
h2 { font-family: 'Display', 'Body', sans-serif; font-weight: 500; font-size: 13pt; letter-spacing: -0.005em; margin: 1.05em 0 0.4em 0;
  padding-top: 0.45em; border-top: 0.6px solid var(--rule); break-after: avoid; }
h2 .n, h3 .n { color: var(--accent); margin-right: 0.45em; font-variant-numeric: tabular-nums; }
h3 { font-family: 'Display', 'Body', sans-serif; font-weight: 500; font-size: 10.6pt; margin: 1em 0 0.35em 0; break-after: avoid; }
h2 + p, h3 + p { margin-top: 0; }
.title + h2 { border-top: none; padding-top: 0; margin-top: 0.2em; }
td.num, td:first-child { white-space: nowrap; }
h2.refs + ul { font-size: 7.6pt; line-height: 1.35; }
h2.refs + ul li { text-align: left; }

/* tables: booktabs */
table { border-collapse: collapse; width: 100%; margin: 0.5em 0 0.85em 0; font-size: 7.7pt; line-height: 1.3; break-inside: avoid;
  border-top: 1.1px solid var(--ink); border-bottom: 1.1px solid var(--ink); font-variant-numeric: tabular-nums; }
th { font-weight: 600; text-align: left; padding: 4px 6px; border-bottom: 0.6px solid var(--ink); vertical-align: bottom; }
td { padding: 3.2px 6px; border-bottom: 0.4px solid var(--hair); vertical-align: top; }
tr:last-child td { border-bottom: none; }
tr.ours td { background: var(--tint); }

/* formulas (MathML, drawn by the browser) */
math { font-family: 'Cambria Math', 'STIX Two Math', math; font-size: 1.18em; }
td math { white-space: nowrap; }

/* figure */
figure { margin: 0.4em 0 0.9em 0; break-inside: avoid; }
figure img { width: 100%; display: block; }
figcaption { font-size: 7.6pt; color: var(--muted); margin-top: 0.35em; }
figcaption b, .tcap b { color: var(--ink); font-weight: 600; }
"""


def title_block(head: str) -> str:
    """The markdown header (h1, subtitle, bullet list) as a designed title block."""
    lines = [ln.strip() for ln in head.strip().splitlines() if ln.strip()]
    subtitle = lines[1] if len(lines) > 1 and not lines[1].startswith("-") else ""
    md = MarkdownIt("commonmark")
    meta = []
    for ln in lines:
        m = re.match(r"- \*\*(.+?):\*\*\s*(.+)", ln)
        if m and m.group(1) not in ("Track", "Event"):
            value = md.renderInline(m.group(2))
            meta.append(f"<div><b>{htmllib.escape(m.group(1))}</b><span>{value}</span></div>")
    logo = ROOT / "web" / "src" / "logo-mark.png"
    mark = f'<div class="mark"><img src="{logo.as_uri()}" alt=""></div>' if logo.exists() else ""
    return (
        '<header class="title"><div class="eyebrow">Hack Apertus 2026 &nbsp;·&nbsp; Track 2B &nbsp;·&nbsp; Technical report</div>'
        f'<div class="brand">{mark}<h1>rosetta-flow</h1></div>'
        f'<p class="subtitle">{md.renderInline(subtitle)}</p><div class="meta">{"".join(meta)}</div></header>'
    )


# $...$ is LaTeX (GitHub renders it too); a $ followed by a digit is a price ("$1.23"), not math
MATH = re.compile(r"(?<![\\$\w])\$(?=[^\s\d$])(.+?)(?<=\S)\$(?!\d)")


def protect_math(text: str) -> tuple[str, list[str]]:
    """Swap inline LaTeX for placeholders before markdown sees it; return the MathML to put back."""
    formulas: list[str] = []

    def keep(m: re.Match[str]) -> str:
        formulas.append(latex2mathml.converter.convert(m.group(1)))
        return f"MATH{len(formulas) - 1}X"

    return MATH.sub(keep, text), formulas


def polish(body: str) -> str:
    # numbered headings: accent number
    body = re.sub(r"<h([23])>(\d+(?:\.\d+)?)\.?\s+", r'<h\1><span class="n">\2</span>', body)
    # images as captioned figures
    body = re.sub(
        r'<p><img src="([^"]+)" alt="([^"]*)" ?/?></p>',
        lambda m: f'<figure><img src="{m.group(1)}" alt="{m.group(2)}"><figcaption><b>Figure 1.</b> '
        "Build time (online, once) and runtime (inside the customer network).</figcaption></figure>",
        body,
    )
    body = body.replace("<h2>References</h2>", '<h2 class="refs">References</h2>')
    # numeric cells ("0.71 / 0.64", "41 / 7") never wrap
    body = re.sub(r"<td>((?:<strong>)?[\d.,%/ x]+(?:</strong>)?)</td>", r'<td class="num">\1</td>', body)
    # highlight our row in result tables
    return re.sub(r"<tr>\s*<td><strong>", '<tr class="ours"><td><strong>', body)


def find_browser() -> str:
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "chromium",
        "chromium-browser",
        "google-chrome",
    ]
    for c in candidates:
        if Path(c).exists() or shutil.which(c):
            return c
    sys.exit("no Chromium-based browser found")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=ROOT / "technical_report.md", type=Path)
    ap.add_argument("--out", default=ROOT / "rosetta-flow_Report.pdf", type=Path)
    args = ap.parse_args()

    text = args.src.read_text(encoding="utf-8")
    head, _, rest = text.partition("\n## ")
    rest, formulas = protect_math(rest)
    md = MarkdownIt("commonmark").enable("table")
    body = polish(md.render("## " + rest))
    for i, mathml in enumerate(formulas):
        body = body.replace(f"MATH{i}X", mathml)
    page = (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><style>{font_faces()}{CSS}</style></head>'
        f"<body>{title_block(head)}{body}</body></html>"
    )
    html_path = args.src.with_suffix(".html")
    html_path.write_text(page, encoding="utf-8")

    out = args.out.resolve()
    cmd = [
        find_browser(),
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--allow-file-access-from-files",
        f"--print-to-pdf={out}",
        html_path.resolve().as_uri(),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    html_path.unlink()
    pages = len(re.findall(rb"/Type\s*/Page[^s]", out.read_bytes()))
    print(f"{out.name}: {pages} pages, {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
