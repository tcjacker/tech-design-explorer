# Shipping the explorer

## Local file (default)

```sh
python3 scripts/render_html.py design-summary.json -o design-explorer.html
```

One complete document. Mermaid is fetched from a CDN at open time (cdnjs first,
jsdelivr as fallback). If neither loads, every diagram shows its own source with an
explanation instead of a blank box — the page never breaks, it degrades.

Fully offline, for an air-gapped review or an email attachment:

```sh
npm pack mermaid@11.6.0            # or take dist/mermaid.min.js from anywhere
python3 scripts/render_html.py design-summary.json -o design-explorer.html \
  --inline-mermaid ./mermaid/dist/mermaid.min.js
```
That embeds ~2.6 MB and the page then works with no network at all.

## Answering questions on your own machine

```sh
python3 scripts/ask_server.py design-explorer.html --open        # auto-detects claude / codex
python3 scripts/ask_server.py design-explorer.html --agent codex
python3 scripts/ask_server.py design-explorer.html --cmd "ollama run llama3"
```

Serves the page on `127.0.0.1:7654` and exposes two endpoints the page looks for by
itself: `GET __tde/health` (which agent, if any) and `POST __tde/ask` (question in,
answer out). Each question is sent to the agent's stdin as a prompt carrying the
design document and the structured summary; whatever the agent prints is the answer.

The agent runs as you, on your machine, with your credentials — nothing is uploaded,
and the server binds to localhost only. One question is answered at a time.
If no agent CLI is installed the page stays in copy-prompt mode and says so.

## Interface language

`--lang auto` (the default) looks at the design summary itself: a predominantly CJK
design gets a Chinese interface, anything else English. `--lang en` / `--lang zh`
forces it. Only the chrome, the generated view titles and the generated captions
are localised — your own text is always shown as written, and English is the
fallback for any string a translation does not cover.

## As a Claude Artifact

```sh
python3 scripts/render_html.py design-summary.json -o explorer.html --format artifact
```

`--format artifact` omits the `<!doctype>`, `<html>`, `<head>` and `<body>` wrapper
because the Artifact runtime supplies them. Publish `explorer.html` with the
Artifact tool and pass:

```jsonc
capabilities: { sample: {} }
```

That is what turns the **Ask** panel live: the page calls
`await claude.use("sample")`, and every question is answered from the design summary
embedded in the page — the reader can interrogate the design while looking at it,
without leaving the artifact. The panel shows a `live` pill when the capability
resolved.

Without the capability (a plain local file, a shared HTML page, a viewer whose
account cannot run `sample`), `claude.use` resolves `null` and the panel falls back
to composing the same fully-grounded prompt with a **Copy full prompt** button. The
feature degrades; it never errors.

Keep the CDN default when publishing as an artifact: `cdnjs.cloudflare.com` and
`cdn.jsdelivr.net/npm/` are both on the artifact CSP allowlist, and inlining 2.6 MB
of library into a published page is wasteful.

## As a bundle

```sh
python3 scripts/export_bundle.py design-summary.json -o design-explorer/ --zip
```

Gives a folder (and optional zip) with the HTML, the summary JSON, one `.mmd` per
view and a README explaining the views and listing the open consistency checks.
Useful when the `.mmd` sources should live in the repo next to the design doc.

## Regenerating after a design change

Edit `design-summary.json`, never the HTML. Re-run stage 3. The JSON is the
artifact's source of truth and diffs review well in a pull request.
