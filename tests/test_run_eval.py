"""Tests for scripts/run_eval.py, the evaluation runner, against the sample tool and the fake host."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_project  # noqa: E402
import run_eval  # noqa: E402

SAMPLE = ROOT / "tests" / "sample"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

QUESTION = '''
"""Read the value of R1."""

SCENARIO = "read_answer"
COMMANDS = ["part get"]
TURNS = ["What value does R1 on board.fake have?"]
FAKE_HOST = {"files": [], "instances": [{"id": "fake-1", "documents": [
    {"id": "doc-1", "name": "board.fake", "objects": {"R1": {"value": "10k"}}}]}]}


def grade(run):
    run.check(run.said("10k"), "the answer does not give 10k")
    run.check(not run.write_calls(), "a write command ran")


def right(agent, turn):
    value = agent.run("part", "get", "--doc", "doc-1", "--id", "R1").data["items"][0]["value"]
    agent.say(f"R1 has the value {value}.")


def wrong(agent, turn):
    agent.say("R1 has the value 4k7.")
'''


def sample_facts() -> check_project.Facts:
    """What run_eval needs to know about the sample tool, read the way the suites read it."""
    facts = check_project.Facts(root=SAMPLE, contract=check_project.load_contract())
    facts.tool, facts.pkg, facts.prefix, facts.version = "sample-cli", "sample_cli", "SAMPLE_CLI", "0.1.0"
    facts.registration = json.loads((SAMPLE / "contract" / "commands.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "reference.json"
        env = {**os.environ, "SAMPLE_CLI_STATE_DIR": str(Path(tmp) / "state"), "PYTHONPATH": str(SAMPLE)}
        subprocess.run([sys.executable, "-m", "sample_cli", "reference", "--all", "--output", str(out)], cwd=tmp, env=env,
                       capture_output=True, check=True, timeout=120, creationflags=NO_WINDOW)
        facts.reference = json.loads(out.read_text(encoding="utf-8"))
    return facts


class QuestionFormatTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="eval-q-"))
        self.contract = check_project.load_contract()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def facts_of(self, name: str, text: str):
        path = self.tmp / name
        path.write_text(textwrap.dedent(text), encoding="utf-8")
        return check_project.question_facts(path, self.contract)

    def test_a_well_formed_question(self):
        values, functions, problems = self.facts_of("read_r1.py", QUESTION)
        self.assertEqual(problems, [])
        self.assertEqual(values["SCENARIO"], "read_answer")
        self.assertEqual({"grade", "right", "wrong"}, functions)

    def test_what_a_question_must_define(self):
        _, _, problems = self.facts_of("empty.py", "X = 1\n")
        for name in ("SCENARIO", "COMMANDS", "TURNS", "grade"):
            self.assertTrue(any(name in p for p in problems), (name, problems))

    def test_values_are_literals_and_well_typed(self):
        _, _, problems = self.facts_of("bad.py", """
            SCENARIO = "made_up"
            COMMANDS = "part get"
            TURNS = [""]
            SCOPE = ["change"]
            FAKE_HOST = FACTORY()
            FILES = "missing"
            def grade(run): pass
            """)
        text = " ".join(problems)
        for part in ("SCENARIO 'made_up'", "COMMANDS is a list", "TURNS is a list", "SCOPE is an object",
                     "FAKE_HOST must be a literal", "FILES names a folder"):
            self.assertIn(part, text)

    def test_fake_host_none_marks_a_question_for_the_real_application(self):
        _, _, problems = self.facts_of("real_only.py", QUESTION.replace("FAKE_HOST =", "FAKE_HOST = None\nIGNORED ="))
        self.assertEqual(problems, [])
        _, _, problems = self.facts_of("wrong.py", QUESTION.replace("FAKE_HOST =", 'FAKE_HOST = "real"\nIGNORED ='))
        self.assertTrue(any("FAKE_HOST is an object" in p for p in problems), problems)

    def test_the_file_name_is_the_question_id(self):
        _, _, problems = self.facts_of("Read-R1.py", QUESTION)
        self.assertTrue(any("file name" in p for p in problems), problems)

    def test_an_unreadable_question(self):
        _, _, problems = self.facts_of("broken.py", "def (:\n")
        self.assertTrue(problems and "cannot read" in problems[0], problems)


class CallTest(unittest.TestCase):
    def call(self, *args: str, stdout: str = "{}") -> run_eval.Call:
        return run_eval.Call({"tool": "sample-cli", "turn": 0, "args": list(args), "exit": 0, "stdout": stdout,
                              "stderr": "", "started": 1})

    def test_command_flags_and_lines(self):
        call = self.call("operation", "resolve", "--id", "op_1", "--wait=5s")
        self.assertEqual(call.command, "operation resolve")
        self.assertEqual(call.value("--id"), "op_1")
        self.assertEqual(call.value("--wait"), "5s")
        self.assertTrue(call.matches("sample-cli operation resolve --id op_1 --wait=5s"))
        self.assertFalse(call.matches("sample-cli operation resolve --id op_2 --wait=5s"))
        self.assertFalse(call.matches("other-cli operation resolve --id op_1 --wait=5s"))

    def test_the_envelope(self):
        call = self.call("part", "move", stdout=json.dumps({"ok": False, "error": {"code": "E_BUSY", "details": {"retry_after_ms": 5}}}))
        self.assertFalse(call.ok)
        self.assertEqual(call.code, "E_BUSY")
        self.assertEqual(call.details, {"retry_after_ms": 5})
        self.assertIsNone(self.call("x", stdout="not json").envelope)


class AuthorizeTest(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp(prefix="eval-auth-"))
        (self.project / "docs").mkdir()
        self.question = type("Q", (), {"id": "q", "scope": {"targets": ["{documents}", "device:cnc-01"]}})()

    def tearDown(self):
        shutil.rmtree(self.project, ignore_errors=True)

    def targets(self, *keys: str) -> None:
        lines = "\n".join(f"- `{k}`" for k in keys)
        (self.project / "docs" / "E2E.md").write_text(f"# E2E\n\n## Authorized Targets\n\n{lines}\n\n## Procedure\n", encoding="utf-8")

    def test_nothing_runs_without_authorized_targets(self):
        with self.assertRaisesRegex(run_eval.EvalError, "no Authorized Targets"):
            run_eval.authorize(self.project, [self.question], self.project / "ws")

    def test_a_root_with_spaces_and_chinese(self):
        root = self.project / "My Evals" / "评测"
        self.targets(run_eval.file_key(root.resolve()) + "/", "device:cnc-01")
        run_eval.authorize(self.project, [self.question], root)

    def test_the_workspace_root_and_every_scope_target_need_authorization(self):
        root = self.project / "ws"
        self.targets("device:cnc-01")
        with self.assertRaisesRegex(run_eval.EvalError, "--workspace-root"):
            run_eval.authorize(self.project, [self.question], None)
        with self.assertRaisesRegex(run_eval.EvalError, "workspace root"):
            run_eval.authorize(self.project, [self.question], root)
        self.targets(run_eval.file_key(root.resolve()) + "/")
        with self.assertRaisesRegex(run_eval.EvalError, "device:cnc-01"):
            run_eval.authorize(self.project, [self.question], root)
        self.targets(run_eval.file_key(root.resolve()) + "/", "device:cnc-01")
        run_eval.authorize(self.project, [self.question], root)


class RunTest(unittest.TestCase):
    """Whole runs against the sample tool and the fake host."""

    @classmethod
    def setUpClass(cls):
        cls.facts = sample_facts()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="eval-run-"))
        self.questions = self.tmp / "questions"
        self.questions.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def load(self, **files: str) -> list[run_eval.Question]:
        for name, text in files.items():
            (self.questions / f"{name}.py").write_text(text, encoding="utf-8")
        return run_eval.load_questions(self.questions, self.facts.contract, None)

    def test_graders_tell_right_from_wrong(self):
        questions = self.load(read_r1=QUESTION)
        self.assertEqual(run_eval.check_graders(SAMPLE, self.facts, questions, True, self.tmp, False), 0)

    def test_a_grader_that_misses_the_mistake(self):
        weak = QUESTION.replace('run.check(run.said("10k"), "the answer does not give 10k")', "pass")
        questions = self.load(weak=weak)
        self.assertEqual(run_eval.check_graders(SAMPLE, self.facts, questions, True, self.tmp, False), 1)

    def test_check_needs_both_scripted_agents(self):
        questions = self.load(no_wrong=QUESTION.split("def wrong")[0])
        self.assertEqual(run_eval.check_graders(SAMPLE, self.facts, questions, True, self.tmp, False), 1)

    def test_the_workspace_scope_and_recorded_calls(self):
        question = QUESTION.replace("FAKE_HOST =", 'SCOPE = {"effects": ["persist"]}\nFAKE_HOST =')
        question += textwrap.dedent('''
            def wrong_scope(agent, turn):
                (agent.workspace / "scope.json").write_text("{}", encoding="utf-8")
                agent.say("R1 has the value 10k.")
            ''')
        question = question.replace('run.check(not run.write_calls(), "a write command ran")',
                                    'run.check(not run.write_calls(), "a write command ran")\n'
                                    '    run.check(not run.scope_changed(), "the scope file changed")\n'
                                    '    run.check(all(c.turn == 0 for c in run.calls), "a call outside the turn")')
        [loaded] = self.load(scoped=question)
        session = run_eval.Session(SAMPLE, self.facts, loaded, True, self.tmp, False)
        try:
            scope = json.loads(session.scope_file.read_text(encoding="utf-8"))
            self.assertEqual(scope["effects"], ["persist"])
            self.assertEqual(scope["targets"][0], run_eval.file_key(session.documents) + "/")
            self.assertTrue((session.workspace / ".claude" / "skills" / "sample-cli" / "SKILL.md").is_file())
            self.assertTrue((session.tmp / "home" / ".agents" / "skills" / "sample-cli" / "SKILL.md").is_file())
            self.assertFalse(session.documents.is_relative_to(session.workspace))
        finally:
            session.close()
        self.assertEqual(run_eval.check_graders(SAMPLE, self.facts, [loaded], True, self.tmp, False), 0)

    def test_a_question_only_for_the_real_application_is_skipped_on_the_fake_host(self):
        questions = self.load(real_only=QUESTION.replace("FAKE_HOST =", "FAKE_HOST = None\nIGNORED ="), read_r1=QUESTION)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            kept = run_eval.on_fake_host(questions)
        self.assertEqual([q.id for q in kept], ["read_r1"])
        self.assertIn("SKIP real_only", out.getvalue())

    def test_the_agent_loads_only_the_tool_s_skills(self):
        self.assertEqual(run_eval.claude_skills(SAMPLE), ["Skill(sample-cli)", "Skill(sample-cli *)"])
        self.assertNotIn("Skill", run_eval.CLAUDE_TOOLS)
        home = self.tmp / "claude"
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(home)}):
            self.assertEqual(run_eval.shadowing_skills(SAMPLE, self.facts, False), [])
            shutil.copytree(SAMPLE / "skills" / "sample-cli", home / "skills" / "sample-cli")
            self.assertEqual(run_eval.shadowing_skills(SAMPLE, self.facts, False), [])  # the same copy changes nothing
            with open(home / "skills" / "sample-cli" / "SKILL.md", "a", encoding="utf-8") as handle:
                handle.write("\nAn older version.\n")
            [(path, why)] = run_eval.shadowing_skills(SAMPLE, self.facts, False)
            self.assertEqual(path, home / "skills" / "sample-cli")
            self.assertIn("in place of", why)

    def test_on_the_real_application_every_skill_folder_doctor_reads_counts(self):
        person = self.tmp / "person"
        old = person / ".agents" / "skills" / "sample-cli"
        shutil.copytree(SAMPLE / "skills" / "sample-cli", old)
        text = (old / "SKILL.md").read_text(encoding="utf-8")
        (old / "SKILL.md").write_text(text + "\nSame version, other words.\n", encoding="utf-8")
        env = {"CLAUDE_CONFIG_DIR": str(self.tmp / "claude"), "HOME": str(person), "USERPROFILE": str(person)}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(run_eval.shadowing_skills(SAMPLE, self.facts, True), [])  # doctor reads only the version
            (old / "SKILL.md").write_text(text.replace("version: 0.1.0", "version: 0.0.9"), encoding="utf-8")
            self.assertEqual(run_eval.shadowing_skills(SAMPLE, self.facts, False), [])  # the fake host gives the tool a home
            [(path, why)] = run_eval.shadowing_skills(SAMPLE, self.facts, True)
            self.assertEqual(path, old)
            self.assertIn("version 0.0.9", why)
            self.assertIn("update", why)

    def test_no_scope_file(self):
        [loaded] = self.load(unscoped=QUESTION.replace("FAKE_HOST =", "SCOPE = None\nFAKE_HOST ="))
        session = run_eval.Session(SAMPLE, self.facts, loaded, True, self.tmp, False)
        try:
            self.assertFalse(session.scope_file.exists())
            self.assertFalse(run_eval.Run(session).scope_changed())
        finally:
            session.close()

    def test_the_report(self):
        [loaded] = self.load(read_r1=QUESTION)

        class Stub:
            name, models, requested = "Stub Agent 1.0", ["stub-model"], None

            def fresh(self):
                return run_eval.ScriptedAgent(loaded.right)

        report = self.tmp / "eval-report.json"
        code = run_eval.evaluate(SAMPLE, self.facts, [loaded], Stub(), True, self.tmp, False, report)
        self.assertEqual(code, 0)
        data = json.loads(report.read_text(encoding="utf-8"))
        checker = check_project.Checker(self.facts)
        self.assertEqual(checker.validate(data, "eval-report.schema.json"), [])
        self.assertEqual((data["agent"], data["model"], data["simulated"]), ("Stub Agent 1.0", "stub-model", True))
        self.assertEqual(data["questions"], [{"scenario": "read_answer", "id": "read_r1", "passed": True,
                                              "notes": "Read the value of R1.", "sha256": loaded.sha256,
                                              "commands": ["part get"], "ran": ["part get"]}])
        self.assertEqual(loaded.sha256, check_project.digest(self.questions / "read_r1.py"))

    def test_a_question_whose_right_answer_fails_stops_the_run_before_the_agent(self):
        # The question's own data is wrong: the grader wants 10k, the document holds 1k.
        self.load(read_r1=QUESTION, mismatched=QUESTION.replace('{"value": "10k"}', '{"value": "1k"}'))
        asked: list = []
        env = {"CLAUDE_CONFIG_DIR": str(self.tmp / "claude-home")}
        with mock.patch.dict(os.environ, env), mock.patch.object(run_eval, "ClaudeAgent", side_effect=asked.append), \
                mock.patch.object(run_eval.check_project, "gather", return_value=self.facts), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            code = run_eval.main([str(SAMPLE), "--fake-host", "--questions", str(self.questions),
                                  "--workspace-root", str(self.tmp / "work")])
        self.assertEqual(code, 2, err.getvalue())
        self.assertIn("mismatched (the answer does not give 10k)", err.getvalue())
        self.assertNotIn("read_r1", err.getvalue())
        self.assertEqual(asked, [], "the Agent was started")

    def test_a_question_only_for_the_real_application_checks_its_right_answer_there_first(self):
        questions = self.load(real_only=QUESTION.replace("FAKE_HOST =", "FAKE_HOST = None\nIGNORED ="), read_r1=QUESTION)
        ran = []

        def attempt(project, facts, question, agent, fake_host, root, keep):
            ran.append((question.id, fake_host, root))
            return (["the answer does not give 10k"] if question.id == "real_only" else []), None, None

        with mock.patch.object(run_eval, "attempt", side_effect=attempt):
            broken = run_eval.broken_questions(SAMPLE, self.facts, questions, False, self.tmp)
        self.assertEqual(ran, [("read_r1", True, None), ("real_only", False, self.tmp)])
        self.assertEqual(broken, ["real_only (the answer does not give 10k)"])

    def test_a_broken_scripted_agent_fails_the_check(self):
        broken = QUESTION.replace('agent.say("R1 has the value 4k7.")', 'raise KeyError("confirm_token")')
        questions = self.load(broken=broken)
        self.assertEqual(run_eval.check_graders(SAMPLE, self.facts, questions, True, self.tmp, False), 1)

    def test_after_runs_even_when_the_grader_fails(self):
        marker = self.tmp / "after-ran"
        question = QUESTION.replace("def right(agent, turn):", textwrap.dedent(f'''
            def after(run):
                open({str(marker)!r}, "w").close()


            def right(agent, turn):''').lstrip("\n"))
        [loaded] = self.load(cleanup=question)
        problems, error, _ = run_eval.attempt(SAMPLE, self.facts, loaded, run_eval.ScriptedAgent(loaded.wrong[0][1]), True,
                                               self.tmp, False)
        self.assertTrue(problems and error is None, (problems, error))
        self.assertTrue(marker.exists())

    def test_the_default_scope_follows_the_commands(self):
        writes = QUESTION.replace('COMMANDS = ["part get"]', 'COMMANDS = ["part get", "part delete"]')
        loaded = {q.id: q for q in self.load(reads=QUESTION, deletes=writes)}
        reads, deletes = loaded["reads"], loaded["deletes"]
        session = run_eval.Session(SAMPLE, self.facts, reads, True, self.tmp, False)
        try:
            self.assertFalse(session.scope_file.exists())
        finally:
            session.close()
        session = run_eval.Session(SAMPLE, self.facts, deletes, False, self.tmp, False)
        try:
            scope = json.loads(session.scope_file.read_text(encoding="utf-8"))
            self.assertEqual((scope["effects"], scope["dangerous"]), (["change"], True))
            self.assertEqual(scope["targets"], [run_eval.file_key(session.documents) + "/"])
            self.assertEqual(session.targets(), ["{documents}"])
        finally:
            session.close()

    def test_hooks_are_not_held_by_the_question_scope(self):
        # A read-only question has no scope file, yet its hook may open the document it reads.
        question = QUESTION.replace(
            'FAKE_HOST = {"files": [], "instances": [{"id": "fake-1", "documents": [\n'
            '    {"id": "doc-1", "name": "board.fake", "objects": {"R1": {"value": "10k"}}}]}]}',
            'FAKE_HOST = {"instances": [{"id": "fake-1", "documents": []}],\n'
            '             "files": [{"id": "doc-1", "name": "board.fake", "objects": {"R1": {"value": "10k"}}}]}\n\n\n'
            'def before(run, turn):\n'
            '    out = run.tool("doc", "open", "--session", "fake-1", "--doc", str(run.documents / "board.fake"))\n'
            '    run.check(out["ok"], f"the hook could not open the board: {out}")\n')
        question = question.replace('"--doc", "doc-1"', '"--session", "fake-1", "--doc", str(agent.documents / "board.fake")')
        self.assertIn("def before", question)
        [loaded] = self.load(opened=question)
        problems, error, _ = run_eval.attempt(SAMPLE, self.facts, loaded, run_eval.ScriptedAgent(loaded.right), True,
                                               self.tmp, False)
        self.assertEqual((problems, error), ([], None))

    def test_a_question_that_needs_the_fake_host_fails_alone_on_the_real_application(self):
        question = QUESTION.replace('run.check(not run.write_calls(), "a write command ran")',
                                    'run.check(not run.applied(), "a change arrived")')
        [loaded] = self.load(needs_host=question)
        problems, error, _ = run_eval.attempt(SAMPLE, self.facts, loaded, run_eval.ScriptedAgent(lambda agent, turn: None),
                                               False, self.tmp, False)
        self.assertIn("only with --fake-host", error or "")

    def test_report_names_do_not_overwrite(self):
        folder = self.tmp / "docs" / "evidence"
        first = run_eval.default_report(self.tmp)
        folder.mkdir(parents=True)
        first.write_text("{}", encoding="utf-8")
        self.assertNotEqual(run_eval.default_report(self.tmp), first)


class ReportWords(unittest.TestCase):
    """The worked examples judge a report by meaning: read-back agreement says verified too."""

    def test_verified_in_the_agent_s_own_words(self):
        sys.path.insert(0, str(ROOT / "conformance" / "eval"))
        from _report import says_verified

        for text in ["- **Verified:** Yes, read-back matched.", "Each step's read-back matched the requested values.",
                     "Read-back confirmed all three changes.", "Each change was checked against the board after it ran.",
                     "I read back the values and they match.", "已验证：读回一致。", "读回的数值与要求相符。",
                     "The move is verified by read-back. Not saved: you have not confirmed a save.",
                     "Verified. The DRC has not been checked.", "- Read-back matched\n- Saved: no, I did not save it",
                     "| Verified | Yes, read-back matched |", "Verified with no differences.", "已验证，没有问题。"]:
            self.assertTrue(says_verified(text), text)
        for text in ["Done, R1 is at x 12.5 mm.", "Verified: no, the change waits for a save.", "The change is not verified yet.",
                     "Read-back did not match: R1 is at 12.4 mm.", "The value could not be read back.", "未验证，等保存后再验证。",
                     "读回不一致。", "It has not been checked.", "The read-back showed a mismatch on R5.",
                     "The read-back shows the old value.", "Read-back matched neither the old nor the new value.",
                     "Read-back: no match.", "The read-back was not a match.", "The read-back isn't confirmed.", "I could not verify it.",
                     "Verification failed.", "验证失败。", "未能验证。", "无法核实。", "| Verified | No — waits for the save |",
                     "Verification is deferred until the save."]:
            self.assertFalse(says_verified(text), text)


if __name__ == "__main__":
    unittest.main()
