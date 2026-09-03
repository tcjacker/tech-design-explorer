#!/usr/bin/env python3
"""Stage 2 — turn design-summary.json into focused mermaid views.

One diagram communicates one idea. This script never merges everything into a
single picture: each view gets its own definition, its own caption, and its own
node budget. It also runs consistency checks across views (same names, no
orphan components, failure paths that reference real components) and returns
them so the explorer can show a review panel.

    python3 build_views.py design-summary.json -o assets/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
from svg_views import swimlane  # noqa: E402
from _common import (  # noqa: E402
    IdFactory, VIEW_ORDER, VIEW_TITLES, UI_ZH, detect_lang, esc, known_names, normalize, norm_key,
    read_json, slug, wrap_label, write_json, write_text,
)

NODE_BUDGET = 12

# Diagram titles and captions, English inline / Chinese looked up by key.
TEXT_ZH = {
    "story.caption": "这个故事在系统里怎么走：一行一个参与方，一列一步。",
    "story.noflow": "还没有画出流转路径的用户故事",
    "change.before.title": "现状",
    "change.before.caption": "改动之前系统就长这样。",
    "change.delta.title": "本次改动",
    "change.delta.caption": "带标注的是本次动到的部分；灰色的这次不碰。",
    "change.after.title": "改造后",
    "change.after.caption": "这次改动落地之后的系统。",
    "overview.title": "端到端的正常路径",
    "overview.caption": "对系统最短的一句描述：谁调用谁，才能走完一次成功的流程。",
    "arch.title": "组件与职责",
    "arch.caption": "每个方框都是一个能独立失败的东西；分组画的是部署或归属边界。",
    "seq.caption": "这条流程一次运行的完整消息序列。编号与右侧走查步骤一一对应。",
    "state.caption": "复查者可能遇到的每一个状态，以及推动它前进的事件。没有出口的状态就是隐患。",
    "state.title": "{entity} 生命周期",
    "data.title": "实体与归属",
    "data.caption": "存了什么、放在哪里，以及代码必须一直维持成立的关系。",
    "fail.caption": "出问题之后系统怎么走，最终停在哪里。",
    "rollout.title": "阶段与依赖",
    "rollout.caption": "改动的落地顺序，以及进入下一阶段前必须成立的条件。",
}

CLASSDEFS = "\n".join([
    "classDef ui fill:#e8f0ff,stroke:#5b7cfa,stroke-width:1px,color:#16224a;",
    "classDef service fill:#eef7f0,stroke:#3f9d6a,stroke-width:1px,color:#12341f;",
    "classDef store fill:#fff4e6,stroke:#d9862b,stroke-width:1px,color:#42280a;",
    "classDef queue fill:#f4ecff,stroke:#8b5cf6,stroke-width:1px,color:#2c1a4a;",
    "classDef external fill:#f2f3f5,stroke:#98a2b3,stroke-width:1px,color:#2b3240;",
    "classDef actor fill:#fdeef1,stroke:#e05c76,stroke-width:1px,color:#4a1220;",
    "classDef failure fill:#fdeaea,stroke:#e04747,stroke-width:1px,color:#4a1212;",
    "classDef success fill:#e9f7ef,stroke:#2f9e5f,stroke-width:1px,color:#123222;",
    "classDef decision fill:#fff8e1,stroke:#d99e2b,stroke-width:1px,color:#42320a;",
    "classDef phase fill:#eef2ff,stroke:#6172f3,stroke-width:1px,color:#1c2456;",
])

SHAPES = {
    "ui": ('["', '"]'),
    "service": ('["', '"]'),
    "store": ('[("', '")]'),
    "queue": ('[/"', '"/]'),
    "external": ('["', '"]'),
    "actor": ('(["', '"])'),
}


def state_text(text: str, limit: int = 40) -> str:
    """mermaid's state parser ends a label at `:` — swap it for a dash."""
    return esc(text, limit).replace(":", " –")


class ViewBuilder:
    def __init__(self, summary: Dict[str, Any], lang: str = "en") -> None:
        self.s = summary
        self.lang = lang
        self.checks: List[Dict[str, str]] = []
        self.names = known_names(summary)
        self.kinds = {norm_key(c["name"]): c.get("kind", "service") for c in summary["components"]}
        self.crit = {norm_key(c["name"]) for c in summary["components"] if c.get("critical")}

    # -- helpers ---------------------------------------------------------
    def t(self, key: str, en: str, **fmt) -> str:
        text = TEXT_ZH.get(key, en) if self.lang == "zh" else en
        return text.format(**fmt) if fmt else text

    def view_title(self, key: str) -> str:
        return UI_ZH.get("view." + key, VIEW_TITLES[key]) if self.lang == "zh" else VIEW_TITLES[key]

    def check(self, level: str, view: str, message: str) -> None:
        self.checks.append({"level": level, "view": view, "message": message})

    def display(self, name: str) -> str:
        return self.names.get(norm_key(name), name)

    def kind_of(self, name: str) -> str:
        return self.kinds.get(norm_key(name), "external")

    def node(self, ids: IdFactory, name: str, label: str = "", kind: str = "") -> str:
        nid = ids.get(name)
        kind = kind or self.kind_of(name)
        open_s, close_s = SHAPES.get(kind, ('["', '"]'))
        return f'{nid}{open_s}{wrap_label(label or self.display(name))}{close_s}'

    def budget(self, view: str, count: int) -> None:
        if count > NODE_BUDGET:
            self.check("warn", view,
                       f"{count} nodes — above the {NODE_BUDGET}-node budget; consider splitting "
                       f"this view or grouping detail into a subgraph")

    def primary_flow(self) -> Dict[str, Any] | None:
        flows = self.s.get("runtime_flows") or []
        for f in flows:
            if f.get("kind", "happy") in ("happy", "primary", "main"):
                return f
        return flows[0] if flows else None

    # -- views -----------------------------------------------------------
    def overview(self) -> List[Dict[str, str]]:
        flow = self.primary_flow()
        if not flow and not self.s.get("components"):
            return []
        ids = IdFactory("o")
        lines = ["flowchart LR"]
        classes: List[str] = []
        chain: List[str] = []
        if flow:
            for step in flow["steps"]:
                for side in (step["from"], step["to"]):
                    if side and side not in chain:
                        chain.append(side)
        if not chain:
            chain = [c["name"] for c in self.s["components"][:NODE_BUDGET]]
        chain = chain[:NODE_BUDGET]
        for name in chain:
            lines.append("    " + self.node(ids, name))
            classes.append(f"    class {ids.get(name)} {self.kind_of(name)};")
        edges = set()
        story: List[Dict[str, Any]] = []
        if flow:
            for step in flow["steps"]:
                if step["from"] and step["to"] and step["from"] in chain and step["to"] in chain:
                    key = (step["from"], step["to"])
                    if key in edges:
                        continue
                    edges.add(key)
                    story.append({"n": len(story) + 1, "from": self.display(step["from"]),
                                  "to": self.display(step["to"]), "action": step["action"],
                                  "note": step.get("note", "")})
                    lines.append(f'    {ids.get(step["from"])} -->|"{esc(step["action"], 34)}"| '
                                 f'{ids.get(step["to"])}')
        else:
            for a, b in zip(chain, chain[1:]):
                lines.append(f"    {ids.get(a)} --> {ids.get(b)}")
        lines.append(CLASSDEFS)
        lines.extend(classes)
        self.budget("overview", len(chain))
        caption = (self.s.get("summary") or self.s.get("background") or "")[:280]
        return [{
            "id": "overview-main",
            "title": self.t("overview.title", "The happy path, end to end"),
            "caption": caption or self.t(
                "overview.caption",
                "The shortest description of the system: who calls whom to get one successful "
                "outcome."),
            "mermaid": "\n".join(lines),
            "steps": story,
            "story_mode": "edge" if story else "",
        }]

    def _graph(self, comps, conns, ids, class_of, tag_of=None) -> List[str]:
        """A grouped component graph. Shared by the architecture and change views."""
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for c in comps:
            groups.setdefault(c.get("group") or "", []).append(c)
        lines, classes = ["flowchart TB"], []
        for group, members in groups.items():
            indent = "    "
            if group:
                lines.append(f'    subgraph grp_{slug(group, "g")}["{esc(group, 40)}"]')
                lines.append("    direction TB")
                indent = "        "
            for c in members:
                # a marker at the *start* of a label is parsed as a markdown list by
                # mermaid, so the change state goes underneath the name instead
                label = wrap_label(c["name"])
                sub = [x for x in (tag_of(c) if tag_of else "", c.get("tech", "")) if x]
                if sub:
                    label += f'<br/><small>{esc(" · ".join(sub), 30)}</small>'
                shape_open, shape_close = SHAPES.get(c.get("kind", "service"), ('["', '"]'))
                lines.append(f'{indent}{ids.get(c["name"])}{shape_open}{label}{shape_close}')
                classes.append(f'    class {ids.get(c["name"])} {class_of(c)};')
            if group:
                lines.append("    end")
        for cn in conns:
            if not ids.known(cn["from"]) or not ids.known(cn["to"]):
                continue
            arrow = {"async": "-.->", "data": "==>"}.get(cn.get("kind"), "-->")
            label = f'|"{esc(cn["label"], 30)}"|' if cn.get("label") else ""
            lines.append(f'    {ids.get(cn["from"])} {arrow}{label} {ids.get(cn["to"])}')
        lines.append(CLASSDEFS)
        lines.extend(classes)
        return lines

    # ------------------------------------------------------------------
    def change_impact(self) -> List[Dict[str, str]]:
        """Today, the delta, and the result — the three pictures a reviewer wants."""
        comps = self.s.get("components") or []
        conns = self.s.get("connections") or []
        changes = self.s.get("changes") or []
        touched = [c for c in comps if c.get("change") != "existing"]
        if not touched and not changes and not (self.s.get("current_state") or {}).get("summary"):
            return []
        if not touched and not any(c.get("change") != "existing" for c in conns):
            # the design says what changes in prose but never marks a component
            self.check("info", "change_impact",
                       "no component carries a `change` status — the before/after views fall back "
                       "to the change list alone")

        def subset(states):
            keep = [c for c in comps if c.get("change", "existing") in states]
            names = {norm_key(c["name"]) for c in keep}
            edges = [cn for cn in conns
                     if cn.get("change", "existing") in states
                     and norm_key(cn["from"]) in names and norm_key(cn["to"]) in names]
            return keep, edges

        out = []
        before_comps, before_conns = subset({"existing", "modified", "removed"})
        after_comps, after_conns = subset({"existing", "modified", "added"})
        if before_comps:
            ids = IdFactory("b")
            out.append({
                "id": "change-before",
                "title": self.t("change.before.title", "Before — today"),
                "caption": (self.s.get("current_state") or {}).get("summary") or
                           self.t("change.before.caption", "The system as it stands before this change."),
                "mermaid": "\n".join(self._graph(before_comps, before_conns, ids,
                                                 lambda c: c.get("kind", "service"))),
            })
        if touched or any(cn.get("change", "existing") != "existing" for cn in conns):
            ids = IdFactory("d")
            tag = {"added": self.t("ui.added", "added"),
                   "modified": self.t("ui.modified", "modified"),
                   "removed": self.t("ui.removed", "removed")}
            out.append({
                "id": "change-delta",
                "title": self.t("change.delta.title", "The change"),
                "caption": self.t("change.delta.caption",
                                  "+ added, ~ modified, − removed. Grey is untouched by this design."),
                "mermaid": "\n".join(self._graph(
                    comps, conns, ids,
                    lambda c: {"added": "success", "modified": "decision",
                               "removed": "failure"}.get(c.get("change"), "external"),
                    lambda c: tag.get(c.get("change"), ""))),
            })
        if after_comps:
            ids = IdFactory("a2")
            out.append({
                "id": "change-after",
                "title": self.t("change.after.title", "After — this design"),
                "caption": self.t("change.after.caption", "The system once this change has landed."),
                "mermaid": "\n".join(self._graph(after_comps, after_conns, ids,
                                                 lambda c: c.get("kind", "service"))),
            })

        names = {norm_key(c["name"]) for c in comps} | {norm_key(e["name"]) for e in self.s.get("entities", [])}
        for ch in changes:
            if ch["kind"] == "component" and norm_key(ch["target"]) not in names:
                self.check("warn", "change_impact",
                           f'change targets "{ch["target"]}", which is not a declared component')
        noted = {norm_key(ch["target"]) for ch in changes}
        for c in touched:
            if norm_key(c["name"]) not in noted:
                self.check("info", "change_impact",
                           f'"{c["name"]}" is marked {c["change"]} but has no entry in `changes` — '
                           f"say what changes about it and why")
        return out

    def story_flow(self) -> List[Dict[str, Any]]:
        """Each user story as a walk through the system: lanes × steps."""
        stories = self.s.get("user_stories") or []
        if not stories:
            return []
        meta: Dict[str, Dict[str, str]] = {}
        for c in self.s.get("components", []):
            meta[norm_key(c["name"])] = {"kind": c.get("kind", "service"),
                                         "role": c.get("responsibility", ""),
                                         "change": c.get("change", "existing")}
        for p in self.s.get("personas", []):
            meta.setdefault(norm_key(p["name"]), {"kind": "actor", "role": p.get("role", "")})
        flows = {norm_key(f["name"]): f for f in self.s.get("runtime_flows", [])}

        out, missing = [], []
        for i, story in enumerate(stories):
            steps = list(story.get("flow") or [])
            if not steps and story.get("flow_ref"):
                ref = flows.get(norm_key(story["flow_ref"]))
                if ref:
                    steps = [{"component": st["to"] or st["from"], "action": st["action"],
                              "outcome": st.get("note", ""), "kind": "step"} for st in ref["steps"]]
                else:
                    self.check("warn", "story_flow",
                               f'story "{story["i_want"][:40]}" references flow '
                               f'"{story["flow_ref"]}", which does not exist')
            if not steps:
                missing.append(story)
                continue
            for st in steps:
                st.setdefault("change", meta.get(norm_key(st.get("component", "")), {}).get("change", ""))
                if st.get("component") and norm_key(st["component"]) not in meta:
                    self.check("warn", "story_flow",
                               f'story step runs through "{st["component"]}", which is not a '
                               f"declared component or persona")
            title = story.get("i_want") or f"Story {i + 1}"
            if story.get("as_a"):
                title = f'{story["as_a"]} · {title}'
            out.append({
                "id": f'story-{slug(story.get("id") or str(i), "s")}',
                "title": title,
                "caption": story.get("so_that") or self.t(
                    "story.caption",
                    "How this story moves through the system: one lane per participant, one column "
                    "per step."),
                "svg": swimlane(steps, uid=slug(story.get("id") or str(i), "s"), lanes_meta=meta,
                                col_label=("步骤" if self.lang == "zh" else "Step")),
                "story_mode": "swim",
                "steps": [{"n": n + 1, "from": st.get("component", ""), "to": "",
                           "action": st.get("action", ""), "note": st.get("outcome", "")}
                          for n, st in enumerate(steps)],
            })
        if missing and out:
            self.check("info", "story_flow",
                       f"{len(missing)} user story/stories have no `flow` — add one so the reader "
                       f"can see where they run")
        return out

    def architecture(self) -> List[Dict[str, str]]:
        comps = self.s.get("components") or []
        if not comps:
            return []
        ids = IdFactory("a")
        conns = list(self.s.get("connections") or [])
        if not conns:
            seen = set()
            for f in self.s.get("runtime_flows", []):
                for step in f["steps"]:
                    if step["from"] and step["to"]:
                        key = (norm_key(step["from"]), norm_key(step["to"]))
                        if key not in seen:
                            seen.add(key)
                            conns.append({"from": step["from"], "to": step["to"],
                                          "label": "", "kind": "sync"})
            if conns:
                self.check("info", "architecture",
                           "no explicit `connections` — edges were inferred from the runtime flow")
        for c in conns:
            if not any(norm_key(x["name"]) == norm_key(c["from"]) for x in comps) or \
               not any(norm_key(x["name"]) == norm_key(c["to"]) for x in comps):
                self.check("warn", "architecture",
                           f'connection {c["from"]} → {c["to"]} references a component that is not '
                           f"declared in `components`")
        lines = self._graph(comps, conns, ids, lambda c: c.get("kind", "service"))
        self.budget("architecture", len(comps))

        referenced = {norm_key(c["from"]) for c in conns} | {norm_key(c["to"]) for c in conns}
        for c in comps:
            if conns and norm_key(c["name"]) not in referenced:
                self.check("warn", "architecture",
                           f'component "{c["name"]}" is never connected to anything — either wire it '
                           f"up or drop it from the design")
        return [{
            "id": "architecture-main",
            "title": self.t("arch.title", "Components and responsibilities"),
            "caption": self.t(
                "arch.caption",
                "Every box is something that can fail independently. Grouping shows the "
                "deployment or ownership boundary."),
            "mermaid": "\n".join(lines),
        }]

    def sequence(self) -> List[Dict[str, str]]:
        out = []
        for i, flow in enumerate(self.s.get("runtime_flows") or []):
            ids = IdFactory("p")
            lines = ["sequenceDiagram", "    autonumber"]
            for actor in flow["actors"][:NODE_BUDGET]:
                keyword = "actor" if self.kind_of(actor) == "actor" else "participant"
                lines.append(f'    {keyword} {ids.get(actor)} as {esc(self.display(actor), 26)}')
            for step in flow["steps"]:
                src = step["from"] or (flow["actors"][0] if flow["actors"] else "System")
                dst = step["to"] or src
                if not ids.known(src) or not ids.known(dst):
                    for missing in (src, dst):
                        if not ids.known(missing):
                            lines.insert(2, f'    participant {ids.get(missing)} as '
                                            f'{esc(self.display(missing), 26)}')
                arrow = {"return": "-->>", "async": "->>+", "call": "->>"}.get(step["kind"], "->>")
                if step["kind"] == "return":
                    arrow = "-->>"
                lines.append(f'    {ids.get(src)}{arrow}{ids.get(dst)}: {esc(step["action"], 60)}')
                if step.get("note"):
                    lines.append(f'    Note over {ids.get(dst)}: {esc(step["note"], 50)}')
                if step["to"] and not self.names.get(norm_key(step["to"])):
                    self.check("warn", "sequence",
                               f'flow "{flow["name"]}" talks to "{step["to"]}", which is not a '
                               f"declared component")
            self.budget("sequence", len(flow["actors"]))
            if len(flow["steps"]) > 16:
                self.check("warn", "sequence",
                           f'flow "{flow["name"]}" has {len(flow["steps"])} steps — split the tail '
                           f"into its own flow")
            out.append({
                "id": f"sequence-{slug(flow['name'], 'f')}",
                "title": flow["name"],
                "caption": flow.get("description") or self.t(
                    "seq.caption",
                    "Ordered messages for one run of this flow. Numbers are the step index used "
                    "by the walkthrough."),
                "mermaid": "\n".join(lines),
                "story_mode": "message",
                "steps": [
                    {"n": n + 1, "from": self.display(s["from"]), "to": self.display(s["to"]),
                     "action": s["action"], "note": s.get("note", "")}
                    for n, s in enumerate(flow["steps"])
                ],
            })
        return out

    def state_machine(self) -> List[Dict[str, str]]:
        out = []
        for m in self.s.get("states") or []:
            ids = IdFactory("s")
            lines = ["stateDiagram-v2", "    direction LR"]
            for v in m["values"]:
                if v == "[*]":
                    continue
                sid = ids.get(v)
                if sid != v:
                    lines.append(f'    state "{state_text(v, 30)}" as {sid}')
            initial = m.get("initial") or (m["values"][0] if m["values"] else "")
            if initial:
                lines.append(f"    [*] --> {ids.get(initial)}")
            for t in m["transitions"]:
                label = t["event"]
                if t.get("guard"):
                    label = f'{label} [{t["guard"]}]'.strip()
                src = "[*]" if t["from"] == "[*]" else ids.get(t["from"])
                dst = "[*]" if t["to"] == "[*]" else ids.get(t["to"])
                lines.append(f'    {src} --> {dst}{": " + state_text(label) if label else ""}')
            for t in m.get("terminal", []):
                lines.append(f"    {ids.get(t)} --> [*]")
            if m.get("notes"):
                # the block form is the one that tolerates punctuation in the text
                lines.append(f"    note right of {ids.get(initial)}")
                lines.append(f'        {esc(m["notes"], 90)}')
                lines.append("    end note")
            reachable = {norm_key(t["to"]) for t in m["transitions"]}
            for v in m["values"]:
                if v != initial and norm_key(v) not in reachable:
                    self.check("warn", "state_machine",
                               f'{m["entity"]}: state "{v}" has no incoming transition')
            self.budget("state_machine", len(m["values"]))
            out.append({
                "id": f"state-{slug(m['entity'], 'sm')}",
                "title": self.t("state.title", "{entity} lifecycle", entity=m["entity"]),
                "caption": m.get("notes") or self.t(
                    "state.caption",
                    "Every state a reviewer can find the system in, and the event that moves it "
                    "on. Dead ends are bugs waiting to happen."),
                "mermaid": "\n".join(lines),
            })
        return out

    def data_model(self) -> List[Dict[str, str]]:
        entities = self.s.get("entities") or []
        if not entities:
            return []
        ids = IdFactory("e")
        lines = ["erDiagram"]
        for e in entities:
            eid = ids.get(e["name"]).upper()
            fields = e["fields"][:10]
            if fields:
                lines.append(f"    {eid} {{")
                for f in fields:
                    ftype = slug(f.get("type") or "string", "t")
                    fname = slug(f["name"], "f")
                    note = f' "{esc(f["note"], 30)}"' if f.get("note") else ""
                    lines.append(f"        {ftype} {fname}{note}")
                lines.append("    }")
            else:
                lines.append(f"    {eid} {{")
                lines.append("        string id")
                lines.append("    }")
                self.check("info", "data_model",
                           f'entity "{e["name"]}" has no fields — add the ones a reviewer must see')
            if len(e["fields"]) > 10:
                self.check("info", "data_model",
                           f'entity "{e["name"]}" shows the first 10 of {len(e["fields"])} fields')
        known = {norm_key(e["name"]) for e in entities}
        for e in entities:
            for r in e.get("relations", []):
                if norm_key(r["to"]) not in known:
                    self.check("warn", "data_model",
                               f'{e["name"]} relates to "{r["to"]}", which is not a declared entity')
                    continue
                lines.append(f'    {ids.get(e["name"]).upper()} {cardinality(r["cardinality"])} '
                             f'{ids.get(r["to"]).upper()} : "{esc(r["label"], 24)}"')
        self.budget("data_model", len(entities))
        return [{
            "id": "data-model",
            "title": self.t("data.title", "Entities and ownership"),
            "caption": self.t(
                "data.caption",
                "What is stored, where it lives, and which relationships the code has to keep "
                "true."),
            "mermaid": "\n".join(lines),
        }]

    def failure_paths(self) -> List[Dict[str, str]]:
        out = []
        for fp in self.s.get("failure_paths") or []:
            ids = IdFactory("f")
            lines = ["flowchart TD"]
            classes = []
            steps = fp["steps"]
            trigger_id = None
            if fp.get("trigger"):
                trigger_id = ids.get(f'trigger::{fp["name"]}')
                lines.append(f'    {trigger_id}(["{wrap_label(fp["trigger"])}"])')
                classes.append(f"    class {trigger_id} failure;")
            for st in steps:
                nid = ids.get(st["id"])
                if st["type"] == "decision":
                    lines.append(f'    {nid}{{"{wrap_label(st["text"], 26)}"}}')
                    classes.append(f"    class {nid} decision;")
                elif st["type"] in ("terminal", "end"):
                    lines.append(f'    {nid}(["{wrap_label(st["text"])}"])')
                    classes.append(f"    class {nid} success;")
                else:
                    lines.append(f'    {nid}["{wrap_label(st["text"])}"]')
            by_ref = {norm_key(st["id"]): st["id"] for st in steps}
            by_ref.update({norm_key(st["text"]): st["id"] for st in steps})
            if trigger_id and steps:
                lines.append(f'    {trigger_id} --> {ids.get(steps[0]["id"])}')
            for i, st in enumerate(steps):
                if st["next"]:
                    for nxt in st["next"]:
                        target = by_ref.get(norm_key(nxt["to"]))
                        if not target:
                            target = f'{st["id"]}::{nxt["to"]}'
                            lines.append(f'    {ids.get(target)}["{wrap_label(nxt["to"])}"]')
                        label = f'|"{esc(nxt["label"], 18)}"|' if nxt.get("label") else ""
                        lines.append(f'    {ids.get(st["id"])} -->{label} {ids.get(target)}')
                elif i + 1 < len(steps):
                    lines.append(f'    {ids.get(st["id"])} --> {ids.get(steps[i + 1]["id"])}')
            if fp.get("mitigation"):
                mid = ids.get(f'mitigation::{fp["name"]}')
                lines.append(f'    {mid}["{wrap_label("Recovery: " + fp["mitigation"])}"]')
                classes.append(f"    class {mid} success;")
                if steps:
                    lines.append(f'    {ids.get(steps[-1]["id"])} --> {mid}')
            lines.append(CLASSDEFS)
            lines.extend(classes)
            if fp.get("component") and not self.names.get(norm_key(fp["component"])):
                self.check("warn", "failure_paths",
                           f'failure "{fp["name"]}" blames "{fp["component"]}", which is not a '
                           f"declared component")
            if not fp.get("detection"):
                self.check("info", "failure_paths",
                           f'failure "{fp["name"]}" has no `detection` — how does anyone find out?')
            out.append({
                "id": f"failure-{slug(fp['name'], 'fp')}",
                "title": fp["name"],
                "caption": fp.get("impact") or self.t(
                    "fail.caption",
                    "What the system does when this goes wrong, and where it comes to rest."),
                "mermaid": "\n".join(lines),
            })
        return out

    def rollout_plan(self) -> List[Dict[str, str]]:
        phases = self.s.get("rollout_phases") or []
        if not phases:
            return []
        ids = IdFactory("r")
        lines = ["flowchart LR"]
        classes = []
        for p in phases:
            sub = []
            if p.get("duration"):
                sub.append(p["duration"])
            if p.get("deliverables"):
                sub.append(f'{len(p["deliverables"])} deliverables')
            label = wrap_label(p["name"], 24)
            if sub:
                label += f'<br/><small>{esc(" · ".join(sub), 34)}</small>'
            nid = ids.get(p["name"])
            lines.append(f'    {nid}["{label}"]')
            classes.append(f"    class {nid} phase;")
        names = {norm_key(p["name"]) for p in phases}
        for i, p in enumerate(phases):
            if p.get("depends_on"):
                for dep in p["depends_on"]:
                    if norm_key(dep) not in names:
                        self.check("warn", "rollout_plan",
                                   f'phase "{p["name"]}" depends on "{dep}", which is not a phase')
                        continue
                    lines.append(f'    {ids.get(dep)} --> {ids.get(p["name"])}')
            elif i:
                lines.append(f'    {ids.get(phases[i - 1]["name"])} --> {ids.get(p["name"])}')
            if not p.get("exit_criteria"):
                self.check("info", "rollout_plan",
                           f'phase "{p["name"]}" has no exit criteria — how do you know it is done?')
        lines.append(CLASSDEFS)
        lines.extend(classes)
        return [{
            "id": "rollout-plan",
            "title": self.t("rollout.title", "Phases and dependencies"),
            "caption": self.t(
                "rollout.caption",
                "The order the change lands in, and what has to be true before the next phase "
                "starts."),
            "mermaid": "\n".join(lines),
        }]

    # -- driver ----------------------------------------------------------
    def build(self) -> List[Dict[str, Any]]:
        views = []
        for key in VIEW_ORDER:
            diagrams = getattr(self, key)()
            override = self.s.get("views", {}).get(key)
            if override:
                if diagrams:
                    diagrams[0] = dict(diagrams[0], mermaid=override, source="authored")
                else:
                    diagrams = [{"id": key, "title": self.view_title(key), "caption": "",
                                 "mermaid": override, "source": "authored"}]
            if diagrams:
                views.append({"key": key, "title": self.view_title(key), "diagrams": diagrams})
            else:
                self.check("info", key, "no data for this view — it is omitted from the explorer")
        self.cross_checks()
        return views

    def cross_checks(self) -> None:
        comps = {norm_key(c["name"]) for c in self.s.get("components", [])}
        used = set()
        for f in self.s.get("runtime_flows", []):
            for st in f["steps"]:
                used.add(norm_key(st["from"]))
                used.add(norm_key(st["to"]))
        for c in self.s.get("components", []):
            if comps and used and norm_key(c["name"]) not in used:
                self.check("info", "sequence",
                           f'component "{c["name"]}" never appears in a runtime flow')
        for m in self.s.get("states", []):
            if comps and norm_key(m["entity"]) not in comps and not self.s.get("entities"):
                self.check("info", "state_machine",
                           f'state machine "{m["entity"]}" does not map to a declared component')
        phases = self.s.get("rollout_phases", [])
        if self.s.get("components") and not phases:
            self.check("warn", "rollout_plan",
                       "the design changes components but has no rollout plan")


def cardinality(spec: str) -> str:
    spec = (spec or "").strip().replace(" ", "")
    table = {
        "1..1": "||--||", "1-1": "||--||", "one-to-one": "||--||",
        "1..*": "||--o{", "1-*": "||--o{", "one-to-many": "||--o{", "1..n": "||--o{",
        "0..1": "|o--o|", "0..*": "||--o{", "*..*": "}o--o{", "many-to-many": "}o--o{",
        "n..n": "}o--o{",
    }
    return table.get(spec.lower(), "||--o{")


def build(summary: Dict[str, Any], lang: str = "auto") -> Dict[str, Any]:
    s = normalize(summary)
    if lang == "auto":
        lang = detect_lang(s)
    b = ViewBuilder(s, lang)
    views = b.build()
    return {"summary": s, "views": views, "checks": b.checks, "lang": lang}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("summary", help="design-summary.json")
    ap.add_argument("-o", "--out-dir", default="assets", help="where .mmd files are written")
    ap.add_argument("--views-json", default="", help="also dump the view bundle as JSON")
    ap.add_argument("--lang", choices=["auto", "en", "zh"], default="auto",
                    help="UI language for titles and captions (auto: detect from the design)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    bundle = build(read_json(args.summary), lang=args.lang)
    out = Path(args.out_dir)
    for view in bundle["views"]:
        for d in view["diagrams"]:
            if d.get("mermaid"):
                write_text(out / f'{d["id"]}.mmd', d["mermaid"] + "\n")
            elif d.get("svg"):
                write_text(out / f'{d["id"]}.svg', d["svg"] + "\n")
    if args.views_json:
        write_json(args.views_json, bundle)
    if not args.quiet:
        print(f"wrote {sum(len(v['diagrams']) for v in bundle['views'])} diagrams to {out}/")
        for v in bundle["views"]:
            print(f"  {v['key']:<15} {len(v['diagrams'])} diagram(s)")
        if bundle["checks"]:
            print("\nconsistency checks:")
            for c in bundle["checks"]:
                print(f"  [{c['level']}] {c['view']}: {c['message']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
