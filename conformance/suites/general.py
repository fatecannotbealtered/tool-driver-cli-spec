"""The general conformance suite: G00 to G10 and R01 to R05 (DVER-003)."""
from __future__ import annotations

import json
import re
import shlex
import secrets
from typing import Any

from . import schemas
from .harness import Case, Failure, NotApplicable, Subject, check
from .samples import Sample, all_samples, call, tier_of

CONFIRMING = ("two_step", "dangerous")


def _samples(subject: Subject) -> list[tuple[Sample, str]]:
    """Every sample the tool can run, with its tier."""
    found = []
    for sample in all_samples(subject):
        with Case(subject) as case:
            sample.prepare(case)
            tier, out = tier_of(case, sample)
        if tier == "error":
            raise Failure(f"The dry run of the {sample.path} sample failed: {out.describe()}")
        if tier is not None:
            found.append((sample, tier))
    return found


def _confirming(subject: Subject) -> list[tuple[Sample, str]]:
    found = [(s, t) for s, t in _samples(subject) if t in CONFIRMING]
    if not found:
        raise NotApplicable("no write sample needs confirmation")
    return found


def _unchanged(case: Case, before: str, what: str) -> None:
    check(case.footprint() == before, f"{what}: something was written")


def g00(subject: Subject) -> None:
    missing = [p for p in subject.writes() if p not in subject.samples]
    check(not missing, f"These write commands have no sample in the normal row of tests/matrix/: {', '.join(missing)}")


def g01(subject: Subject) -> None:
    for sample, tier in _confirming(subject):
        with Case(subject) as case:
            argv = sample.prepare(case)
            before = case.footprint()
            out = call(case, sample, argv=argv)
            check(out.exit == 5 and out.code == "E_CONFIRMATION_REQUIRED", f"{sample.path}: {out.describe()}")
            for key in ("preview", "confirm_token", "expires_at"):
                check(key in out.details, f"{sample.path}: details lack {key}")
            _unchanged(case, before, sample.path)


def g02(subject: Subject) -> None:
    for sample, tier in _samples(subject):
        with Case(subject) as case:
            argv = sample.prepare(case)
            before = case.footprint()
            out = call(case, sample, "--dry-run", argv=argv)
            check(out.exit == 0 and out.ok, f"{sample.path}: {out.describe()}")
            problems = schemas.errors(out.data, "preview.schema.json")
            check(not problems, f"{sample.path}: the dry run is not valid: {problems[:3]}")
            _unchanged(case, before, sample.path)


def _token(case: Case, sample: Sample, argv: list[str]) -> str:
    out = call(case, sample, "--dry-run", argv=argv)
    check(out.ok and out.data.get("confirm_token"), f"{sample.path}: the dry run gave no token: {out.describe()}")
    return out.data["confirm_token"]


def _variants(subject: Subject, sample: Sample, argv: list[str]) -> list[tuple[str, list[str], str]]:
    """The sample with one argument changed, one removed and one added, and the flag each names."""
    command = subject.commands[sample.path]
    flags = {f["name"]: f for f in command["flags"]}
    targets = {"--session", "--doc", "--device", "--job", "--output"}
    out = []
    given = [i for i, a in enumerate(argv) if a in flags and a not in targets]
    for i in given:
        flag = flags[argv[i]]
        if flag.get("type") == "boolean" or i + 1 >= len(argv):
            continue
        value = argv[i + 1]
        if flag.get("unit"):
            number = re.match(r"-?[0-9.]+", value)
            changed = f"{float(number.group(0)) + 1}{value[number.end():]}" if number else value
        elif flag.get("type") == "integer":
            changed = str(int(value) + 1) if value.lstrip("-").isdigit() else value + "1"
        elif flag.get("type") == "list":
            changed = value + ",conformance-extra"
        else:
            changed = value + "-changed"
        out.append(("changed", argv[:i + 1] + [changed] + argv[i + 2:], argv[i]))
        if not flag.get("required"):
            out.append(("removed", argv[:i] + argv[i + 2:], argv[i]))
        break
    for name, flag in flags.items():
        if name in argv or name in targets or name in ("--ids", "--input", "--id") or flag.get("required"):
            continue
        value = {"integer": "7", "boolean": None, "number": "7", "path": None}.get(flag.get("type"), "conformance")
        if flag.get("unit"):
            value = f"1{flag['unit'] if flag['unit'] in ('mm', 'deg', 's', 'V', 'A', 'W', 'N', 'J', 'Hz', 'F', 'H', 'Pa') else 'mm'}"
        if flag.get("type") == "path":
            continue
        out.append(("added", argv + ([name] if value is None else [name, value]), name))
        break
    return out


def g03(subject: Subject) -> list[str]:
    notes, tried = [], 0
    for sample, tier in _confirming(subject):
        with Case(subject) as case:
            argv = sample.prepare(case)
            variants = _variants(subject, sample, argv)
            if not variants:
                notes.append(f"{sample.path}: its sample has no argument to change")
                continue
            token = _token(case, sample, argv)
            before = case.footprint()
            for kind, changed, flag in variants:
                extra = ["--confirm", token] + (["--dangerous"] if tier == "dangerous" else [])
                out = call(case, sample, *extra, argv=changed)
                check(out.code == "E_CONFLICT" and out.details.get("conflict") == "token_mismatch",
                      f"{sample.path}, {flag} {kind}: {out.describe()}")
                check(out.details.get("parameter") == flag or flag in out.envelope["error"]["message"],
                      f"{sample.path}: the mismatch does not name {flag}: {out.describe()}")
                tried += 1
            _unchanged(case, before, sample.path)
    if not tried:
        raise Failure("no sample had an argument to change, remove or add")
    return notes


def g04(subject: Subject) -> None:
    for sample, tier in _confirming(subject):
        with Case(subject) as case:
            argv = sample.prepare(case)
            token = _token(case, sample, argv)
            extra = ["--confirm", token] + (["--dangerous"] if tier == "dangerous" else [])
            first = call(case, sample, *extra, argv=argv)
            check(first.exit == 0, f"{sample.path}, first confirm: {first.describe()}")
            applied = len(case.applied())
            second = call(case, sample, *extra, argv=argv)
            check(second.code == "E_CONFLICT" and second.details.get("conflict") == "token_used",
                  f"{sample.path}, second confirm: {second.describe()}")
            check(len(case.applied()) == applied, f"{sample.path}: the second confirm wrote again")


def g05(subject: Subject) -> None:
    for sample, tier in _confirming(subject):
        with Case(subject) as case:
            argv = sample.prepare(case)
            token = _token(case, sample, argv)
            before = case.footprint()
            flipped = token[:-1] + ("A" if token[-1] != "A" else "B")
            for fake in (flipped, token[::-1], secrets.token_urlsafe(16), token + "x"):
                extra = ["--confirm", fake] + (["--dangerous"] if tier == "dangerous" else [])
                out = call(case, sample, *extra, argv=argv)
                check(out.code == "E_CONFLICT" and out.details.get("conflict") == "token_invalid",
                      f"{sample.path} with token {fake!r}: {out.describe()}")
            _unchanged(case, before, sample.path)


def g06(subject: Subject) -> None:
    two_step = [(s, t) for s, t in _confirming(subject) if t == "two_step"] or _confirming(subject)
    for sample, tier in two_step:
        with Case(subject) as case:
            argv = sample.prepare(case)
            before = case.footprint()
            out = call(case, sample, "--format", "text", argv=argv)
            check(out.exit == 5, f"{sample.path} with --format text: exit {out.exit}: {out.stdout[:300]}")
            _unchanged(case, before, sample.path)


def g07(subject: Subject) -> None:
    for sample, tier in _samples(subject):
        if not sample.needs_scope:
            continue
        with Case(subject) as case:
            argv = sample.prepare(case)
            token = _token(case, sample, argv) if tier in CONFIRMING else None
            case.revoke()
            before = case.footprint()
            out = call(case, sample, "--dry-run", argv=argv)
            check(out.code == "E_FORBIDDEN" and "scope" in out.details, f"{sample.path} dry run: {out.describe()}")
            extra = ["--confirm", token] + (["--dangerous"] if tier == "dangerous" else []) if token else []
            out = call(case, sample, *extra, argv=argv)
            check(out.code == "E_FORBIDDEN" and out.details.get("scope", {}).get("missing"), f"{sample.path}: {out.describe()}")
            _unchanged(case, before, sample.path)


def g08(subject: Subject) -> None:
    for sample, tier in _samples(subject):
        with Case(subject) as case:
            argv = sample.prepare(case)
            case.state_dir.mkdir(parents=True, exist_ok=True)
            blocker = case.state_dir / "operations"
            if blocker.is_dir():
                for item in blocker.iterdir():
                    item.unlink()
                blocker.rmdir()
            blocker.write_text("not a directory", encoding="utf-8")
            before = case.footprint()
            out = call(case, sample, argv=argv)
            check(out.code == "E_IO", f"{sample.path} without operation records: {out.describe()}")
            _unchanged(case, before, sample.path)
            read = case.run("session", "list") if "session" in subject.modes else case.run("context")
            check(read.ok, f"a read failed without operation records: {read.describe()}")


def g09(subject: Subject) -> None:
    dangerous = [(s, t) for s, t in _confirming(subject) if t == "dangerous"]
    if not dangerous:
        raise NotApplicable("no write sample is dangerous")
    for sample, tier in dangerous:
        with Case(subject) as case:
            argv = sample.prepare(case)
            token = _token(case, sample, argv)
            before = case.footprint()
            out = call(case, sample, "--confirm", token, argv=argv)
            check(out.exit == 5 and out.code == "E_CONFIRMATION_REQUIRED", f"{sample.path} without --dangerous: {out.describe()}")
            _unchanged(case, before, sample.path)


def g10(subject: Subject) -> None:
    for sample, tier in _confirming(subject):
        if not sample.needs_scope:
            continue
        with Case(subject) as case:
            argv = sample.prepare(case)
            token = _token(case, sample, argv)
            case.grant(scope_id="conformance-changed")
            before = case.footprint()
            extra = ["--confirm", token] + (["--dangerous"] if tier == "dangerous" else [])
            out = call(case, sample, *extra, argv=argv)
            check(out.code == "E_CONFLICT" and out.details.get("conflict") == "scope_changed", f"{sample.path}: {out.describe()}")
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
            tier = one.data["tier"]
            if isinstance(tier, dict):
                check(set(tier) == set(one.data["modes"]), f"{path}: the tier is not given for every mode")
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
            check(words[-1] not in {"show", "inspect", "info", "status"}, f"{path} uses a banned verb")
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


def r04(subject: Subject) -> list[str]:
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
    "G09": g09, "G10": g10, "R01": r01, "R02": r02, "R03": r03, "R05": r05, "R04": r04,
}

