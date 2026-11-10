"""Tests that keep the development Skill skills/build-driver-cli honest (DREPO-062).

The Skill ships in the release bundle. It must follow the Skill rules a driver tool follows
(DSKL-001 to DSKL-003), carry the specification's version, and cite only clauses and
project script actions that exist.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from check_project import front_matter  # noqa: E402

SKILL = ROOT / "skills" / "build-driver-cli"
CLAUSE = re.compile(r"\b(?:DCLI|DSEC|DSKL|DVER|DREPO)-\d{3}\b")
HEADING = re.compile(r"^### ((?:DCLI|DSEC|DSKL|DVER|DREPO)-\d{3}) ", re.MULTILINE)
SPEC_ACTION = re.compile(r"scripts/spec\.py ([a-z]+)\b")
CJK = re.compile(r"[一-鿿]")
LATIN = re.compile(r"[A-Za-z]{3,}")


def skill_files() -> list[Path]:
    return [SKILL / "SKILL.md", *sorted((SKILL / "references").glob("*.md"))]


class BuildSkillTest(unittest.TestCase):
    def setUp(self):
        self.text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.front, _, _ = front_matter(self.text)

    def test_front_matter(self):
        self.assertEqual(self.front.get("name"), "build-driver-cli")
        description = str(self.front.get("description", ""))
        self.assertTrue(description, "the description is missing")
        self.assertRegex(description, CJK, "the description needs Chinese text")
        self.assertRegex(description, LATIN, "the description needs English text")
        metadata = self.front.get("metadata")
        self.assertIsInstance(metadata, dict, "metadata is missing")
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(str(metadata.get("version")), version, "metadata.version must equal VERSION")

    def test_length(self):
        lines = self.text.rstrip("\n").split("\n")
        self.assertLessEqual(len(lines), 150, "SKILL.md is longer than 150 lines")

    def test_references_one_level_and_linked(self):
        folder = SKILL / "references"
        self.assertTrue(folder.is_dir(), "references/ is missing")
        items = sorted(folder.iterdir())
        self.assertTrue(items, "references/ is empty")
        for item in items:
            self.assertFalse(item.is_dir(), f"references/ has a subdirectory: {item.name}")
            self.assertIn(f"](references/{item.name})", self.text, f"SKILL.md does not link references/{item.name}")
        self.assertEqual({p.name for p in SKILL.iterdir()} - {"SKILL.md", "references"}, set(),
                         "a Skill directory holds only SKILL.md and references/")

    def test_cited_clauses_exist(self):
        known = set()
        for spec in (ROOT / "spec").glob("*.md"):
            known.update(HEADING.findall(spec.read_text(encoding="utf-8")))
        self.assertTrue(known)
        for path in skill_files():
            cited = set(CLAUSE.findall(path.read_text(encoding="utf-8")))
            self.assertEqual(sorted(cited - known), [], f"{path.relative_to(ROOT).as_posix()} cites clauses that do not exist")

    def test_spec_actions_exist(self):
        source = (ROOT / "template" / "scripts" / "spec.py").read_text(encoding="utf-8")
        match = re.search(r"argv\[0\] not in \(([^)]*)\)", source)
        self.assertIsNotNone(match, "cannot find the actions template/scripts/spec.py accepts")
        accepted = set(re.findall(r'"([a-z]+)"', match.group(1)))
        self.assertIn("check", accepted)
        shown = set()
        for path in skill_files():
            used = set(SPEC_ACTION.findall(path.read_text(encoding="utf-8")))
            self.assertEqual(sorted(used - accepted), [], f"{path.relative_to(ROOT).as_posix()} shows unknown spec.py actions")
            shown |= used
        self.assertTrue({"check", "suites"} <= shown, "the review runs check and suites")


if __name__ == "__main__":
    unittest.main()
