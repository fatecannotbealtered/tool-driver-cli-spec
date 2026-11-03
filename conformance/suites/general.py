"""The general conformance suite: G00 to G10 and R01 to R05 (DVER-003).

Tiers come from the registration and the contract, never from what the tool reports. A test
that has no sample to run fails: every tool has at least one confirming write, the
`knowledge create` sample the suites bring.
"""
from __future__ import annotations

import json
import re
import secrets
import shlex
from typing import Any

from . import schemas
from .harness import SECOND, Case, Subject, check
from .samples import Sample, all_samples, call, confirm, effects_of, halt, tier, token_for

CONFIRMING = ("two_step", "dangerous")
TARGET_FLAGS = ("--session", "--doc", "--device", "--job")


def _samples(subject: Subject) -> list[tuple[Sample, str]]:
    return [(s, tier(subject, s)) for s in all_samples(subject)]


def _confirming(subject: Subject) -> list[tuple[Sample, str]]:
    found = [(s, t) for s, t in _samples(subject) if t in CONFIRMING]
    check(found, "no write sample needs confirmation, though knowledge create always does")
    return found


def _unchanged(case: Case, before: str, what: str) -> None:
    check(case.footprint() == before, f"{what}: something was written")


def g00(subject: Subject) -> None:
    missing = [p for p in subject.writes() if p not in subject.samples]
    check(not missing, f"These write commands have no sample in the normal row of tests/matrix/: {', '.join(missing)}")


def g01(subject: Subject) -> None:
    for sample, expected in _confirming(subject):
        with Case(subject) as case:
            argv = sample.prepare(case)
            before = case.footprint()
            out = call(case, sample, argv=argv)
            check(out.exit == 5 and out.code == "E_CONFIRMATION_REQUIRED", f"{sample.path}: {out.describe()}")
            for key in ("preview", "confirm_token", "expires_at"):
                check(key in out.details, f"{sample.path}: details lack {key}")
            check(out.details["preview"]["tier"] == expected, f"{sample.path}: the preview says {out.details['preview']['tier']}, "
                                                             f"the rules give {expected}")
            _unchanged(case, before, sample.path)


def g02(subject: Subject) -> None:
    for sample, expected in _samples(subject):
        with Case(subject) as case:
            argv = sample.prepare(case)
            before = case.footprint()
            out = call(case, sample, "--dry-run", argv=argv)
            check(out.exit == 0 and out.ok, f"{sample.path}: {out.describe()}")
            problems = schemas.errors(out.data, "preview.schema.json")
            check(not problems, f"{sample.path}: the dry run is not valid: {problems[:3]}")
            check(out.data["preview"]["tier"] == expected, f"{sample.path}: the preview says {out.data['preview']['tier']}, "
                                                          f"the rules give {expected}")
            check(("confirm_token" in out.data) == (expected in CONFIRMING), f"{sample.path}: a token goes with {expected} only if it confirms")
            _unchanged(case, before, sample.path)


def _changed(flag: dict[str, Any], value: str) -> str | None:
    if flag.get("type") == "boolean":
        return None
    if flag.get("unit"):
        number = re.match(r"-?[0-9.]+", value)
        return f"{float(number.group(0)) + 1:g}{value[number.end():]}" if number else None
    if flag.get("type") == "integer":
        return str(int(value) + 1) if value.lstrip("-").isdigit() else None
    if flag.get("type") == "number":
        return f"{float(value) + 1:g}"
    if flag.get("type") == "list":
        return value + ",conformance-extra"
    if "|" in str(flag.get("type")):
        choices = flag["type"].split("|")
        return next((c for c in choices if c != value), None)
    if flag.get("type") == "path":
        return value + "-changed"
    return value + "-changed"


def _added(flag: dict[str, Any]) -> list[str] | None:
    name, kind = flag["name"], str(flag.get("type"))
    if flag.get("unit"):
        return [name, f"1{flag['unit']}"]
    if kind == "boolean":
        return [name]
    if kind in ("integer", "number"):
        return [name, "7"]
    if "|" in kind:
        return [name, kind.split("|")[0]]
    if kind == "string":
        return [name, "conformance"]
    return None


def _variants(subject: Subject, sample: Sample, argv: list[str]) -> list[tuple[str, list[str], str]]:
    """The sample with each given argument changed, each optional one removed, and one added."""
    flags = {f["name"]: f for f in subject.commands[sample.path]["flags"]}
    out = []
    i = 0
    while i < len(argv):
        name = argv[i]
        flag = flags.get(name)
        valued = flag is not None and flag.get("type") != "boolean" and i + 1 < len(argv)
        if flag is not None and name not in TARGET_FLAGS:
            if valued:
                changed = _changed(flag, argv[i + 1])
                if changed is not None:
                    out.append(("changed", argv[:i + 1] + [changed] + argv[i + 2:], name))
            if not flag.get("required"):
                out.append(("removed", argv[:i] + argv[i + 2 if valued else i + 1:], name))
        i += 2 if valued else 1
    selectors = {"--id", "--ids", "--input"}
    for name, flag in flags.items():
        if name in argv or name in TARGET_FLAGS or name in selectors or flag.get("required") or name == "--output":
            continue
        added = _added(flag)
        if added is not None:
            out.append(("added", argv + added, name))
            break
    return out


def _other_target(sample: Sample, argv: list[str], case: Case) -> tuple[list[str], str] | None:
    """The sample pointed at the second document or device of the SECOND world."""
    if "--doc" in argv and "{doc}" in sample.args:
        i = argv.index("--doc")
        other = case.doc_path("file-2") if sample.file_mode else "doc-2"
        return argv[:i + 1] + [other] + argv[i + 2:], "--doc"
    if "--device" in argv and "{device}" in sample.args:
        i = argv.index("--device")
        return argv[:i + 1] + ["dev-2"] + argv[i + 2:], "--device"
    return None


def g03(subject: Subject) -> list[str]:
    notes, tried = [], 0
    for sample, expected in _confirming(subject):
        with Case(subject, SECOND) as case:
            argv = sample.prepare(case)
            token = token_for(case, sample, argv)
            before = case.footprint()
            variants = _variants(subject, sample, argv)
            other = _other_target(sample, argv, case)
            if other is not None:
                variants.append(("pointed elsewhere", other[0], other[1]))
            for kind, changed, flag in variants:
                out = confirm(case, sample, changed, token, expected == "dangerous")
                if kind in ("added", "removed") and out.code == "E_USAGE":
                    continue  # the changed call is not valid by itself, so it never reaches the token
                check(out.code == "E_CONFLICT" and out.details.get("conflict") == "token_mismatch",
                      f"{sample.path}, {flag} {kind}: {out.describe()}")
                check(out.details.get("parameter") == flag or flag in out.envelope["error"]["message"],
                      f"{sample.path}: the mismatch does not name {flag}: {out.describe()}")
                tried += 1
            _unchanged(case, before, sample.path)
            notes.append(f"{sample.path}: {len(variants)} variants")
    check(tried, "no sample had an argument to change, remove or add")
    return notes


def g04(subject: Subject) -> None:
    for sample, expected in _confirming(subject):
        with Case(subject) as case:
            argv = sample.prepare(case)
            token = token_for(case, sample, argv)
            first = confirm(case, sample, argv, token, expected == "dangerous")
            check(first.exit == 0, f"{sample.path}, first confirm: {first.describe()}")
            applied = case.applied()
            if sample.domain:
                mine = [a for a in applied if a["operation_id"] == first.data.get("operation_id")]
                check(len(mine) == 1, f"{sample.path}: the first confirm wrote {len(mine)} times")
            second = confirm(case, sample, argv, token, expected == "dangerous")
            check(second.code == "E_CONFLICT" and second.details.get("conflict") == "token_used",
                  f"{sample.path}, second confirm: {second.describe()}")
            check(case.applied() == applied, f"{sample.path}: the second confirm wrote again")


def g05(subject: Subject) -> None:
    for sample, expected in _confirming(subject):
        with Case(subject) as case:
            argv = sample.prepare(case)
            token = token_for(case, sample, argv)
            before = case.footprint()
            flipped = token[:-1] + ("A" if token[-1] != "A" else "B")
            for fake in (flipped, token[::-1], secrets.token_urlsafe(16), token + "x"):
                out = confirm(case, sample, argv, fake, expected == "dangerous")
                check(out.code == "E_CONFLICT" and out.details.get("conflict") == "token_invalid",
                      f"{sample.path} with token {fake!r}: {out.describe()}")
            _unchanged(case, before, sample.path)


def g06(subject: Subject) -> None:
    for sample, expected in [(s, t) for s, t in _confirming(subject) if t == "two_step"]:
        with Case(subject) as case:
            argv = sample.prepare(case)
            before = case.footprint()
            out = call(case, sample, "--format", "text", argv=argv)
            check(out.exit == 5, f"{sample.path} with --format text: exit {out.exit}: {out.stdout[:300]}")
            _unchanged(case, before, sample.path)


def _forbidden(out: Any, what: str, part: str) -> None:
    check(out.code == "E_FORBIDDEN", f"{what}: {out.describe()}")
    missing = out.details.get("scope", {}).get("missing", {})
    check(missing.get(part), f"{what}: details.scope.missing.{part} is empty: {out.describe()}")


def g07(subject: Subject) -> list[str]:
    notes = []
    all_effects = [e["effect"] for e in schemas.contract()["effects"] if e["effect"] != "observe"]
    for sample, expected in _samples(subject):
        if not sample.needs_scope:
            continue
        with Case(subject) as case:
            argv = sample.prepare(case)
            dry = call(case, sample, "--dry-run", argv=argv)
            check(dry.ok, f"{sample.path} dry run: {dry.describe()}")
            preview = dry.data["preview"]
            token = dry.data.get("confirm_token")
            before = case.footprint()
            danger = expected == "dangerous"
            case.revoke()
            out = call(case, sample, "--dry-run", argv=argv)
            check(out.code == "E_FORBIDDEN" and "scope" in out.details, f"{sample.path} dry run without a scope: {out.describe()}")
            out = confirm(case, sample, argv, token, danger) if token else call(case, sample, argv=argv)
            check(out.code == "E_FORBIDDEN" and out.details.get("scope", {}).get("missing"), f"{sample.path} without a scope: {out.describe()}")
            if not halt(subject, sample):
                effects = effects_of(subject, sample)
                case.grant(effects=[e for e in all_effects if e not in effects] or ["deliver"])
                _forbidden(call(case, sample, argv=argv), f"{sample.path} without its effects in the scope", "effects")
            if preview.get("target") or preview.get("changes"):
                device = sample.mode == "device"
                case.grant(targets=["file:///conformance-nowhere/"] if device else ["device:conformance-nowhere"])
                _forbidden(call(case, sample, argv=argv), f"{sample.path} outside the scope's targets", "targets")
            if danger:
                case.grant(dangerous=False)
                _forbidden(call(case, sample, argv=argv), f"{sample.path} with dangerous: false", "dangerous")
            _unchanged(case, before, sample.path)
        notes.append(sample.path)
    return notes


def _block_records(case: Case) -> None:
    case.state_dir.mkdir(parents=True, exist_ok=True)
    blocker = case.state_dir / "operations"
    if blocker.is_dir():
        for item in blocker.iterdir():
            item.unlink()
        blocker.rmdir()
    blocker.write_text("not a directory", encoding="utf-8")


def g08(subject: Subject) -> None:
    for sample, expected in _samples(subject):
        with Case(subject) as case:
            argv = sample.prepare(case)
            token = token_for(case, sample, argv) if expected in CONFIRMING else None
            _block_records(case)
            before = case.footprint()
            out = call(case, sample, argv=argv)
            check(out.code == "E_IO", f"{sample.path} without operation records: {out.describe()}")
            if token:
                out = confirm(case, sample, argv, token, expected == "dangerous")
                check(out.code == "E_IO", f"{sample.path} confirmed without operation records: {out.describe()}")
            _unchanged(case, before, sample.path)
            read = case.run("session", "list") if "session" in subject.modes else case.run("context")
            check(read.ok, f"a read failed without operation records: {read.describe()}")


def g09(subject: Subject) -> list[str]:
    dangerous = [(s, t) for s, t in _confirming(subject) if t == "dangerous"]
    for sample, expected in dangerous:
        with Case(subject) as case:
            argv = sample.prepare(case)
            token = token_for(case, sample, argv)
            before = case.footprint()
            out = confirm(case, sample, argv, token, dangerous=False)
            check(out.exit == 5 and out.code == "E_CONFIRMATION_REQUIRED", f"{sample.path} without --dangerous: {out.describe()}")
            _unchanged(case, before, sample.path)
            again = confirm(case, sample, argv, token, dangerous=True)
            check(again.ok, f"{sample.path}: the token was spent by the refused call: {again.describe()}")
    return [] if dangerous else ["the tool has no dangerous command"]


def g10(subject: Subject) -> None:
    for sample, expected in _confirming(subject):
        if not sample.needs_scope:
            continue
        for change in ("scope_id", "content"):
            with Case(subject) as case:
                argv = sample.prepare(case)
                token = token_for(case, sample, argv)
                if change == "scope_id":
                    case.grant(scope_id="conformance-changed")
                else:
                    case.grant(targets=["file:///", "untitled:", "device:", "file:///conformance-extra/"])
                before = case.footprint()
                out = confirm(case, sample, argv, token, expected == "dangerous")
                check(out.code == "E_CONFLICT" and out.details.get("conflict") == "scope_changed",
                      f"{sample.path} after the scope's {change} changed: {out.describe()}")
                _unchanged(case, before, sample.path)


# ------------------------------------------------------------------ R tests


def r01(subject: Subject) -> None:
    limits = schemas.contract()["envelope"]["limits"]
    with Case(subject) as case:
        index = case.run("reference")
        check(index.ok, f"reference failed: {index.describe()}")
        check(len(index.stdout.strip()) <= limits["reference_index_chars"], f"the index is {len(index.stdout.strip())} characters")
        problems = schemas.errors(index.data, "reference.schema.json")
        check(not problems, f"the index is not valid: {problems[:3]}")
        for path, command in subject.commands.items():
            one = case.run("reference", "--command", path)
            check(one.ok, f"reference --command {path}: {one.describe()}")
            check(len(one.stdout.strip()) <= limits["reference_command_chars"], f"{path}: {len(one.stdout.strip())} characters")
            problems = schemas.errors(one.data, "reference.schema.json", "/$defs/command")
            check(not problems, f"{path} is not valid: {problems[:3]}")
            check(one.data["effects"], f"{path} declares no effects")
            shown = one.data["tier"]
            if isinstance(shown, dict):
                check(set(shown) == set(one.data["modes"]), f"{path}: the tier is not given for every mode")
            if path in subject.registrations:
                for mode in one.data["modes"]:
                    got = shown[mode] if isinstance(shown, dict) else shown
                    want = subject.tier(path, mode)
                    check(got == want, f"{path} in {mode} mode: reference shows {got}, the rules give {want}")
            for example in one.data["examples"]:
                _example(subject, path, example)
        out = case.dir / "reference.json"
        full = case.run("reference", "--all", "--output", str(out))
        check(full.ok and out.exists(), f"reference --all --output: {full.describe()}")
        problems = schemas.errors(json.loads(out.read_text(encoding="utf-8")), "reference.schema.json")
        check(not problems, f"the full reference is not valid: {problems[:3]}")


def _example(subject: Subject, path: str, example: str) -> None:
    words = shlex.split(example, posix=True)
    check(words and words[0] == subject.name, f"{path}: the example {example!r} does not start with {subject.name}")
    rest = words[1:]
    n = len(path.split(" "))
    check(" ".join(rest[:n]) == path, f"{path}: the example {example!r} runs another command")
    flags = {f["name"] for f in subject.commands[path]["flags"]} | {f["flag"] for f in schemas.contract()["global_flags"]}
    for word in rest[n:]:
        if word.startswith("--"):
            check(word.split("=")[0] in flags, f"{path}: the example {example!r} uses an unknown flag {word}")


def r02(subject: Subject) -> None:
    contract = schemas.contract()
    verbs = {v["verb"] for v in contract["verbs"]}
    reserved = set(contract["reserved_names"])
    paths = set(subject.commands)
    for path, command in subject.commands.items():
        check(command["summary"].strip(), f"{path} has no summary")
        check(command["output_schema"], f"{path} has no output schema")
        check(command["examples"], f"{path} has no example")
        words = path.split(" ")
        prefix = " ".join(words[:-1])
        check(not any(p.startswith(path + " ") for p in paths), f"{path} is both a group and a command")
        if path in subject.registrations:
            check(len(words) >= 2 and words[-1] in verbs, f"{path}: a domain command is `noun verb` with a verb of DCLI-022")
            check(words[0] not in reserved, f"{path}: the noun {words[0]} is reserved")
            check(words[-1] not in set(contract["banned_verbs"]), f"{path} uses a banned verb")
            reg = subject.registrations[path]
            check((words[-1] == "stop") == reg["halt"], f"{path}: only a command with the verb stop is a halt command")
        check(prefix == "" or prefix not in paths, f"{path}: its group {prefix} is also a command")


def r03(subject: Subject) -> None:
    with Case(subject) as case:
        for args, what in ((["conformance-no-such", "command"], "an unknown command"),
                           (["context", "--conformance-no-such-flag"], "an unknown flag"),
                           (["context", "conformance-extra"], "an extra argument")):
            out = case.run(*args)
            check(out.code == "E_USAGE" and out.details.get("problem"), f"{what}: {out.describe()}")
            check("`" in out.details.get("next_action", ""), f"{what}: next_action gives no command to run: {out.describe()}")
        close = next(iter(subject.registrations), "doc list")
        out = case.run(*close[:-1].split(" "))  # one letter short
        check(out.code == "E_USAGE", f"a misspelled command: {out.describe()}")


DATA_SCHEMAS = {
    "session list": ("objects.schema.json", "/$defs/page"), "doc list": ("objects.schema.json", "/$defs/page"),
    "job list": ("objects.schema.json", "/$defs/page"), "device list": ("objects.schema.json", "/$defs/page"),
    "session get": ("objects.schema.json", "/$defs/session"), "doc get": ("objects.schema.json", "/$defs/document"),
    "device get": ("objects.schema.json", "/$defs/device"), "job get": ("objects.schema.json", "/$defs/job"),
    "plugin get": ("objects.schema.json", "/$defs/plugin"), "context": ("context.schema.json", ""),
    "doctor": ("doctor.schema.json", ""), "changelog": ("changelog.schema.json", ""),
    "operation get": ("operation.schema.json", ""), "operation resolve": ("operation.schema.json", ""),
    "knowledge get": ("knowledge.schema.json", ""),
}


def _path(subject: Subject, args: list[str]) -> str | None:
    words = [a for a in args if not a.startswith("-")]
    for n in range(len(words), 0, -1):
        if " ".join(words[:n]) in subject.commands:
            return " ".join(words[:n])
    return None


def _data_problems(subject: Subject, args: list[str], data: Any) -> list[str]:
    if not isinstance(data, dict):
        return []
    path = _path(subject, args)
    if path in DATA_SCHEMAS:
        return schemas.errors(data, *DATA_SCHEMAS[path])
    if path == "operation list":
        return [p for item in data.get("items", []) for p in schemas.errors(item, "operation.schema.json")]
    if path == "reference" and "--all" not in args:
        return schemas.errors(data, "reference.schema.json")
    if {"operation_id", "receipt", "result"} <= set(data):
        return schemas.errors(data, "receipt.schema.json")
    if {"operation_id", "items", "summary"} <= set(data):
        return schemas.errors(data, "batch.schema.json")
    if "preview" in data:
        return schemas.errors(data, "preview.schema.json")
    return []


def r04(subject: Subject) -> list[str]:
    """Runs last, so it sees the envelopes of both suites."""
    contract = schemas.contract()
    limits = contract["envelope"]["limits"]
    codes = {e["code"]: e for e in contract["error_codes"]}
    seen = list(subject.envelopes)
    check(seen, "no envelope was recorded")
    for args, env, exit_code in seen:
        where = f"`{' '.join(args)[:120]}`"
        problems = schemas.errors(env, "envelope.schema.json")
        check(not problems, f"{where}: the envelope is not valid: {problems[:3]}")
        problems = schemas.naming(env)
        check(not problems, f"{where}: {problems[:3]}")
        text = json.dumps(env, ensure_ascii=False, separators=(",", ":"))
        if env["ok"]:
            check(exit_code == 0, f"{where}: a success exits {exit_code}")
            check(len(text) <= limits["success_chars"], f"{where}: {len(text)} characters")
            data = env["data"]
            if isinstance(data, dict) and isinstance(data.get("items"), list) and "operation_id" not in data:
                for key in ("count", "has_more"):
                    check(key in data, f"{where}: a list lacks {key}")
            problems = _data_problems(subject, args, data)
            check(not problems, f"{where}: the data is not valid: {problems[:3]}")
        else:
            code = env["error"]["code"]
            check(exit_code == codes[code]["exit"], f"{where}: {code} exits {exit_code}, not {codes[code]['exit']}")
            limit = limits["confirmation_required_chars" if code == "E_CONFIRMATION_REQUIRED" else "error_chars"]
            check(len(text) <= limit, f"{where}: the {code} envelope has {len(text)} characters")
    return [f"{len(seen)} envelopes checked"]


def r05(subject: Subject) -> None:
    contract = schemas.contract()
    with Case(subject) as case:
        for args, schema in ((["context"], "context.schema.json"), (["doctor"], "doctor.schema.json")):
            out = case.run(*args)
            check(out.ok, f"{args[0]}: {out.describe()}")
            problems = schemas.errors(out.data, schema)
            check(not problems, f"{args[0]} is not valid: {problems[:3]}")
        doctor = case.run("doctor").data
        names = [c["check"] for c in doctor["checks"]]
        missing = [c for c in contract["doctor"]["checks"] if c not in names]
        check(not missing, f"doctor lacks the checks {missing}")
        out = case.run("operation", "list")
        check(out.ok and out.data["items"] == [] and out.data["count"] == 0, f"operation list: {out.describe()}")


TESTS: dict[str, Any] = {
    "G00": g00, "G01": g01, "G02": g02, "G03": g03, "G04": g04, "G05": g05, "G06": g06, "G07": g07, "G08": g08,
    "G09": g09, "G10": g10, "R01": r01, "R02": r02, "R03": r03, "R05": r05,
}
LAST: dict[str, Any] = {"R04": r04}
