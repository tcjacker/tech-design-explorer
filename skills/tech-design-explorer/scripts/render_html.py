#!/usr/bin/env python3
"""Stage 3 — render the interactive explorer.

Takes design-summary.json, builds every view, and injects the whole model into
one HTML file. The template is the view; the JSON payload is the model, so the
page needs no build step and works from `file://`.

    python3 render_html.py design-summary.json -o design-explorer.html

Two output shapes:
  --format standalone   a complete document you can open or share  (default)
  --format artifact     title + style + body only, ready to publish with the
                        Artifact tool (declare `capabilities: {sample: {}}` to
                        light up the in-page Ask panel)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import read_json, strings, write_text  # noqa: E402
from build_views import build  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "explorer.html"

MERMAID_URLS = [
    "https://cdnjs.cloudflare.com/ajax/libs/mermaid/11.6.0/mermaid.min.js",
    "https://cdn.jsdelivr.net/npm/mermaid@11.6.0/dist/mermaid.min.js",
]

HEAD = (
    '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    '<meta name="generator" content="tech-design-explorer">\n'
)


def payload_script(bundle: Dict[str, Any]) -> str:
    text = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    # keep the JSON from terminating the surrounding <script> element
    return text.replace("</", "<\\/").replace("<!--", "<\\!--")


def render(summary: Dict[str, Any], *, mermaid_urls: List[str], inline_mermaid: str = "",
           fmt: str = "standalone", template: Path = TEMPLATE,
           lang: str = "auto") -> Dict[str, Any]:
    bundle = build(summary, lang=lang)
    bundle["strings"] = strings(bundle["lang"])
    bundle["generated_at"] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    bundle["mermaid_urls"] = [] if inline_mermaid else mermaid_urls

    tpl = template.read_text(encoding="utf-8")
    title = bundle["summary"].get("title") or "Technical Design"
    html = tpl.replace("__TITLE__", title)
    html = html.replace("__DESIGN_PAYLOAD__", payload_script(bundle))

    if inline_mermaid:
        lib = Path(inline_mermaid).read_text(encoding="utf-8")
        html = html.replace("<!--MERMAID_SLOT-->", "<script>\n" + lib + "\n</script>")
    else:
        html = html.replace("<!--MERMAID_SLOT-->", "")

    head, _, body = html.partition("<!--HEAD/BODY-->")
    if fmt == "artifact":
        out = head + body
    else:
        out = HEAD + head + "</head>\n<body>\n" + body + "\n</body>\n</html>\n"
    bundle["_html"] = out
    return bundle


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("summary", help="design-summary.json")
    ap.add_argument("-o", "--out", default="design-explorer.html")
    ap.add_argument("--format", choices=["standalone", "artifact"], default="standalone")
    ap.add_argument("--mermaid-url", action="append", default=[],
                    help="override the mermaid CDN URLs (repeatable, tried in order)")
    ap.add_argument("--inline-mermaid", default="",
                    help="path to mermaid.min.js to embed for a fully offline page")
    ap.add_argument("--template", default=str(TEMPLATE))
    ap.add_argument("--lang", choices=["auto", "en", "zh"], default="auto",
                    help="UI language (auto: detect from the design's own text)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    bundle = render(read_json(args.summary),
                    mermaid_urls=args.mermaid_url or MERMAID_URLS,
                    inline_mermaid=args.inline_mermaid,
                    fmt=args.format,
                    template=Path(args.template),
                    lang=args.lang)
    write_text(args.out, bundle["_html"])
    if not args.quiet:
        size = Path(args.out).stat().st_size
        print(f"wrote {args.out} ({size // 1024} KB, "
              f"{sum(len(v['diagrams']) for v in bundle['views'])} diagrams, lang={bundle['lang']})")
        warns = [c for c in bundle["checks"] if c["level"] == "warn"]
        if warns:
            print(f"  {len(warns)} consistency warning(s) — shown in the Review checks section")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
