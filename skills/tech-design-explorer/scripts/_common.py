"""Shared helpers for the tech-design-explorer pipeline.

Only the Python standard library is used so the skill runs anywhere.
The normalisation layer is deliberately forgiving: an agent writing
design-summary.json by hand may use short forms (plain strings instead of
objects) and every consumer still sees one canonical shape.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SCHEMA_VERSION = "1.0"

# Sections rendered by the explorer, in review order.
VIEW_ORDER = [
    "overview",
    "change_impact",
    "architecture",
    "story_flow",
    "sequence",
    "state_machine",
    "data_model",
    "failure_paths",
    "rollout_plan",
]

VIEW_TITLES = {
    "overview": "Overview",
    "change_impact": "Current State and Change",
    "architecture": "Architecture",
    "story_flow": "Story Flow",
    "sequence": "Runtime Flow",
    "state_machine": "State Model",
    "data_model": "Data Model",
    "failure_paths": "Failure Paths",
    "rollout_plan": "Rollout Plan",
}

# Localisation. English is the default and lives inline at every call site as the
# fallback, so a missing key degrades to English instead of an empty label.
UI_ZH = {
    "view.overview": "总览", "view.change_impact": "现状与本次改动",
    "view.architecture": "架构", "view.story_flow": "用户故事流转",
    "view.sequence": "运行时流程",
    "view.state_machine": "状态机", "view.data_model": "数据模型",
    "view.failure_paths": "失败路径", "view.rollout_plan": "实施计划",
    "sec.summary": "概要", "sec.stories": "用户与故事", "sec.decisions": "设计决策",
    "sec.risks": "风险", "sec.questions": "开放问题", "sec.checks": "一致性检查",
    "ui.filter": "筛选章节…  /", "ui.collapseAll": "全部折叠", "ui.expandAll": "全部展开",
    "ui.theme": "浅色 / 深色 (t)", "ui.print": "打印 / 存为 PDF", "ui.sections": "章节",
    "ui.focus": "只看本节", "ui.walkthrough": "分步走查", "ui.play": "播放走查",
    "ui.prev": "上一步", "ui.next": "下一步", "ui.clear": "取消高亮",
    "ui.zoomIn": "放大", "ui.zoomOut": "缩小", "ui.fit": "复位（画布上双击）",
    "ui.fullscreen": "全屏", "ui.copyMmd": "复制 mermaid 源码",
    "ui.svg": "下载 SVG", "ui.png": "下载 PNG（2 倍）",
    "ui.goals": "目标", "ui.nonGoals": "非目标", "ui.constraints": "约束",
    "ui.metrics": "成功指标", "ui.persona": "角色", "ui.asA": "作为",
    "ui.iWant": "我希望", "ui.soThat": "以便", "ui.chosen": "选定",
    "ui.why": "为什么选", "ui.consequence": "代价", "ui.exit": "完成标准",
    "ui.ownedBy": "归属", "ui.critical": "关键", "ui.blocking": "阻塞", "ui.open": "待定",
    "ui.views": "个视图", "ui.checksLede": "生成视图时自动跑的一致性检查。它们是复查提示，不是报错。",
    "th.component": "组件", "th.responsibility": "职责", "th.group": "分组", "th.tech": "技术",
    "th.failure": "失败场景", "th.detected": "如何发现", "th.impact": "影响", "th.recovery": "恢复方式",
    "th.risk": "风险", "th.severity": "严重度", "th.mitigation": "缓解措施", "th.owner": "负责人",
    "th.term": "术语", "th.definition": "释义", "ui.likelihood": "发生概率",
    "ask.title": "就这份方案提问", "ask.live": "在线", "ask.offline": "离线",
    "ask.placeholder": "例如：CAS 写入连续失败两次会怎样？",
    "ask.send": "发送", "ask.close": "关闭",
    "ask.intro": "关于这份方案随便问。回答基于随页面一起打包的方案原文，以及生成这些视图的结构化摘要。",
    "ask.thinking": "思考中…",
    "ask.noModel": "本页未连接模型。把下面的提示词复制到 Claude Code（或任意助手），它会基于这份方案的摘要作答。",
    "ask.copyPrompt": "复制完整提示词", "ask.copied": "提示词已复制",
    "ask.q1": "哪里最先扛不住压力？", "ask.q2": "哪条失败路径覆盖得最薄弱？",
    "ask.q3": "实施计划和架构改动对得上吗？", "ask.failed": "无法作答",
    "toast.mmdCopied": "已复制 mermaid 源码", "toast.clipboard": "浏览器阻止了剪贴板",
    "toast.nothing": "还没有可导出的内容", "toast.pngFailed": "PNG 导出失败，请用 SVG",
    "err.render": "此处无法渲染该图", "err.source": "以下是源码，可粘贴到任意 mermaid 工具中查看。",
    "sec.document": "方案原文", "ui.source": "原文", "ui.sourceOf": "对应原文章节",
    "ui.before": "现状", "ui.delta": "改动", "ui.after": "改造后",
    "ui.added": "新增", "ui.modified": "改动", "ui.removed": "移除", "ui.existing": "沿用",
    "th.target": "对象", "th.change": "变更", "th.what": "做什么", "th.why": "为什么",
    "th.files": "涉及位置", "ui.painPoints": "现状痛点", "ui.currentState": "技术现状",
    "ui.storyLane": "参与方", "ui.storyStep": "步骤", "ui.noStoryFlow": "这个故事还没有画出流转路径",
    "ask.agent": "本地 agent", "ask.docContext": "已加载方案原文",
    "ask.answersHere": "正在本机作答",
    "stat.changes": "处改动",
    "stat.components": "组件", "stat.flows": "流程", "stat.failures": "失败路径",
    "stat.decisions": "决策", "stat.phases": "阶段", "stat.questions": "开放问题",
    "foot.by": "由 tech-design-explorer 生成", "foot.from": "来源",
    "foot.hint": "Shift/⌘ + 滚轮缩放，双击复位。",
}

CJK_RE = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]")


def detect_lang(summary: Dict[str, Any]) -> str:
    """`zh` when the design's own text is CJK, `en` otherwise.

    Only values are counted — the schema's key names are always English and would
    otherwise drown out a short Chinese design.
    """
    chunks: List[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if not str(k).startswith("_"):
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str):
            chunks.append(node)

    walk(summary)
    text = " ".join(chunks)
    cjk = len(CJK_RE.findall(text))
    latin = sum(ch.isalpha() and ord(ch) < 128 for ch in text)
    return "zh" if cjk * 3 > latin else "en"


def strings(lang: str) -> Dict[str, str]:
    return dict(UI_ZH) if lang == "zh" else {}


# --------------------------------------------------------------------------
# text helpers
# --------------------------------------------------------------------------

def slug(text: str, prefix: str = "n") -> str:
    """Stable, mermaid-safe identifier derived from free text.

    Non-ASCII text (CJK especially) keeps whatever ASCII it has and gains a short
    digest, so `会话服务` and `冷表` stay distinct without emitting raw bytes into
    a diagram id or a file name.
    """
    raw = unicodedata.normalize("NFKD", str(text or ""))
    out, non_ascii = [], False
    for ch in raw:
        if ch.isalnum() and ord(ch) < 128:
            out.append(ch)
        else:
            non_ascii = non_ascii or ch.isalnum()
            out.append("_")
    ident = re.sub(r"_+", "_", "".join(out)).strip("_")
    if non_ascii:
        digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:6]
        ident = f"{ident[:32]}_{digest}".lstrip("_") if ident else f"{prefix}_{digest}"
    if not ident:
        ident = "x"
    if not ident[0].isalpha():
        ident = f"{prefix}_{ident}"
    return ident[:48]


class IdFactory:
    """Hands out unique ids and remembers the mapping from display name."""

    def __init__(self, prefix: str = "n") -> None:
        self._prefix = prefix
        self._by_name: Dict[str, str] = {}
        self._used: set[str] = set()

    def get(self, name: str) -> str:
        key = norm_key(name)
        if key in self._by_name:
            return self._by_name[key]
        candidate = slug(name, self._prefix)
        base, i = candidate, 2
        while candidate in self._used:
            candidate = f"{base}_{i}"
            i += 1
        self._used.add(candidate)
        self._by_name[key] = candidate
        return candidate

    def known(self, name: str) -> bool:
        return norm_key(name) in self._by_name

    @property
    def mapping(self) -> Dict[str, str]:
        return dict(self._by_name)


def norm_key(text: str) -> str:
    """Loose comparison key so `Backend FSM` == `backend_fsm`."""
    return re.sub(r"[^a-z0-9一-鿿]+", "", str(text or "").lower())


def esc(text: str, limit: int = 70) -> str:
    """Escape a label for use inside a quoted mermaid node."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    text = text.replace('"', "'").replace("`", "'")
    # characters mermaid's parser chokes on even inside quotes
    text = text.replace("#", "＃").replace(";", ",")
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def wrap_label(text: str, width: int = 22) -> str:
    """Insert mermaid line breaks so long labels stay in a readable box."""
    text = esc(text, limit=120)
    if len(text) <= width:
        return text
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return "<br/>".join(lines[:3])


def as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (str, int, float)):
        return [value]
    if isinstance(value, dict):
        return [value]
    return list(value)


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(as_text(v) for v in value)
    if isinstance(value, dict):
        return value.get("text") or value.get("description") or json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def obj(value: Any, key: str = "name") -> Dict[str, Any]:
    """Accept either a plain string or an object for list entries."""
    if isinstance(value, dict):
        return dict(value)
    return {key: as_text(value)}


# --------------------------------------------------------------------------
# io
# --------------------------------------------------------------------------

def read_json(path: str | Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: str | Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def write_text(path: str | Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------
# normalisation
# --------------------------------------------------------------------------

KIND_ALIASES = {
    "ui": "ui", "frontend": "ui", "client": "ui", "web": "ui",
    "service": "service", "backend": "service", "engine": "service", "worker": "service",
    "store": "store", "db": "store", "database": "store", "cache": "store", "queue": "queue",
    "external": "external", "third_party": "external", "3rd_party": "external",
    "actor": "actor", "user": "actor",
}


def _kind(value: Any, fallback: str = "service") -> str:
    key = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return KIND_ALIASES.get(key, fallback)


CHANGE_STATES = ("existing", "added", "modified", "removed")
CHANGE_ALIASES = {
    "new": "added", "add": "added", "added": "added", "新增": "added", "新加": "added",
    "changed": "modified", "modify": "modified", "modified": "modified", "update": "modified",
    "updated": "modified", "改动": "modified", "修改": "modified", "变更": "modified",
    "delete": "removed", "deleted": "removed", "removed": "removed", "drop": "removed",
    "移除": "removed", "删除": "removed", "下线": "removed",
    "existing": "existing", "unchanged": "existing", "same": "existing",
    "沿用": "existing", "不变": "existing", "现状": "existing",
}


def _change(value: Any) -> str:
    key = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())
    return CHANGE_ALIASES.get(key, "existing")


def _step_from_string(text: str) -> Dict[str, Any]:
    """Parse `Frontend FSM -> Backend FSM: start commit` into a step object."""
    m = re.match(r"^\s*(.+?)\s*(-->|->|=>|→)\s*(.+?)\s*[:：]\s*(.+?)\s*$", text)
    if m:
        return {"from": m.group(1), "to": m.group(3), "action": m.group(4), "kind": "call"}
    m = re.match(r"^\s*(.+?)\s*[:：]\s*(.+?)\s*$", text)
    if m and len(m.group(1)) < 40:
        return {"from": m.group(1), "to": "", "action": m.group(2), "kind": "call"}
    return {"from": "", "to": "", "action": text.strip(), "kind": "call"}


def normalize(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce a hand-written design summary into the canonical shape."""
    d: Dict[str, Any] = {}
    d["schema_version"] = raw.get("schema_version", SCHEMA_VERSION)
    d["title"] = as_text(raw.get("title") or "Technical Design")
    d["subtitle"] = as_text(raw.get("subtitle"))
    d["status"] = as_text(raw.get("status"))
    d["authors"] = [as_text(a) for a in as_list(raw.get("authors"))]
    d["date"] = as_text(raw.get("date"))
    d["source_document"] = as_text(raw.get("source_document"))
    d["background"] = as_text(raw.get("background"))
    d["summary"] = as_text(raw.get("summary") or raw.get("tldr"))
    d["goals"] = [as_text(g) for g in as_list(raw.get("goals")) if as_text(g)]
    d["non_goals"] = [as_text(g) for g in as_list(raw.get("non_goals")) if as_text(g)]

    # -- personas & user stories ------------------------------------------
    d["personas"] = [
        {
            "name": as_text(p.get("name")),
            "role": as_text(p.get("role")),
            "need": as_text(p.get("need") or p.get("goal")),
        }
        for p in (obj(x) for x in as_list(raw.get("personas")))
        if as_text(p.get("name"))
    ]
    stories = []
    for s in as_list(raw.get("user_stories")):
        if isinstance(s, str):
            stories.append({"as_a": "", "i_want": as_text(s), "so_that": "", "acceptance": []})
            continue
        flow = []
        for i, st in enumerate(as_list(s.get("flow"))):
            if isinstance(st, str):
                parsed = _step_from_string(st)
                flow.append({"component": parsed["from"] or parsed["to"],
                             "action": parsed["action"], "outcome": "", "kind": "step"})
                continue
            flow.append({
                "component": as_text(st.get("component") or st.get("actor") or st.get("lane")),
                "action": as_text(st.get("action") or st.get("text") or st.get("step")),
                "outcome": as_text(st.get("outcome") or st.get("note")),
                "kind": (as_text(st.get("kind")) or "step").lower(),
            })
        stories.append({
            "id": as_text(s.get("id")) or f"story-{len(stories) + 1}",
            "as_a": as_text(s.get("as_a") or s.get("persona") or s.get("role")),
            "i_want": as_text(s.get("i_want") or s.get("want") or s.get("story")),
            "so_that": as_text(s.get("so_that") or s.get("value")),
            "acceptance": [as_text(a) for a in as_list(s.get("acceptance") or s.get("acceptance_criteria"))],
            "flow_ref": as_text(s.get("flow_ref")),
            "flow": [f for f in flow if f["action"] or f["component"]],
            "change": _change(s.get("change")),
        })
    d["user_stories"] = [s for s in stories if s["i_want"]]

    # -- components --------------------------------------------------------
    ids = IdFactory("c")
    components = []
    for c in (obj(x) for x in as_list(raw.get("components"))):
        name = as_text(c.get("name") or c.get("id"))
        if not name:
            continue
        cid = as_text(c.get("id")) or ids.get(name)
        ids.get(name)  # register alias
        components.append({
            "id": slug(cid, "c"),
            "name": name,
            "group": as_text(c.get("group") or c.get("layer") or c.get("zone")),
            "kind": _kind(c.get("kind") or c.get("type"), "service"),
            "responsibility": as_text(c.get("responsibility") or c.get("description")),
            "tech": as_text(c.get("tech") or c.get("technology")),
            "interfaces": [as_text(i) for i in as_list(c.get("interfaces"))],
            "critical": bool(c.get("critical", False)),
            "change": _change(c.get("change")),
        })
    d["components"] = components
    by_name = {norm_key(c["name"]): c["id"] for c in components}
    by_name.update({norm_key(c["id"]): c["id"] for c in components})

    def resolve(name: str) -> str:
        return by_name.get(norm_key(name), "")

    d["connections"] = [
        {
            "from": as_text(c.get("from") or c.get("source")),
            "to": as_text(c.get("to") or c.get("target")),
            "label": as_text(c.get("label") or c.get("action")),
            "kind": (as_text(c.get("kind")) or "sync").lower(),
            "change": _change(c.get("change")),
        }
        for c in (obj(x, "from") for x in as_list(raw.get("connections")))
        if as_text(c.get("from")) and as_text(c.get("to"))
    ]

    # -- runtime flows -----------------------------------------------------
    flows = []
    for f in (obj(x) for x in as_list(raw.get("runtime_flows") or raw.get("flows"))):
        steps = []
        for s in as_list(f.get("steps")):
            step = _step_from_string(s) if isinstance(s, str) else {
                "from": as_text(s.get("from") or s.get("actor")),
                "to": as_text(s.get("to") or s.get("target")),
                "action": as_text(s.get("action") or s.get("text") or s.get("message")),
                "kind": (as_text(s.get("kind")) or "call").lower(),
                "note": as_text(s.get("note")),
            }
            step.setdefault("note", "")
            if step["action"]:
                steps.append(step)
        actors = [as_text(a) for a in as_list(f.get("actors"))]
        if not actors:
            seen: List[str] = []
            for s in steps:
                for side in (s["from"], s["to"]):
                    if side and side not in seen:
                        seen.append(side)
            actors = seen
        flows.append({
            "name": as_text(f.get("name") or "Runtime Flow"),
            "kind": (as_text(f.get("kind")) or "happy").lower(),
            "description": as_text(f.get("description")),
            "actors": actors,
            "steps": steps,
        })
    d["runtime_flows"] = [f for f in flows if f["steps"]]

    # -- state machines ----------------------------------------------------
    machines = []
    for m in (obj(x, "entity") for x in as_list(raw.get("states") or raw.get("state_machines"))):
        values = [as_text(v) for v in as_list(m.get("values") or m.get("states")) if as_text(v)]
        transitions = []
        for t in as_list(m.get("transitions")):
            if isinstance(t, str):
                mm = re.match(r"^\s*(.+?)\s*(?:-->|->)\s*(.+?)\s*(?:[:：]\s*(.+))?$", t)
                if not mm:
                    continue
                transitions.append({"from": mm.group(1), "to": mm.group(2),
                                    "event": as_text(mm.group(3)), "guard": ""})
            else:
                transitions.append({
                    "from": as_text(t.get("from")),
                    "to": as_text(t.get("to")),
                    "event": as_text(t.get("event") or t.get("trigger")),
                    "guard": as_text(t.get("guard")),
                })
        transitions = [t for t in transitions if t["from"] and t["to"]]
        for t in transitions:
            for side in (t["from"], t["to"]):
                if side not in values and side not in ("[*]",):
                    values.append(side)
        if not transitions and len(values) > 1:
            transitions = [{"from": a, "to": b, "event": "", "guard": ""}
                           for a, b in zip(values, values[1:])]
        machines.append({
            "entity": as_text(m.get("entity") or m.get("name") or "Lifecycle"),
            "initial": as_text(m.get("initial") or (values[0] if values else "")),
            "terminal": [as_text(v) for v in as_list(m.get("terminal"))],
            "values": values,
            "transitions": transitions,
            "notes": as_text(m.get("notes")),
        })
    d["states"] = [m for m in machines if m["values"]]

    # -- data model --------------------------------------------------------
    entities = []
    for e in (obj(x) for x in as_list(raw.get("entities"))):
        fields = []
        for f in as_list(e.get("fields")):
            if isinstance(f, str):
                parts = f.split()
                if len(parts) >= 2 and re.match(r"^[a-zA-Z_\[\]<>]+$", parts[0]):
                    fields.append({"name": parts[1], "type": parts[0], "note": " ".join(parts[2:])})
                else:
                    fields.append({"name": f.strip(), "type": "string", "note": ""})
            else:
                fields.append({
                    "name": as_text(f.get("name")),
                    "type": as_text(f.get("type") or "string"),
                    "note": as_text(f.get("note") or f.get("description")),
                })
        relations = [
            {
                "to": as_text(r.get("to") or r.get("target")),
                "cardinality": as_text(r.get("cardinality") or "1..*"),
                "label": as_text(r.get("label") or "relates to"),
            }
            for r in (obj(x, "to") for x in as_list(e.get("relations")))
            if as_text(r.get("to"))
        ]
        entities.append({
            "name": as_text(e.get("name")),
            "owner": as_text(e.get("owner") or e.get("owned_by")),
            "store": as_text(e.get("store")),
            "description": as_text(e.get("description")),
            "fields": [f for f in fields if f["name"]],
            "relations": relations,
        })
    d["entities"] = [e for e in entities if e["name"]]

    # -- failure paths -----------------------------------------------------
    failures = []
    for f in (obj(x) for x in as_list(raw.get("failure_paths") or raw.get("failures"))):
        steps = []
        for i, s in enumerate(as_list(f.get("steps"))):
            if isinstance(s, str):
                steps.append({"id": f"s{i}", "text": s.strip(), "type": "step", "next": []})
                continue
            nxt = []
            for n in as_list(s.get("next")):
                n = obj(n, "to")
                nxt.append({"to": as_text(n.get("to")), "label": as_text(n.get("label"))})
            for key, label in (("on_yes", "Yes"), ("on_no", "No")):
                if s.get(key):
                    nxt.append({"to": as_text(s.get(key)), "label": label})
            steps.append({
                "id": as_text(s.get("id")) or f"s{i}",
                "text": as_text(s.get("text") or s.get("step")),
                "type": (as_text(s.get("type")) or ("decision" if nxt else "step")).lower(),
                "next": nxt,
            })
        failures.append({
            "name": as_text(f.get("name") or "Failure Path"),
            "trigger": as_text(f.get("trigger")),
            "component": as_text(f.get("component")),
            "detection": as_text(f.get("detection")),
            "impact": as_text(f.get("impact")),
            "mitigation": as_text(f.get("mitigation") or f.get("recovery")),
            "severity": (as_text(f.get("severity")) or "medium").lower(),
            "steps": [s for s in steps if s["text"]],
        })
    d["failure_paths"] = [f for f in failures if f["steps"] or f["mitigation"]]

    # -- rollout -----------------------------------------------------------
    phases = []
    for p in (obj(x) for x in as_list(raw.get("rollout_phases") or raw.get("rollout"))):
        phases.append({
            "name": as_text(p.get("name") or "Phase"),
            "description": as_text(p.get("description")),
            "duration": as_text(p.get("duration") or p.get("estimate")),
            "depends_on": [as_text(x) for x in as_list(p.get("depends_on"))],
            "deliverables": [as_text(x) for x in as_list(p.get("deliverables"))],
            "exit_criteria": as_text(p.get("exit_criteria")),
            "risk": (as_text(p.get("risk")) or "").lower(),
        })
    d["rollout_phases"] = [p for p in phases if p["name"]]

    # -- decisions / risks / questions -------------------------------------
    decisions = []
    for dec in (obj(x, "title") for x in as_list(raw.get("decisions") or raw.get("adrs"))):
        alts = []
        for a in as_list(dec.get("alternatives")):
            a = obj(a)
            alts.append({
                "name": as_text(a.get("name")),
                "pros": [as_text(x) for x in as_list(a.get("pros"))],
                "cons": [as_text(x) for x in as_list(a.get("cons"))],
            })
        decisions.append({
            "title": as_text(dec.get("title") or dec.get("decision")),
            "status": as_text(dec.get("status") or "accepted"),
            "context": as_text(dec.get("context")),
            "alternatives": [a for a in alts if a["name"]],
            "chosen": as_text(dec.get("chosen") or dec.get("choice")),
            "reason": as_text(dec.get("reason") or dec.get("rationale")),
            "consequences": as_text(dec.get("consequences") or dec.get("tradeoffs")),
        })
    d["decisions"] = [x for x in decisions if x["title"]]

    d["risks"] = [
        {
            "title": as_text(r.get("title") or r.get("risk")),
            "severity": (as_text(r.get("severity")) or "medium").lower(),
            "likelihood": (as_text(r.get("likelihood")) or "").lower(),
            "impact": as_text(r.get("impact")),
            "mitigation": as_text(r.get("mitigation")),
            "owner": as_text(r.get("owner")),
        }
        for r in (obj(x, "title") for x in as_list(raw.get("risks")))
        if as_text(r.get("title") or r.get("risk"))
    ]
    d["constraints"] = [as_text(c) for c in as_list(raw.get("constraints")) if as_text(c)]
    d["open_questions"] = [
        {
            "question": as_text(q.get("question") or q.get("title")),
            "owner": as_text(q.get("owner")),
            "blocking": bool(q.get("blocking", False)),
        }
        for q in (obj(x, "question") for x in as_list(raw.get("open_questions")))
        if as_text(q.get("question") or q.get("title"))
    ]
    d["metrics"] = [
        {"name": as_text(m.get("name")), "target": as_text(m.get("target")), "note": as_text(m.get("note"))}
        for m in (obj(x) for x in as_list(raw.get("metrics")))
        if as_text(m.get("name"))
    ]
    d["glossary"] = [
        {"term": as_text(g.get("term")), "definition": as_text(g.get("definition"))}
        for g in (obj(x, "term") for x in as_list(raw.get("glossary")))
        if as_text(g.get("term"))
    ]

    # -- current state and this increment ----------------------------------
    cs = raw.get("current_state")
    cs = obj(cs, "summary") if cs is not None else {}
    d["current_state"] = {
        "summary": as_text(cs.get("summary") or cs.get("description")),
        "components": [as_text(c) for c in as_list(cs.get("components")) if as_text(c)],
        "pain_points": [as_text(c) for c in as_list(cs.get("pain_points") or cs.get("problems"))
                        if as_text(c)],
    }
    d["changes"] = [
        {
            "target": as_text(c.get("target") or c.get("name") or c.get("component")),
            "kind": (as_text(c.get("kind")) or "component").lower(),
            "type": _change(c.get("type") or c.get("change")),
            "what": as_text(c.get("what") or c.get("description")),
            "why": as_text(c.get("why") or c.get("reason")),
            "files": [as_text(f) for f in as_list(c.get("files") or c.get("where")) if as_text(f)],
            "risk": (as_text(c.get("risk")) or "").lower(),
        }
        for c in (obj(x, "target") for x in as_list(raw.get("changes")))
        if as_text(c.get("target") or c.get("name") or c.get("component"))
    ]

    # -- the source document itself ----------------------------------------
    d["document_sections"] = [
        {
            "id": as_text(sec.get("id")) or slug(as_text(sec.get("heading")), "doc"),
            "heading": as_text(sec.get("heading")),
            "level": int(sec.get("level") or 2),
            "text": as_text(sec.get("text")),
        }
        for sec in (obj(x, "heading") for x in as_list(raw.get("document_sections")))
        if as_text(sec.get("text")) or as_text(sec.get("heading"))
    ]
    d["source_map"] = {k: as_text(v) for k, v in (raw.get("source_map") or {}).items() if as_text(v)}

    # -- diagram overrides supplied by the author --------------------------
    views = raw.get("views") or {}
    d["views"] = {k: as_text(v) for k, v in views.items() if as_text(v)}
    d["_component_ids"] = by_name
    return d


def component_lookup(summary: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {norm_key(c["name"]): c for c in summary.get("components", [])}


def known_names(summary: Dict[str, Any]) -> Dict[str, str]:
    """Every name a diagram may legitimately reference -> its display form."""
    names: Dict[str, str] = {}
    for c in summary.get("components", []):
        names[norm_key(c["name"])] = c["name"]
    for p in summary.get("personas", []):
        names[norm_key(p["name"])] = p["name"]
    for e in summary.get("entities", []):
        names[norm_key(e["name"])] = e["name"]
    return names
