---
description: Turn a design doc into an interactive HTML design explorer
argument-hint: [path/to/design.md] [--out design-explorer.html]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

Build a design explorer for: $ARGUMENTS

Follow the `tech-design-explorer` skill (`skills/tech-design-explorer/SKILL.md`)
end to end:

1. If no document was given, find the most likely one (`design.md`, `tech-spec.md`,
   `rfc*.md`, `architecture.md`, or the newest doc under `docs/`) and say which you
   picked before continuing.
2. Run `parse_design.py` to scaffold, then **read the document yourself** and write
   `design-summary.json` — the draft is raw material, not the answer. Close every
   entry in the draft's `_gaps` list or record it in `open_questions`.
3. Render with `render_html.py`, then report:
   - where the file is,
   - which views were generated and which were skipped for lack of material,
   - every consistency warning, and what you would change in the design to clear it.

Do not invent components, flows or decisions the document does not support. Missing
structure is a finding about the design — surface it in `open_questions` and in your
reply instead of filling the gap.
