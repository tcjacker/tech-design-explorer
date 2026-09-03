---
name: tech-design-explorer
description: Turn a technical design document (design.md, tech-spec.md, rfc.md, architecture.md) into an interactive HTML design explorer — overview, architecture, sequence, state machine, data model, failure paths, rollout plan and ADR cards in one reviewable artifact. Use when someone wants to visualize, review, or walk through a technical plan, spec or RFC rather than read it top to bottom.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# Tech Design Explorer

Turn a design document into a **visual review artifact**: one self-contained HTML
page a reviewer can understand in three to five minutes.

The output is not "a diagram of the doc". It is a set of focused views —
each answering one question — plus the decisions, failures and risks that a
reviewer actually argues about.

## Use this when

- The user asks to visualize / review / explore a design doc, tech spec, RFC or plan.
- The design has components, a runtime flow, states, data, or failure handling.
- The user wants something to share with reviewers instead of a wall of markdown.

Do **not** use it when the doc is a paragraph long (draw one diagram instead), when
the task is to *write* the spec, or when there is not enough structure to fill more
than two views — say so rather than padding the page with empty sections.

## Pipeline

Four stages. Stage 1 and 3 are scripts; **stage 2 is you** — the scripts cannot read
prose, and the quality of the artifact is decided entirely by the JSON you write.

```sh
# the scripts sit next to this file; installed as a plugin they are under
# $CLAUDE_PLUGIN_ROOT. Resolve the path once, then use $S everywhere.
S="$(dirname "$(ls -d "${CLAUDE_PLUGIN_ROOT:-.}"/skills/tech-design-explorer/SKILL.md \
     ./skills/tech-design-explorer/SKILL.md ./.claude/skills/tech-design-explorer/SKILL.md \
     2>/dev/null | head -1)")/scripts"

# 1. scaffold: classify sections, pull out the obvious structure, list the gaps
python3 $S/parse_design.py design.md -o design-summary.draft.json

# 2. YOU read the document and the draft, then write design-summary.json
#    (see reference/schema.md — the draft's `_gaps` list is your worklist)

# 3. generate the views + the explorer
python3 $S/render_html.py design-summary.json -o design-explorer.html

# or, for a shareable folder with the .mmd sources and a README
python3 $S/export_bundle.py design-summary.json -o design-explorer/
```

`build_views.py` runs inside `render_html.py`; call it directly only when you want
the `.mmd` files alone.

The page's own labels follow the design: a document written in Chinese produces a
Chinese explorer. Force it either way with `--lang en|zh` (default `auto`). The
content is never translated — only the chrome, view titles and generated captions.

### Stage 1 — scaffold

`parse_design.py` splits the document by heading, labels each section, and extracts
bullets, tables, numbered flows and any mermaid blocks the author already wrote. It
writes `_gaps` (what it could not find), `_source_sections` (the raw text per label)
and `_unclassified_sections`. It is a starting point, never the deliverable.

### Stage 2 — extract the design (the part that matters)

Read the document yourself. Then write `design-summary.json`, using the draft only
as raw material. Rules that decide whether the artifact is any good:

- **Name things once.** One name per component, used identically in every flow,
  failure path and state machine. Inconsistent names are the #1 way these pages rot.
- **Responsibilities, not labels.** `"responsibility": "Owns the hour commit
  lifecycle and its failure states"` — not `"handles commits"`.
- **Flows are messages between named components.** `{"from": "Frontend FSM", "to":
  "Backend FSM", "action": "request hour commit"}`. Every `from`/`to` must be a
  declared component or persona.
- **Failure paths need a decision.** A failure path that is a straight line is a
  log statement, not a failure path. Give it the branch (`"type": "decision"` with
  `next`), the detection, and where it comes to rest.
- **Decisions need real alternatives.** Pros *and* cons for each, an explicit
  `chosen`, and a `reason` that would survive a reviewer asking "why not the other one?".
- **Delete what the design does not have.** An empty section is worse than a missing
  one; omitted keys are simply skipped. Note the real gap in `open_questions`.
- Drop `_gaps`, `_source_sections` and `_unclassified_sections` from the final file.

Field-by-field reference: `reference/schema.md`. Worked example:
`examples/sample_design-summary.json` next to `examples/sample_design.md`.

### Stage 3 — views

One diagram, one idea; 5–12 nodes each. The generator picks the form per semantic:

| What you extracted | View | Mermaid form |
| --- | --- | --- |
| primary `runtime_flow` | Overview | `flowchart LR` of the happy path |
| `components` + `connections` | Architecture | `flowchart TB` with a subgraph per group |
| each `runtime_flow` | Runtime Flow | `sequenceDiagram` + a step walkthrough |
| `states` | State Model | `stateDiagram-v2` |
| `entities` | Data Model | `erDiagram` |
| each `failure_path` | Failure Paths | `flowchart TD` with decision diamonds |
| `rollout_phases` | Rollout Plan | `flowchart LR` of phases and dependencies |
| `decisions` | ADR cards | HTML comparison cards, not a diagram |

Hand-write a view only when the generated one cannot express the idea: put the
mermaid source in `views.<view_key>` and it replaces the generated one. Read
`reference/views.md` first — it lists the mermaid pitfalls that silently break a
render (colons in state labels, `#` and `;` in any label, `[*]` handling).

### Stage 4 — check before you hand it over

`render_html.py` prints consistency warnings and the page shows them in
**Review checks**. Treat a `warn` as a bug in your extraction, not as noise:

- a flow talks to something that is not a declared component
- a component is connected to nothing, or never appears in any flow
- a state has no incoming transition
- the design changes components but has no rollout plan
- a view is over the node budget

Then open the file and look at it. If a diagram is unreadable, the fix is fewer
nodes in the JSON, not more zooming.

## What the reader gets

Sticky section nav with scroll-spy · text filter · light/dark · collapse/expand ·
`⤢` focus-one-section · per-diagram zoom, pan, fullscreen, copy-mermaid, SVG/PNG
export · a **Walkthrough** that steps and auto-plays through a flow, highlighting
one message at a time · ADR comparison cards · risk and failure tables ·
an **Ask** panel for questions about the design.

The page is one file. Mermaid loads from a CDN; pass
`--inline-mermaid path/to/mermaid.min.js` to embed it for a fully offline page,
and the page falls back to showing the diagram source if the library never loads.

## Publishing and the Ask panel

- **Local / attachment**: `--format standalone` (default) writes a complete document.
- **Claude Artifact**: `--format artifact` writes title + style + body only. Publish
  it with `capabilities: {sample: {}}` and the Ask panel goes **live** — the reader
  asks questions and Claude answers grounded in the embedded design summary. Without
  that capability the panel degrades to a copyable, fully-grounded prompt.

See `reference/publishing.md`.

## Deliverable standard

A good result:

- puts the whole design in front of a reviewer in three to five minutes
- uses one vocabulary across every view
- makes failure paths and tradeoffs explicit instead of implied
- has no empty sections and no diagram nobody can read
- ends with the open questions the author still owes an answer to
