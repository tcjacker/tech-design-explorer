#!/usr/bin/env python3
"""End-to-end tests for the tech-design-explorer pipeline (stdlib only).

    python3 -m unittest discover -s tests -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "tech-design-explorer" / "scripts"))

import _common  # noqa: E402
import build_views  # noqa: E402
import export_bundle  # noqa: E402
import parse_design  # noqa: E402
import render_html  # noqa: E402

DOC = ROOT / "examples" / "sample_design.md"
SUMMARY = ROOT / "examples" / "sample_design-summary.json"


class TestParse(unittest.TestCase):
    def setUp(self):
        self.draft = parse_design.parse(DOC.read_text(encoding="utf-8"), source=str(DOC))

    def test_finds_the_title_and_the_major_sections(self):
        self.assertEqual(self.draft["title"], "Hour Commit Decoupling")
        for field in ("goals", "non_goals", "components", "runtime_flows", "states",
                      "entities", "failure_paths", "rollout_phases", "risks"):
            self.assertTrue(self.draft[field], f"{field} was not extracted")

    def test_components_come_from_the_table(self):
        names = {c["name"] for c in self.draft["components"]}
        self.assertIn("Backend FSM", names)
        self.assertIn("Session Store", names)

    def test_state_values_come_from_the_transitions(self):
        machine = self.draft["states"][0]
        self.assertEqual(machine["values"][0], "IDLE")
        self.assertIn("FAILED", machine["values"])
        self.assertNotIn("FSM", machine["values"])  # acronyms are not states

    def test_user_stories_are_split_into_role_want_value(self):
        story = self.draft["user_stories"][0]
        self.assertEqual(story["as_a"], "player")
        self.assertTrue(story["so_that"])

    def test_gaps_are_reported_for_what_prose_cannot_give(self):
        self.assertTrue(any("connections" in g for g in self.draft["_gaps"]))


class TestNormalize(unittest.TestCase):
    def test_short_forms_are_accepted(self):
        s = _common.normalize({
            "title": "T",
            "components": ["Alpha", {"name": "Beta", "kind": "db"}],
            "runtime_flows": [{"name": "f", "steps": ["Alpha -> Beta: write"]}],
            "states": [{"entity": "Beta", "transitions": ["IDLE -> BUSY: go"]}],
            "entities": [{"name": "row", "fields": ["uuid id", "payload"]}],
            "failure_paths": [{"name": "boom", "steps": ["it broke", "we noticed"]}],
        })
        self.assertEqual(s["components"][1]["kind"], "store")
        step = s["runtime_flows"][0]["steps"][0]
        self.assertEqual((step["from"], step["to"], step["action"]), ("Alpha", "Beta", "write"))
        self.assertEqual(s["states"][0]["values"], ["IDLE", "BUSY"])
        self.assertEqual(s["entities"][0]["fields"][0], {"name": "id", "type": "uuid", "note": ""})
        self.assertEqual(len(s["failure_paths"][0]["steps"]), 2)

    def test_labels_are_escaped_for_mermaid(self):
        self.assertNotIn("#", _common.esc("a # b ; c"))
        self.assertNotIn(";", _common.esc("a # b ; c"))
        self.assertEqual(_common.esc('say "hi"'), "say 'hi'")

    def test_ids_match_loosely_but_stay_unique(self):
        ids = _common.IdFactory("c")
        # punctuation and case are not identity: these are one component
        self.assertEqual(ids.get("Backend FSM"), ids.get("backend_fsm"))
        self.assertEqual(ids.get("A B"), ids.get("A-B"))
        # distinct names never collide, even when they slug to the same prefix
        long_a, long_b = "Session store for the engine tier one", "Session store for the engine tier two"
        self.assertNotEqual(ids.get(long_a), ids.get(long_b))
        self.assertTrue(ids.get("9 Lives").startswith("c_"))  # ids never start with a digit


class TestViews(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = build_views.build(json.loads(SUMMARY.read_text(encoding="utf-8")))
        cls.by_key = {v["key"]: v for v in cls.bundle["views"]}

    def test_every_view_is_generated_for_a_complete_design(self):
        self.assertEqual(set(self.by_key), set(_common.VIEW_ORDER))

    def test_diagrams_declare_their_own_kind_of_mermaid(self):
        self.assertTrue(self.by_key["overview"]["diagrams"][0]["mermaid"].startswith("flowchart LR"))
        self.assertTrue(self.by_key["sequence"]["diagrams"][0]["mermaid"].startswith("sequenceDiagram"))
        self.assertTrue(self.by_key["state_machine"]["diagrams"][0]["mermaid"].startswith("stateDiagram-v2"))
        self.assertTrue(self.by_key["data_model"]["diagrams"][0]["mermaid"].startswith("erDiagram"))

    def test_state_diagram_never_emits_a_bare_colon_in_a_label(self):
        code = self.by_key["state_machine"]["diagrams"][0]["mermaid"]
        for line in code.splitlines():
            body = line.strip()
            if body.startswith("state ") or "-->" in body:
                self.assertLessEqual(body.count(":"), 1, f"two colons on: {body}")
        self.assertIn("end note", code)  # notes use the block form

    def test_a_failure_path_keeps_its_decision_branch(self):
        code = self.by_key["failure_paths"]["diagrams"][0]["mermaid"]
        self.assertIn("{\"", code)          # a diamond
        self.assertIn('|"Yes"|', code)      # a labelled branch

    def test_walkthrough_metadata_matches_the_flow(self):
        seq = self.by_key["sequence"]["diagrams"][0]
        self.assertEqual(seq["story_mode"], "message")
        self.assertEqual(len(seq["steps"]),
                         len(self.bundle["summary"]["runtime_flows"][0]["steps"]))

    def test_a_clean_design_produces_no_warnings(self):
        warns = [c for c in self.bundle["checks"] if c["level"] == "warn"]
        self.assertEqual(warns, [], f"unexpected warnings: {warns}")

    def test_inconsistent_names_are_caught(self):
        bundle = build_views.build({
            "title": "T",
            "components": [{"name": "Alpha", "responsibility": "does things"}],
            "connections": [{"from": "Alpha", "to": "Ghost"}],
            "runtime_flows": [{"name": "f", "steps": ["Alpha -> Ghost: call"]}],
        })
        messages = " ".join(c["message"] for c in bundle["checks"] if c["level"] == "warn")
        self.assertIn("Ghost", messages)

    def test_authored_views_override_the_generated_one(self):
        bundle = build_views.build({
            "title": "T",
            "components": [{"name": "Alpha"}],
            "views": {"architecture": "flowchart LR\n  X --> Y"},
        })
        arch = [v for v in bundle["views"] if v["key"] == "architecture"][0]
        self.assertEqual(arch["diagrams"][0]["source"], "authored")
        self.assertIn("X --> Y", arch["diagrams"][0]["mermaid"])


class TestRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary = json.loads(SUMMARY.read_text(encoding="utf-8"))

    def test_standalone_is_a_complete_document_with_an_embedded_payload(self):
        html = render_html.render(self.summary, mermaid_urls=render_html.MERMAID_URLS)["_html"]
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn("</html>", html)
        payload = html.split('<script id="design-payload" type="application/json">')[1].split("</script>")[0]
        data = json.loads(payload.replace("<\\/", "</").replace("<\\!--", "<!--"))
        self.assertEqual(data["summary"]["title"], "Hour Commit Decoupling")
        self.assertEqual(len(data["views"]), len(_common.VIEW_ORDER))

    def test_artifact_format_omits_the_document_wrapper(self):
        html = render_html.render(self.summary, mermaid_urls=[], fmt="artifact")["_html"]
        self.assertNotIn("<!doctype", html.lower())
        self.assertNotIn("<body", html.lower())
        self.assertTrue(html.lstrip().startswith("<title>"))

    def test_payload_cannot_close_the_script_element(self):
        summary = dict(self.summary, title="</script><script>alert(1)</script>")
        html = render_html.render(summary, mermaid_urls=[])["_html"]
        body = html.split('type="application/json">')[1].split("</script>")[0]
        # only `</script` can terminate the element early; it must not survive
        self.assertNotIn("</script", body)
        self.assertIn("<\\/script>", body)
        self.assertIn("alert(1)", body)  # the text itself is preserved, just neutralised

    def test_inline_mermaid_embeds_the_library_and_drops_the_cdn(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = Path(tmp) / "mermaid.min.js"
            lib.write_text("globalThis.mermaid = {};", encoding="utf-8")
            html = render_html.render(self.summary, mermaid_urls=render_html.MERMAID_URLS,
                                      inline_mermaid=str(lib))["_html"]
        self.assertIn("globalThis.mermaid = {};", html)
        self.assertIn('"mermaid_urls":[]', html.replace(", ", ",").replace('"mermaid_urls": []', '"mermaid_urls":[]'))


class TestLanguage(unittest.TestCase):
    CJK = {
        "title": "会话缓存迁移方案",
        "background": "现有单表在高并发下写放大严重，需要拆分冷热数据。",
        "components": [{"name": "会话服务", "responsibility": "读写会话状态"},
                       {"name": "热表", "responsibility": "存放活跃会话"}],
        "runtime_flows": [{"name": "主流程", "steps": ["会话服务 -> 热表: 写入活跃状态"]}],
    }

    def test_language_is_detected_from_the_design(self):
        self.assertEqual(_common.detect_lang(self.CJK), "zh")
        self.assertEqual(_common.detect_lang(json.loads(SUMMARY.read_text(encoding="utf-8"))), "en")

    def test_chinese_designs_get_chinese_chrome_and_captions(self):
        out = render_html.render(self.CJK, mermaid_urls=[])
        self.assertEqual(out["lang"], "zh")
        self.assertEqual(out["strings"]["sec.summary"], "概要")
        titles = [v["title"] for v in out["views"]]
        self.assertIn("架构", titles)
        self.assertIn("端到端的正常路径", out["views"][0]["diagrams"][0]["title"])

    def test_language_can_be_forced(self):
        out = render_html.render(self.CJK, mermaid_urls=[], lang="en")
        self.assertEqual(out["lang"], "en")
        self.assertEqual(out["strings"], {})
        self.assertIn("Architecture", [v["title"] for v in out["views"]])

    def test_cjk_names_become_stable_ascii_ids(self):
        code = render_html.render(self.CJK, mermaid_urls=[])["views"][0]["diagrams"][0]["mermaid"]
        for line in code.splitlines():
            node = line.strip().split("[")[0].split(" ")[0]
            self.assertTrue(all(ord(c) < 128 for c in node), f"non-ascii id in: {line}")
        self.assertIn("会话服务", code)  # labels keep the original text


class TestBundle(unittest.TestCase):
    def test_bundle_writes_html_summary_assets_and_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "design-explorer"
            result = export_bundle.bundle(json.loads(SUMMARY.read_text(encoding="utf-8")), out)
            self.assertTrue((out / "design-explorer.html").exists())
            self.assertTrue((out / "README.md").exists())
            mmds = list((out / "assets").glob("*.mmd"))
            self.assertEqual(len(mmds), sum(len(v["diagrams"]) for v in result["views"]))
            written = json.loads((out / "design-summary.json").read_text(encoding="utf-8"))
            self.assertFalse([k for k in written if k.startswith("_")], "internal keys leaked")

    def test_a_document_can_go_all_the_way_through_without_a_human(self):
        draft = parse_design.parse(DOC.read_text(encoding="utf-8"), source=str(DOC))
        with tempfile.TemporaryDirectory() as tmp:
            result = export_bundle.bundle(draft, Path(tmp) / "b")
            self.assertGreaterEqual(len(result["views"]), 5)


if __name__ == "__main__":
    unittest.main()
