"""Tests for scripts/check_spec.py."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_spec as cs  # noqa: E402

CONTRACT = json.loads((ROOT / "contract" / "driver-contract.json").read_text(encoding="utf-8"))
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
DSEC = next(d for d in CONTRACT["spec_documents"] if d["prefix"] == "DSEC")

EN = f"""# DRIVER-SEC-SPEC

English | [中文](DRIVER-SEC-SPEC_zh.md)

> Version {VERSION} · Clauses DSEC-001 to DSEC-002

## How to Read

Text.

## Scope

Text.

## Terms

Text.

## Runtime and Tool Responsibilities

| Area | Runtime | Tool |
|---|---|---|
| a | b | c |

## Risk Tiers

### DSEC-001 Risk tiers

Each command MUST have a tier.

<!-- contract:risk_tiers -->
| Tier | Meaning |
|---|---|
| `T0` | read only |
| `T1` | local change |
| `T2` | environment |

Why: People need to see the risk.
Check: 🤖 R02.

### DSEC-002 Tool risk tier

The README MUST show the tool's tier.

Why: People need to see the risk.
Check: 👀 Review.

## Checklist

- [ ] DSEC-001 Risk tiers
- [ ] DSEC-002 Tool risk tier
"""

REPLACE_ZH = [
    ("English | [中文](DRIVER-SEC-SPEC_zh.md)", "[English](DRIVER-SEC-SPEC.md) | 中文"),
    (f"> Version {VERSION} · Clauses DSEC-001 to DSEC-002", f"> 版本 {VERSION} · 条款 DSEC-001 至 DSEC-002"),
    ("## How to Read", "## 怎么读"),
    ("## Scope", "## 适用范围"),
    ("## Terms", "## 术语"),
    ("## Runtime and Tool Responsibilities", "## 运行时与工具的分工"),
    ("## Risk Tiers", "## 风险等级"),
    ("## Checklist", "## 检查清单"),
    ("MUST have", "必须有"),
    ("MUST show", "必须显示"),
    ("Why: ", "为什么："),
    ("Check: ", "检查："),
]


def to_zh(text: str) -> str:
    for old, new in REPLACE_ZH:
        text = text.replace(old, new)
    return text


def problems(en: str, zh: str | None = None, contract: dict | None = None) -> list[str]:
    contract = contract or CONTRACT
    zh = to_zh(en) if zh is None else zh
    report = cs.Report()
    with tempfile.TemporaryDirectory() as tmp:
        a = Path(tmp) / "DRIVER-SEC-SPEC.md"
        b = Path(tmp) / "DRIVER-SEC-SPEC_zh.md"
        a.write_text(en, encoding="utf-8")
        b.write_text(zh, encoding="utf-8")
        old_root = cs.ROOT
        cs.ROOT = Path(tmp)
        try:
            spec_en = cs.parse(a, "en")
            spec_zh = cs.parse(b, "zh")
            cs.check_spec_file(spec_en, DSEC, VERSION, contract, report)
            cs.check_spec_file(spec_zh, DSEC, VERSION, contract, report)
            cs.check_pair(spec_en, spec_zh, report)
            cs.check_cross_refs([spec_en, spec_zh], {c.id for c in spec_en.clauses}, {"DSEC"}, report)
        finally:
            cs.ROOT = old_root
    return report.errors


class SplitRowTest(unittest.TestCase):
    def test_escaped_pipe_stays_in_cell(self):
        self.assertEqual(cs.split_row("| `--format` | json\\|text\\|raw |"), ["`--format`", "json|text|raw"])


class SpecFileTest(unittest.TestCase):
    def test_minimal_pair_passes(self):
        self.assertEqual(problems(EN), [])

    def test_wrong_contract_key(self):
        errors = problems(EN.replace("`T1` | local", "`T3` | local"))
        self.assertTrue(any("risk_tiers" in e for e in errors), errors)

    def test_check_line_needs_label(self):
        errors = problems(EN.replace("Check: 👀 Review.", "Check: Review."))
        self.assertTrue(any("🤖 or 👀" in e for e in errors), errors)

    def test_unknown_test_id(self):
        errors = problems(EN.replace("Check: 🤖 R02.", "Check: 🤖 D99."))
        self.assertTrue(any("unknown conformance test D99" in e for e in errors), errors)

    def test_clause_must_end_with_why_and_check(self):
        errors = problems(EN.replace("Why: People need to see the risk.\nCheck: 👀 Review.", "Check: 👀 Review."))
        self.assertTrue(any("must end with" in e for e in errors), errors)

    def test_normative_word_required(self):
        errors = problems(EN.replace("The README MUST show the tool's tier.", "The README shows the tool's tier."))
        self.assertTrue(any("no normative word" in e for e in errors), errors)

    def test_checklist_must_match(self):
        errors = problems(EN.replace("- [ ] DSEC-002 Tool risk tier", "- [ ] DSEC-002 Risk of the tool"))
        self.assertTrue(any("checklist" in e for e in errors), errors)

    def test_order_and_segments(self):
        swapped = EN.replace("### DSEC-002 Tool risk tier", "### DSEC-099 Tool risk tier").replace("DSEC-002", "DSEC-099")
        errors = problems(swapped)
        self.assertTrue(any("outside every numbering segment" in e for e in errors), errors)

    def test_missing_cross_reference(self):
        errors = problems(EN.replace("Each command MUST have a tier.", "Each command MUST have a tier (DSEC-005)."))
        self.assertTrue(any("missing clause DSEC-005" in e for e in errors), errors)

    def test_pair_table_rows_must_match(self):
        zh = to_zh(EN).replace("| a | b | c |", "| a | b | c |\n| d | e | f |")
        en = EN
        self.assertEqual(problems(en, zh), [])  # rows outside clauses are free
        zh2 = to_zh(EN).replace("必须显示", "必须显示。\n\n| x | y |\n|---|---|\n| 1 | 2 |\n\n说明")
        errors = problems(en, zh2)
        self.assertTrue(any("table rows differ" in e for e in errors), errors)

    def test_banned_reference(self):
        errors = problems(EN.replace("Text.\n\n## Scope", "Based on ai-native rules.\n\n## Scope"))
        self.assertTrue(any("banned reference" in e for e in errors), errors)


class ContractTablesTest(unittest.TestCase):
    def test_error_code_columns(self):
        row = ["`E_BUSY`", "7", "no", "Busy"]
        errors = cs.extra_row_checks("error_codes", CONTRACT, "E_BUSY", row, "en")
        self.assertTrue(any("retryable" in e for e in errors), errors)
        row = ["`E_BUSY`", "7", "是", "忙"]
        self.assertEqual(cs.extra_row_checks("error_codes", CONTRACT, "E_BUSY", row, "zh"), [])

    def test_every_marker_reads_the_contract(self):
        for name, keys in cs.MARKERS.items():
            with self.subTest(marker=name):
                self.assertTrue(keys(CONTRACT), f"marker {name} has no contract values")


class RepositoryTest(unittest.TestCase):
    def test_schema_enums_match_contract(self):
        report = cs.Report()
        cs.check_schema_consistency(CONTRACT, report)
        self.assertEqual(report.errors, [])

    def test_schema_drift_is_reported(self):
        contract = copy.deepcopy(CONTRACT)
        contract["conflict_values"].append("new_value")
        report = cs.Report()
        cs.check_schema_consistency(contract, report)
        self.assertTrue(any("conflict" in e for e in report.errors), report.errors)

    def test_schemas_and_examples(self):
        report = cs.Report()
        cs.check_schemas_and_examples(CONTRACT, report)
        self.assertEqual(report.errors, [])

    def test_full_check_passes(self):
        self.assertEqual(cs.main([]), 0)


if __name__ == "__main__":
    unittest.main()
