#!/usr/bin/env python3
"""Check the specifications, the contract, the schemas and the examples.

Usage:
    python scripts/check_spec.py                 # everything
    python scripts/check_spec.py --doc DRIVER-CLI-SPEC   # one specification pair
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC_DIR = ROOT / "spec"
CONTRACT = ROOT / "contract" / "driver-contract.json"
SCHEMA_DIR = ROOT / "contract" / "schemas"
EXAMPLE_DIR = ROOT / "contract" / "examples"

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?$")
CLAUSE_HEADING = re.compile(r"^### ([A-Z]+)-(\d{3}) (\S.*)$")
CLAUSE_REF = re.compile(r"\b(DCLI|DSEC|DSKL|DVER|DREPO)-(\d{3})\b")
TEST_REF = re.compile(r"\b([GRD]\d{2})\b")
MARKER = re.compile(r"^<!-- contract:([a-z0-9_]+) -->$")
FIRST_KEY = re.compile(r"^`([^`]+)`")
CJK = re.compile(r"[㐀-鿿]")
BANNED = [re.compile(r"ai-native", re.IGNORECASE)]

LANG = {
    "en": {
        "suffix": "",
        "front": ["How to Read", "Scope", "Terms", "Runtime and Tool Responsibilities"],
        "checklist": "Checklist",
        "why": "Why: ",
        "check": "Check: ",
        "normative": re.compile(r"\b(MUST|SHOULD|MAY)\b"),
        "switch": "English | [中文]({name}_zh.md)",
        "version": "> Version {version} · Clauses {first} to {last}",
        "yes": "yes",
        "no": "no",
    },
    "zh": {
        "suffix": "_zh",
        "front": ["怎么读", "适用范围", "术语", "运行时与工具的分工"],
        "checklist": "检查清单",
        "why": "为什么：",
        "check": "检查：",
        "normative": re.compile(r"(必须|禁止|应该|不应该|可以)"),
        "switch": "[English]({name}.md) | 中文",
        "version": "> 版本 {version} · 条款 {first} 至 {last}",
        "yes": "是",
        "no": "否",
    },
}


# --------------------------------------------------------------------------- contract markers

def _knowledge_commands(c):
    return [s["path"] for s in c["standard_commands"] if s["path"].startswith("knowledge ")]


MARKERS = {
    # name: (keys from the contract, extra row check or None)
    "error_codes": lambda c: [e["code"] for e in c["error_codes"]],
    "exit_codes": lambda c: [str(x) for x in c["exit_codes"]],
    "verbs": lambda c: [v["verb"] for v in c["verbs"]],
    "global_flags": lambda c: [f["flag"] for f in c["global_flags"]],
    "shared_flags": lambda c: [f["flag"] for f in c["shared_flags"]],
    "target_flags": lambda c: [f["flag"] for f in c["target_flags"]],
    "target_keys": lambda c: [t["kind"] for t in c["target_keys"]],
    "builtin_commands": lambda c: [b["path"] for b in c["builtin_commands"]],
    "context_keys": lambda c: list(c["context_keys"]),
    "doctor_checks": lambda c: list(c["doctor"]["checks"]),
    "effects": lambda c: [e["effect"] for e in c["effects"]],
    "preview_fields": lambda c: list(c["preview"]["fields"]),
    "token_binds": lambda c: list(c["confirm_token"]["binds"]),
    "confirm_review": lambda c: [str(r["step"]) for r in c["confirm_review"]],
    "receipt_dimensions": lambda c: list(c["receipt"]["dimensions"]),
    "derivation": lambda c: [str(r["rule"]) for r in c["derivation"]],
    "human_required_actions": lambda c: list(c["human_required_actions"]),
    "update_failures": lambda c: [f["case"] for f in c["update"]["failures"]],
    "units": lambda c: [u["quantity"] for u in c["units"]],
    "registration_fields": lambda c: list(c["registration_fields"]),
    "standard_commands": lambda c: [s["path"] for s in c["standard_commands"]],
    "modes": lambda c: [m["mode"] for m in c["modes"]],
    "session_states": lambda c: [s["state"] for s in c["session_states"]],
    "disk_states": lambda c: [s["state"] for s in c["disk_states"]],
    "device_states": lambda c: [s["state"] for s in c["device_states"]],
    "adapter_capabilities": lambda c: [a["name"] for a in c["adapter_capabilities"]],
    "host_methods": lambda c: list(c["host_protocol"]["methods"]),
    "host_error_codes": lambda c: list(c["host_protocol"]["allowed_error_codes"]),
    "risk_tiers": lambda c: list(c["risk_tiers"]),
    "scope_fields": lambda c: list(c["scope_file"]["fields"]),
    "scope_statuses": lambda c: list(c["scope_statuses"]),
    "state_dir_entries": lambda c: list(c["state_dir"]["entries"]),
    "skill_frontmatter": lambda c: list(c["skill"]["frontmatter"]),
    "stop_checkpoints": lambda c: list(c["skill"]["stop_checkpoints"]),
    "driver_playbooks": lambda c: list(c["skill"]["driver_playbooks"]),
    "eval_scenarios_general": lambda c: [x["scenario"] for x in c["skill"]["eval_scenarios"]["general"]],
    "eval_scenarios_driver": lambda c: [x["scenario"] for x in c["skill"]["eval_scenarios"]["driver"]],
    "knowledge_kinds": lambda c: list(c["knowledge"]["kinds"]),
    "knowledge_sources": lambda c: list(c["knowledge"]["sources"]),
    "knowledge_builtin_fields": lambda c: (
        c["knowledge"]["builtin_fields"] + c["knowledge"]["rule_fields"] + c["knowledge"]["resource_fields"]
    ),
    "knowledge_team_fields": lambda c: list(c["knowledge"]["team_fields"]),
    "knowledge_commands": _knowledge_commands,
    "conformance_general": lambda c: [t["id"] for t in c["conformance"]["general"]],
    "conformance_driver": lambda c: [t["id"] for t in c["conformance"]["driver"]],
    "behavior_matrix_rows": lambda c: [r["row"] for r in c["behavior_matrix_rows"]],
    "maturity_levels": lambda c: [m["level"] for m in c["maturity_levels"]],
    "evidence_kinds": lambda c: list(c["evidence_kinds"]),
    "badges": lambda c: list(c["badges"]),
    "compatibility_labels": lambda c: [x["label"] for x in c["compatibility_labels"]],
    "root_files": lambda c: list(c["project"]["root_files"]),
    "required_paths": lambda c: list(c["project"]["required_paths"]),
    "bilingual_files": lambda c: list(c["project"]["bilingual_files"]),
    "readme_sections": lambda c: list(c["project"]["sections"]["README.md"]),
    "agents_sections": lambda c: list(c["project"]["sections"]["AGENTS.md"]),
    "security_sections": lambda c: list(c["project"]["sections"]["SECURITY.md"]),
    "contributing_sections": lambda c: list(c["project"]["sections"]["CONTRIBUTING.md"]),
    "application_sections": lambda c: list(c["project"]["sections"]["docs/APPLICATION.md"]),
    "compatibility_sections": lambda c: list(c["project"]["sections"]["docs/COMPATIBILITY.md"]),
    "e2e_sections": lambda c: list(c["project"]["sections"]["docs/E2E.md"]),
    "changelog_sections": lambda c: list(c["project"]["changelog_sections"]),
    "capability_dispositions": lambda c: list(c["project"]["capability_dispositions"]),
}


SECTION_FILES = {
    "readme_sections": "README.md",
    "agents_sections": "AGENTS.md",
    "security_sections": "SECURITY.md",
    "contributing_sections": "CONTRIBUTING.md",
    "application_sections": "docs/APPLICATION.md",
    "compatibility_sections": "docs/COMPATIBILITY.md",
    "e2e_sections": "docs/E2E.md",
}


def _cell_has(cell: str, value: str) -> bool:
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(value) + r"(?![A-Za-z0-9_])", cell) is not None


def extra_row_checks(name: str, contract: dict, key: str, cells: list[str], lang: str) -> list[str]:
    """Checks beyond the first column, for tables where more columns are data."""
    problems = []
    row = " | ".join(cells)
    if name == "error_codes":
        entry = next(e for e in contract["error_codes"] if e["code"] == key)
        if len(cells) < 3 or cells[1].strip("` ") != str(entry["exit"]):
            problems.append(f"{key}: exit column must be {entry['exit']}")
        want = LANG[lang]["yes"] if entry["retryable"] else LANG[lang]["no"]
        if len(cells) < 3 or cells[2].strip("` ") != want:
            problems.append(f"{key}: retryable column must be '{want}'")
    elif name == "verbs":
        entry = next(v for v in contract["verbs"] if v["verb"] == key)
        want = entry["effect"] or "—"
        if len(cells) < 2 or cells[1].strip("` ") != want:
            problems.append(f"{key}: effect column must be '{want}'")
    elif name == "standard_commands":
        entry = next(s for s in contract["standard_commands"] if s["path"] == key)
        if len(cells) < 2 or cells[1].strip("` ") != entry["effect"]:
            problems.append(f"{key}: effect column must be '{entry['effect']}'")
    elif name == "effects":
        entry = next(e for e in contract["effects"] if e["effect"] == key)
        if cells[-1].strip("` ") != entry["risk"]:
            problems.append(f"{key}: last column must be the risk tier {entry['risk']}")
    elif name == "confirm_review":
        entry = next(r for r in contract["confirm_review"] if str(r["step"]) == key)
        for value in entry["conflicts"]:
            if not _cell_has(row, value):
                problems.append(f"step {key}: row must name conflict '{value}'")
    elif name == "receipt_dimensions":
        for value in contract["receipt"]["dimensions"][key]:
            if not _cell_has(row, value):
                problems.append(f"{key}: row must list value '{value}'")
    elif name == "derivation":
        entry = next(r for r in contract["derivation"] if str(r["rule"]) == key)
        code = entry.get("default_code") or entry.get("code")
        if code and not _cell_has(row, code):
            problems.append(f"rule {key}: row must name {code}")
    elif name == "update_failures":
        entry = next(f for f in contract["update"]["failures"] if f["case"] == key)
        if not _cell_has(row, entry["code"]):
            problems.append(f"{key}: row must name {entry['code']}")
    elif name == "units":
        entry = next(u for u in contract["units"] if u["quantity"] == key)
        if entry["unit"] not in row:
            problems.append(f"{key}: row must name the unit {entry['unit']}")
    elif name in ("session_states", "disk_states", "device_states"):
        entry = next(s for s in contract[name] if s["state"] == key)
        if entry.get("error") and not _cell_has(row, entry["error"]):
            problems.append(f"{key}: row must name {entry['error']}")
    elif name in SECTION_FILES and lang == "zh":
        names = contract["project"]["sections"][SECTION_FILES[name]]
        want = contract["project"]["sections_zh"][SECTION_FILES[name]][names.index(key)]
        if FIRST_KEY.sub("", cells[0]).strip() != want:
            problems.append(f"{key}: the Chinese name must be '{want}'")
    elif name == "compatibility_labels":
        entry = next(x for x in contract["compatibility_labels"] if x["label"] == key)
        if entry["emoji"] not in row:
            problems.append(f"{key}: row must show {entry['emoji']}")
    return problems


# --------------------------------------------------------------------------- parsing

@dataclass
class Clause:
    id: str
    prefix: str
    number: int
    title: str
    line: int
    body: list[str] = field(default_factory=list)
    section: str = ""
    markers: list[str] = field(default_factory=list)
    table_rows: int = 0


@dataclass
class Table:
    marker: str
    line: int
    rows: list[list[str]]
    clause: str | None


@dataclass
class SpecFile:
    path: Path
    lang: str
    lines: list[str]
    h2: list[tuple[int, str]] = field(default_factory=list)
    clauses: list[Clause] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    checklist: list[tuple[str, str]] = field(default_factory=list)
    stray_h3: list[tuple[int, str]] = field(default_factory=list)


def split_row(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    cells, current, i = [], "", 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body) and body[i + 1] == "|":
            current += "|"
            i += 2
            continue
        if ch == "|":
            cells.append(current.strip())
            current = ""
        else:
            current += ch
        i += 1
    cells.append(current.strip())
    return cells


def is_separator(line: str) -> bool:
    return re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?", line.strip()) is not None


def parse(path: Path, lang: str) -> SpecFile:
    lines = path.read_text(encoding="utf-8").splitlines()
    spec = SpecFile(path=path, lang=lang, lines=lines)
    current: Clause | None = None
    section = ""
    in_code = False
    pending_marker: tuple[str, int] | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            in_code = not in_code
            if current:
                current.body.append(line)
            i += 1
            continue
        if in_code:
            if current:
                current.body.append(line)
            i += 1
            continue
        if line.startswith("## "):
            section = line[3:].strip()
            spec.h2.append((i + 1, section))
            current = None
            i += 1
            continue
        if line.startswith("### "):
            m = CLAUSE_HEADING.match(line)
            if m:
                current = Clause(
                    id=f"{m.group(1)}-{m.group(2)}", prefix=m.group(1), number=int(m.group(2)),
                    title=m.group(3).strip(), line=i + 1, section=section,
                )
                spec.clauses.append(current)
            else:
                spec.stray_h3.append((i + 1, line))
                current = None
            i += 1
            continue
        mk = MARKER.match(line.strip())
        if mk:
            pending_marker = (mk.group(1), i + 1)
            if current:
                current.markers.append(mk.group(1))
            i += 1
            continue
        if line.lstrip().startswith("|"):
            start = i
            block = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                block.append(lines[i])
                i += 1
            rows = [split_row(r) for r in block[2:]] if len(block) >= 2 and is_separator(block[1]) else []
            if current:
                current.table_rows += len(rows)
                current.body.extend(block)
            if pending_marker and pending_marker[1] == start:
                spec.tables.append(Table(pending_marker[0], start + 1, rows, current.id if current else None))
                pending_marker = None
            continue
        if pending_marker and line.strip():
            pending_marker = None
        if section == LANG[lang]["checklist"]:
            cm = re.match(r"^- \[ \] ([A-Z]+-\d{3}) (\S.*)$", line)
            if cm:
                spec.checklist.append((cm.group(1), cm.group(2).strip()))
            elif line.strip():
                spec.checklist.append(("?", line.strip()))
        if current:
            current.body.append(line)
        i += 1
    return spec


# --------------------------------------------------------------------------- checks

class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def add(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def segment_of(doc: dict, number: int) -> dict | None:
    for seg in doc["segments"]:
        if seg["from"] <= number <= seg["to"]:
            return seg
    return None


def check_spec_file(spec: SpecFile, doc: dict, version: str, contract: dict, report: Report) -> None:
    where = rel(spec.path)
    lang = LANG[spec.lang]
    content = [ln for ln in spec.lines if ln.strip()]
    if not content or content[0] != f"# {doc['name']}":
        report.add(where, f"first line must be '# {doc['name']}'")
    if len(content) < 2 or content[1] != lang["switch"].format(name=doc["name"]):
        report.add(where, f"second line must be '{lang['switch'].format(name=doc['name'])}'")
    if spec.clauses:
        want = lang["version"].format(version=version, first=spec.clauses[0].id, last=spec.clauses[-1].id)
        if len(content) < 3 or content[2] != want:
            report.add(where, f"version line must be '{want}'")
    else:
        report.add(where, "no clauses found")

    names = [name for _, name in spec.h2]
    if names[: len(lang["front"])] != lang["front"]:
        report.add(where, f"the first sections must be {lang['front']}, found {names[:len(lang['front'])]}")
    if not names or names[-1] != lang["checklist"]:
        report.add(where, f"the last section must be '{lang['checklist']}'")
    for line_no, text in spec.stray_h3:
        report.add(f"{where}:{line_no}", f"level-3 headings are only for clauses: {text!r}")

    seen: set[str] = set()
    previous = -1
    section_segment: dict[str, dict] = {}
    for clause in spec.clauses:
        at = f"{where}:{clause.line}"
        if clause.prefix != doc["prefix"]:
            report.add(at, f"{clause.id} must use prefix {doc['prefix']}")
        if clause.id in seen:
            report.add(at, f"duplicate clause {clause.id}")
        seen.add(clause.id)
        if clause.number <= previous:
            report.add(at, f"{clause.id} is out of order")
        previous = clause.number
        seg = segment_of(doc, clause.number)
        if seg is None:
            report.add(at, f"{clause.id} is outside every numbering segment")
        elif clause.section in section_segment and section_segment[clause.section] is not seg:
            report.add(at, f"{clause.id} shares section '{clause.section}' with another segment")
        else:
            section_segment[clause.section] = seg
        if clause.section in lang["front"] or clause.section == lang["checklist"]:
            report.add(at, f"{clause.id} must not sit in section '{clause.section}'")

        text = [ln for ln in clause.body if ln.strip()]
        why = [ln for ln in text if ln.startswith(lang["why"])]
        check = [ln for ln in text if ln.startswith(lang["check"])]
        if len(why) != 1 or len(check) != 1 or text[-2:] != [why[0] if why else None, check[0] if check else None]:
            report.add(at, f"{clause.id} must end with one '{lang['why'].strip()}' line and one '{lang['check'].strip()}' line")
        if check:
            label = check[0][len(lang["check"]):].lstrip()
            if not (label.startswith("🤖") or label.startswith("👀")):
                report.add(at, f"{clause.id}: the check line must start with 🤖 or 👀")
            known = {t["id"] for t in contract["conformance"]["general"] + contract["conformance"]["driver"]}
            for test in TEST_REF.findall(check[0]):
                if test not in known:
                    report.add(at, f"{clause.id}: unknown conformance test {test}")
        normative_text = "\n".join(ln for ln in text if not ln.startswith((lang["why"], lang["check"])))
        if not lang["normative"].search(normative_text):
            report.add(at, f"{clause.id} has no normative word")

    want_list = [(c.id, c.title) for c in spec.clauses]
    if spec.checklist != want_list:
        missing = [c for c in want_list if c not in spec.checklist]
        extra = [c for c in spec.checklist if c not in want_list]
        report.add(where, f"checklist must list every clause in order with its title; missing {missing[:3]}, extra {extra[:3]}")

    for table in spec.tables:
        at = f"{where}:{table.line}"
        if table.marker not in MARKERS:
            report.add(at, f"unknown contract marker '{table.marker}'")
            continue
        try:
            want = MARKERS[table.marker](contract)
        except (KeyError, TypeError) as exc:
            report.add(at, f"contract has no data for marker '{table.marker}': {exc}")
            continue
        got = []
        for cells in table.rows:
            m = FIRST_KEY.match(cells[0]) if cells else None
            got.append(m.group(1) if m else None)
        if got != want:
            report.add(at, f"table '{table.marker}' keys must be {want}, found {got}")
            continue
        for key, cells in zip(got, table.rows):
            for problem in extra_row_checks(table.marker, contract, key, cells, spec.lang):
                report.add(at, f"table '{table.marker}': {problem}")

    for i, line in enumerate(spec.lines, 1):
        for pattern in BANNED:
            if pattern.search(line):
                report.add(f"{where}:{i}", f"banned reference: {line.strip()[:60]}")


def check_pair(en: SpecFile, zh: SpecFile, report: Report) -> None:
    where = f"{rel(en.path)} <-> {rel(zh.path)}"
    if len(en.h2) != len(zh.h2):
        report.add(where, f"section count differs: {len(en.h2)} vs {len(zh.h2)}")
    ids_en = [c.id for c in en.clauses]
    ids_zh = [c.id for c in zh.clauses]
    if ids_en != ids_zh:
        only_en = [x for x in ids_en if x not in ids_zh]
        only_zh = [x for x in ids_zh if x not in ids_en]
        report.add(where, f"clause IDs differ; only English {only_en[:5]}, only Chinese {only_zh[:5]}")
        return
    for a, b in zip(en.clauses, zh.clauses):
        if a.table_rows != b.table_rows:
            report.add(where, f"{a.id}: table rows differ ({a.table_rows} vs {b.table_rows})")
        if a.markers != b.markers:
            report.add(where, f"{a.id}: contract markers differ ({a.markers} vs {b.markers})")
        if [s for s in (a.section,)] and en.h2 and zh.h2:
            ia = [n for _, n in en.h2].index(a.section)
            ib = [n for _, n in zh.h2].index(b.section)
            if ia != ib:
                report.add(where, f"{a.id}: sits in section {ia + 1} in English and {ib + 1} in Chinese")
    rows_en = sum(len(t.rows) for t in en.tables if t.clause is None)
    rows_zh = sum(len(t.rows) for t in zh.tables if t.clause is None)
    if rows_en != rows_zh:
        report.add(where, f"marked tables outside clauses differ in rows: {rows_en} vs {rows_zh}")


def check_cross_refs(specs: list[SpecFile], all_ids: set[str], checked_prefixes: set[str], report: Report) -> None:
    for spec in specs:
        for i, line in enumerate(spec.lines, 1):
            for prefix, number in CLAUSE_REF.findall(line):
                ref = f"{prefix}-{number}"
                if prefix in checked_prefixes and ref not in all_ids:
                    report.add(f"{rel(spec.path)}:{i}", f"reference to missing clause {ref}")


TEST_RANGE = re.compile(r"\b[GRD]\d{2} (to|至) [GRD]\d{2}\b")


def check_test_columns(specs: list[SpecFile], report: Report) -> None:
    """The last column of the G/R/D tables lists exactly the clauses whose check line cites that test.

    A check line that names a range of tests (such as "D01 to D25") cites a whole suite and is not counted.
    """
    for lang in LANG:
        cited: dict[str, set[str]] = {}
        listed: dict[str, set[str]] = {}
        for spec in (s for s in specs if s.lang == lang):
            for clause in spec.clauses:
                check = [ln for ln in clause.body if ln.startswith(LANG[lang]["check"])]
                if not check or TEST_RANGE.search(check[0]):
                    continue
                for test in set(TEST_REF.findall(check[0])):
                    cited.setdefault(test, set()).add(clause.id)
            for table in spec.tables:
                if table.marker in ("conformance_general", "conformance_driver"):
                    for cells in table.rows:
                        key = FIRST_KEY.match(cells[0])
                        if key:
                            listed[key.group(1)] = {f"{a}-{b}" for a, b in CLAUSE_REF.findall(cells[-1])}
        if not listed:
            continue
        for test in sorted(set(cited) | set(listed)):
            if cited.get(test, set()) != listed.get(test, set()):
                report.add(
                    f"spec/DRIVER-VERIFY-SPEC{LANG[lang]['suffix']}.md",
                    f"test {test}: the last column must list exactly the clauses citing it; "
                    f"missing {sorted(cited.get(test, set()) - listed.get(test, set()))}, "
                    f"extra {sorted(listed.get(test, set()) - cited.get(test, set()))}",
                )


def check_markers_once(specs: list[SpecFile], lang: str, report: Report) -> None:
    counts: dict[str, int] = {}
    for spec in specs:
        if spec.lang != lang:
            continue
        for table in spec.tables:
            counts[table.marker] = counts.get(table.marker, 0) + 1
    for name in MARKERS:
        if counts.get(name, 0) != 1:
            report.add(f"spec/*{LANG[lang]['suffix']}.md", f"marker '{name}' appears {counts.get(name, 0)} times; it must appear once")


def check_version(contract: dict, report: Report) -> str:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    m = SEMVER.match(version)
    if not m:
        report.add("VERSION", f"'{version}' is not a semantic version")
        return version
    if contract.get("version") != version:
        report.add("contract/driver-contract.json", f"version must be {version}")
    if contract.get("schema_version") != f"{m.group(1)}.{m.group(2)}":
        report.add("contract/driver-contract.json", f"schema_version must be {m.group(1)}.{m.group(2)}")
    return version


def check_schemas_and_examples(contract: dict, report: Report) -> None:
    try:
        from jsonschema import Draft202012Validator
        from referencing import Registry, Resource
    except ImportError:
        report.add("requirements-dev.txt", "jsonschema is not installed; run pip install -r requirements-dev.txt")
        return
    resources = []
    validators: dict[str, object] = {}
    for name in contract.get("schemas", []):
        path = SCHEMA_DIR / name
        if not path.is_file():
            report.add(rel(path), "listed in the contract but missing")
            continue
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
        except Exception as exc:  # noqa: BLE001 - report every kind of schema problem
            report.add(rel(path), f"invalid schema: {exc}")
            continue
        resources.append((schema.get("$id", name), Resource.from_contents(schema)))
        validators[name] = schema
    for path in sorted(SCHEMA_DIR.glob("*.json")):
        if path.name not in contract.get("schemas", []):
            report.add(rel(path), "not listed in the contract's schemas")
    registry = Registry().with_resources(resources)

    def validator(name: str):
        return Draft202012Validator(validators[name], registry=registry)

    if "contract.schema.json" in validators:
        errors = list(validator("contract.schema.json").iter_errors(contract))
        for err in errors[:5]:
            report.add("contract/driver-contract.json", f"{'/'.join(map(str, err.path))}: {err.message}")

    for kind in ("valid", "invalid"):
        base = EXAMPLE_DIR / kind
        if not base.is_dir():
            report.add(rel(base), "missing")
            continue
        for folder in sorted(p for p in base.iterdir() if p.is_dir()):
            schema_name = f"{folder.name}.schema.json"
            if schema_name not in validators:
                report.add(rel(folder), f"no schema {schema_name}")
                continue
            files = sorted(folder.glob("*.json"))
            if not files:
                report.add(rel(folder), "has no examples")
            for path in files:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    report.add(rel(path), f"not JSON: {exc}")
                    continue
                errors = list(validator(schema_name).iter_errors(data))
                if kind == "valid" and errors:
                    report.add(rel(path), f"must be valid: {errors[0].message}")
                if kind == "invalid" and not errors:
                    report.add(rel(path), "must be invalid but passes")
    for name in validators:
        stem = name[: -len(".schema.json")]
        if stem != "contract" and not (EXAMPLE_DIR / "valid" / stem).is_dir():
            report.add(f"contract/examples/valid/{stem}", "every schema needs valid examples")


SCHEMA_ENUMS = [
    # (schema file, JSON pointer to a list or an object whose keys count, values from the contract)
    ("error.schema.json", "/properties/code/enum", lambda c: [e["code"] for e in c["error_codes"]]),
    ("error.schema.json", "/allOf/0/if/properties/code/enum", lambda c: [e["code"] for e in c["error_codes"] if e["retryable"]]),
    ("error.schema.json", "/$defs/details/properties/dispatch_state/enum", lambda c: c["envelope"]["dispatch_states"]),
    ("error.schema.json", "/$defs/details/properties/conflict/enum", lambda c: c["conflict_values"]),
    ("error.schema.json", "/$defs/details/properties/action/enum", lambda c: c["human_required_actions"]),
    ("envelope.schema.json", "/$defs/meta/properties", lambda c: c["envelope"]["meta_keys"]),
    ("envelope.schema.json", "/$defs/meta/properties/notices/items/properties/severity/enum", lambda c: c["envelope"]["notice_severities"]),
    ("envelope.schema.json", "/$defs/success/required", lambda c: c["envelope"]["success_keys"]),
    ("envelope.schema.json", "/$defs/failure/required", lambda c: c["envelope"]["error_keys"]),
    ("preview.schema.json", "/$defs/tier/enum", lambda c: c["tiers"]),
    ("preview.schema.json", "/$defs/effect/enum", lambda c: [e["effect"] for e in c["effects"]]),
    ("preview.schema.json", "/$defs/preview/properties", lambda c: c["preview"]["fields"]),
    ("preview.schema.json", "/$defs/change/properties", lambda c: c["preview"]["change_keys"]),
    ("preview.schema.json", "/$defs/change/properties/origin/enum", lambda c: c["preview"]["change_origins"]),
    ("receipt.schema.json", "/$defs/receipt/properties", lambda c: c["receipt"]["keys"]),
    ("receipt.schema.json", "/$defs/outcome/properties", lambda c: list(c["receipt"]["dimensions"])),
    ("receipt.schema.json", "/$defs/outcome/properties/execution/enum", lambda c: c["receipt"]["dimensions"]["execution"]),
    ("receipt.schema.json", "/$defs/outcome/properties/change/enum", lambda c: c["receipt"]["dimensions"]["change"]),
    ("receipt.schema.json", "/$defs/outcome/properties/delivery/enum", lambda c: c["receipt"]["dimensions"]["delivery"]),
    ("receipt.schema.json", "/$defs/outcome/properties/persistence/enum", lambda c: c["receipt"]["dimensions"]["persistence"]),
    ("receipt.schema.json", "/$defs/outcome/properties/verification/enum", lambda c: c["receipt"]["dimensions"]["verification"]),
    ("receipt.schema.json", "/$defs/receipt/properties/failed_stage/enum", lambda c: c["receipt"]["failed_stages"]),
    ("batch.schema.json", "/properties/summary/required", lambda c: c["batch"]["summary_keys"]),
    ("batch.schema.json", "/properties/items/items/properties", lambda c: c["batch"]["item_keys"]),
    ("objects.schema.json", "/$defs/session/required", lambda c: c["objects"]["session"]),
    ("objects.schema.json", "/$defs/document/properties", lambda c: c["objects"]["document"]),
    ("objects.schema.json", "/$defs/job/required", lambda c: [k for k in c["objects"]["job"] if k not in ("progress", "finished_at")]),
    ("objects.schema.json", "/$defs/device/required", lambda c: c["objects"]["device"]),
    ("objects.schema.json", "/$defs/plugin/required", lambda c: c["objects"]["plugin"]),
    ("objects.schema.json", "/$defs/session/properties/state/enum", lambda c: [s["state"] for s in c["session_states"]]),
    ("objects.schema.json", "/$defs/document/properties/disk/enum", lambda c: [s["state"] for s in c["disk_states"]]),
    ("objects.schema.json", "/$defs/device/properties/state/enum", lambda c: [s["state"] for s in c["device_states"]]),
    ("objects.schema.json", "/$defs/job/properties/state/enum", lambda c: c["jobs"]["states"]),
    ("scope.schema.json", "/properties", lambda c: c["scope_file"]["fields"]),
    ("scope.schema.json", "/properties/effects/items/enum", lambda c: [e["effect"] for e in c["effects"] if e["effect"] != "observe"]),
    ("scope.schema.json", "/properties/confirm/const", lambda c: c["scope_file"]["confirm_values"]),
    ("operation.schema.json", "/properties/state/enum", lambda c: c["operation"]["states"]),
    ("operation.schema.json", "/properties/resolution/properties/outcome/enum", lambda c: c["operation"]["resolve_outcomes"]),
    ("context.schema.json", "/required", lambda c: c["context_keys"]),
    ("context.schema.json", "/properties/authorization/properties/status/enum", lambda c: c["scope_statuses"]),
    ("doctor.schema.json", "/properties/checks/items/properties/status/enum", lambda c: c["doctor"]["statuses"]),
    ("doctor.schema.json", "/properties/checks/items/properties", lambda c: c["doctor"]["check_keys"]),
    ("changelog.schema.json", "/properties/entries/items/properties/changes/properties", lambda c: c["changelog_groups"]),
    ("update.schema.json", "/properties", lambda c: c["update"]["data_keys"]),
    ("update.schema.json", "/properties/status/enum", lambda c: c["update"]["statuses"]),
    ("update.schema.json", "/properties/provenance_status/enum", lambda c: c["update"]["provenance_statuses"]),
    ("update.schema.json", "/properties/skill_sync_status/enum", lambda c: c["update"]["skill_sync_statuses"]),
    ("update.schema.json", "/properties/entry/enum", lambda c: c["update"]["entry_values"]),
    ("knowledge.schema.json", "/$defs/kind/enum", lambda c: c["knowledge"]["kinds"]),
    ("knowledge.schema.json", "/$defs/builtin_front_matter/required", lambda c: c["knowledge"]["builtin_fields"]),
    ("knowledge.schema.json", "/$defs/builtin_front_matter/properties", lambda c: c["knowledge"]["builtin_fields"] + c["knowledge"]["rule_fields"] + c["knowledge"]["resource_fields"]),
    ("knowledge.schema.json", "/$defs/builtin_front_matter/properties/lang/enum", lambda c: c["knowledge"]["langs"]),
    ("knowledge.schema.json", "/$defs/builtin_front_matter/properties/severity/enum", lambda c: c["knowledge"]["severities"]),
    ("knowledge.schema.json", "/$defs/team_entry/properties", lambda c: c["knowledge"]["team_fields"]),
    ("knowledge.schema.json", "/$defs/team_entry/properties/provider/const", lambda c: [p["provider"] for p in c["knowledge"]["providers"]]),
    ("knowledge.schema.json", "/$defs/get_team/properties/reader/const", lambda c: [p["reader"] for p in c["knowledge"]["providers"]]),
    ("host-protocol.schema.json", "/$defs/method/enum", lambda c: c["host_protocol"]["methods"]),
    ("host-protocol.schema.json", "/$defs/discovery_file/required", lambda c: c["host_protocol"]["discovery_keys"]),
    ("host-protocol.schema.json", "/$defs/error_response/properties/error/properties/data/properties/code/enum", lambda c: c["host_protocol"]["allowed_error_codes"]),
    ("host-protocol.schema.json", "/$defs/error_response/properties/error/properties/code/const", lambda c: [c["host_protocol"]["rpc_error_code"]]),
    ("host-protocol.schema.json", "/$defs/hello_result/required", lambda c: c["host_protocol"]["handshake"]["response_keys"]),
    ("evidence.schema.json", "/properties/runs/items/properties/matrix_row/enum", lambda c: [r["row"] for r in c["behavior_matrix_rows"]]),
    ("adapter.schema.json", "/$defs/requests/properties", lambda c: [a["name"] for a in c["adapter_capabilities"]]),
    ("adapter.schema.json", "/$defs/results/properties", lambda c: [a["name"] for a in c["adapter_capabilities"]]),
    ("behavior-matrix.schema.json", "/$defs/row/properties/row/enum", lambda c: [r["row"] for r in c["behavior_matrix_rows"]]),
    ("commands.schema.json", "/$defs/command/properties", lambda c: c["registration_fields"]),
    ("eval-report.schema.json", "/$defs/question/properties/scenario/enum", lambda c: [x["scenario"] for g in ("general", "driver") for x in c["skill"]["eval_scenarios"][g]]),
    ("reference.schema.json", "/$defs/command/properties/maturity/enum", lambda c: [m["level"] for m in c["maturity_levels"]]),
]


def _pointer(doc, pointer: str):
    node = doc
    for part in pointer.strip("/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def check_schema_consistency(contract: dict, report: Report) -> None:
    """Every enumerated value in a schema must equal the contract's list, in the same order."""
    cache: dict[str, dict] = {}
    for name, pointer, values in SCHEMA_ENUMS:
        path = SCHEMA_DIR / name
        if not path.is_file():
            continue
        schema = cache.setdefault(name, json.loads(path.read_text(encoding="utf-8")))
        try:
            node = _pointer(schema, pointer)
        except (KeyError, IndexError, ValueError):
            report.add(f"{rel(path)}#{pointer}", "missing; the contract expects it")
            continue
        got = list(node) if isinstance(node, (list, dict)) else [node]
        want = list(values(contract))
        if got != want:
            report.add(f"{rel(path)}#{pointer}", f"must be {want}, found {got}")


def check_repo_docs(report: Report) -> None:
    for name in ("README", "AGENTS"):
        en, zh = ROOT / f"{name}.md", ROOT / f"{name}_zh.md"
        if not en.is_file() or not zh.is_file():
            report.add(f"{name}.md", "English and Chinese files are both required")
            continue
        a = en.read_text(encoding="utf-8").splitlines()
        b = zh.read_text(encoding="utf-8").splitlines()
        if f"English | [中文]({name}_zh.md)" not in a:
            report.add(rel(en), "missing the language switch line")
        if f"[English]({name}.md) | 中文" not in b:
            report.add(rel(zh), "missing the language switch line")
        ha = [ln for ln in a if ln.startswith("## ")]
        hb = [ln for ln in b if ln.startswith("## ")]
        if len(ha) != len(hb):
            report.add(f"{name}.md <-> {name}_zh.md", f"section count differs: {len(ha)} vs {len(hb)}")
        for path, lines in ((en, a), (zh, b)):
            for i, line in enumerate(lines, 1):
                for pattern in BANNED:
                    if pattern.search(line):
                        report.add(f"{rel(path)}:{i}", "banned reference")
    changelog = ROOT / "CHANGELOG.md"
    if not changelog.is_file():
        report.add("CHANGELOG.md", "missing")
    else:
        text = changelog.read_text(encoding="utf-8")
        heads = [ln for ln in text.splitlines() if ln.startswith("## ")]
        if not heads or heads[0] != "## [Unreleased]":
            report.add("CHANGELOG.md", "the first section must be '## [Unreleased]'")
        if CJK.search(text):
            report.add("CHANGELOG.md", "CHANGELOG is English only")
    if not (ROOT / "docs" / "OPEN-QUESTIONS.md").is_file():
        report.add("docs/OPEN-QUESTIONS.md", "missing")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--doc", action="append", help="check only this specification pair (repeatable)")
    args = parser.parse_args(argv)

    report = Report()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    version = check_version(contract, report)
    docs = contract["spec_documents"]
    selected = [d for d in docs if not args.doc or d["name"] in args.doc]
    if args.doc and len(selected) != len(set(args.doc)):
        report.add("--doc", f"unknown specification in {args.doc}")

    parsed: list[SpecFile] = []
    for doc in selected:
        pair = {}
        for lang, info in LANG.items():
            path = SPEC_DIR / f"{doc['name']}{info['suffix']}.md"
            if not path.is_file():
                report.add(rel(path), "missing")
                continue
            spec = parse(path, lang)
            check_spec_file(spec, doc, version, contract, report)
            parsed.append(spec)
            pair[lang] = spec
        if len(pair) == 2:
            check_pair(pair["en"], pair["zh"], report)

    all_ids = {c.id for s in parsed for c in s.clauses}
    checked = {d["prefix"] for d in selected}
    check_cross_refs(parsed, all_ids, checked, report)
    if not args.doc:
        for lang in LANG:
            check_markers_once(parsed, lang, report)
        check_test_columns(parsed, report)
        check_schemas_and_examples(contract, report)
        check_schema_consistency(contract, report)
        check_repo_docs(report)

    if report.errors:
        for error in report.errors:
            print(error)
        print(f"\n{len(report.errors)} problem(s) found.")
        return 1
    clauses = sum(len(s.clauses) for s in parsed if s.lang == "en")
    print(f"OK: {len(selected)} specification pair(s), {clauses} clauses.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
