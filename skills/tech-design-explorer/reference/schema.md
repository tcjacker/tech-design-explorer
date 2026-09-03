# design-summary.json

The one file you hand-write. Everything in the explorer is generated from it, so
this is where the thinking goes. Every key is optional — an omitted key means "the
design has none of this" and the matching view is skipped.

The loader is forgiving: where a field takes a list of objects it also accepts a
list of strings, and it will parse the short forms noted below. Prefer the object
form; the short form is for quick drafts.

Canonical example: `examples/sample_design-summary.json`.

## Header

```jsonc
{
  "title": "Hour Commit Decoupling",          // required in practice
  "subtitle": "Splitting progression from durable commit",
  "status": "Draft",                          // shown as a pill in the header
  "authors": ["Platform Team"],
  "date": "2026-08-20",
  "source_document": "docs/design.md",        // shown in the footer
  "summary": "Two or three sentences a reviewer reads first.",
  "background": "Why this exists. What hurts today. Keep it factual.",
  "goals": ["…"],
  "non_goals": ["…"],
  "constraints": ["Postgres is the only durable store"],
  "metrics": [{ "name": "p95 commit latency", "target": "< 800ms", "note": "" }]
}
```

## current_state / changes

What the system looks like today, and what this design does to it. Drives the
before / delta / after views and the change table; omit both and that view is
skipped (a greenfield design has no "before").

```jsonc
"current_state": {
  "summary": "One HourFSM owns both the player-visible hour and the durable write.",
  "pain_points": ["A failed write leaves the frontend an hour ahead", "Operators hand-edit SQL"]
},
"changes": [{
  "target": "Backend FSM",          // a declared component, entity, or a named process
  "kind": "component",              // component | connection | entity | process
  "type": "added",                  // added | modified | removed  (新增/改动/移除 also parse)
  "what": "New state machine owning PREPARING → COMMITTING → FAILED",
  "why": "Partial failure needs a state of its own",
  "files": ["engine/backend_fsm.py"],
  "risk": "medium"
}]
```

Each component and connection also carries its own `"change"`, which is what the
diagrams colour and label:

```jsonc
"components": [{ "name": "Backend FSM", "change": "added" }]      // default: "existing"
```

## personas / user_stories

Drives the "Users and stories" section. A persona `name` may be used as a `from`
in a runtime flow.

```jsonc
"personas": [{ "name": "Operator", "role": "On-call engineer", "need": "Retry a failed commit" }],
"user_stories": [{
  "as_a": "operator",
  "i_want": "a failed commit to be visible and retryable",
  "so_that": "I never hand-edit the database",
  "acceptance": ["Every FAILED commit emits an event", "Retry is one idempotent call"],
  "flow": [
    { "component": "Backend FSM", "action": "Commit lands in FAILED", "outcome": "write rejected" },
    { "component": "Event Bus",   "action": "Publish the failure with a session id" },
    { "component": "Operator",    "action": "Retry from the ops view", "outcome": "no SQL needed" }
  ]
}]
```
Short form: `"As an operator, I want X, so that Y"` (English or 作为…我希望…以便…) is parsed.

`flow` is what the Story Flow swimlane is drawn from: one lane per `component`, one
column per step, in order. `component` must be a declared component or persona.
A story that follows an existing runtime flow can point at it instead:
`"flow_ref": "Happy path: commit one hour"`. A story with neither is listed but not
drawn, and the checks say so.

## components / connections

The vocabulary for every other view. `name` is the identity — reuse it verbatim.

```jsonc
"components": [{
  "name": "Backend FSM",
  "group": "Engine",            // becomes a subgraph boundary
  "kind": "service",            // ui | service | store | queue | external | actor -> shape + colour
  "responsibility": "Owns the hour commit lifecycle and its failure states",
  "tech": "Python",             // optional, rendered as a sub-label
  "interfaces": ["commit(session_id)"],
  "critical": true              // flags it in the component table
}],
"connections": [
  { "from": "Backend FSM", "to": "Session Store", "label": "CAS write", "kind": "data" }
]
```
`kind` on a connection: `sync` (solid, default), `async` (dotted), `data` (thick).
Omit `connections` entirely and edges are inferred from the runtime flows — the
explorer says so in Review checks.

## runtime_flows

```jsonc
"runtime_flows": [{
  "name": "Happy path: commit one hour",
  "kind": "happy",              // happy | error | admin … the first `happy` drives the Overview
  "description": "One sentence about when this runs.",
  "actors": ["Web Client", "Backend FSM"],   // optional; derived from the steps otherwise
  "steps": [
    { "from": "Frontend FSM", "to": "Backend FSM", "action": "request hour commit" },
    { "from": "Backend FSM", "to": "Scenario Plugin", "action": "before_hour_tick()", "note": "200ms budget" },
    { "from": "Session Store", "to": "Hour Commit Service", "action": "write acknowledged", "kind": "return" }
  ]
}]
```
`kind` on a step: `call` (default), `return` (dashed), `async` (open arrow).
Short form for a step: `"Frontend FSM -> Backend FSM: request hour commit"`.

Keep a flow under ~16 steps. Longer means it is two flows.

## states

```jsonc
"states": [{
  "entity": "Backend FSM",      // ideally the name of a component
  "initial": "IDLE",
  "values": ["IDLE", "PREPARING", "COMMITTING", "FAILED"],
  "terminal": [],               // states that end the lifecycle
  "notes": "FAILED is parked: nothing leaves it without a retry.",
  "transitions": [
    { "from": "COMMITTING", "to": "FAILED", "event": "write rejected", "guard": "CAS version moved" }
  ]
}]
```
Short form for a transition: `"COMMITTING -> FAILED: write rejected"`.
Any state without an incoming transition is reported in Review checks.

## entities

```jsonc
"entities": [{
  "name": "session_cache",
  "owner": "Hour Commit Service",     // which component owns the writes
  "store": "PostgreSQL",
  "description": "Hot per-session state, one row per session",
  "fields": [{ "name": "session_id", "type": "uuid", "note": "PK" }],
  "relations": [{ "to": "hour_commit", "cardinality": "1..*", "label": "records" }]
}]
```
Short form for a field: `"uuid session_id"` or just `"session_id"`.
`cardinality`: `1..1`, `1..*`, `0..1`, `*..*`. Only the first 10 fields are drawn
(all of them are listed in the entity cards below the diagram).

## failure_paths

The section reviewers skip to. Give each one a branch and an end state.

```jsonc
"failure_paths": [{
  "name": "CAS write rejected",
  "trigger": "Concurrent write moved the session version",
  "component": "Session Store",
  "severity": "high",                 // low | medium | high
  "detection": "CAS mismatch counted in commit_failed_total",
  "impact": "The hour is not committed; the player stays on the current hour",
  "mitigation": "Re-draft against the fresh version, at most twice, then park",
  "steps": [
    { "id": "mark", "text": "Transition to FAILED and publish a failure event" },
    { "id": "retry", "text": "Retry budget left?", "type": "decision",
      "next": [{ "to": "redraft", "label": "Yes" }, { "to": "park", "label": "No" }] },
    { "id": "redraft", "text": "Re-draft against the fresh version" },
    { "id": "park", "text": "Park for operator intervention", "type": "terminal" }
  ]
}]
```
`type`: `step` (box), `decision` (diamond), `terminal` (rounded end).
`next[].to` refers to another step's `id`; steps without `next` fall through to the
next step in the list. Short form: a list of strings makes a straight line.

## rollout_phases

```jsonc
"rollout_phases": [{
  "name": "Phase 2 · Migration",
  "description": "Move commit execution behind the Backend FSM.",
  "duration": "3 weeks",
  "depends_on": ["Phase 1 · Scaffolding"],   // by phase name; sequential if omitted
  "deliverables": ["Commit execution moved", "Operator retry endpoint"],
  "exit_criteria": "One full release with zero fallbacks to the legacy path",
  "risk": "high"
}]
```

## decisions / risks / open_questions / glossary

```jsonc
"decisions": [{
  "title": "Two state machines instead of one",
  "status": "accepted",
  "context": "Why this came up at all.",
  "alternatives": [
    { "name": "Single FSM", "pros": ["Fewer parts"], "cons": ["Cannot express partial failure"] },
    { "name": "Two FSMs with an explicit boundary", "pros": ["Failure is explicit"], "cons": ["Needs reconciliation"] }
  ],
  "chosen": "Two FSMs with an explicit boundary",   // matched against alternative names
  "reason": "Smallest migration cost that makes the failure surface explicit.",
  "consequences": "We accept a reconciliation job and CAS versioning."
}],
"risks": [{ "title": "State divergence", "severity": "high", "likelihood": "medium",
            "impact": "Player sees an uncommitted hour", "mitigation": "CAS + reconciliation", "owner": "Platform" }],
"open_questions": [{ "question": "Auto-retry or always wait for an operator?", "owner": "Platform", "blocking": true }],
"glossary": [{ "term": "CAS", "definition": "Compare-and-set write guarded by a version token" }]
```

## document_sections / source_map

The design document itself, carried into the page: the reader can open the original
prose behind any view, read the whole thing in the last section, and every question
in the Ask panel is answered from it.

```jsonc
"document_sections": [{ "id": "doc-3", "heading": "Architecture", "level": 2, "text": "…markdown…" }],
"source_map": { "architecture": "doc-3", "sequence": "doc-4" }
```

You rarely write these by hand: `parse_design.py` produces both, and
`render_html.py --document design.md` fills them in at render time.

## views (escape hatch)

```jsonc
"views": {
  "architecture": "flowchart TB\n  A[\"…\"] --> B[\"…\"]"
}
```
Keys: `overview`, `architecture`, `sequence`, `state_machine`, `data_model`,
`failure_paths`, `rollout_plan`. The supplied mermaid replaces the generated
diagram for that view. Use it only when the generator genuinely cannot express the
idea — a hand-written view stops benefiting from the consistency checks.
