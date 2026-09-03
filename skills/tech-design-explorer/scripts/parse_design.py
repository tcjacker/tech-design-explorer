#!/usr/bin/env python3
"""Stage 1 — read a design document, emit a *draft* design-summary.json.

This is deliberately a scaffold, not an oracle. It splits the document into
labelled sections, pulls out the obvious structure (bullets, tables, numbered
flows, existing mermaid blocks) and reports what it could not find, so the
agent knows exactly which fields still need real reading.

    python3 parse_design.py design.md -o design-summary.draft.json

The `_source_sections` block is kept in the draft on purpose: the agent reads
it, rewrites the weak fields, then deletes `_source_sections` and `_gaps`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import as_text, norm_key, write_json  # noqa: E402

SECTION_PATTERNS: List[Tuple[str, List[str]]] = [
    ("current_state", ["current state", "as-is", "as is", "today", "status quo",
                       "existing system", "existing implementation",
                       "现状", "现有", "当前实现", "当前架构", "今天"]),
    ("changes", ["what changes", "this change", "increment", "delta", "modifications",
                 "changes in this", "proposed change", "改动", "变更", "增量",
                 "本次修改", "本次改动", "改造", "要做什么"]),
    ("non_goals", ["non-goal", "non goal", "nongoal", "out of scope", "not in scope",
                   "非目标", "不做", "范围外"]),
    ("goals", ["goal", "objective", "requirement", "目标", "需求"]),
    ("background", ["background", "context", "motivation", "problem", "why",
                    "背景", "动机", "问题"]),
    ("summary", ["summary", "tl;dr", "tldr", "abstract", "概述", "摘要", "总览"]),
    ("failure_paths", ["failure", "error handling", "edge case", "exception", "retry",
                       "fallback", "degradation", "异常", "失败", "容错", "降级", "重试"]),
    ("states", ["state machine", "state model", "fsm", "lifecycle", "states",
                "状态机", "状态", "生命周期"]),
    ("entities", ["data model", "schema", "entity", "entities", "storage", "table",
                  "persistence", "数据模型", "数据结构", "表结构", "存储"]),
    ("runtime_flows", ["flow", "sequence", "request path", "workflow", "runtime",
                       "happy path", "interaction", "流程", "时序", "调用"]),
    ("rollout_phases", ["rollout", "migration", "implementation plan", "phase",
                        "milestone", "delivery", "plan", "实施", "计划", "阶段",
                        "迁移", "上线", "里程碑"]),
    ("decisions", ["decision", "adr", "alternative", "trade-off", "tradeoff",
                   "options considered", "决策", "方案对比", "取舍", "备选"]),
    ("risks", ["risk", "风险"]),
    ("open_questions", ["open question", "unresolved", "todo", "tbd",
                        "开放问题", "待定", "未决"]),
    ("metrics", ["metric", "success criteria", "kpi", "measurement", "指标", "度量"]),
    ("constraints", ["constraint", "assumption", "约束", "假设", "前提"]),
    ("user_stories", ["user story", "user stories", "persona", "use case",
                      "用户故事", "用户场景", "角色"]),
    ("components", ["component", "architecture", "module", "design overview",
                    "system design", "high level", "架构", "组件", "模块", "设计"]),
]

MERMAID_KIND = [
    ("sequenceDiagram", "sequence"),
    ("stateDiagram", "state_machine"),
    ("erDiagram", "data_model"),
    ("gantt", "rollout_plan"),
    ("timeline", "rollout_plan"),
    ("classDiagram", "data_model"),
    ("flowchart", "architecture"),
    ("graph", "architecture"),
]


def classify(heading: str) -> str:
    h = heading.lower()
    for label, needles in SECTION_PATTERNS:
        for n in needles:
            if n in h:
                return label
    return ""


def split_sections(md: str) -> List[Dict[str, Any]]:
    lines = md.splitlines()
    sections: List[Dict[str, Any]] = []
    current = {"heading": "", "level": 0, "lines": []}
    in_fence = False
    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        m = re.match(r"^(#{1,6})\s+(.*)$", line) if not in_fence else None
        if m:
            sections.append(current)
            current = {"heading": m.group(2).strip(), "level": len(m.group(1)), "lines": []}
        else:
            current["lines"].append(line)
    sections.append(current)
    for s in sections:
        s["text"] = "\n".join(s["lines"]).strip()
        s["label"] = classify(s["heading"])
    return [s for s in sections if s["heading"] or s["text"]]


def bullets(text: str) -> List[str]:
    out = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$", line)
        if m:
            item = m.group(1).strip()
            item = re.sub(r"^\[[ xX]\]\s*", "", item)
            if item:
                out.append(item)
    return out


def tables(text: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    header: List[str] = []
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            header = []
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if re.match(r"^[\s:|-]+$", line.strip()):
            continue
        if not header:
            header = [norm_key(c) for c in cells]
            continue
        if len(cells) == len(header):
            rows.append(dict(zip(header, cells)))
    return rows


CHANGE_VERBS = [
    (["新增", "增加", "引入", "add", "introduce", "new "], "added"),
    (["移除", "删除", "下线", "remove", "delete", "drop "], "removed"),
    (["改", "调整", "迁移", "modify", "change", "update", "migrate", "refactor"], "modified"),
]


def change_type(text: str) -> str:
    low = text.lower()
    for needles, kind in CHANGE_VERBS:
        if any(n in low for n in needles):
            return kind
    return "modified"


def strip_md(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
    return text.strip()


def split_named(item: str) -> Tuple[str, str]:
    """`**Name** — does X` / `Name: does X` -> (name, rest)."""
    m = re.match(r"^\s*\*\*(.+?)\*\*\s*[:：\-—–]?\s*(.*)$", item)
    if not m:
        m = re.match(r"^\s*`(.+?)`\s*[:：\-—–]?\s*(.*)$", item)
    if not m:
        m = re.match(r"^\s*([^:：\-—–]{2,48}?)\s*[:：]\s*(.+)$", item)
    if not m:
        m = re.match(r"^\s*([^\-—–]{2,48}?)\s+[—–\-]\s+(.+)$", item)
    if m:
        return strip_md(m.group(1)), strip_md(m.group(2))
    return "", strip_md(item)


def collect_mermaid(md: str) -> Dict[str, str]:
    views: Dict[str, str] = {}
    for block in re.findall(r"```mermaid\s*\n(.*?)```", md, re.S):
        body = block.strip()
        head = body.splitlines()[0] if body else ""
        for needle, kind in MERMAID_KIND:
            if head.startswith(needle):
                views.setdefault(kind, body)
                break
    return views


def parse(md: str, source: str = "") -> Dict[str, Any]:
    sections = split_sections(md)
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for s in sections:
        if s["label"]:
            grouped.setdefault(s["label"], []).append(s)

    def text_of(label: str) -> str:
        return "\n\n".join(s["text"] for s in grouped.get(label, []))

    def bullets_of(label: str) -> List[str]:
        return [strip_md(b) for b in bullets(text_of(label))]

    title = ""
    for s in sections:
        if s["level"] == 1 and s["heading"]:
            title = s["heading"]
            break
    if not title:
        title = Path(source).stem.replace("-", " ").replace("_", " ").title() or "Technical Design"

    intro = sections[0]["text"] if sections and not sections[0]["heading"] else ""
    background = text_of("background") or intro
    background = strip_md(re.sub(r"```.*?```", "", background, flags=re.S)).strip()

    # components ---------------------------------------------------------
    components: List[Dict[str, Any]] = []
    for s in grouped.get("components", []):
        for row in tables(s["text"]):
            name = row.get("component") or row.get("module") or row.get("name") or row.get("组件")
            if name:
                components.append({
                    "name": strip_md(name),
                    "responsibility": strip_md(row.get("responsibility")
                                               or row.get("description")
                                               or row.get("职责") or ""),
                })
        for b in bullets(s["text"]):
            name, rest = split_named(b)
            if name and len(name) < 48:
                components.append({"name": name, "responsibility": rest})

    # runtime flows ------------------------------------------------------
    flows: List[Dict[str, Any]] = []
    for s in grouped.get("runtime_flows", []):
        steps = [strip_md(b) for b in bullets(s["text"])]
        if steps:
            flows.append({"name": s["heading"] or "Runtime Flow", "kind": "happy", "steps": steps})

    # states -------------------------------------------------------------
    states: List[Dict[str, Any]] = []
    for s in grouped.get("states", []):
        transitions = [strip_md(b) for b in bullets(s["text"]) if re.search(r"(-->|->|→)", b)]
        seen: List[str] = []
        if transitions:
            # trust the transitions: they name the real states, in order
            for t in transitions:
                for side in re.split(r"\s*(?:-->|->|→)\s*", t.split(":")[0].split("：")[0]):
                    side = side.strip()
                    if side and side not in seen:
                        seen.append(side)
        else:
            for v in re.findall(r"\b([A-Z][A-Z0-9_]{2,})\b", s["text"]):
                if v not in seen:
                    seen.append(v)
            if len(seen) < 3:
                seen = []
        if seen:
            states.append({
                "entity": strip_md(s["heading"]) or "Lifecycle",
                "values": seen,
                "transitions": transitions,
            })

    # entities -----------------------------------------------------------
    entities: List[Dict[str, Any]] = []
    for s in grouped.get("entities", []):
        for row in tables(s["text"]):
            name = row.get("table") or row.get("entity") or row.get("name") or row.get("表")
            if name:
                entities.append({"name": strip_md(name),
                                 "description": strip_md(row.get("description") or row.get("说明") or ""),
                                 "fields": []})
        for b in bullets(s["text"]):
            name, rest = split_named(b)
            if name and len(name) < 48:
                entities.append({"name": name, "description": rest, "fields": []})

    # failure paths ------------------------------------------------------
    failures = []
    for s in grouped.get("failure_paths", []):
        items = bullets(s["text"])
        if items:
            failures.append({"name": strip_md(s["heading"]) or "Failure Path",
                             "steps": [strip_md(i) for i in items]})

    # rollout ------------------------------------------------------------
    phases = []
    for s in grouped.get("rollout_phases", []):
        items = bullets(s["text"])
        if re.search(r"(phase|stage|阶段|step)\s*\d", s["heading"], re.I):
            phases.append({"name": strip_md(s["heading"]),
                           "description": strip_md(" ".join(items)) or strip_md(s["text"])[:200],
                           "deliverables": [strip_md(i) for i in items]})
        else:
            for b in items:
                name, rest = split_named(b)
                phases.append({"name": name or strip_md(b)[:48], "description": rest})

    # decisions ----------------------------------------------------------
    decisions = []
    for s in grouped.get("decisions", []):
        items = [strip_md(b) for b in bullets(s["text"])]
        decisions.append({
            "title": strip_md(s["heading"]) or "Design Decision",
            "context": strip_md(re.sub(r"```.*?```", "", s["text"], flags=re.S))[:400],
            "alternatives": [{"name": i} for i in items[:4]],
            "chosen": "",
            "reason": "",
        })

    # current state and this increment ------------------------------------
    current_state: Dict[str, Any] = {}
    for s in grouped.get("current_state", []):
        items = [strip_md(b) for b in bullets(s["text"])]
        prose = "\n".join(line for line in s["text"].splitlines()
                          if not re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", line))
        body = strip_md(re.sub(r"```.*?```", "", prose, flags=re.S))
        current_state = {
            "summary": current_state.get("summary") or body[:600],
            "pain_points": current_state.get("pain_points", []) + items,
        }
    changes = []
    for s in grouped.get("changes", []):
        for row in tables(s["text"]):
            target = (row.get("component") or row.get("target") or row.get("组件")
                      or row.get("对象") or row.get("模块") or row.get("名称"))
            if target:
                what = strip_md(row.get("change") or row.get("what") or row.get("改动")
                                or row.get("变更") or "")
                changes.append({"target": strip_md(target), "type": change_type(what),
                                "what": what, "why": strip_md(row.get("why") or row.get("原因") or "")})
        for b in bullets(s["text"]):
            name, rest = split_named(b)
            text = strip_md(b)
            changes.append({"target": name or text[:48], "type": change_type(text),
                            "what": rest or text, "why": ""})

    risks = []
    for s in grouped.get("risks", []):
        for row in tables(s["text"]):
            risk_title = row.get("risk") or row.get("title") or row.get("风险")
            if risk_title:
                risks.append({"title": strip_md(risk_title),
                              "mitigation": strip_md(row.get("mitigation") or row.get("缓解") or "")})
        for b in bullets(s["text"]):
            name, rest = split_named(b)
            risks.append({"title": name or strip_md(b), "mitigation": rest if name else ""})

    draft: Dict[str, Any] = {
        "schema_version": "1.0",
        "title": strip_md(title),
        "source_document": source,
        "background": background[:1200],
        "summary": strip_md(text_of("summary"))[:600],
        "goals": bullets_of("goals"),
        "non_goals": bullets_of("non_goals"),
        "user_stories": [parse_story(b) for b in bullets_of("user_stories")],
        "components": dedupe(components, "name"),
        "connections": [],
        "runtime_flows": flows,
        "states": states,
        "entities": dedupe(entities, "name"),
        "failure_paths": failures,
        "rollout_phases": phases,
        "decisions": decisions,
        "risks": dedupe(risks, "title"),
        "constraints": bullets_of("constraints"),
        "open_questions": [{"question": b} for b in bullets_of("open_questions")],
        "metrics": [{"name": split_named(b)[0] or b, "target": split_named(b)[1]}
                    for b in bullets_of("metrics")],
        "current_state": current_state,
        "changes": dedupe(changes, "target"),
        "views": collect_mermaid(md),
        "document_sections": [
            {"id": f"doc-{i}", "heading": sec["heading"], "level": sec["level"] or 1,
             "text": sec["text"]}
            for i, sec in enumerate(sections) if sec["text"].strip() or sec["heading"]
        ],
        "source_map": source_map(sections),
    }

    # a change table names components; carry that onto the components themselves so
    # the before/after views work straight from the document
    by_change = {norm_key(c["target"]): c["type"] for c in draft["changes"]}
    for comp in draft["components"]:
        state = by_change.get(norm_key(comp["name"]))
        if state:
            comp["change"] = state

    draft["_gaps"] = gaps(draft)
    draft["_source_sections"] = {
        label: [{"heading": s["heading"], "text": s["text"][:4000]} for s in secs]
        for label, secs in grouped.items()
    }
    draft["_unclassified_sections"] = [
        {"heading": s["heading"], "text": s["text"][:2000]}
        for s in sections if not s["label"] and s["heading"]
    ]
    return draft


def parse_story(text: str) -> Dict[str, Any]:
    """`As a player, I want X, so that Y` (or the Chinese equivalent)."""
    pat = (r"^\s*(?:as an?|作为)\s*(.+?)\s*[,，]\s*(?:i want|我希望|我想要?)\s*(.+?)"
           r"(?:\s*[,，]\s*(?:so that|以便|这样)\s*(.+?))?\s*[.。]?\s*$")
    m = re.match(pat, text, re.I)
    if m:
        return {"as_a": m.group(1), "i_want": m.group(2), "so_that": m.group(3) or "", "acceptance": []}
    return {"as_a": "", "i_want": text, "so_that": "", "acceptance": []}


SOURCE_VIEWS = {
    "background": "summary", "summary": "summary", "goals": "summary",
    "non_goals": "summary", "constraints": "summary", "metrics": "summary",
    "user_stories": "story_flow", "current_state": "change_impact", "changes": "change_impact",
    "components": "architecture", "runtime_flows": "sequence", "states": "state_machine",
    "entities": "data_model", "failure_paths": "failure_paths",
    "rollout_phases": "rollout_plan", "decisions": "decisions", "risks": "risks",
    "open_questions": "questions",
}


def source_map(sections: List[Dict[str, Any]]) -> Dict[str, str]:
    """Which document section a reader should open behind each view."""
    out: Dict[str, str] = {}
    for i, sec in enumerate(sections):
        view = SOURCE_VIEWS.get(sec["label"])
        if view and view not in out and sec["text"].strip():
            out[view] = f"doc-{i}"
    return out


def dedupe(items: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for it in items:
        k = norm_key(it.get(key, ""))
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


REQUIRED = ["background", "goals", "components", "runtime_flows", "states",
            "entities", "failure_paths", "rollout_phases", "decisions", "risks"]


def gaps(draft: Dict[str, Any]) -> List[str]:
    out = []
    for field in REQUIRED:
        if not draft.get(field):
            out.append(f"{field}: nothing extracted — read the document and fill this in, "
                       f"or delete the key if the design genuinely has none")
    if draft.get("components") and not draft.get("connections"):
        out.append("connections: no component-to-component edges found — infer them from the prose")
    for c in draft.get("components", []):
        if not c.get("responsibility"):
            out.append(f"components[{c['name']}].responsibility is empty")
    for f in draft.get("runtime_flows", []):
        if not any(re.search(r"(->|-->|→)", as_text(s)) for s in f.get("steps", [])):
            out.append(f"runtime_flows[{f['name']}]: steps have no actor -> actor form; "
                       f"rewrite as 'Caller -> Callee: message'")
    for d in draft.get("decisions", []):
        if not d.get("chosen"):
            out.append(f"decisions[{d['title']}]: chosen/reason not extracted")
    if not draft.get("changes") and not draft.get("current_state"):
        out.append("current_state/changes: none found — if this design modifies an existing "
                   "system, describe what it looks like today and mark what this change touches")
    for story in draft.get("user_stories", []):
        if not story.get("flow"):
            out.append(f"user_stories[{story.get('i_want', '')[:40]}]: no `flow` — trace the story "
                       f"through the components so it can be drawn")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("document", help="path to design.md / tech-spec.md / rfc.md")
    ap.add_argument("-o", "--out", default="design-summary.draft.json")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    md = Path(args.document).read_text(encoding="utf-8")
    draft = parse(md, source=args.document)
    write_json(args.out, draft)
    if not args.quiet:
        print(f"wrote {args.out}")
        print(f"  sections classified: {len(draft['_source_sections'])}")
        for field in REQUIRED:
            n = len(draft.get(field) or []) if isinstance(draft.get(field), list) else bool(draft.get(field))
            print(f"  {field:<16} {n}")
        if draft["_gaps"]:
            print("\ngaps to close before rendering:")
            for g in draft["_gaps"][:20]:
                print(f"  - {g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
