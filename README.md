# tech-design-explorer

Turn a technical design document into an **interactive visual review artifact** —
not one architecture diagram, but the whole design as something a reviewer can
browse in three to five minutes.

```
design.md  ──▶  design-summary.json  ──▶  8 focused views  ──▶  design-explorer.html
             (the agent reads)          (generated)            (one self-contained file)
```

## What comes out

One HTML file with:

| Section | What it answers |
| --- | --- |
| Summary | Why this exists, goals, non-goals, constraints, success metrics |
| Users and stories | Who this is for and what they need |
| Overview | The happy path end to end, with a step-by-step walkthrough |
| Architecture | Components, boundaries, responsibilities |
| Runtime Flow | A sequence diagram per flow, with an auto-playing walkthrough |
| State Model | The lifecycle of the core object, dead ends included |
| Data Model | Entities, fields, ownership, relationships |
| Failure Paths | What happens on timeout, rejection, partial failure — with the branch |
| Rollout Plan | Phases, dependencies, exit criteria |
| Design decisions | ADR cards: alternatives, pros, cons, what was chosen and why |
| Risks / Open questions | What could go wrong, and what the author still owes |
| Review checks | Automated consistency findings across the views |

Plus: sticky nav with scroll-spy, text filter, light/dark, focus-one-section,
per-diagram zoom / pan / fullscreen / copy-mermaid / SVG + PNG export, and an
**Ask** panel that answers questions about the design from the summary embedded in
the page.

## Install

As a Claude Code plugin:

```
/plugin marketplace add tcjacker/tech-design-explorer
/plugin install tech-design-explorer
```

Then `/design-explore docs/design.md`, or just ask: *"turn this RFC into a design
explorer"*.

Or copy `skills/tech-design-explorer/` into any project's `.claude/skills/`. The
scripts are pure Python 3.8+ standard library — no dependencies, no build step.

## Use it without an agent

```sh
S=skills/tech-design-explorer/scripts

python3 $S/parse_design.py  design.md -o design-summary.draft.json   # scaffold + gap list
cp design-summary.draft.json design-summary.json                     # then edit it
python3 $S/render_html.py   design-summary.json -o design-explorer.html
```

The scaffold is only a scaffold: it classifies sections and pulls out bullets,
tables, numbered flows and existing mermaid blocks, then tells you what it could
not find. The design semantics — responsibilities, real failure branches, why one
alternative won — have to be written by a reader, human or agent. That is the whole
point of the split, and it is what `SKILL.md` walks an agent through.

Other entry points:

```sh
python3 $S/build_views.py    design-summary.json -o assets/            # just the .mmd files
python3 $S/export_bundle.py  design-summary.json -o design-explorer/ --zip
python3 $S/render_html.py    design-summary.json -o page.html --format artifact
python3 $S/render_html.py    design-summary.json -o page.html --inline-mermaid mermaid.min.js
```

The interface follows the document: a Chinese design doc produces a Chinese
explorer (`--lang auto`, the default); `--lang en|zh` forces it. Only the chrome is
localised, never your content.

`--format artifact` emits a body-only page for the Claude Artifact tool; publish it
with `capabilities: {sample: {}}` and the Ask panel answers live instead of handing
over a copyable prompt.

## Repository layout

```
skills/tech-design-explorer/
├── SKILL.md                 the agent-facing procedure
├── reference/
│   ├── schema.md            every field of design-summary.json
│   ├── views.md             which view for which semantic + mermaid pitfalls
│   └── publishing.md        local / offline / artifact / bundle
├── scripts/                 parse → build → render → bundle (stdlib only)
└── templates/explorer.html  the page: CSS + runtime, payload injected at render
commands/design-explore.md   /design-explore slash command
examples/                    a full worked design doc and its summary
tests/                       pipeline tests + optional real-mermaid validation
```

## Design principles

- **One diagram, one idea.** 5–12 nodes; the generator warns past that.
- **One vocabulary.** A component is named identically in every view, and the
  checks fail loudly when a flow talks to something that was never declared.
- **Failures are first-class.** A failure path without a branch and an end state is
  a log line, not a design.
- **JSON is the source of truth.** Regenerate the page; never hand-edit the HTML.
- **Degrade, never break.** No mermaid CDN → the diagram shows its own source. No
  model capability → the Ask panel hands over a grounded prompt.

## Development

```sh
python3 -m unittest discover -s tests -v          # 22 pipeline tests, stdlib only

# optional: parse every generated diagram with the real mermaid parser
npm i mermaid playwright
python3 skills/tech-design-explorer/scripts/export_bundle.py \
  examples/sample_design-summary.json -o /tmp/bundle
node tests/validate_mermaid.mjs /tmp/bundle/assets
```

## Roadmap

- **v1 (here)** — parse → summary → 8 views → interactive explorer; ADR cards;
  walkthrough; consistency checks; artifact publishing with a live Ask panel.
- **v2** — diff two versions of a spec; filter a flow to the happy or failure path
  only; click a node to jump to the section that explains it.
- **v3** — Excalidraw-style rendering for the whiteboard views; link diagram nodes
  to source files in the repository.
