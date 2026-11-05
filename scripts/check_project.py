#!/usr/bin/env python3
"""Check a driver tool project against the specification: check_project.

    python scripts/check_project.py <project> [--fix] [--json]

It runs from an unpacked specification release (or a checkout of this repository) and
checks the project against that release: the layout, the documents and their fixed text,
the generated content, the pinned copies, versions, Skills, knowledge, behavior matrices,
evidence and maturity. Each problem names the clause it breaks. The exit code is 1 when
there is a problem.

With ``--fix`` it first writes the generated content: ``contract/commands.json``, the
command maps, the badge row, the info card, the risk block, the support matrix and the
evidence index. Everything else is for the author to fix.

The project's own Python runs the tool once, to read its command registration and
``reference --all``. Validation uses jsonschema.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BUNDLE = Path(__file__).resolve().parents[1]
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?\Z")
CJK = re.compile(r"[㐀-鿿豈-﫿　-〿＀-￯]")
LATIN = re.compile(r"[A-Za-z]{3,}")
VARIABLES = ["tool", "package", "pkg", "PREFIX", "product", "application", "versions", "repo", "author", "year", "modes", "host_component",
             "version", "spec_version"]
CONDITIONS = ["host_component", "session", "device", "file"]
LEFTOVER = re.compile(r"\{\{fill:[^}]*(?:\}\})?|\{\{(?:(?:%s)|[#^/](?:%s))\}\}" % ("|".join(VARIABLES), "|".join(CONDITIONS)))
OS_NAMES = {"win32": "Windows", "darwin": "macOS", "linux": "Linux"}
OS_KEYS = {"Windows": "windows", "macOS": "macos", "Linux": "linux"}
NPM_OS = {"windows": "win32", "macos": "darwin", "linux": "linux"}
SKIP_DIRS = {".git", "node_modules", "build", "dist", "__pycache__", ".venv", "venv", ".mypy_cache", ".ruff_cache"}
ROOT_CONFIG = {"package-lock.json", "npm-shrinkwrap.json", "Pipfile", "go.mod", "go.sum"}
ROOT_CONFIG_SUFFIXES = (".toml", ".cfg", ".ini", ".lock", ".yaml", ".yml")
JUNK = {".DS_Store", "Thumbs.db", "desktop.ini"}
FIXED = {"README.md": ["Install", "How It Works"], "AGENTS.md": ["Bare minimum to obey"],
         "SECURITY.md": ["Write Confirmation", "State Directory", "Untrusted Content", "Supply Chain", "Self-update"]}
REGIONS = {
    "README.md": ["badges", "info-card", "command-map"],
    "SECURITY.md": ["risk"],
    "docs/COMPATIBILITY.md": ["support-matrix"],
    "docs/E2E.md": ["evidence"],
}
TEXT = {
    "en": {
        "info": ("Item", "Value"),
        "rows": ["Application", "Modes", "Systems and CPUs", "Risk tier", "Maturity", "Specification", "Host component"],
        "yes": "yes", "no": "no",
        "matrix": ("Application version", "Operating system", "Mode", "Status"),
        "evidence": ("Record", "Recorded at", "Application", "Platform", "Result"),
        "no_records": "No live record yet.",
        "passed": "{p} of {n} runs passed",
        "risk_t0": "Risk tier: **T0**. Every command only reads.",
        "risk": "Risk tier: **{tier}**, set by these commands:",
        "maturity": "{level}: {draft} draft, {verified} verified, {stable} stable",
    },
    "zh": {
        "info": ("项目", "内容"),
        "rows": ["软件", "模式", "系统与 CPU", "风险等级", "成熟度", "规范", "宿主组件"],
        "yes": "需要", "no": "不需要",
        "matrix": ("软件版本", "操作系统", "模式", "状态"),
        "evidence": ("记录", "运行时间", "软件", "平台", "结果"),
        "no_records": "还没有真实软件运行记录。",
        "passed": "{n} 次运行中 {p} 次通过",
        "risk_t0": "风险等级：**T0**。所有命令都只读取。",
        "risk": "风险等级：**{tier}**，由这些命令决定：",
        "maturity": "{level}：draft {draft} 个，verified {verified} 个，stable {stable} 个",
    },
}


@dataclass
class Problem:
    clause: str
    path: str
    message: str
    line: int | None = None

    def text(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{self.clause} {where}: {self.message}"


@dataclass
class Facts:
    """What the checks read about the project."""

    root: Path
    contract: dict[str, Any]
    package: dict[str, Any] = field(default_factory=dict)
    tool: str = ""
    pkg: str = ""
    prefix: str = ""
    version: str = ""
    spec_version: str = ""
    registration: dict[str, Any] | None = None
    reference: dict[str, Any] | None = None
    tool_error: str | None = None

    @property
    def driver(self) -> dict[str, Any]:
        return (self.reference or {}).get("driver") or {}

    @property
    def modes(self) -> list[str]:
        return list(self.driver.get("modes") or [])

    @property
    def host_component(self) -> bool:
        return bool(self.driver.get("host_component"))

    @property
    def commands(self) -> list[dict[str, Any]]:
        return list((self.reference or {}).get("commands") or [])

    def implemented(self) -> set[str]:
        """The adapter capabilities the tool implements: the methods of its adapter, and with a
        host component the instance-side methods its manifest lists (DCLI-240, DVER-030)."""
        found = set((self.reference or {}).get("adapter_capabilities") or [])
        manifest = self.root / "plugin" / "manifest.json"
        if self.host_component and manifest.is_file():
            try:
                methods = json.loads(read(manifest)).get("methods")
            except ValueError:
                methods = None
            found |= {m for m in methods or [] if isinstance(m, str)}
        return found

    @property
    def domain_paths(self) -> list[str]:
        return [c["path"] for c in (self.registration or {}).get("commands", [])]

    @property
    def product(self) -> str:
        return self.tool[:-4] if self.tool.endswith("-cli") else self.tool

    @property
    def repo(self) -> str:
        url = self.package.get("repository")
        url = url.get("url", "") if isinstance(url, dict) else (url or "")
        match = re.search(r"github\.com[/:]([^/]+/[^/#]+?)(?:\.git)?(?:#.*)?$", url)
        return match.group(1) if match else ""

    def platforms(self) -> list[tuple[str, str]]:
        """The shipped (os, cpu) pairs, from the platform packages in package.json."""
        out = []
        for name in self.package.get("optionalDependencies") or {}:
            match = re.fullmatch(re.escape(self.package.get("name", "")) + r"-(win32|darwin|linux)-(x64|arm64)", name)
            if match:
                out.append((match.group(1), match.group(2)))
        return out

    def variables(self) -> dict[str, str]:
        return {"tool": self.tool, "package": self.package.get("name", ""), "pkg": self.pkg, "PREFIX": self.prefix,
                "product": self.product, "application": str(self.driver.get("application", "")),
                "versions": str(self.driver.get("versions", "")), "repo": self.repo, "version": self.version,
                "spec_version": self.spec_version}

    def conditions(self) -> dict[str, bool]:
        return {"host_component": self.host_component, "session": "session" in self.modes,
                "device": "device" in self.modes, "file": "file" in self.modes}


# ------------------------------------------------------------------ reading


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_contract() -> dict[str, Any]:
    return json.loads(read(BUNDLE / "contract" / "driver-contract.json"))


def bundle_version() -> str:
    return read(BUNDLE / "VERSION").strip()


def gather(root: Path) -> Facts:
    facts = Facts(root=root, contract=load_contract())
    try:
        facts.package = json.loads(read(root / "package.json"))
    except (OSError, ValueError):
        facts.package = {}
    bins = facts.package.get("bin")
    facts.tool = next(iter(bins)) if isinstance(bins, dict) and len(bins) == 1 else ""
    facts.pkg = facts.tool.replace("-", "_")
    facts.prefix = facts.tool.upper().replace("-", "_")
    facts.version = str(facts.package.get("version", ""))
    try:
        facts.spec_version = read(root / ".agent" / "SPEC_VERSION").strip()
    except OSError:
        facts.spec_version = ""
    if facts.tool:
        facts.registration, facts.reference, facts.tool_error = run_tool(root, facts.pkg, facts.prefix)
    return facts


TOOL_PROBE = r"""
import io, json, os, sys, tempfile
sys.path.insert(0, os.getcwd())
from {pkg} import TOOL
from {pkg}._driver import Adapter as _Base
names = [c["name"] for c in TOOL.contract["adapter_capabilities"]]
out = {{"registration": TOOL.registration(),
        "capabilities": [n for n in names if callable(getattr(TOOL.adapter_class, n, None)) and not hasattr(_Base, n)]}}
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "reference.json")
    env = {{k: v for k, v in os.environ.items() if not k.startswith("{prefix}_")}}
    env["{prefix}_STATE_DIR"] = os.path.join(tmp, "state")
    TOOL.run(["reference", "--all", "--output", path], env, io.StringIO())
    with open(path, encoding="utf-8") as handle:
        out["reference"] = json.load(handle)
sys.stdout.write(json.dumps(out))
"""


def run_tool(root: Path, pkg: str, prefix: str) -> tuple[dict | None, dict | None, str | None]:
    script = TOOL_PROBE.format(pkg=pkg, prefix=prefix)
    try:
        proc = subprocess.run([sys.executable, "-c", script], cwd=root, capture_output=True, text=True, encoding="utf-8",
                              timeout=120, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, None, str(exc)
    if proc.returncode != 0:
        return None, None, (proc.stderr.strip().splitlines() or ["the tool exited with " + str(proc.returncode)])[-1]
    try:
        data = json.loads(proc.stdout)
        return data["registration"], {**data["reference"], "adapter_capabilities": data["capabilities"]}, None
    except (ValueError, KeyError) as exc:
        return None, None, f"unreadable output: {exc}"


# ------------------------------------------------------------------ markdown


def sections(text: str) -> list[tuple[str, int, list[str]]]:
    """The ``##`` sections of a Markdown text: (heading, line number, body lines). Headings
    inside code fences do not count."""
    out: list[tuple[str, int, list[str]]] = []
    fence = False
    for number, line in enumerate(text.split("\n"), 1):
        if line.lstrip().startswith("```"):
            fence = not fence
        if not fence and line.startswith("## "):
            out.append((line[3:].strip(), number, []))
        elif out:
            out[-1][2].append(line)
    return out


def section_body(text: str, name: str) -> str | None:
    for heading, _, body in sections(text):
        if heading == name:
            return normalize("\n".join(body))
    return None


def set_section(text: str, name: str, body: str) -> str:
    """Replace the body of one ``##`` section, keeping its heading."""
    lines = text.split("\n")
    found = [(number, heading) for heading, number, _ in sections(text)]
    for i, (number, heading) in enumerate(found):
        if heading == name:
            end = found[i + 1][0] - 1 if i + 1 < len(found) else len(lines)
            tail = lines[end:]
            return "\n".join(lines[:number] + ["", body, ""] + (tail if tail and tail[0] else tail[1:]))
    return text


def normalize(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n")).strip("\n")


def table_rows(lines: list[str]) -> int:
    rows = [line for line in lines if line.strip().startswith("|")]
    return max(0, len([r for r in rows if not re.fullmatch(r"\|[\s:|-]+\|?", r.strip())]) - 1) if rows else 0


def tables(lines: list[str]) -> list[list[list[str]]]:
    """The tables in some lines: each a list of rows of cells, the header row first."""
    out: list[list[list[str]]] = []
    current: list[list[str]] | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if re.fullmatch(r"[\s:|-]+", stripped.replace("|", "")):
                continue
            if current is None:
                current = []
                out.append(current)
            current.append(cells)
        else:
            current = None
    return out


def region(name: str) -> tuple[str, str]:
    return f"<!-- driver:{name}:start -->", f"<!-- driver:{name}:end -->"


def get_region(text: str, name: str) -> str | None:
    start, end = region(name)
    if text.count(start) != 1 or text.count(end) != 1 or text.index(start) > text.index(end):
        return None
    return text[text.index(start) + len(start):text.index(end)].strip("\n")


def set_region(text: str, name: str, content: str) -> str:
    start, end = region(name)
    if get_region(text, name) is None:
        return text
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    return f"{head}{start}\n{content}\n{end}{tail}" if content else f"{head}{start}\n{end}{tail}"


def front_matter(text: str) -> tuple[dict[str, Any], str, int]:
    """Simple YAML front matter: ``key: value``, ``key: [a, b]``, one level of nesting and
    ``>-`` folded text. Returns the fields, the body and the number of lines it took."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise ValueError("no front matter")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise ValueError("unterminated front matter") from None
    data: dict[str, Any] = {}
    parent: dict[str, Any] | None = None
    folded: tuple[dict[str, Any], str] | None = None
    last: tuple[dict[str, Any], str] | None = None
    for raw in lines[1:end]:
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip())
        if folded and indent > 0:
            target, key = folded
            target[key] = (target[key] + " " + raw.strip()).strip()
            continue
        folded = None
        if indent == 0:
            parent = None
        if raw.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s+-\s+(.*)$", raw)
        if item and last is not None:
            items = last[0].get(last[1])
            if items == {}:
                items = last[0][last[1]] = []  # a block list: the key's value is the items below it
            if isinstance(items, list):
                items.append(item.group(1).strip().strip("'\""))
                continue
        match = re.match(r"^\s*([A-Za-z_][\w-]*):\s*(.*)$", raw)
        if not match:
            raise ValueError(f"cannot read the line {raw.strip()!r}")
        key, value = match.group(1), match.group(2).strip()
        target = parent if indent > 0 and parent is not None else data
        last = (target, key)
        if value in (">-", ">", "|", "|-"):
            target[key] = ""
            folded = (target, key)
        elif value == "":
            target[key] = {}
            parent = target[key]
        elif value.startswith("[") and value.endswith("]"):
            target[key] = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
        else:
            target[key] = value.strip("'\"")
    return data, "\n".join(lines[end + 1:]), end + 1


# ------------------------------------------------------------------ template


def render(text: str, facts: Facts) -> str:
    """Fill in a template text: the conditional blocks, then the variables."""
    conditions = facts.conditions()
    out: list[str] = []
    keep = [True]
    for line in text.replace("\r\n", "\n").split("\n"):
        match = re.fullmatch(r"\{\{([#^/])(%s)\}\}" % "|".join(CONDITIONS), line.strip())
        if match:
            sign, name = match.groups()
            if sign == "/":
                keep.pop() if len(keep) > 1 else None
            else:
                keep.append(keep[-1] and (conditions[name] if sign == "#" else not conditions[name]))
            continue
        if keep[-1]:
            out.append(line)
    rendered = "\n".join(out)
    for key, value in facts.variables().items():
        rendered = rendered.replace("{{%s}}" % key, value)
    return rendered


def template_text(name: str, facts: Facts) -> str | None:
    path = BUNDLE / "template" / name
    if not path.is_file():
        return None
    return render(read(path), facts)


# ------------------------------------------------------------------ generated content


def shield(text: str) -> str:
    return urllib.parse.quote(text.replace("-", "--").replace("_", "__").replace(" ", "_"), safe="·_")


def lowest_maturity(facts: Facts) -> str:
    order = [m["level"] for m in facts.contract["maturity_levels"]]
    levels = [c.get("maturity", "draft") for c in facts.commands if c["path"] in facts.domain_paths]
    return min(levels, key=order.index) if levels else order[0]


def risk(facts: Facts) -> tuple[str, list[tuple[str, list[str]]]]:
    """The tool's risk tier and the commands that set it (DSEC-002)."""
    effects = {e["effect"]: e for e in facts.contract["effects"]}
    ranks = facts.contract["risk_tiers"]
    exempt = {s["path"] for s in facts.contract["standard_commands"] if s.get("counts_for_risk") is False}
    tiers = []
    for command in facts.commands:
        if command["path"] in exempt:
            continue
        tier = max((effects[e]["risk"] for e in command.get("effects", []) if e in effects), key=ranks.index, default="T0")
        tiers.append((command["path"], tier, [e for e in command.get("effects", []) if e != "observe"]))
    top = max((t for _, t, _ in tiers), key=ranks.index, default="T0")
    return top, [(path, effs) for path, tier, effs in tiers if tier == top and top != "T0"]


def platform_text(facts: Facts) -> list[str]:
    cpus: dict[str, list[str]] = {}
    for os_name, cpu in facts.platforms():
        cpus.setdefault(os_name, []).append(cpu)
    return [f"{OS_NAMES[o]} ({', '.join(sorted(cpus[o], key=['x64', 'arm64'].index))})" for o in ("win32", "darwin", "linux") if o in cpus]


def badges(facts: Facts) -> str:
    repo, package = facts.repo, facts.package.get("name", "")
    systems = [OS_NAMES[o] for o in ("win32", "darwin", "linux") if o in {p[0] for p in facts.platforms()}]
    tier, _ = risk(facts)
    drives = f"{facts.driver.get('application', '')} {facts.driver.get('versions', '')}".strip()
    license_name = str(facts.package.get("license", ""))
    return "\n".join([
        "![Agent-native](https://img.shields.io/badge/🤖-Agent--native-6f42c1)",
        f"[![CI](https://github.com/{repo}/actions/workflows/ci.yml/badge.svg)](https://github.com/{repo}/actions/workflows/ci.yml)",
        f"[![npm](https://img.shields.io/npm/v/{package})](https://www.npmjs.com/package/{package})",
        f"![drives](https://img.shields.io/badge/drives-{shield(drives)}-1f6feb)",
        f"![mode](https://img.shields.io/badge/mode-{shield(' · '.join(facts.modes))}-0e8a16)",
        f"![platform](https://img.shields.io/badge/platform-{shield(' · '.join(systems) or 'none')}-555555)",
        f"![risk](https://img.shields.io/badge/risk-{tier}-d29922)",
        f"![maturity](https://img.shields.io/badge/maturity-{lowest_maturity(facts)}-8957e5)",
        f"![spec](https://img.shields.io/badge/spec-{shield('tool-driver-cli-spec ' + facts.spec_version)}-0969da)",
        f"![license](https://img.shields.io/badge/license-{shield(license_name)}-blue)",
    ])


def info_card(facts: Facts, lang: str) -> str:
    t = TEXT[lang]
    tier, _ = risk(facts)
    levels = [c.get("maturity", "draft") for c in facts.commands if c["path"] in facts.domain_paths]
    maturity = t["maturity"].format(level=lowest_maturity(facts), draft=levels.count("draft"),
                                    verified=levels.count("verified"), stable=levels.count("stable"))
    values = [f"{facts.driver.get('application', '')} {facts.driver.get('versions', '')}".strip(),
              ", ".join(facts.modes), ", ".join(platform_text(facts)) or "-", tier, maturity,
              f"tool-driver-cli-spec {facts.spec_version}", t["yes"] if facts.host_component else t["no"]]
    rows = [f"| {t['info'][0]} | {t['info'][1]} |", "|---|---|"]
    rows += [f"| {name} | {value} |" for name, value in zip(t["rows"], values)]
    return "\n".join(rows)


def risk_block(facts: Facts, lang: str) -> str:
    t = TEXT[lang]
    tier, setters = risk(facts)
    if tier == "T0":
        return t["risk_t0"]
    lines = [t["risk"].format(tier=tier), ""]
    lines += [f"- `{path}`: {', '.join(effects)}" for path, effects in setters]
    return "\n".join(lines)


def dangerous(command: dict[str, Any]) -> bool:
    tier = command.get("tier")
    return "dangerous" in (tier.values() if isinstance(tier, dict) else [tier])


def command_map(commands: list[dict[str, Any]]) -> str:
    """One line per noun with its verbs, ``(dangerous)`` after a dangerous verb (DSKL-006)."""
    nouns: dict[str, list[str]] = {}
    for command in commands:
        words = command["path"].split(" ")
        noun = " ".join(words[:-1]) if len(words) > 1 else words[0]
        verbs = nouns.setdefault(noun, [])
        if len(words) > 1:
            verbs.append(words[-1] + (" (dangerous)" if dangerous(command) else ""))
    return "\n".join(f"- `{noun}`" + (f": {', '.join(verbs)}" if verbs else "") for noun, verbs in nouns.items())


def live_records(facts: Facts) -> list[tuple[Path, dict[str, Any]]]:
    folder = facts.root / "docs" / "evidence"
    out = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        if path.name.startswith("eval-"):
            continue
        try:
            data = json.loads(read(path))
        except (OSError, ValueError):
            continue
        if live_shape(data):
            out.append((path, data))
    return out


def live_shape(data: Any) -> bool:
    """Enough of evidence.schema.json for the generators; check_project reports the rest."""
    return (isinstance(data, dict) and data.get("kind") == "live" and isinstance(data.get("application"), dict)
            and isinstance(data.get("platform"), str) and isinstance(data.get("runs"), list)
            and all(isinstance(r, dict) for r in data["runs"]) and isinstance(data.get("tool_version"), str))


def current(tool_version: Any, version: str) -> bool:
    """Evidence counts while its tool version has the tool's major and minor (DVER-043)."""
    a, b = SEMVER.match(str(tool_version)), SEMVER.match(version)
    return bool(a and b and a.group(1, 2) == b.group(1, 2))


def minor(version: str) -> str:
    parts = str(version).split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else str(version)


def support_matrix(facts: Facts, lang: str) -> str:
    t = TEXT[lang]
    shipped = {o for o, _ in facts.platforms()}
    labels = {c["label"]: f"{c['emoji']} {c['label']}" for c in facts.contract["compatibility_labels"]}
    modes = [m for m in ("file", "session", "device") if m in facts.modes]
    rows: dict[tuple[str, str, str], str] = {}
    for _, record in live_records(facts):
        if record.get("tool") != facts.tool or not current(record.get("tool_version"), facts.version):
            continue
        app = minor((record.get("application") or {}).get("version", ""))
        platform = record.get("platform")
        for mode in modes:
            runs = [r for r in record.get("runs", []) if r.get("mode") == mode]
            if not runs or platform not in NPM_OS:
                continue
            key = (app, platform, mode)
            ok = all(r.get("result") == "pass" for r in runs)
            if NPM_OS[platform] not in shipped:
                rows[key] = "unsupported"
            elif ok:
                rows[key] = "verified"
            else:
                rows.setdefault(key, "untested")
    declared = str(facts.driver.get("versions", ""))
    for platform in ("windows", "macos", "linux"):
        for mode in modes:
            if not any(k[1] == platform and k[2] == mode for k in rows):
                rows[(declared, platform, mode)] = "untested" if NPM_OS[platform] in shipped else "unsupported"
    names = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}

    def order(key: tuple[str, str, str]) -> tuple[Any, ...]:
        app, platform, mode = key
        nums = tuple(-int(p) for p in app.split(".") if p.isdigit()) if re.fullmatch(r"[0-9.]+", app) else (1,)
        return (app == declared, nums, ["windows", "macos", "linux"].index(platform), modes.index(mode))

    lines = [f"| {' | '.join(t['matrix'])} |", "|---|---|---|---|"]
    for key in sorted(rows, key=order):
        lines.append(f"| {key[0]} | {names[key[1]]} | {key[2]} | {labels[rows[key]]} |")
    return "\n".join(lines)


def evidence_index(facts: Facts, lang: str) -> str:
    t = TEXT[lang]
    records = sorted(live_records(facts), key=lambda r: str(r[1].get("recorded_at", "")), reverse=True)
    if not records:
        return t["no_records"]
    lines = [f"| {' | '.join(t['evidence'])} |", "|---|---|---|---|---|"]
    for path, record in records:
        runs = record.get("runs", [])
        passed = sum(1 for r in runs if r.get("result") == "pass")
        app = record.get("application") or {}
        lines.append(f"| [{path.name}](evidence/{path.name}) | {record.get('recorded_at', '')} | "
                     f"{app.get('name', '')} {app.get('version', '')} | {record.get('platform', '')} | "
                     f"{t['passed'].format(p=passed, n=len(runs))} |")
    return "\n".join(lines)


def knowledge_entries(facts: Facts) -> list[tuple[Path, dict[str, Any], str]]:
    folder = facts.root / "knowledge"
    parse = runtime_front_matter()
    out = []
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        try:
            front, body = parse(read(path))
        except (OSError, ValueError):
            front, body = {}, ""
        out.append((path, front, body))
    return out


def runtime_front_matter() -> Any:
    """The front matter parser of the driver runtime in this release."""
    sys.path.insert(0, str(BUNDLE / "sdk" / "python"))
    try:
        from _driver.knowledge import front_matter as parse
    finally:
        sys.path.pop(0)
    return parse


def skills(facts: Facts) -> list[tuple[Path, dict[str, Any], str, int]]:
    folder = facts.root / "skills"
    out = []
    for path in sorted(folder.glob("*/SKILL.md")) if folder.is_dir() else []:
        try:
            front, body, length = front_matter(read(path))
        except (OSError, ValueError):
            front, body, length = {}, read(path), 0
        out.append((path, front, body, length))
    return out


def skill_commands(facts: Facts) -> dict[str, list[dict[str, Any]]]:
    """The commands each Skill owns: the domain Skills' lists, the rest to the entry Skill."""
    by_path = {c["path"]: c for c in facts.commands}
    owned: dict[str, list[dict[str, Any]]] = {}
    claimed: set[str] = set()
    for path, front, _, _ in skills(facts):
        name = path.parent.name
        if name == facts.tool:
            continue
        listed = (front.get("metadata") or {}).get("commands") or []
        owned[name] = [by_path[p] for p in listed if p in by_path]
        claimed.update(listed)
    owned[facts.tool] = [c for c in facts.commands if c["path"] not in claimed]
    return owned


def generate(facts: Facts) -> dict[Path, str]:
    """Every generated file or region, as the full new text of each file."""
    root = facts.root
    out: dict[Path, str] = {}
    if facts.registration is not None:
        out[root / "contract" / "commands.json"] = json.dumps(facts.registration, indent=2) + "\n"
    if facts.reference is None:
        return out
    fills = {
        "README.md": {"badges": badges(facts), "info-card": info_card(facts, "en"), "command-map": command_map(facts.commands)},
        "README_zh.md": {"badges": badges(facts), "info-card": info_card(facts, "zh"), "command-map": command_map(facts.commands)},
        "SECURITY.md": {"risk": risk_block(facts, "en")},
        "SECURITY_zh.md": {"risk": risk_block(facts, "zh")},
        "docs/COMPATIBILITY.md": {"support-matrix": support_matrix(facts, "en")},
        "docs/COMPATIBILITY_zh.md": {"support-matrix": support_matrix(facts, "zh")},
        "docs/E2E.md": {"evidence": evidence_index(facts, "en")},
        "docs/E2E_zh.md": {"evidence": evidence_index(facts, "zh")},
    }
    owned = skill_commands(facts)
    for path, _, _, _ in skills(facts):
        fills[path.relative_to(root).as_posix()] = {"command-map": command_map(owned.get(path.parent.name, []))}
    project = facts.contract["project"]
    for english, names in FIXED.items():
        for lang_file in (english, english[:-3] + "_zh.md"):
            template = template_text(lang_file, facts)
            for name in names if template is not None else []:
                heading = name if lang_file == english else project["sections_zh"][english][project["sections"][english].index(name)]
                body = section_body(template, heading)
                if body is not None:
                    fills.setdefault(lang_file, {})[f"section:{heading}"] = body
    for name, regions in fills.items():
        path = root / name
        if not path.is_file():
            continue
        text = read(path)
        for region_name, content in regions.items():
            if region_name.startswith("section:"):
                if section_body(text, region_name[8:]) is not None and section_body(text, region_name[8:]) != content:
                    text = set_section(text, region_name[8:], content)
            else:
                text = set_region(text, region_name, content)
        out[path] = text
    manifest = plugin_manifest(facts)
    if manifest is not None:
        out[root / "plugin" / "manifest.json"] = manifest
    return out


def matrix_commands(facts: Facts) -> dict[str, dict[str, Any]]:
    """The commands that need a behavior matrix: every domain command, and every standard
    command whose adapter capabilities the tool implements (DVER-030)."""
    builtin = {c["path"] for c in facts.contract["builtin_commands"]}
    implemented = facts.implemented()
    return {c["path"]: c for c in facts.commands
            if c["path"] in facts.domain_paths
            or (c["path"] not in builtin and c.get("capabilities") and set(c["capabilities"]) <= implemented)}


def plugin_manifest(facts: Facts) -> str | None:
    """plugin/manifest.json: the tool version, the protocol version and the SHA-256 of every
    file the install copies, with the instance-side methods the author lists (DCLI-240)."""
    folder = facts.root / "plugin"
    if not facts.host_component or not folder.is_dir():
        return None
    path = folder / "manifest.json"
    try:
        methods = json.loads(read(path)).get("methods", []) if path.is_file() else []
    except ValueError:
        methods = []
    # plugin/source/ holds code that is built into the installed files; it is not installed.
    files = {p.relative_to(folder).as_posix(): digest(p) for p in sorted(folder.rglob("*"))
             if p.is_file() and p.name not in ("manifest.json", "README.md") and "__pycache__" not in p.parts
             and p.relative_to(folder).parts[0] != "source"}
    data = {"version": facts.version, "protocol_version": facts.contract["host_protocol"]["version"],
            "files": files, "methods": methods if isinstance(methods, list) else []}
    return json.dumps(data, indent=2) + "\n"


def command_facts(facts: Facts, command: dict[str, Any]) -> dict[str, bool]:
    """The values of a behavior matrix row's ``applies_when``, for one command."""
    flags = {f["name"] for f in command.get("flags", [])}
    return {"always": True, "writes": any(e != "observe" for e in command.get("effects", [])),
            "session": "session" in command.get("modes", []), "device": "device" in command.get("modes", []),
            "documents": "--doc" in flags or command.get("path", "").split(" ")[0] == "doc",
            "host_component": facts.host_component and bool(command.get("capabilities"))}


SKELETON_CODES = {"invalid_input": "E_USAGE", "not_found": "E_NOT_FOUND", "ambiguous": "E_AMBIGUOUS", "conflict": "E_CONFLICT",
                  "no_scope": "E_FORBIDDEN", "busy": "E_BUSY", "dialog": "E_HUMAN_REQUIRED", "read_back_mismatch": "E_VERIFY_FAILED"}
CONDITION_TEXT = {"writes": "changes something", "session": "works in session mode", "device": "works in device mode",
                  "documents": "acts on a document", "host_component": "reaches the application through the host component"}


def matrix_skeleton(facts: Facts, command: dict[str, Any]) -> str:
    """A first behavior matrix for a command that has none. The rows whose condition holds
    get placeholders for their arguments, so the author fills each one in (DREPO-019)."""
    exits = {e["code"]: e["exit"] for e in facts.contract["error_codes"]}
    holds = command_facts(facts, command)
    rows = []
    for spec in facts.contract["behavior_matrix_rows"]:
        name = spec["row"]
        if not any(holds.get(w) for w in spec["applies_when"]):
            reason = " or ".join(CONDITION_TEXT.get(w, w) for w in spec["applies_when"])
            rows.append({"row": name, "applies": False, "reason": f"This row applies only to a command that {reason}."})
            continue
        code = SKELETON_CODES.get(name)
        if name == "disconnect":
            code = "E_OUTCOME_UNKNOWN" if holds["writes"] else "E_BACKEND_UNAVAILABLE"
        expected = {"exit": exits[code], "code": code} if code else {"exit": 0}
        what = "the write sample" if name == "normal" and holds["writes"] else f"the arguments of the {name} situation"
        rows.append({"row": name, "applies": True,
                     "arguments": ["{{fill: %s; name every target only with the sample placeholders}}" % what],
                     "expected": expected})
    return json.dumps({"command": command["path"], "rows": rows}, indent=2, ensure_ascii=False) + "\n"


def fix(facts: Facts) -> list[Path]:
    written = []
    for path, text in generate(facts).items():
        old = read(path) if path.is_file() else None
        if old != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            written.append(path)
    folder = facts.root / "tests" / "matrix"
    for path, command in matrix_commands(facts).items() if facts.reference is not None else []:
        matrix = folder / (path.replace(" ", "-") + ".json")
        if not matrix.exists():
            folder.mkdir(parents=True, exist_ok=True)
            matrix.write_text(matrix_skeleton(facts, command), encoding="utf-8", newline="\n")
            written.append(matrix)
    return written


# ------------------------------------------------------------------ checks


class Checker:
    def __init__(self, facts: Facts) -> None:
        self.facts = facts
        self.root = facts.root
        self.contract = facts.contract
        self.problems: list[Problem] = []
        self._validators: dict[str, Any] = {}
        self._questions: dict[str, tuple[dict[str, Any], str]] | None = None

    def add(self, clause: str, path: str, message: str, line: int | None = None) -> None:
        self.problems.append(Problem(clause, path, message, line))

    def text(self, name: str) -> str | None:
        path = self.root / name
        try:
            return read(path)
        except (OSError, UnicodeDecodeError):
            return None

    def validate(self, instance: Any, schema: str) -> list[str]:
        if schema not in self._validators:
            from jsonschema import Draft202012Validator
            from referencing import Registry, Resource

            registry = Registry()
            schemas = {}
            for path in sorted((BUNDLE / "contract" / "schemas").glob("*.schema.json")):
                data = json.loads(read(path))
                schemas[path.name] = data
                resource = Resource.from_contents(data)
                registry = registry.with_resource(data["$id"], resource).with_resource(path.name, resource)
            for name, data in schemas.items():
                self._validators[name] = Draft202012Validator(data, registry=registry)
        errors = sorted(self._validators[schema].iter_errors(instance), key=lambda e: list(e.absolute_path))
        return [f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message[:200]}" for e in errors]

    def run(self) -> list[Problem]:
        if not self.facts.tool:
            self.add("DREPO-053", "package.json", "package.json must name exactly one command in `bin`")
        if self.facts.tool_error:
            self.add("DREPO-031", f"{self.facts.pkg}/", f"the tool could not run to report its commands: {self.facts.tool_error}")
        for step in (self.layout, self.documents, self.generated, self.placeholders, self.labels, self.pinned,
                     self.versions, self.platforms, self.survey, self.skills, self.knowledge, self.matrices,
                     self.evidence):
            step()
        return self.problems

    # -------------------------------------------------------------- layout (DREPO-001 to DREPO-004)

    def layout(self) -> None:
        project = self.contract["project"]
        for name in project["root_files"]:
            if not (self.root / name).is_file():
                self.add("DREPO-002", name, "this root file is missing")
        for entry in sorted(self.root.iterdir()):
            if entry.is_file() and entry.name not in project["root_files"] and not entry.name.startswith(".") \
                    and entry.name not in ROOT_CONFIG and not entry.name.endswith(ROOT_CONFIG_SUFFIXES) \
                    and not re.fullmatch(r"requirements[\w.-]*\.txt", entry.name) and entry.name not in JUNK:
                self.add("DREPO-003", entry.name, "only the root files, build configuration and tool configuration may sit at the root")
        for name in project["required_paths"]:
            path = self.root / name
            if not (path.is_dir() if name.endswith("/") else path.is_file()):
                self.add("DREPO-004", name, "this required path is missing")
        pkg = self.facts.pkg
        if pkg and not (self.root / pkg / "_driver" / project["runtime_manifest"]).is_file():
            self.add("DREPO-004", f"{pkg}/_driver/{project['runtime_manifest']}", "the runtime and its manifest are missing")
        for sub in ("commands", "adapter"):
            if pkg and not (self.root / pkg / sub).is_dir():
                self.add("DREPO-001", f"{pkg}/{sub}/", "domain commands live in commands/ and the adapter in adapter/")
        plugin = (self.root / "plugin").is_dir()
        if self.facts.reference is not None and plugin != self.facts.host_component:
            self.add("DREPO-004", "plugin/", "plugin/ exists exactly when the tool has a host component")
        stable = [c["path"] for c in self.facts.commands if c["path"] in self.facts.domain_paths and c.get("maturity") == "stable"]
        if stable and not (self.root / "tests" / "eval").is_dir():
            self.add("DREPO-004", "tests/eval/", f"commands marked stable need evaluation questions: {', '.join(stable)}")

    # -------------------------------------------------------------- documents (DREPO-010 to DREPO-018)

    def documents(self) -> None:
        project = self.contract["project"]
        for english in project["bilingual_files"]:
            chinese = english[:-3] + "_zh.md"
            en, zh = self.text(english), self.text(chinese)
            if zh is None and (self.root / chinese).exists() is False:
                self.add("DREPO-010", chinese, "the Chinese file of this pair is missing")
            if en is None or zh is None:
                continue
            self.pair(english, chinese, en, zh)
        self.readme_title()
        self.fixed_text()
        self.changelog()

    def pair(self, english: str, chinese: str, en: str, zh: str) -> None:
        project = self.contract["project"]
        wanted_en = list(project["sections"].get(english, []))
        wanted_zh = list(project["sections_zh"].get(english, []))
        optional = project.get("optional_sections", {}).get(english, {})
        conditions = {"host_component": self.facts.host_component, "device_mode": "device" in self.facts.modes}
        for name, condition in optional.items():
            if self.facts.reference is not None and not conditions[condition]:
                index = wanted_en.index(name)
                wanted_en.pop(index)
                wanted_zh.pop(index)
        got_en, got_zh = sections(en), sections(zh)
        if wanted_en:
            self.order(english, [h for h, _, _ in got_en], wanted_en)
            self.order(chinese, [h for h, _, _ in got_zh], wanted_zh)
        elif len(got_en) != len(got_zh):
            self.add("DREPO-010", chinese, f"{len(got_zh)} sections, but {english} has {len(got_en)}")
        for (h_en, _, body_en), (h_zh, line, body_zh) in zip(got_en, got_zh):
            if table_rows(body_en) != table_rows(body_zh):
                self.add("DREPO-010", chinese, f"section {h_zh} has {table_rows(body_zh)} table rows, but {h_en} in "
                         f"{english} has {table_rows(body_en)}", line)
        name_en, name_zh = Path(english).name, Path(chinese).name
        switch_en = f"English | [中文]({name_zh})"
        switch_zh = f"[English]({name_en}) | 中文"
        for path, text, switch in ((english, en, switch_en), (chinese, zh, switch_zh)):
            lines = [line.strip() for line in text.split("\n")]
            if english == "README.md":
                if switch not in lines:
                    self.add("DREPO-011", path, f"the title area needs the language switch line `{switch}`")
            elif len(lines) < 3 or not lines[0].startswith("# ") or next((x for x in lines[1:] if x), "") != switch:
                self.add("DREPO-010", path, f"the first line after the title must be `{switch}`")

    def order(self, path: str, got: list[str], wanted: list[str]) -> None:
        if got != wanted:
            self.add(f"DREPO-0{self.clause_of(path)}", path, f"the `##` sections must be exactly {wanted}, in this order; found {got}")

    @staticmethod
    def clause_of(path: str) -> str:
        base = path.replace("_zh.md", ".md")
        return {"README.md": "11", "AGENTS.md": "12", "SECURITY.md": "13", "CONTRIBUTING.md": "14",
                "docs/APPLICATION.md": "15", "docs/COMPATIBILITY.md": "16", "docs/E2E.md": "17"}.get(base, "10")

    def readme_title(self) -> None:
        for name, switch in (("README.md", "English | [中文](README_zh.md)"), ("README_zh.md", "[English](README.md) | 中文")):
            text = self.text(name)
            if text is None:
                continue
            lines = text.split("\n")
            head = lines[: next((i for i, line in enumerate(lines) if line.startswith("## ")), len(lines))]
            content = [line.strip() for line in head if line.strip()]
            if not content or content[0] != f"# {self.facts.tool}":
                self.add("DREPO-011", name, f"the README starts with the title `# {self.facts.tool}`")
                continue
            start_b, end_b = region("badges")
            start_i, end_i = region("info-card")
            try:
                order = [content.index(start_b), content.index(end_b), content.index(switch), content.index(start_i),
                         content.index(end_i)]
            except ValueError:
                self.add("DREPO-011", name, "the title area is the title, the pitch, the badge row, the language switch "
                         "line and the info card, in this order")
                continue
            pitch = content[1:order[0]]
            if order != sorted(order) or len(pitch) != 1:
                self.add("DREPO-011", name, "the title area is the title, a one-line pitch, the badge row, the language "
                         "switch line and the info card, in this order")

    def fixed_text(self) -> None:
        """Sections whose text comes from the template (DREPO-011, DREPO-012, DREPO-013, DREPO-054)."""
        if self.facts.reference is None:
            return
        project = self.contract["project"]
        for english, names in FIXED.items():
            for lang_file in (english, english[:-3] + "_zh.md"):
                text, template = self.text(lang_file), template_text(lang_file, self.facts)
                if text is None or template is None:
                    continue
                for name in names:
                    heading = name if lang_file == english else \
                        project["sections_zh"][english][project["sections"][english].index(name)]
                    have, want = section_body(text, heading), section_body(template, heading)
                    if want is not None and have != want:
                        clause = "DREPO-054" if name == "Install" else f"DREPO-0{self.clause_of(english)}"
                        self.add(clause, lang_file, f"section {heading} must keep the template's fixed text; "
                                 "copy it from the template unchanged")

    def changelog(self) -> None:
        text = self.text("CHANGELOG.md")
        if text is None:
            return
        allowed = self.contract["project"]["changelog_sections"]
        heads = []
        group_index = -1
        for number, line in enumerate(text.split("\n"), 1):
            if CJK.search(line):
                self.add("DREPO-018", "CHANGELOG.md", "the CHANGELOG is English only", number)
            if line.startswith("## "):
                heads.append((line[3:].strip(), number))
                group_index = -1
            elif line.startswith("### "):
                name = line[4:].strip()
                if name not in allowed:
                    self.add("DREPO-018", "CHANGELOG.md", f"subsection {name!r} is not one of {allowed}", number)
                elif allowed.index(name) <= group_index:
                    self.add("DREPO-018", "CHANGELOG.md", f"subsections follow the order {allowed}", number)
                else:
                    group_index = allowed.index(name)
        if not heads or heads[0][0] != "[Unreleased]":
            self.add("DREPO-018", "CHANGELOG.md", "`## [Unreleased]` is the first section")
        releases = []
        for head, number in heads[1:]:
            match = re.fullmatch(r"\[([^\]]+)\] - ([0-9]{4}-[0-9]{2}-[0-9]{2})", head)
            if not match or not SEMVER.match(match.group(1)):
                self.add("DREPO-018", "CHANGELOG.md", f"a release section is `## [X.Y.Z] - YYYY-MM-DD`, not {head!r}", number)
            else:
                releases.append(match.group(1))
        keys = [semver_key(v) for v in releases]
        if keys != sorted(keys, reverse=True):
            self.add("DREPO-018", "CHANGELOG.md", "release sections are newest first")
        if releases and releases[0] != self.facts.version:
            self.add("DREPO-040", "CHANGELOG.md", f"the newest release section is {releases[0]}, but package.json says "
                     f"{self.facts.version}")

    # -------------------------------------------------------------- generated content

    def generated(self) -> None:
        if self.facts.reference is None:
            return
        clauses = {"commands.json": "DREPO-031", "README.md": "DREPO-020", "README_zh.md": "DREPO-020",
                   "SECURITY.md": "DSEC-002", "SECURITY_zh.md": "DSEC-002", "COMPATIBILITY.md": "DREPO-016",
                   "COMPATIBILITY_zh.md": "DREPO-016", "E2E.md": "DREPO-017", "E2E_zh.md": "DREPO-017",
                   "SKILL.md": "DSKL-006", "manifest.json": "DCLI-240"}
        for path, text in generate(self.facts).items():
            name = path.relative_to(self.root).as_posix()
            old = read(path) if path.is_file() else None
            if old is None:
                self.add(clauses.get(path.name, "DREPO-023"), name, "this generated file is missing; run `python scripts/spec.py generate`")
                continue
            base = name.replace("_zh.md", ".md")
            for region_name in REGIONS.get(base, ["command-map"] if path.name == "SKILL.md" else []):
                if get_region(old, region_name) is None:
                    self.add(clauses.get(path.name, "DREPO-023"), name, f"the region `{region(region_name)[0]}` ... "
                             f"`{region(region_name)[1]}` must appear once")
            if old != text:
                which = [r for r in REGIONS.get(base, ["command-map"]) if get_region(old, r) != get_region(text, r)] \
                    if path.suffix == ".md" else []
                clause = {"badges": "DREPO-020", "info-card": "DREPO-021", "command-map": "DSKL-006", "risk": "DSEC-002",
                          "support-matrix": "DREPO-016", "evidence": "DREPO-017"}.get(which[0] if which else "",
                                                                                      clauses.get(path.name, "DREPO-023"))
                self.add(clause, name, f"generated content is out of date ({', '.join(which) or path.name}); "
                         "run `python scripts/spec.py generate`")
        if self.facts.registration is not None and not self.facts.registration.get("commands"):
            self.add("DCLI-029", "contract/commands.json", f"no domain command is registered yet; register them in "
                     f"{self.facts.pkg}/commands/ (DCLI-029), then run `python scripts/spec.py generate`")
        elif self.facts.registration is not None:
            for message in self.validate(self.facts.registration, "commands.schema.json"):
                self.add("DREPO-031", "contract/commands.json", f"does not validate against commands.schema.json: {message}")

    def placeholders(self) -> None:
        """No template leftovers anywhere in the project (DREPO-019)."""
        for path in self.files():
            rel = path.relative_to(self.root).as_posix()
            try:
                text = read(path)
            except (OSError, UnicodeDecodeError):
                continue
            for number, line in enumerate(text.split("\n"), 1):
                for match in LEFTOVER.finditer(line):
                    self.add("DREPO-019", rel, f"template placeholder left: {match.group(0)}", number)

    def files(self) -> list[Path]:
        """The project's own files: no pinned copies, no build output, no version control."""
        pinned = {".agent", "licenses", f"{self.facts.pkg}/_driver", "contract/driver-contract.json"}
        out = []
        for folder, dirs, names in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in names:
                path = Path(folder) / name
                rel = path.relative_to(self.root).as_posix()
                if not any(rel == p or rel.startswith(p + "/") for p in pinned):
                    out.append(path)
        return sorted(out)

    def labels(self) -> None:
        """Only the series' badges (DREPO-024)."""
        for path in self.files():
            if path.suffix != ".md":
                continue
            rel = path.relative_to(self.root).as_posix()
            try:
                text = read(path)
            except (OSError, UnicodeDecodeError):
                continue
            outside = text
            for name in ("badges", "support-matrix"):
                inside = get_region(text, name)
                if inside:
                    outside = outside.replace(inside, "")
            marks = [f"{c['emoji']} {c['label']}" for c in self.contract["compatibility_labels"]]
            for number, line in enumerate(outside.split("\n"), 1):
                if re.search(r"!\[[^\]]*\]\([^)]*(shields\.io|badge)[^)]*\)|<img[^>]+(shields\.io|badge)", line, re.I):
                    self.add("DREPO-024", rel, "badges appear only in the README badge row", number)
                elif any(mark in line for mark in marks) and (line.lstrip().startswith("|") or "COMPATIBILITY" not in rel):
                    self.add("DREPO-022", rel, "compatibility labels appear only in the generated support matrix", number)

    # -------------------------------------------------------------- pinned copies (DREPO-030 to DREPO-034)

    def pinned(self) -> None:
        release = bundle_version()
        spec_version = self.facts.spec_version
        if not spec_version:
            self.add("DREPO-030", ".agent/SPEC_VERSION", "the pinned specification version is missing")
            return
        if read(self.root / ".agent" / "SPEC_VERSION") != spec_version + "\n":
            self.add("DREPO-030", ".agent/SPEC_VERSION", "the file holds the version number as its only line")
        if spec_version != release:
            self.add("DREPO-034", ".agent/SPEC_VERSION", f"the project pins {spec_version}, but this check comes from "
                     f"release {release}; run the check of the pinned release (`python scripts/spec.py check`)")
            return
        for source, dest in pinned_files(self.facts.pkg):
            clause = pinned_clause(dest)
            path = self.root / dest
            if not path.is_file():
                self.add(clause, dest, "this pinned file is missing; run `python scripts/spec.py sync <version>`")
            elif digest(path) != digest(source):
                self.add(clause, dest, f"differs from release {release}; pinned copies are never edited (DREPO-034)")
        runtime = {digest(source) for source, dest in pinned_files(self.facts.pkg) if dest.endswith(".py")}
        for path in self.files():
            rel = path.relative_to(self.root).as_posix()
            if path.suffix == ".py" and path.stat().st_size > 200 and digest(path) in runtime:
                self.add("DREPO-034", rel, "a copy of a runtime file outside the pinned runtime; import the runtime from "
                         f"{self.facts.pkg}/_driver/ instead")
        expected = {dest for _, dest in pinned_files(self.facts.pkg)}
        for folder in (".agent", "licenses", f"{self.facts.pkg}/_driver"):
            base = self.root / folder
            for path in sorted(base.rglob("*")) if base.is_dir() else []:
                rel = path.relative_to(self.root).as_posix()
                if path.is_file() and "__pycache__" not in path.parts and rel not in expected and path.name not in JUNK \
                        and rel not in (".agent/SPEC_VERSION", ".agent/SPEC_SHA256", f"{self.facts.pkg}/_driver/MANIFEST.json"):
                    self.add(pinned_clause(rel), rel, "this file is not part of the pinned release")
        manifest_path = self.root / self.facts.pkg / "_driver" / "MANIFEST.json"
        try:
            manifest = json.loads(read(manifest_path))
        except (OSError, ValueError):
            manifest = None
        if manifest != runtime_manifest(release):
            self.add("DREPO-032", f"{self.facts.pkg}/_driver/MANIFEST.json", "the manifest does not record the release and "
                     "the hash of every runtime file; run `python scripts/spec.py sync <version>`")

    # -------------------------------------------------------------- versions (DREPO-040, DREPO-053)

    def versions(self) -> None:
        version = self.facts.version
        if not SEMVER.match(version):
            self.add("DREPO-040", "package.json", f"version {version!r} is not SemVer")
        for name, value in (self.facts.package.get("optionalDependencies") or {}).items():
            if value != version:
                self.add("DREPO-040", "package.json", f"platform package {name} is at {value}, not {version}")
        pyproject = self.text("pyproject.toml")
        if pyproject:
            match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproject)
            if match and match.group(1) != version:
                self.add("DREPO-053", "pyproject.toml", f"version {match.group(1)} differs from package.json {version}")
        if self.facts.reference is not None and self.facts.reference.get("version") != version:
            self.add("DREPO-040", "package.json", "the tool reports another version than package.json")
        scripts = self.facts.package.get("scripts") or {}
        for hook in ("preinstall", "install", "postinstall"):
            if hook in scripts:
                self.add("DSEC-072", "package.json", f"npm packages have no install scripts; remove `{hook}`")

    # -------------------------------------------------------------- platforms (DREPO-051, DREPO-052)

    def platforms(self) -> None:
        package = self.facts.package.get("name", "")
        for name in self.facts.package.get("optionalDependencies") or {}:
            if not re.fullmatch(re.escape(package) + r"-(win32|darwin|linux)-(x64|arm64)", name):
                self.add("DREPO-051", "package.json", f"{name} is not a platform package `<package>-<os>-<cpu>`")
        shipped = self.facts.platforms()
        if not shipped:
            self.add("DREPO-051", "package.json", "list at least one platform package in optionalDependencies")
        for os_name in {o for o, _ in shipped}:
            if (os_name, "x64") not in shipped:
                self.add("DREPO-052", "package.json", f"{OS_NAMES[os_name]} is shipped, so it needs an x64 platform package")
        surveyed = self.survey_platforms()
        if surveyed is None:
            self.add("DREPO-052", "docs/APPLICATION.md", "the Application section needs the table of operating systems and "
                     "CPU architectures")
            return
        for os_name, cpu in shipped:
            if (os_name, cpu) not in surveyed:
                self.add("DREPO-052", "package.json", f"{OS_NAMES[os_name]} {cpu} is shipped, but the capability survey "
                         "does not list it")

    def survey_platforms(self) -> set[tuple[str, str]] | None:
        text = self.text("docs/APPLICATION.md")
        if text is None:
            return None
        body = next((b for h, _, b in sections(text) if h == "Application"), None)
        if body is None:
            return None
        for table in tables(body):
            if [c.lower() for c in table[0][:2]] == ["operating system", "cpu architectures"]:
                out = set()
                for row in table[1:]:
                    name = OS_KEYS.get(row[0])
                    if name is None:
                        self.add("DREPO-052", "docs/APPLICATION.md", f"{row[0]!r} is not Windows, macOS or Linux")
                        continue
                    for cpu in (c.strip() for c in row[1].split(",")):
                        if cpu not in ("x64", "arm64"):
                            self.add("DREPO-052", "docs/APPLICATION.md", f"{cpu!r} is not x64 or arm64")
                        out.add((NPM_OS[name], cpu))
                return out
        return None

    # -------------------------------------------------------------- capability survey (DREPO-060)

    def survey(self) -> None:
        text = self.text("docs/APPLICATION.md")
        if text is None:
            return
        body = next((b for h, _, b in sections(text) if h == "Capabilities"), None)
        table = next((t for t in tables(body or []) if [c.lower() for c in t[0][:1]] == ["id"]), None)
        if table is None:
            self.add("DREPO-060", "docs/APPLICATION.md", "the Capabilities section needs the capability table "
                     "`| ID | Capability | Interface | Disposition | Reason |`")
            return
        header = [c.lower() for c in table[0]]
        if "disposition" not in header:
            self.add("DREPO-060", "docs/APPLICATION.md", "the capability table needs a Disposition column")
            return
        column = header.index("disposition")
        pattern = re.compile(self.contract["project"]["capability_id_pattern"])
        dispositions = self.contract["project"]["capability_dispositions"]
        ids: list[str] = []
        for row in table[1:]:
            cap = row[0]
            if not pattern.match(cap):
                self.add("DREPO-060", "docs/APPLICATION.md", f"capability ID {cap!r} is not CAP-nnn")
            elif cap in ids:
                self.add("DREPO-060", "docs/APPLICATION.md", f"capability ID {cap} appears twice")
            ids.append(cap)
            value = row[column] if column < len(row) else ""
            if value not in dispositions:
                self.add("DREPO-060", "docs/APPLICATION.md", f"{cap} has disposition {value!r}, not one of {dispositions}")

    # -------------------------------------------------------------- Skills (DSKL-001 to DSKL-032)

    def skills(self) -> None:
        facts = self.facts
        entry = self.root / "skills" / facts.tool / "SKILL.md"
        if facts.tool and not entry.is_file():
            self.add("DSKL-022", f"skills/{facts.tool}/SKILL.md", "the entry Skill is missing")
        folder = self.root / "skills"
        for item in sorted(folder.iterdir()) if folder.is_dir() else []:
            if item.name in JUNK:
                continue
            if not item.is_dir():
                self.add("DSKL-032", f"skills/{item.name}", "skills/ holds only Skill directories")
            elif not [p for p in item.iterdir() if p.name == "SKILL.md"]:
                self.add("DSKL-001", f"skills/{item.name}/", "a Skill directory holds one SKILL.md, spelled so")
        readme = self.text("README.md")
        if readme and get_region(readme, "command-map") is not None:
            capabilities = section_body(readme, "Capabilities") or ""
            if region("command-map")[0] not in capabilities:
                self.add("DSKL-006", "README.md", "the command map belongs in the Capabilities section")
        paths = {c["path"] for c in facts.commands}
        claims: dict[str, list[str]] = {}
        recipe = self.entry_template_lines()
        names = {path.parent.name for path, *_ in skills(facts)}
        for path, front, body, _ in skills(facts):
            name = path.parent.name
            rel = path.relative_to(self.root).as_posix()
            folder = path.parent
            text = read(path)
            for extra in sorted(folder.iterdir()):
                if extra.name not in ("SKILL.md", "references"):
                    self.add("DSKL-032", f"{rel[:-8]}{extra.name}", "a Skill directory holds only SKILL.md and references/")
            refs = folder / "references"
            if refs.is_dir():
                for item in sorted(refs.iterdir()):
                    if item.is_dir():
                        self.add("DSKL-003", f"{rel[:-8]}references/{item.name}", "references/ has no subdirectories")
                    elif f"references/{item.name}" not in text:
                        self.add("DSKL-003", rel, f"SKILL.md must link references/{item.name}")
            if len(text.rstrip("\n").split("\n")) > self.contract["skill"]["max_lines"]:
                self.add("DSKL-003", rel, f"SKILL.md is longer than {self.contract['skill']['max_lines']} lines")
            if not front:
                self.add("DSKL-002", rel, "SKILL.md begins with front matter")
                continue
            meta = front.get("metadata") if isinstance(front.get("metadata"), dict) else {}
            if front.get("name") != name:
                self.add("DSKL-002", rel, f"`name` must be the directory name {name!r}")
            description = str(front.get("description", ""))
            if not description or not CJK.search(description) or not LATIN.search(description):
                self.add("DSKL-001", rel, "the description phrases the requests in both Chinese and English")
            if str(meta.get("version", "")) != facts.version:
                self.add("DSKL-030", rel, f"metadata.version must be the tool version {facts.version}")
            if name == facts.tool:
                if "commands" in meta or "replaced_by" in meta:
                    self.add("DSKL-002", rel, "only domain Skills carry metadata.commands, and only rename stubs metadata.replaced_by")
                self.playbooks(rel, body)
                continue
            if not facts.product or not name.startswith(facts.product + "-"):
                self.add("DSKL-023", rel, f"a domain Skill lives in skills/{facts.product}-<area>/")
            opening = next((x for x in body.splitlines() if x.strip() and not x.lstrip().startswith("#")), "")
            if "replaced_by" not in meta and facts.tool and facts.tool not in opening:
                self.add("DSKL-024", rel, f"the body starts by telling the Agent to read the entry Skill {facts.tool!r} first")
            listed = meta.get("commands")
            if "replaced_by" in meta:
                # A rename stub owns no commands and names the Skill to read instead (DSKL-026, DSKL-028).
                if meta["replaced_by"] not in names - {name}:
                    self.add("DSKL-028", rel, "metadata.replaced_by names another Skill of the tool")
                if "commands" in meta:
                    self.add("DSKL-028", rel, "a rename stub owns no commands")
                continue
            if not isinstance(listed, list) or not listed:
                self.add("DSKL-026", rel, "a domain Skill lists the commands it owns in metadata.commands")
                listed = []
            for command in listed:
                if facts.reference is not None and command not in paths:
                    self.add("DSKL-026", rel, f"`{command}` is not a command of the tool")
                claims.setdefault(command, []).append(name)
            area = name[len(facts.product) + 1:] if name.startswith(facts.product + "-") else name
            nouns = {w for c in listed for w in c.split(" ")[:-1]}
            if listed and area not in nouns:
                self.add("DSKL-027", rel, f"the area {area!r} must be a noun of a command the Skill owns")
            for line in body.split("\n"):
                if line.strip() and line.strip() in recipe:
                    self.add("DSKL-023", rel, "a domain Skill does not repeat the write recipe or the STOP checkpoints")
                    break
        for command, owners in sorted(claims.items()):
            if len(owners) > 1:
                self.add("DSKL-026", "skills/", f"`{command}` belongs to more than one Skill: {', '.join(owners)}")

    def entry_template_lines(self) -> set[str]:
        """Distinctive lines of the template's write recipe and STOP checkpoints."""
        text = template_text(f"skills/{{{{tool}}}}/SKILL.md", self.facts) if self.facts.reference is not None else None
        if text is None:
            return set()
        out = set()
        grab = False
        for line in text.split("\n"):
            if line.startswith("## "):
                grab = any(word in line.lower() for word in ("write recipe", "stop"))
                continue
            if grab and len(line.strip()) > 40:
                out.add(line.strip())
        return out

    def playbooks(self, rel: str, body: str) -> None:
        headings = {re.sub(r"[^a-z0-9]+", "_", line.lstrip("#").strip().lower()).strip("_")
                    for line in body.split("\n") if re.match(r"^#{2,4} ", line)}
        for playbook in self.contract["skill"]["driver_playbooks"]:
            if playbook == "physical_effects" and "device" not in self.facts.modes:
                if playbook in headings:
                    self.add("DSKL-009", rel, "only a tool with device mode includes the physical_effects playbook")
                continue
            if playbook not in headings:
                self.add("DSKL-009", rel, f"the entry Skill needs the driver playbook `{playbook}` as a heading")

    # -------------------------------------------------------------- knowledge (DSKL-120 to DSKL-127)

    def knowledge(self) -> None:
        kn = self.contract["knowledge"]
        entries = knowledge_entries(self.facts)
        ids: dict[str, str] = {}
        kinds = set()
        for path, front, body in entries:
            rel = path.relative_to(self.root).as_posix()
            if not front:
                self.add("DSKL-127", rel, "the entry begins with front matter")
                continue
            kind = front.get("kind")
            required = list(kn["builtin_fields"]) + (kn["rule_fields"] if kind == "rule" else []) + \
                (kn["resource_fields"] if kind == "resource" else [])
            for name in required:
                if name not in front or front[name] in ("", None):
                    self.add("DSKL-120", rel, f"front matter field `{name}` is missing")
            for name in kn["rule_fields"] + kn["resource_fields"]:
                if name in front and name not in required:
                    self.add("DSKL-120", rel, f"`{name}` belongs only to {'rule' if name in kn['rule_fields'] else 'resource'} entries")
            for name in front:
                if name not in kn["builtin_fields"] + kn["rule_fields"] + kn["resource_fields"]:
                    self.add("DSKL-120", rel, f"`{name}` is not a field of a builtin entry; remove it")
            if kind not in kn["kinds"]:
                self.add("DSKL-127", rel, f"kind {kind!r} is not one of {kn['kinds']}")
            kinds.add(kind)
            entry_id = str(front.get("id", ""))
            if not re.match(kn["id_pattern"], entry_id):
                self.add("DSKL-127", rel, f"id {entry_id!r} is lowercase words joined by hyphens")
            elif entry_id in ids:
                self.add("DSKL-127", rel, f"id {entry_id} is also used by {ids[entry_id]}")
            ids[entry_id] = rel
            if kind == "rule" and front.get("severity") not in kn["severities"]:
                self.add("DSKL-120", rel, f"severity is one of {kn['severities']}")
            if len(body.strip()) > kn["max_body_chars"]:
                self.add("DSKL-121", rel, f"the body is longer than {kn['max_body_chars']} characters; split the entry")
            for target in re.findall(r"\]\(([^)\s]+)\)", body):
                if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
                    continue
                if not (path.parent / target.split("#", 1)[0]).exists():
                    self.add("DSKL-127", rel, f"the link {target} does not resolve")
        for kind in kn["required_builtin_kinds"]:
            if kind not in kinds:
                self.add("DSKL-126", "knowledge/", f"builtin knowledge needs at least one `{kind}` entry")
        for command in self.facts.commands:
            for entry_id in command.get("related_knowledge", []) or []:
                if entry_id not in ids:
                    self.add("DSKL-124", "contract/commands.json", f"`{command['path']}` names related knowledge "
                             f"{entry_id!r}, which is not a builtin entry")

    # -------------------------------------------------------------- behavior matrices (DVER-030)

    def matrices(self) -> None:
        if self.facts.reference is None:
            return
        needs = matrix_commands(self.facts)
        folder = self.root / "tests" / "matrix"
        seen = set()
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            rel = path.relative_to(self.root).as_posix()
            try:
                matrix = json.loads(read(path))
            except (OSError, ValueError) as exc:
                self.add("DVER-030", rel, f"cannot read the matrix: {exc}")
                continue
            problems = self.validate(matrix, "behavior-matrix.schema.json")
            for message in problems:
                self.add("DVER-041", rel, f"does not validate against behavior-matrix.schema.json: {message}")
            if problems:
                if isinstance(matrix, dict) and isinstance(matrix.get("command"), str):
                    seen.add(matrix["command"])
                continue
            command = needs.get(matrix["command"])
            if command is None:
                self.add("DVER-030", rel, f"{matrix['command']} is not a command that needs a behavior matrix")
                continue
            seen.add(command["path"])
            if path.name != command["path"].replace(" ", "-") + ".json":
                self.add("DVER-030", rel, f"the file is named after the command: {command['path'].replace(' ', '-')}.json")
            facts = command_facts(self.facts, command)
            for row in matrix["rows"]:
                spec = next(r for r in self.contract["behavior_matrix_rows"] if r["row"] == row["row"])
                holds = any(facts.get(w) for w in spec["applies_when"])
                if row["applies"] and not holds:
                    self.add("DVER-030", rel, f"row {row['row']} applies only when {', '.join(spec['applies_when'])}")
                if row["row"] == "normal" and not row["applies"]:
                    self.add("DVER-030", rel, "the normal row always applies; for a write command it is the write sample (DVER-002)")
                if row["applies"] and "actual" in row and not same_result(row["actual"], row.get("expected")):
                    self.add("DVER-030", rel, f"row {row['row']} failed: expected {row.get('expected')}, got {row['actual']}")
                if row.get("evidence"):
                    problem = self.live_problem(row["evidence"], command["path"], row["row"])
                    if problem:
                        self.add("DVER-041", rel, f"row {row['row']}: {problem}")
        for path in sorted(set(needs) - seen):
            self.add("DVER-030", f"tests/matrix/{path.replace(' ', '-')}.json", f"`{path}` needs a behavior matrix; "
                     "`python scripts/spec.py generate` writes a first one")

    # -------------------------------------------------------------- evidence and maturity (DVER-040 to DVER-050)

    def evidence(self) -> None:
        folder = self.root / "docs" / "evidence"
        authorized = authorized_targets(self.root)
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            rel = path.relative_to(self.root).as_posix()
            try:
                data = json.loads(read(path))
            except (OSError, ValueError) as exc:
                self.add("DVER-042", rel, f"cannot read the record: {exc}")
                continue
            schema = "eval-report.schema.json" if path.name.startswith("eval-") else "evidence.schema.json"
            problems = self.validate(data, schema)
            for message in problems:
                self.add("DVER-042" if schema == "evidence.schema.json" else "DVER-041", rel,
                         f"does not validate against {schema}: {message}")
            if not problems and not data.get("simulated"):
                for target in data["targets"]:
                    if not any(target_covered(target, t) for t in authorized):
                        self.add("DVER-050", rel, f"target {target} is not listed under Authorized Targets in docs/E2E.md")
        if self.facts.reference is None:
            return
        for command in self.facts.commands:
            for ref in command.get("evidence", []) or []:
                self.reference_problem("contract/commands.json", ref)
        needs = matrix_commands(self.facts)
        stable = False
        for command in self.facts.commands:
            if command["path"] not in needs:
                continue
            level = command.get("maturity", "draft")
            refs = [str(r) for r in command.get("evidence", []) or []]
            if level in ("verified", "stable"):
                if not any(r.startswith("live:") and not self.live_problem(r, command["path"]) for r in refs):
                    self.add("DVER-040", "contract/commands.json", f"`{command['path']}` is {level}, which needs current "
                             "`live:` evidence of a passing run of this command (DVER-043)")
                self.matrix_passed(command)
            if level == "stable":
                stable = True
                reasons = [self.eval_problem(r, command["path"]) for r in refs if r.startswith("eval:")]
                if not reasons or all(reasons):
                    self.add("DSKL-043", "contract/commands.json", f"`{command['path']}` is stable, which needs a current "
                             "`eval:` report from the real application of every question in tests/eval/, all passed, "
                             f"among them one that lists and ran the command ({'; '.join(reasons) or 'none named'})")
        self.eval_questions(stable)

    def reference_problem(self, where: str, ref: str) -> None:
        match = re.fullmatch(r"([a-z]+):([^#]+)(?:#(.+))?", str(ref))
        kinds = self.contract["evidence_kinds"]
        if not match or match.group(1) not in kinds:
            self.add("DVER-041", where, f"evidence {ref!r} is not <kind>:<path>[#<anchor>] with a kind of {kinds}")
        elif not (self.root / match.group(2)).is_file():
            self.add("DVER-041", where, f"evidence {ref!r} names a file that does not exist")

    def _evidence_file(self, ref: str, kind: str) -> tuple[Any, str | None, str | None]:
        """The data a reference names, its anchor, and what is wrong with it."""
        match = re.fullmatch(r"([a-z]+):([^#]+)(?:#(.+))?", ref)
        if not match or match.group(1) != kind:
            return None, None, f"{ref!r} is not `{kind}:` evidence"
        path = match.group(2)
        folder = "docs/evidence/"
        is_eval = Path(path).name.startswith("eval-")
        if not path.startswith(folder) or "/" in path[len(folder):] or is_eval != (kind == "eval"):
            return None, None, f"{ref!r} does not name a {'report docs/evidence/eval-*.json' if kind == 'eval' else 'live record in docs/evidence/'}"
        try:
            data = json.loads(read(self.root / path))
        except (OSError, ValueError):
            return None, None, f"{ref!r} names no readable file"
        if self.validate(data, "eval-report.schema.json" if kind == "eval" else "evidence.schema.json"):
            return None, None, f"{ref!r} does not validate against its schema"
        if data["tool"] != self.facts.tool:
            return None, None, f"{ref!r} is a record of {data['tool']}, not {self.facts.tool}"
        if not current(data["tool_version"], self.facts.version):
            return None, None, f"{ref!r} is from {data['tool_version']}, not the current minor version (DVER-043)"
        return data, match.group(3), None

    def live_problem(self, ref: str, command: str, row: str | None = None) -> str | None:
        """Why a `live:` reference does not show a passing run of this command (and row)."""
        data, anchor, problem = self._evidence_file(str(ref), "live")
        if problem:
            return problem
        wanted = row or anchor
        runs = [r for r in data["runs"] if r["command"] == command and (wanted is None or r.get("matrix_row") == wanted)]
        if not runs:
            return f"{ref!r} has no run of `{command}`{' for row ' + wanted if wanted else ''}"
        if not all(r["result"] == "pass" for r in runs):
            return f"{ref!r} records a failed run of `{command}`"
        return None

    def eval_problem(self, ref: str, command: str) -> str | None:
        """Why an `eval:` reference does not show that Agents use this command correctly: the
        report must be the newest from the real application, cover every current question
        unchanged, pass all of them, and hold a question that lists and ran the command."""
        data, _, problem = self._evidence_file(str(ref), "eval")
        if problem:
            return problem
        if data["simulated"]:
            return f"{ref!r} is a run on the fake host; a simulated result is never evidence (DVER-021)"
        failed = [q["id"] for q in data["questions"] if not q["passed"]]
        if failed:
            return f"{ref!r}: questions failed: {', '.join(failed)}"
        asked = {q["id"]: q for q in data["questions"]}
        for question_id, (_, digest) in self.questions().items():
            if question_id not in asked:
                return f"{ref!r} has no result for the question {question_id} in tests/eval/"
            if asked[question_id]["sha256"] != digest:
                return f"{ref!r} ran an earlier version of the question {question_id}; run the evaluation again"
        if not any(command in q["commands"] and command in q["ran"] for q in data["questions"]):
            return f"{ref!r} has no question that lists `{command}` in COMMANDS and ran it"
        newer = self.newer_report(Path(str(ref)[len("eval:"):].split("#")[0]), data)
        return f"{ref!r} is not the newest evaluation report; {newer} is" if newer else None

    def newer_report(self, path: Path, data: dict[str, Any]) -> str | None:
        """A later report from the real application for the same minor version, if any."""
        mine = (data["date"], path.name)
        for other in sorted((self.root / "docs" / "evidence").glob("eval-*.json")):
            try:
                found = json.loads(read(other))
            except (OSError, ValueError):
                continue
            if self.validate(found, "eval-report.schema.json") or found["simulated"] or found["tool"] != self.facts.tool:
                continue
            if current(found["tool_version"], self.facts.version) and (found["date"], other.name) > mine:
                return other.relative_to(self.root).as_posix()
        return None

    def questions(self) -> dict[str, tuple[dict[str, Any], str]]:
        """The well-formed evaluation questions in tests/eval/, with their values and file hashes."""
        if self._questions is None:
            self._questions = {}
            for path in sorted((self.root / "tests" / "eval").glob("*.py")):
                if not path.name.startswith("_"):
                    values, _, problems = question_facts(path, self.contract)
                    if not problems:
                        self._questions[path.stem] = (values, digest(path))
        return self._questions

    def matrix_passed(self, command: dict[str, Any]) -> None:
        path = self.root / "tests" / "matrix" / (command["path"].replace(" ", "-") + ".json")
        try:
            matrix = json.loads(read(path))
        except (OSError, ValueError):
            return
        if self.validate(matrix, "behavior-matrix.schema.json"):
            return
        for row in matrix["rows"]:
            if not row["applies"] or row.get("unrunnable"):
                continue
            if "actual" not in row or not same_result(row["actual"], row.get("expected")) \
                    or self.live_problem(row.get("evidence", ""), command["path"], row["row"]):
                self.add("DVER-040", path.relative_to(self.root).as_posix(), f"`{command['path']}` is "
                         f"{command.get('maturity')}, but row {row['row']} has no current passing run")
        # The normal row passed on every kind of document the command lists (DVER-030, DVER-040).
        for kind in command.get("doc_kinds") or []:
            if not self.kind_passed(command["path"], kind):
                self.add("DVER-040", path.relative_to(self.root).as_posix(), f"`{command['path']}` is "
                         f"{command.get('maturity')}, but its normal row has no current passing run on a {kind}")

    def kind_passed(self, command: str, kind: str) -> bool:
        folder = self.root / "docs" / "evidence"
        for record in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            if record.name.startswith("eval-"):
                continue
            data, _, problem = self._evidence_file(f"live:docs/evidence/{record.name}", "live")
            if problem:
                continue
            if any(r["command"] == command and r.get("matrix_row") == "normal" and r.get("doc_kind") == kind
                   and r["result"] == "pass" for r in data["runs"]):
                return True
        return False

    def eval_questions(self, stable: bool) -> None:
        """Every question in tests/eval/ is well formed (DSKL-044); once a command is stable, the
        questions cover every per-tool scenario that applies to the tool (DSKL-042)."""
        facts = self.facts
        paths = {c["path"] for c in facts.commands}
        for path in sorted((self.root / "tests" / "eval").glob("*.py")):
            if not path.name.startswith("_"):
                for message in question_facts(path, self.contract)[2]:
                    self.add("DSKL-044", path.relative_to(self.root).as_posix(), message)
        covered = set()
        for question_id, (values, _) in self.questions().items():
            for command in values["COMMANDS"]:
                if command not in paths:
                    self.add("DSKL-044", f"tests/eval/{question_id}.py", f"COMMANDS names `{command}`, which is not a "
                             "command of the tool")
            covered.add(values["SCENARIO"])
        if not stable:
            return
        holds = {"always": True, "writes": any(any(e != "observe" for e in c.get("effects", [])) for c in facts.commands
                                               if c["path"] in facts.domain_paths),
                 "session": "session" in facts.modes, "device": "device" in facts.modes,
                 "dangerous": any(dangerous(c) for c in facts.commands if c["path"] in facts.domain_paths),
                 "jobs": any("job_status" in (c.get("capabilities") or []) for c in facts.commands),
                 "physical": any("physical" in c.get("effects", []) for c in facts.commands)}
        scenarios = self.contract["skill"]["eval_scenarios"]
        wanted = [s["scenario"] for group in scenarios.values() for s in group
                  if s.get("per_tool") and any(holds.get(w) for w in s["applies_when"])]
        for scenario in wanted:
            if scenario not in covered:
                self.add("DSKL-042", "tests/eval/", f"no evaluation question covers the scenario {scenario}")


QUESTION_ID = re.compile(r"[a-z0-9]+([-_][a-z0-9]+)*")


def question_facts(path: Path, contract: dict[str, Any]) -> tuple[dict[str, Any], set[str], list[str]]:
    """The values and functions an evaluation question defines, read without running it, and
    what is wrong with them (DSKL-044)."""

    try:
        tree = ast.parse(read(path), filename=str(path))
    except (OSError, SyntaxError, ValueError) as exc:
        return {}, set(), [f"cannot read the question: {exc}"]
    spec = contract["skill"]["eval_question"]
    names = {n["name"] for n in spec if n["kind"] == "value"}
    values: dict[str, Any] = {}
    functions: set[str] = set()
    problems = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in names:
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                problems.append(f"{node.targets[0].id} must be a literal value")
        elif isinstance(node, ast.FunctionDef):
            functions.add(node.name)
    for item in spec:
        if item["required"] and item["name"] not in (values if item["kind"] == "value" else functions):
            problems.append(f"the question defines no {item['name']}")
    if not QUESTION_ID.fullmatch(path.stem):
        problems.append("the file name is the question ID: lowercase words joined by hyphens or underscores")
    scenarios = [s["scenario"] for group in contract["skill"]["eval_scenarios"].values() for s in group]
    if "SCENARIO" in values and values["SCENARIO"] not in scenarios:
        problems.append(f"SCENARIO {values['SCENARIO']!r} is not one of {scenarios}")
    for name in ("COMMANDS", "TURNS"):
        value = values.get(name)
        if name in values and not (isinstance(value, list) and value and all(isinstance(v, str) and v.strip() for v in value)):
            problems.append(f"{name} is a list of one or more texts")
    scope = values.get("SCOPE")
    if "SCOPE" in values and scope is not None and not isinstance(scope, dict):
        problems.append("SCOPE is an object of scope file fields, or None for no scope file")
    elif isinstance(scope, dict) and set(scope) - set(contract["scope_file"]["fields"]):
        problems.append(f"SCOPE holds fields a scope file does not have: {sorted(set(scope) - set(contract['scope_file']['fields']))}")
    if "FAKE_HOST" in values and not isinstance(values["FAKE_HOST"], dict):
        problems.append("FAKE_HOST is an object")
    if "FILES" in values:
        files = values["FILES"]
        folder = path.parent / files if isinstance(files, str) else None
        if folder is None or not folder.is_dir() or not folder.resolve().is_relative_to(path.parent.resolve()):
            problems.append("FILES names a folder next to the question")
    return values, functions, problems


def authorized_targets(root: Path) -> list[str]:
    """The targets listed under Authorized Targets in docs/E2E.md (DVER-050)."""
    try:
        text = read(root / "docs" / "E2E.md")
    except OSError:
        return []
    body = next((b for h, _, b in sections(text) if h == "Authorized Targets"), [])
    return [m.group(1) for line in body if (m := re.match(r"^\s*[-*]\s+`([^`]+)`", line))]


def target_covered(target: str, authorized: str) -> bool:
    """A file URL inside an authorized folder, or the same target."""
    a, b = target.rstrip("/"), authorized.rstrip("/")
    if os.name == "nt" and a.startswith("file:"):
        a, b = a.lower(), b.lower()
    return a == b or (authorized.endswith("/") and a.startswith(b + "/"))


def same_result(actual: Any, expected: Any) -> bool:
    if not isinstance(actual, dict) or not isinstance(expected, dict):
        return False
    return actual.get("exit") == expected.get("exit") and actual.get("code") == expected.get("code")


def semver_key(version: str) -> tuple[Any, ...]:
    match = SEMVER.match(version)
    if not match:
        return (-1,)
    pre = match.group(4)
    parts: tuple[Any, ...] = tuple(int(match.group(i)) for i in (1, 2, 3))
    if pre is None:
        return parts + ((1,),)
    return parts + ((0,) + tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split(".")),)


# ------------------------------------------------------------------ the pinned release


def spec_files() -> list[Path]:
    return sorted((BUNDLE / "spec").glob("*.md"))


def runtime_files() -> list[Path]:
    folder = BUNDLE / "sdk" / "python" / "_driver"
    return sorted(p for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix == ".py")


def pinned_files(pkg: str) -> list[tuple[Path, str]]:
    """Each pinned file of the release and where it goes in a tool project."""
    out = [(path, f".agent/{path.name}") for path in spec_files()]
    out.append((BUNDLE / "contract" / "driver-contract.json", "contract/driver-contract.json"))
    runtime = BUNDLE / "sdk" / "python" / "_driver"
    out += [(path, f"{pkg}/_driver/{path.relative_to(runtime).as_posix()}") for path in runtime_files()]
    out += [(BUNDLE / "LICENSE", "licenses/tool-driver-cli-spec-LICENSE"),
            (BUNDLE / "NOTICE.md", "licenses/tool-driver-cli-spec-NOTICE.md")]
    return out


def pinned_clause(dest: str) -> str:
    if dest.startswith(".agent/"):
        return "DREPO-030"
    if dest.startswith("contract/"):
        return "DREPO-031"
    if dest.startswith("licenses/"):
        return "DREPO-033"
    return "DREPO-032"


def runtime_manifest(release: str) -> dict[str, Any]:
    runtime = BUNDLE / "sdk" / "python" / "_driver"
    return {"spec_version": release,
            "files": {p.relative_to(runtime).as_posix(): digest(p) for p in runtime_files()}}


# ------------------------------------------------------------------ main


def check(root: Path) -> list[Problem]:
    return Checker(gather(root)).run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", type=Path)
    parser.add_argument("--fix", action="store_true", help="write the generated content first")
    parser.add_argument("--json", action="store_true", help="print the problems as JSON")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    root = args.project.resolve()
    if args.fix:
        for path in fix(gather(root)):
            print(f"wrote {path.relative_to(root).as_posix()}")
    problems = check(root)
    if args.json:
        print(json.dumps([p.__dict__ for p in problems], ensure_ascii=False, indent=1))
    else:
        for problem in problems:
            print(problem.text())
        print(f"{len(problems)} problem(s)." if problems else "OK: the project conforms.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
