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
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

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

    def authorize(self, url: str) -> None:
        self.edit("docs/E2E.md", "No target is authorized yet.", f"- `{url}`: the demo files")

    def record(self, name: str, **changes) -> str:
        """A live record in docs/evidence/; returns its path."""
        record = {"kind": "live", "tool": "demo-cli", "tool_version": "0.1.3", "commit": "abc1234",
                  "application": {"name": "FakeApp", "version": "1.5.2"}, "os": "Windows 11", "platform": "windows",
                  "recorded_at": "2026-11-01T09:30:00Z", "targets": ["file:///D:/e2e/demo/"],
                  "runs": [{"command": "part move", "arguments": ["--session", "s1"], "exit": 0, "result": "pass",
                            "mode": "session", "matrix_row": "normal"}]}
        record.update(changes)
        path = self.project / "docs" / "evidence" / name
        path.write_text(json.dumps(record), encoding="utf-8")
        return f"docs/evidence/{name}"

    def mature(self, level: str, evidence: list[str], row_evidence: str | None) -> None:
        """Mark part move at a maturity level, with its normal row run and the other rows not applying."""
        self.edit("demo_cli/commands/__init__.py", '"maturity": "draft", "evidence": []',
                  f'"maturity": "{level}" if path == "part move" else "draft", '
                  f'"evidence": {evidence!r} if path == "part move" else []')
        matrix = self.project / "tests" / "matrix" / "part-move.json"
        data = json.loads(matrix.read_text(encoding="utf-8"))
        if row_evidence:
            data["rows"][0].update(actual={"exit": 0}, evidence=row_evidence)
        matrix.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.fix()

    # -------------------------------------------------------------- instantiate

    def test_a_fresh_project_lacks_only_what_the_author_fills_in(self):
        found = self.problems(self.fresh)
        self.assertTrue(found)
        rest = [p.text() for p in found if p.clause != "DREPO-019"
                and not (p.clause == "DCLI-029" and p.path == "contract/commands.json")]
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
        self.authorize("file:///D:/e2e/demo/")
        self.record("2026-11-01-current.json")
        self.record("2026-10-01-old.json", tool_version="0.0.9", application={"name": "FakeApp", "version": "1.4.0"},
                    platform="linux")
        self.record("2026-10-02-failed.json", application={"name": "FakeApp", "version": "1.3.0"},
                    runs=[{"command": "part move", "arguments": [], "exit": 1, "result": "fail", "mode": "session"}])
        self.expect("DREPO-016")
        self.fix()
        matrix = (self.project / "docs" / "COMPATIBILITY.md").read_text(encoding="utf-8")
        self.assertIn("| 1.5 | Windows | session | ✅ verified |", matrix)
        self.assertIn("| >=1.0 <2 | Windows | file | ⏳ untested |", matrix)
        self.assertIn("| 1.3 | Windows | session | ⏳ untested |", matrix)
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
        self.authorize("file:///D:/e2e/demo/")
        self.record("2026-11-01-windows.json")
        self.fix()
        matrix = (self.project / "docs" / "COMPATIBILITY.md").read_text(encoding="utf-8")
        self.assertIn("| 1.5 | Windows | session | ⛔ unsupported |", matrix)
        self.assertNotIn("| ✅ verified |", matrix)

    def test_unauthorized_targets_in_records(self):
        self.record("2026-11-01-elsewhere.json", targets=["file:///C:/production/customer/"])
        self.expect("DVER-050")

    def test_malformed_records_are_reported_not_crashed_on(self):
        self.record("2026-11-01-odd.json", application="FakeApp", runs=["x"], platform=["windows"])
        self.fix()
        self.expect("DVER-042")

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
        self.assertIn("DREPO-060", found)

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
                                         "  commands: [part get, part move, part fly]\n---\n\nParts and their values.\n",
                                         encoding="utf-8")
        other = self.project / "skills" / "demo-boards"
        other.mkdir()
        (other / "SKILL.md").write_text("---\nname: demo-boards\ndescription: Boards. 电路板。\nmetadata:\n  version: 0.1.0\n"
                                        "  commands: [part get]\n---\n\nRead the demo-cli Skill first.\n",
                                        encoding="utf-8")
        found = self.clauses()
        self.assertTrue({"DSKL-024", "DSKL-026", "DSKL-027"} <= found, found)

    # -------------------------------------------------------------- knowledge

    def test_knowledge_rules(self):
        self.edit("knowledge/demo-troubleshooting.md", "kind: troubleshooting", "kind: guide")
        self.edit("knowledge/demo-troubleshooting.md", "id: demo-troubleshooting", "id: demo-basics")
        self.edit("knowledge/demo-basics.md", "tags: [basics]\n", "")
        self.edit("knowledge/demo-basics.md", "\n---\n", "\n---\n\nSee [the guide](missing.md).\n" + "word " * 1300)
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
        self.assertTrue(any("no readable file" in m for m in problems), problems)

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

    def test_verified_rests_on_a_passing_run_of_the_command(self):
        self.authorize("file:///D:/e2e/demo/")
        ref = self.record("2026-11-01-move.json")
        self.mature("verified", [f"live:{ref}"], f"live:{ref}#normal")
        self.assertEqual([p.text() for p in self.problems()], [])
        self.assertIn("maturity-draft", (self.project / "README.md").read_text(encoding="utf-8"))  # part get is draft

    def test_evidence_that_does_not_show_the_run(self):
        self.authorize("file:///D:/e2e/demo/")
        cases = {
            "foreign tool": self.record("2026-11-01-a.json", tool="other-cli"),
            "older minor": self.record("2026-11-01-b.json", tool_version="0.0.9"),
            "failed run": self.record("2026-11-01-c.json", runs=[{"command": "part move", "arguments": [], "exit": 1,
                                                                  "result": "fail", "mode": "session", "matrix_row": "normal"}]),
            "other command": self.record("2026-11-01-d.json", runs=[{"command": "part get", "arguments": [], "exit": 0,
                                                                     "result": "pass", "mode": "session", "matrix_row": "normal"}]),
        }
        stray = self.project / "tests" / "fixture.json"
        stray.write_text(json.dumps({"tool_version": "0.1.0"}), encoding="utf-8")
        cases["not a record"] = "tests/fixture.json"
        for what, ref in cases.items():
            with self.subTest(what=what):
                project = Path(tempfile.mkdtemp(prefix="evidence-", dir=self.work)) / "demo-cli"
                shutil.copytree(self.project, project)
                keep, self.project = self.project, project
                try:
                    self.mature("verified", [f"live:{ref}"], f"live:{ref}#normal")
                    self.expect("DVER-040")
                finally:
                    self.project = keep

    def test_rows_need_their_own_passing_runs(self):
        self.authorize("file:///D:/e2e/demo/")
        ref = self.record("2026-11-01-move.json")
        self.mature("verified", [f"live:{ref}"], None)
        self.expect("DVER-040")

    def test_the_normal_row_always_applies(self):
        self.edit("tests/matrix/part-get.json", '"row": "normal",\n      "applies": true,\n      "arguments": [\n        "--session",\n        "{session}",\n        "--doc",\n        "{doc}",\n        "--id",\n        "R1"\n      ],\n      "expected": {\n        "exit": 0\n      }',
                  '"row": "normal",\n      "applies": false,\n      "reason": "skipped"')
        self.expect("DVER-030")

    def test_a_row_cannot_apply_when_its_condition_does_not_hold(self):
        self.edit("tests/matrix/part-get.json", '"row": "conflict",\n      "applies": false,\n      "reason": "The demo tool drives no real application."',
                  '"row": "conflict",\n      "applies": true,\n      "arguments": [],\n      "expected": {"exit": 6, "code": "E_CONFLICT"}')
        problems = [p.message for p in self.problems() if p.clause == "DVER-030"]
        self.assertTrue(any("row conflict applies only when writes" in m for m in problems), problems)

    def question(self, name: str, scenario: str, commands: list[str]) -> None:
        folder = self.project / "tests" / "eval"
        folder.mkdir(parents=True, exist_ok=True)
        text = (f'"""A question."""\nSCENARIO = {scenario!r}\nCOMMANDS = {commands!r}\nTURNS = ["Do it."]\n\n\n'
                'def grade(run):\n    pass\n')
        (folder / f"{name}.py").write_text(text, encoding="utf-8")

    def report(self, name: str, **change) -> dict:
        """An evaluation report from the real application of every current question, all passed."""
        folder = self.project / "tests" / "eval"
        questions = []
        for path in sorted(folder.glob("*.py")):
            commands = ["part move"] if path.stem == "move-r1" else ["part get"]
            questions.append({"scenario": "scoped_change" if path.stem == "move-r1" else path.stem, "id": path.stem,
                              "passed": True, "sha256": check_project.digest(path), "commands": commands, "ran": commands})
        data = {"tool": "demo-cli", "tool_version": "0.1.0", "date": "2026-11-01", "agent": "a", "model": "m",
                "simulated": False, "platform": "windows", "targets": ["file:///D:/e2e/demo/eval/"], "questions": questions}
        data.update(change)
        (self.project / "docs" / "evidence" / name).write_text(json.dumps(data), encoding="utf-8")
        return data

    def test_stable_needs_an_evaluation(self):
        self.authorize("file:///D:/e2e/demo/")
        ref = self.record("2026-11-01-move.json")
        self.mature("stable", [f"live:{ref}", "eval:docs/evidence/eval-2026-11-01.json"], f"live:{ref}#normal")
        found = self.clauses()
        self.assertTrue({"DSKL-043", "DREPO-004", "DSKL-042"} <= found, found)
        self.question("move-r1", "scoped_change", ["part move"])
        for scenario in ("read_answer", "knowledge_lookup", "separate_save"):
            self.question(scenario, scenario, ["part get"])
        data = self.report("eval-2026-11-01.json")
        self.assertEqual([p.text() for p in self.problems()], [])
        moved = [dict(q, ran=[]) if q["id"] == "move-r1" else q for q in data["questions"]]
        cases = {"simulated": {"simulated": True},
                 "a question failed": {"questions": [dict(q, passed=q["id"] != "read_answer") for q in data["questions"]]},
                 "a question is missing": {"questions": [q for q in data["questions"] if q["id"] != "separate_save"]},
                 "a question changed since": {"questions": [dict(q, sha256="0" * 64) if q["id"] == "read_answer" else q
                                                            for q in data["questions"]]},
                 "the command never ran": {"questions": moved}}
        for what, change in cases.items():
            with self.subTest(what=what):
                self.report("eval-2026-11-01.json", **change)
                self.expect("DSKL-043")
        self.report("eval-2026-11-01.json")
        self.report("eval-2026-11-02.json", date="2026-11-02",
                    questions=[dict(q, passed=False) for q in data["questions"]])
        problems = [p.message for p in self.problems() if p.clause == "DSKL-043"]
        self.assertTrue(any("not the newest" in m for m in problems), problems)
        (self.project / "docs" / "evidence" / "eval-2026-11-02.json").unlink()
        self.report("eval-2026-11-01.json", targets=["file:///D:/elsewhere/"])
        self.expect("DVER-050")

    def test_question_files_are_checked(self):
        self.question("move-r1", "made_up", ["part move"])
        self.question("get-r1", "read_answer", ["part fly"])
        messages = [p.message for p in self.problems() if p.clause == "DSKL-044"]
        self.assertTrue(any("made_up" in m for m in messages), messages)
        self.assertTrue(any("`part fly`" in m for m in messages), messages)

    def test_corrupt_runtime_manifest(self):
        (self.project / "demo_cli" / "_driver" / "MANIFEST.json").write_text("garbage", encoding="utf-8")
        self.expect("DREPO-032")

    def test_a_second_copy_of_the_runtime(self):
        shutil.copyfile(self.project / "demo_cli" / "_driver" / "writes.py", self.project / "demo_cli" / "writes_copy.py")
        self.expect("DREPO-034")

    def test_junk_files_and_config_files_are_not_problems(self):
        for name in (".agent/.DS_Store", "licenses/Thumbs.db", "tox.ini", "requirements-docs.txt"):
            (self.project / name).write_text("x", encoding="utf-8")
        self.assertEqual([p.text() for p in self.problems()], [])
        (self.project / "Makefile").write_text("all:\n", encoding="utf-8")
        self.expect("DREPO-003")

    def test_install_scripts_and_platform_names(self):
        package = json.loads((self.project / "package.json").read_text(encoding="utf-8"))
        package["scripts"] = {"postinstall": "node x.js"}
        package["optionalDependencies"]["@tool-driver/demo-cli-win32-ia32"] = "0.1.0"
        (self.project / "package.json").write_text(json.dumps(package, indent=2), encoding="utf-8")
        found = self.clauses()
        self.assertTrue({"DSEC-072", "DREPO-051"} <= found, found)

    def test_hand_typed_labels(self):
        self.edit("README.md", "## About This Tool\n", "## About This Tool\n\nStatus: ✅ verified everywhere.\n")
        self.edit("README_zh.md", "## 关于本工具\n", '## 关于本工具\n\n<img src="https://img.shields.io/badge/production-ready-green">\n')
        found = self.clauses()
        self.assertTrue({"DREPO-022", "DREPO-024"} <= found, found)

    def test_one_line_pitch(self):
        self.edit("README.md", "Filled in by the author\n", "Filled in by the author\nAnd a second line.\n")
        self.expect("DREPO-011")

    def test_skill_details(self):
        skill = "skills/demo-cli/SKILL.md"
        (self.project / "skills" / "demo-cli" / "references").mkdir()
        (self.project / "skills" / "demo-cli" / "references" / "deep.md").write_text("x", encoding="utf-8")
        (self.project / "skills" / "stray.txt").write_text("x", encoding="utf-8")
        self.edit(skill, "### Scope refused", "### Physical effects\n\nx\n\n### Scope refused")
        text = (self.project / skill).read_text(encoding="utf-8")
        start = text.index("description:")
        end = text.index("metadata:")
        (self.project / skill).write_text(text[:start] + "description: English only, no other language.\n" + text[end:],
                                          encoding="utf-8")
        found = self.clauses()
        self.assertTrue({"DSKL-003", "DSKL-032", "DSKL-009", "DSKL-001"} <= found, found)

    def test_domain_skill_repeating_the_recipe(self):
        entry = (self.project / "skills" / "demo-cli" / "SKILL.md").read_text(encoding="utf-8")
        line = next(x for x in entry.split("\n") if x.startswith("2. When it returns"))
        folder = self.project / "skills" / "demo-part"
        folder.mkdir()
        (folder / "SKILL.md").write_text("---\nname: demo-part\ndescription: Parts. 零件。\nmetadata:\n  version: 0.1.0\n"
                                         f"  commands: [part move]\n---\n\nRead demo-cli first.\n\n{line}\n",
                                         encoding="utf-8")
        self.fix()
        self.expect("DSKL-023")

    def test_matrices_follow_the_implemented_capabilities(self):
        # The template's adapter implements only probe, so no standard command needs a matrix yet.
        self.assertFalse((self.project / "tests" / "matrix" / "doc-list.json").exists())
        self.edit("demo_cli/adapter/__init__.py", "        return {\"found\": False}",
                  "        return {\"found\": False}\n\n    def documents(self, request: dict[str, Any]) -> dict[str, Any]:\n"
                  "        return {\"items\": []}")
        messages = [p.message for p in self.problems() if p.clause == "DVER-030"]
        self.assertTrue(any("`doc list`" in m for m in messages), messages)

    def test_host_component_manifest(self):
        self.edit("demo_cli/__init__.py", "host_component=False,",
                  'host_component=True,\n    plugin_manifest=ROOT / "plugin" / "manifest.json",')
        (self.project / "plugin").mkdir(exist_ok=True)
        self.expect("DCLI-240")
        self.fix()
        manifest = json.loads((self.project / "plugin" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((manifest["version"], manifest["files"], manifest["methods"]), ("0.1.0", {}, []))
        manifest["methods"] = ["read", "apply"]
        (self.project / "plugin" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (self.project / "plugin" / "host.py").write_text("print('host')\n", encoding="utf-8")
        self.expect("DCLI-240")
        self.fix()
        manifest = json.loads((self.project / "plugin" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["methods"], ["read", "apply"])
        self.assertEqual(manifest["files"], {"host.py": check_project.digest(self.project / "plugin" / "host.py")})
        self.assertNotIn("DCLI-240", self.clauses())

    def test_rename_stubs(self):
        folder = self.project / "skills" / "demo-part"
        folder.mkdir()
        stub = ("---\nname: demo-part\ndescription: Renamed; read demo-cli. 已改名，请读 demo-cli。\nmetadata:\n"
                "  version: 0.1.0\n  replaced_by: demo-cli\n---\n\n# demo-part\n\nThis Skill was merged into `demo-cli`; read it instead.\n\n"
                "<!-- driver:command-map:start -->\n<!-- driver:command-map:end -->\n")
        (folder / "SKILL.md").write_text(stub, encoding="utf-8")
        self.fix()
        self.assertEqual([p.text() for p in self.problems() if p.path.startswith("skills/")], [])
        (folder / "SKILL.md").write_text(stub.replace("replaced_by: demo-cli", "replaced_by: demo-gone"), encoding="utf-8")
        self.expect("DSKL-028")
        # A full domain Skill that forgets its commands is not a stub.
        (folder / "SKILL.md").write_text(stub.replace("  replaced_by: demo-cli\n", ""), encoding="utf-8")
        self.expect("DSKL-026")

    def test_related_knowledge_must_exist(self):
        self.edit("demo_cli/commands/__init__.py", '"related_knowledge": []', '"related_knowledge": ["no-such-entry"]')
        self.fix()
        self.expect("DSKL-124")

    def test_runtime_parser_reads_knowledge(self):
        self.edit("knowledge/demo-basics.md", "\nkind: guide", "\n# a comment\nkind: guide")
        self.assertEqual([p.text() for p in self.problems()], [])
        self.edit("knowledge/demo-basics.md", "\ntags: [basics]", "\ntags:")
        self.expect("DSKL-120")

    def test_evidence_records_validate(self):
        (self.project / "docs" / "evidence" / "2026-11-01-bad.json").write_text(json.dumps({"kind": "live"}), encoding="utf-8")
        self.expect("DVER-042")

    # -------------------------------------------------------------- run_matrix

    def git(self) -> None:
        for args in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "x"]):
            subprocess.run(["git", *args], cwd=self.project, check=True, capture_output=True, creationflags=NO_WINDOW)

    def test_run_matrix_runs_only_on_authorized_targets(self):
        target = self.work / "authorized"
        target.mkdir(exist_ok=True)
        (target / "board.fake").write_text("x", encoding="utf-8")
        argv = [str(self.project), "--command", "part get", "--row", "normal", "--set", f"doc={target / 'board.fake'}",
                "--set", "session=s1", "--application-version", "1.5.0"]
        with self.assertRaises(SystemExit):
            run_matrix.main(argv)  # not a git checkout: the record could not name the build
        self.git()
        with self.assertRaises(SystemExit):
            run_matrix.main(argv)  # no authorized target
        url = target.resolve().as_uri() + "/"
        self.authorize(url)
        self.edit("tests/matrix/part-move.json", '"{doc}"', '"C:/production/customer.fake"')
        with self.assertRaises(SystemExit):
            run_matrix.main([*argv[:2], "part move", *argv[3:]])  # a target written into the row
        with mock.patch.dict(os.environ, {"DEMO_CLI_FAKE_HOST": "nowhere"}):
            code = run_matrix.main(argv)
        self.assertEqual(code, 1)  # the demo adapter drives no application, so the row fails
        records = list((self.project / "docs" / "evidence").glob("*-part-get.json"))
        self.assertEqual(len(records), 1)
        record = json.loads(records[0].read_text(encoding="utf-8"))
        self.assertEqual((record["targets"], record["runs"][0]["mode"]), ([url], "session"))
        row = json.loads((self.project / "tests" / "matrix" / "part-get.json").read_text(encoding="utf-8"))["rows"][0]
        self.assertTrue(row["evidence"].startswith("live:docs/evidence/"))
        for written in (records[0], self.project / "tests" / "matrix" / "part-get.json"):
            self.assertNotIn(b"\r\n", written.read_bytes(), written.name)  # LF, like every file in the repository
        self.fix()
        problems = [p.message for p in self.problems() if p.clause == "DVER-030"]
        self.assertTrue(any("row normal failed" in m for m in problems), problems)

    def test_covered(self):
        base = self.work / "e2e"
        targets = [(base / "demo").resolve().as_uri() + "/", (base / "one.fake").resolve().as_uri(), "device:cnc-01"]
        target = run_matrix.target_of
        self.assertEqual(run_matrix.covered(target("doc", str(base / "demo" / "sub" / "board.fake")), targets), targets[0])
        self.assertEqual(run_matrix.covered(target("doc", str(base / "one.fake")), targets), targets[1])
        self.assertIsNone(run_matrix.covered(target("doc", str(base / "demo2" / "board.fake")), targets))
        self.assertEqual(run_matrix.covered(target("device", "cnc-01"), targets), "device:cnc-01")
        self.assertIsNone(run_matrix.covered(target("device", "cnc-02"), targets))

    def test_run_matrix_masks_secrets_and_never_passes_simulated_results(self):
        self.assertTrue(run_matrix.simulated({"data": {"receipt": {"simulated": True}}}))
        self.assertEqual(run_matrix.pairs(["--token=abc", "--id", "R1", "--dry-run"]), [("--token", "abc"), ("--id", "R1")])


class RunMatrixTest(unittest.TestCase):
    def tmp(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="run-matrix-"))
        self.addCleanup(shutil.rmtree, path, True)
        return path

    def test_a_call_that_does_not_answer_ends_with_every_process_it_started(self):
        # The child starts a grandchild that holds the output pipe and outlives the child.
        child = ("import os, subprocess, sys, time\n"
                 "flags = 0x08000000 if os.name == 'nt' else 0\n"
                 "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(90)'], creationflags=flags)\n"
                 "time.sleep(90)\n")
        notes: list[str] = []
        started = time.monotonic()
        code, _ = run_matrix._run([sys.executable, "-c", child], self.tmp(), dict(os.environ), notes, timeout=3)
        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual((code, notes), (-1, ["no answer within 3 s"]))

    def test_files_a_command_only_reads_from_tests_inputs_are_not_targets(self):
        root = self.tmp()
        inputs = root / "tests" / "inputs"
        authorized = [(root / "authorized").resolve().as_uri() + "/"]
        command = {"path": "design import", "effects": ["change"],
                   "flags": [{"name": "--from", "type": "path"}, {"name": "--to", "type": "path", "output": True}]}
        run_matrix._check_row("normal", command, ["--from", str(inputs / "design.json")], authorized, inputs)
        run_matrix._check_row("normal", command, ["--to", str(root / "authorized" / "out.json")], authorized, inputs)
        for arguments in (["--from", str(root / "elsewhere" / "design.json")],  # read, but not from tests/inputs
                          ["--to", str(inputs / "out.json")],                   # written
                          ["--doc", str(inputs / "board.fake")]):               # the document a write changes
            with self.assertRaises(SystemExit):
                run_matrix._check_row("normal", command, arguments, authorized, inputs)
        observe = {**command, "effects": ["observe"]}
        run_matrix._check_row("normal", observe, ["--doc", str(inputs / "board.fake")], authorized, inputs)
        with self.assertRaises(SystemExit):
            run_matrix._check_row("normal", observe, ["--job", "{job}"], authorized, inputs)
        run_matrix._check_row("normal", observe, ["--job", "{job}"], authorized, inputs, job_pending=True)

    def test_job_comes_from_the_normal_row_of_a_long_command(self):
        root = self.tmp()
        (root / "tests" / "matrix").mkdir(parents=True)
        row = {"row": "normal", "applies": True, "arguments": ["--session", "{session}"]}
        (root / "tests" / "matrix" / "route-run.json").write_text(json.dumps({"command": "route run", "rows": [row]}), encoding="utf-8")
        facts = SimpleNamespace(commands=[{"path": "route run", "long": True, "effects": ["change"], "flags": []},
                                          {"path": "job get", "effects": ["observe"], "flags": []}])
        values = {"session": "s1", "inputs": str(root / "tests" / "inputs")}
        self.assertEqual(run_matrix._job_starter(root, facts, None, values, []), ("route run", ["--session", "s1"]))
        self.assertEqual(run_matrix._job_starter(root, facts, "route run", values, []), ("route run", ["--session", "s1"]))
        with self.assertRaises(SystemExit):
            run_matrix._job_starter(root, facts, "job get", values, [])  # not a long command
        facts.commands.append({"path": "design check", "long": True, "effects": ["observe"], "flags": []})
        with self.assertRaises(SystemExit):
            run_matrix._job_starter(root, facts, None, values, [])  # two long commands: name one


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
