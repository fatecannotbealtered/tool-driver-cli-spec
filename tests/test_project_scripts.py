"""Unit tests of the project scripts: instantiate, sync_spec, check_project and run_matrix.

One project is generated from the template and filled in the way an author would. Each test
copies it, breaks one rule, and expects check_project to name the clause.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import check_project  # noqa: E402
import e2e_template  # noqa: E402
import run_matrix  # noqa: E402
import sync_spec  # noqa: E402

NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class ProjectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="project-scripts-"))
        cls.fresh = e2e_template.generate(cls.work, "file,session", False)
        cls.filled = cls.work / "filled"
        shutil.copytree(cls.fresh, cls.filled)
        e2e_template.register(cls.filled)
        e2e_template.fill(cls.filled)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        self.project = Path(tempfile.mkdtemp(prefix="project-", dir=self.work)) / "demo-cli"
        shutil.copytree(self.filled, self.project)

    def problems(self, project: Path | None = None) -> list[check_project.Problem]:
        return check_project.check(project or self.project)

    def clauses(self, project: Path | None = None) -> set[str]:
        return {p.clause for p in self.problems(project)}

    def edit(self, name: str, old: str, new: str, count: int = 1) -> None:
        path = self.project / name
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text, name)
        path.write_text(text.replace(old, new, count), encoding="utf-8", newline="\n")

    def expect(self, clause: str) -> None:
        found = self.problems()
        self.assertIn(clause, {p.clause for p in found}, [p.text() for p in found])

    def fix(self) -> None:
        check_project.fix(check_project.gather(self.project))

    # -------------------------------------------------------------- instantiate

    def test_a_fresh_project_lacks_only_what_the_author_fills_in(self):
        found = self.problems(self.fresh)
        self.assertTrue(found)
        rest = [p.text() for p in found if p.clause != "DREPO-019"
                and not (p.clause == "DREPO-061" and p.path == "contract/commands.json")]
        self.assertEqual(rest, [])

    def test_the_filled_project_conforms(self):
        self.assertEqual([p.text() for p in self.problems()], [])

    def test_every_mode_and_a_host_component_instantiate_cleanly(self):
        for modes, host in (("device", False), ("file,session,device", True)):
            project = e2e_template.generate(Path(tempfile.mkdtemp(prefix="variant-", dir=self.work)), modes, host)
            self.assertEqual((project / "plugin").is_dir(), host)
            security = (project / "SECURITY.md").read_text(encoding="utf-8")
            self.assertEqual("## Host Component" in security, host)
            self.assertEqual("## Physical Effects" in security, "device" in modes)

    # -------------------------------------------------------------- layout and documents

    def test_root_files_and_paths(self):
        (self.project / "CODE_OF_CONDUCT.md").unlink()
        (self.project / "notes.txt").write_text("x", encoding="utf-8")
        (self.project / "plugin").mkdir()
        shutil.rmtree(self.project / "docs" / "evidence")
        self.assertTrue({"DREPO-002", "DREPO-003", "DREPO-004"} <= self.clauses())

    def test_sections_and_language_pairs(self):
        self.edit("README_zh.md", "## 卸载", "## 移除")
        self.expect("DREPO-011")

    def test_table_rows_must_match_between_languages(self):
        self.edit("docs/COMPATIBILITY.md", "|---|---|---|---|", "|---|---|---|---|\n| 9.0 | Linux | file | ⏳ untested |")
        self.expect("DREPO-010")

    def test_language_switch_line(self):
        self.edit("CONTRIBUTING_zh.md", "[English](CONTRIBUTING.md) | 中文", "English")
        self.expect("DREPO-010")

    def test_fixed_text_cannot_change(self):
        cases = [("README.md", "## How It Works\n", "## How It Works\n\nAlso this.\n", "DREPO-011"),
                 ("README_zh.md", "npm install -g @tool-driver/demo-cli", "npm i -g @tool-driver/demo-cli", "DREPO-054"),
                 ("AGENTS.md", "## Bare minimum to obey\n", "## Bare minimum to obey\n\nOr not.\n", "DREPO-012"),
                 ("SECURITY_zh.md", "## 自更新\n", "## 自更新\n\n改过。\n", "DREPO-013")]
        for name, old, new, clause in cases:
            with self.subTest(name=name):
                self.setUp()
                self.edit(name, old, new)
                self.expect(clause)
                self.fix()
                self.assertNotIn(clause, self.clauses(), "generate restores the fixed text")

    def test_changelog(self):
        self.edit("CHANGELOG.md", "### Added", "### 新增")
        self.expect("DREPO-018")
        self.setUp()
        self.edit("CHANGELOG.md", "## [Unreleased]", "## [0.1.0] - 2026-01-01\n\n### Fixed\n\n- x\n\n## [Unreleased]")
        self.expect("DREPO-018")

    def test_placeholders_anywhere(self):
        self.edit("demo_cli/adapter/__init__.py", "return {\"found\": False}", "return {\"found\": False}  # {{fill: later}}")
        self.edit("docs/E2E.md", "## Procedure\n", "## Procedure\n\n{{application}}\n")
        problems = [p for p in self.problems() if p.clause == "DREPO-019"]
        self.assertEqual({p.path for p in problems}, {"demo_cli/adapter/__init__.py", "docs/E2E.md"})

    def test_no_invented_badges(self):
        self.edit("docs/E2E.md", "## Procedure\n", "## Procedure\n\n![beta](https://img.shields.io/badge/beta-yes-red)\n")
        self.expect("DREPO-024")

    # -------------------------------------------------------------- generated content

    def test_generated_regions_are_compared(self):
        cases = [("README.md", "![risk](https://img.shields.io/badge/risk-T1-d29922)", "![risk](https://img.shields.io/badge/risk-T0-d29922)", "DREPO-020"),
                 ("README_zh.md", "| 风险等级 | T1 |", "| 风险等级 | T0 |", "DREPO-021"),
                 ("SECURITY.md", "`part move`: change", "`part move`: observe", "DSEC-002"),
                 ("skills/demo-cli/SKILL.md", "- `part`: get, move", "- `part`: get", "DSKL-006"),
                 ("docs/COMPATIBILITY_zh.md", "| >=1.0 <2 | Windows | file | ⏳ untested |", "| >=1.0 <2 | Windows | file | ✅ verified |", "DREPO-016")]
        for name, old, new, clause in cases:
            with self.subTest(name=name):
                self.setUp()
                self.edit(name, old, new)
                self.expect(clause)
                self.fix()
                self.assertNotIn(clause, self.clauses())

    def test_commands_json_is_regenerated_and_validated(self):
        self.edit("contract/commands.json", '"summary": "Read one part."', '"summary": "Read a part."')
        self.expect("DREPO-031")

    def test_support_matrix_rests_on_current_live_records(self):
        record = {"kind": "live", "tool": "demo-cli", "tool_version": "0.1.3", "commit": "abc1234",
                  "application": {"name": "FakeApp", "version": "1.5.2"}, "os": "Windows 11", "platform": "windows",
                  "recorded_at": "2026-11-01T09:30:00Z", "targets": ["file:///D:/e2e/demo/"],
                  "runs": [{"command": "part move", "arguments": ["--session", "s1"], "exit": 0, "result": "pass", "mode": "session"}]}
        old = {**record, "tool_version": "0.0.9", "application": {"name": "FakeApp", "version": "1.4.0"}, "platform": "linux"}
        folder = self.project / "docs" / "evidence"
        (folder / "2026-11-01-current.json").write_text(json.dumps(record), encoding="utf-8")
        (folder / "2026-10-01-old.json").write_text(json.dumps(old), encoding="utf-8")
        self.expect("DREPO-016")
        self.fix()
        matrix = (self.project / "docs" / "COMPATIBILITY.md").read_text(encoding="utf-8")
        self.assertIn("| 1.5 | Windows | session | ✅ verified |", matrix)
        self.assertIn("| >=1.0 <2 | Windows | file | ⏳ untested |", matrix)
        self.assertNotIn("1.4", matrix)
        self.assertIn("2026-11-01-current.json", (self.project / "docs" / "E2E.md").read_text(encoding="utf-8"))
        self.assertEqual([p.text() for p in self.problems()], [])

    def test_unshipped_systems_are_unsupported(self):
        package = json.loads((self.project / "package.json").read_text(encoding="utf-8"))
        package["optionalDependencies"] = {"@tool-driver/demo-cli-linux-x64": "0.1.0"}
        (self.project / "package.json").write_text(json.dumps(package, indent=2), encoding="utf-8")
        self.fix()
        matrix = (self.project / "docs" / "COMPATIBILITY.md").read_text(encoding="utf-8")
        self.assertIn("| >=1.0 <2 | Windows | session | ⛔ unsupported |", matrix)
        self.assertIn("platform-Linux-555555", (self.project / "README.md").read_text(encoding="utf-8"))

    # -------------------------------------------------------------- pinned copies

    def test_pinned_copies_are_never_edited(self):
        self.edit("demo_cli/_driver/update.py", "MOVE_ASIDE = WINDOWS", "MOVE_ASIDE = False")
        self.edit(".agent/DRIVER-CLI-SPEC.md", "MUST", "SHOULD")
        self.edit("contract/driver-contract.json", '"notice_interval_hours": 24', '"notice_interval_hours": 48')
        (self.project / "licenses" / "extra.txt").write_text("x", encoding="utf-8")
        self.assertTrue({"DREPO-030", "DREPO-031", "DREPO-032", "DREPO-033"} <= self.clauses())

    def test_sync_restores_the_release(self):
        (self.project / "demo_cli" / "_driver" / "update.py").unlink()
        (self.project / "demo_cli" / "_driver" / "mine.py").write_text("x = 1\n", encoding="utf-8")
        (self.project / ".agent" / "SPEC_VERSION").write_text("0.9.0\n", encoding="utf-8")
        self.expect("DREPO-034")
        changes = sync_spec.sync(self.project)
        self.assertIn("removed demo_cli/_driver/mine.py", changes)
        self.assertEqual([p.text() for p in self.problems()], [])
        self.assertEqual(sync_spec.sync(self.project), [])

    # -------------------------------------------------------------- versions, platforms and the survey

    def test_one_version_everywhere(self):
        self.edit("package.json", '"version": "0.1.0"', '"version": "0.2.0"')
        found = self.clauses()
        self.assertTrue({"DREPO-040", "DREPO-053", "DSKL-030"} <= found, found)

    def test_platforms_follow_the_survey(self):
        package = json.loads((self.project / "package.json").read_text(encoding="utf-8"))
        package["optionalDependencies"]["@tool-driver/demo-cli-linux-arm64"] = "0.1.0"
        package["optionalDependencies"].pop("@tool-driver/demo-cli-darwin-x64")
        package["optionalDependencies"]["@tool-driver/demo-cli-darwin-arm64"] = "0.1.0"
        (self.project / "package.json").write_text(json.dumps(package, indent=2), encoding="utf-8")
        problems = [p.message for p in self.problems() if p.clause == "DREPO-052"]
        self.assertTrue(any("Linux arm64" in m for m in problems), problems)
        self.assertTrue(any("needs an x64" in m for m in problems), problems)

    def test_capability_survey(self):
        self.edit("docs/APPLICATION.md", "| CAP-001 | Move parts | The automation API | provided | - |",
                  "| CAP-1 | Move parts | The automation API | maybe | - |")
        found = self.clauses()
        self.assertTrue({"DREPO-060", "DREPO-061"} <= found, found)

    # -------------------------------------------------------------- Skills

    def test_entry_skill_rules(self):
        skill = "skills/demo-cli/SKILL.md"
        self.edit(skill, "name: demo-cli", "name: demo")
        self.edit(skill, "### Scope refused", "### Scope")
        self.edit(skill, "## Errors\n", "## Errors\n" + "\nline" * 160 + "\n")
        (self.project / "skills" / "demo-cli" / "notes.txt").write_text("x", encoding="utf-8")
        found = self.clauses()
        self.assertTrue({"DSKL-002", "DSKL-009", "DSKL-003", "DSKL-032"} <= found, found)

    def test_domain_skill_rules(self):
        folder = self.project / "skills" / "demo-parts"
        folder.mkdir()
        (folder / "SKILL.md").write_text("---\nname: demo-parts\ndescription: Parts. 零件。\nmetadata:\n  version: 0.1.0\n"
                                         "  commands: [part get, part move, part fly]\n---\n\nRead the demo-cli Skill first.\n",
                                         encoding="utf-8")
        other = self.project / "skills" / "demo-boards"
        other.mkdir()
        (other / "SKILL.md").write_text("---\nname: demo-boards\ndescription: Boards. 电路板。\nmetadata:\n  version: 0.1.0\n"
                                        "  requires: demo-cli\n  commands: [part get]\n---\n\nRead the demo-cli Skill first.\n",
                                        encoding="utf-8")
        found = self.clauses()
        self.assertTrue({"DSKL-024", "DSKL-026", "DSKL-027"} <= found, found)

    # -------------------------------------------------------------- knowledge

    def test_knowledge_rules(self):
        self.edit("knowledge/demo-troubleshooting.md", "kind: troubleshooting", "kind: guide")
        self.edit("knowledge/demo-troubleshooting.md", "id: demo-troubleshooting", "id: demo-basics")
        self.edit("knowledge/demo-basics.md", "lang: en\n", "")
        self.edit("knowledge/demo-basics.md", "\n---\n", "\n---\n\nSee [the guide](missing.md).\n")
        found = self.clauses()
        self.assertTrue({"DSKL-120", "DSKL-121", "DSKL-126", "DSKL-127"} <= found, found)

    # -------------------------------------------------------------- matrices, evidence and maturity

    def test_matrices(self):
        (self.project / "tests" / "matrix" / "part-get.json").unlink()
        self.edit("tests/matrix/part-move.json", '"row": "busy",\n      "applies": false,\n      "reason": "The demo tool drives no real application."',
                  '"row": "busy",\n      "applies": true,\n      "arguments": [],\n      "expected": {"exit": 7, "code": "E_BUSY"},\n'
                  '      "actual": {"exit": 0},\n      "evidence": "live:docs/evidence/none.json"')
        problems = [p.message for p in self.problems() if p.clause in ("DVER-030", "DVER-041")]
        self.assertTrue(any("needs a behavior matrix" in m for m in problems), problems)
        self.assertTrue(any("row busy failed" in m for m in problems), problems)
        self.assertTrue(any("does not exist" in m for m in problems), problems)

    def test_generate_writes_a_first_matrix(self):
        (self.project / "tests" / "matrix" / "part-get.json").unlink()
        self.fix()
        matrix = json.loads((self.project / "tests" / "matrix" / "part-get.json").read_text(encoding="utf-8"))
        rows = {r["row"]: r for r in matrix["rows"]}
        self.assertFalse(rows["conflict"]["applies"])
        self.assertEqual(rows["not_found"]["expected"]["code"], "E_NOT_FOUND")
        self.assertIn("DREPO-019", self.clauses())

    def test_maturity_needs_current_evidence(self):
        self.edit("demo_cli/commands/__init__.py", '"maturity": "draft"', '"maturity": "verified"')
        self.fix()
        self.expect("DVER-040")

    def test_evidence_records_validate(self):
        (self.project / "docs" / "evidence" / "2026-11-01-bad.json").write_text(json.dumps({"kind": "live"}), encoding="utf-8")
        self.expect("DVER-042")

    # -------------------------------------------------------------- run_matrix

    def test_run_matrix_runs_only_on_authorized_targets(self):
        target = self.work / "authorized"
        target.mkdir(exist_ok=True)
        (target / "board.fake").write_text("x", encoding="utf-8")
        with self.assertRaises(SystemExit):
            run_matrix.main([str(self.project), "--command", "part get", "--set", f"doc={target / 'board.fake'}",
                             "--application-version", "1.5.0"])
        url = target.resolve().as_uri() + "/"
        self.edit("docs/E2E.md", "No target is authorized yet.", f"- `{url}`: the demo files")
        code = run_matrix.main([str(self.project), "--command", "part get", "--row", "normal", "--set",
                                f"doc={target / 'board.fake'}", "--set", "session=s1", "--application-version", "1.5.0"])
        self.assertEqual(code, 1)  # the demo adapter drives no application, so the row fails
        records = list((self.project / "docs" / "evidence").glob("*-part-get.json"))
        self.assertEqual(len(records), 1)
        record = json.loads(records[0].read_text(encoding="utf-8"))
        self.assertEqual((record["targets"], record["runs"][0]["mode"]), ([url], "session"))
        row = json.loads((self.project / "tests" / "matrix" / "part-get.json").read_text(encoding="utf-8"))["rows"][0]
        self.assertTrue(row["evidence"].startswith("live:docs/evidence/"))
        self.fix()
        problems = [p.message for p in self.problems() if p.clause == "DVER-030"]
        self.assertTrue(any("row normal failed" in m for m in problems), problems)

    def test_covered(self):
        targets = ["file:///D:/e2e/demo/", "file:///D:/e2e/one.fake", "device:cnc-01"]
        if os.name == "nt":
            self.assertEqual(run_matrix.covered("D:/e2e/demo/sub/board.fake", "file", targets), targets[0])
            self.assertEqual(run_matrix.covered("D:/e2e/one.fake", "file", targets), targets[1])
            self.assertIsNone(run_matrix.covered("D:/e2e/demo2/board.fake", "file", targets))
        self.assertEqual(run_matrix.covered("cnc-01", "device", targets), "device:cnc-01")
        self.assertIsNone(run_matrix.covered("cnc-02", "device", targets))


class GeneratorTest(unittest.TestCase):
    def test_command_map(self):
        commands = [{"path": "reference"}, {"path": "doc save"}, {"path": "doc close", "tier": {"session": "dangerous", "file": "direct"}},
                    {"path": "part pin list"}]
        self.assertEqual(check_project.command_map(commands),
                         "- `reference`\n- `doc`: save, close (dangerous)\n- `part pin`: list")

    def test_front_matter(self):
        front, body, length = check_project.front_matter("---\nname: x\ndescription: >-\n  one\n  two\nmetadata:\n  version: 1.0.0\n"
                                                         "  commands: [a b, c d]\n---\nbody\n")
        self.assertEqual(front, {"name": "x", "description": "one two", "metadata": {"version": "1.0.0", "commands": ["a b", "c d"]}})
        self.assertEqual((body, length), ("body\n", 9))

    def test_render(self):
        facts = check_project.Facts(root=Path("."), contract=check_project.load_contract())
        facts.tool = "x-cli"
        facts.reference = {"driver": {"modes": ["file"], "host_component": True}}
        text = "a {{tool}}\n{{#host_component}}\nhost\n{{/host_component}}\n{{^host_component}}\nnone\n{{/host_component}}\n{{#session}}\ns\n{{/session}}\nz"
        self.assertEqual(check_project.render(text, facts), "a x-cli\nhost\nz")

    def test_leftovers(self):
        found = [m.group(0) for m in check_project.LEFTOVER.finditer("{{fill: a}} {{tool}} {{#device}} ${{ matrix.os }} {{other}}")]
        self.assertEqual(found, ["{{fill: a}}", "{{tool}}", "{{#device}}"])


if __name__ == "__main__":
    unittest.main()
