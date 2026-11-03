"""The driver conformance suite: D01 to D25 (DVER-010)."""
from __future__ import annotations

import re
import time
from typing import Any

from .harness import Case, NotApplicable, Outcome, Recorder, Subject, check
from .samples import Sample, all_samples, call, standard_samples


# ------------------------------------------------------------------ choosing samples


def _own(subject: Subject, mode: str | None = None, effect: str | None = None, halt: bool | None = False) -> list[Sample]:
    out = []
    for sample in all_samples(subject):
        reg = subject.registrations.get(sample.path)
        if reg is None:
            continue
        if mode and sample.mode != mode:
            continue
        if effect and effect not in reg["effects"]:
            continue
        if halt is not None and reg["halt"] != halt:
            continue
        out.append(sample)
    return out


def _direct(subject: Subject, samples: list[Sample]) -> list[Sample]:
    return [s for s in samples if subject.tier(s.path, s.mode) == "direct"]


def _session_write(subject: Subject) -> Sample:
    own = _own(subject, "session", "change")
    if own:
        return (_direct(subject, own) or own)[0]
    return next(s for s in standard_samples(subject) if s.path == "doc save")


def _device_write(subject: Subject) -> Sample:
    own = _own(subject, "device")
    if not own:
        raise NotApplicable("no device-mode write command has a sample")
    return own[0]


def _changes_fields(subject: Subject) -> Sample:
    """A write whose verification reads fields back, not files."""
    for sample in _own(subject):
        reg = subject.registrations[sample.path]
        if "artifact" not in reg["effects"]:
            return sample
    raise NotApplicable("no write command that changes fields has a sample")


def _method(subject: Subject, sample: Sample) -> str:
    return "save_doc" if sample.path == "doc save" else "apply"


def _fault(case: Case, subject: Subject, sample: Sample, **rule: Any) -> None:
    method = rule.pop("method", None) or _method(subject, sample)
    if method == "apply" or method == "read_back":
        rule.setdefault("command", sample.path)
    case.control("fault", rule={"method": method, **rule})


def _through(case: Case, sample: Sample, argv: list[str], dangerous: bool = True) -> Outcome:
    """Run a write to its end: confirm it when it asks for confirmation."""
    out = call(case, sample, argv=argv)
    if out.code == "E_CONFIRMATION_REQUIRED":
        extra = ["--confirm", out.details["confirm_token"]]
        if out.details["preview"]["tier"] == "dangerous" and dangerous:
            extra.append("--dangerous")
        out = call(case, sample, *extra, argv=argv)
    return out


# ------------------------------------------------------------------ the tests


def d01(subject: Subject) -> None:
    with Case(subject) as case:
        case.control("add_session", session="fake-2")
        out = case.run("session", "get")
        check(out.code == "E_AMBIGUOUS", f"session get with two instances: {out.describe()}")
        candidates = out.details.get("candidates", [])
        check(len(candidates) >= 2, f"the candidates are not listed: {out.describe()}")
        for candidate in candidates:
            check("id" in candidate and isinstance(candidate.get("documents"), list), f"a candidate lacks its summary: {candidate}")


def _token_then(subject: Subject, sample: Sample, change: Any, conflict: str) -> None:
    with Case(subject) as case:
        argv = sample.prepare(case)
        first = call(case, sample, argv=argv)
        if first.code != "E_CONFIRMATION_REQUIRED":
            first = call(case, sample, "--dry-run", argv=argv)
            token = (first.data or {}).get("confirm_token")
            check(token, f"{sample.path}: no token to confirm: {first.describe()}")
        else:
            token = first.details["confirm_token"]
        applied = len(case.applied())
        change(case)
        out = call(case, sample, "--confirm", token, "--dangerous", argv=argv)
        check(out.code == "E_CONFLICT" and out.details.get("conflict") == conflict, f"{sample.path}: {out.describe()}")
        check(len(case.applied()) == applied, f"{sample.path}: the write was sent")


def _confirmable_on_doc(subject: Subject) -> Sample:
    if "session" in subject.modes:
        return next(s for s in standard_samples(subject) if s.path == "doc save")
    for sample in _own(subject, "file"):
        if subject.tier(sample.path, "file") != "direct":
            return sample
    raise NotApplicable("no confirmable write acts on a document")


def d02(subject: Subject) -> None:
    sample = next(s for s in standard_samples(subject) if s.path == "doc save")
    _token_then(subject, sample, lambda case: case.control("restart_session", session="fake-1"), "session_changed")


def d03(subject: Subject) -> None:
    sample = _confirmable_on_doc(subject)
    doc = "doc-1" if sample.mode == "session" else "file-1"
    _token_then(subject, sample, lambda case: case.control("edit", document=doc, object="conformance-d03",
                                                           field="note", value="changed"), "document_changed")


def _busy(case: Case, out: Outcome, what: str) -> None:
    check(out.code == "E_BUSY" and out.envelope["error"]["retryable"], f"{what}: {out.describe()}")
    check(isinstance(out.details.get("retry_after_ms"), int), f"{what}: no retry_after_ms")
    check(out.details.get("dispatch_state") == "not_started", f"{what}: dispatch_state is not not_started")


def d04(subject: Subject) -> list[str]:
    notes = []
    if "session" in subject.modes:
        sample = _session_write(subject)
        with Case(subject) as case:
            argv = sample.prepare(case)
            case.control("set_session", session="fake-1", state="busy")
            _busy(case, call(case, sample, argv=argv), f"{sample.path} on a busy instance")
            check(not case.applied(), "something was sent to a busy instance")
        notes.append(f"session: {sample.path}")
    if "device" in subject.modes:
        sample = _device_write(subject)
        with Case(subject) as case:
            argv = sample.prepare(case)
            case.control("set_device", device="dev-1", state="busy")
            _busy(case, call(case, sample, argv=argv), f"{sample.path} on a busy device")
            check(not case.applied(), "something was sent to a busy device")
        notes.append(f"device: {sample.path}")
    return notes


def d05(subject: Subject) -> None:
    sample = _session_write(subject)
    with Case(subject) as case:
        argv = sample.prepare(case)
        case.control("set_session", session="fake-1", state="blocked", title="Conformance dialog")
        out = call(case, sample, argv=argv)
        check(out.code == "E_HUMAN_REQUIRED" and out.details.get("action"), f"a dialog before dispatch: {out.describe()}")
        resume = out.details.get("resume", "")
        check(sample.path in resume and "operation resolve" not in resume, f"resume does not run the call again: {resume!r}")
        check("$.error.details.title" in out.envelope["meta"].get("untrusted", []), "the dialog title is not marked untrusted")
        check(not case.applied(), "something was sent past a dialog")
    with Case(subject) as case:
        argv = sample.prepare(case)
        _fault(case, subject, sample, action="error", apply_first=True, error={"code": "E_HUMAN_REQUIRED", "action": "dismiss_dialog"})
        out = _through(case, sample, argv)
        check(out.code == "E_HUMAN_REQUIRED", f"a dialog after dispatch: {out.describe()}")
        resume = out.details.get("resume", "")
        check("operation resolve" in resume, f"after dispatch, resume must settle the outcome, not write again: {resume!r}")
        again = call(case, sample, argv=argv)
        check(again.code == "E_CONFLICT" and again.details.get("conflict") == "target_locked",
              f"the target is not locked after a dialog opened by the change: {again.describe()}")


def d06(subject: Subject) -> list[str]:
    notes = []
    samples = []
    if "session" in subject.modes:
        samples.append(_session_write(subject))
    if "device" in subject.modes:
        samples.append(_device_write(subject))
    for sample in samples:
        with Case(subject) as case:
            argv = sample.prepare(case)
            _fault(case, subject, sample, action="close", apply_first=True)
            out = _through(case, sample, argv)
            check(out.exit == 8 and out.code == "E_OUTCOME_UNKNOWN", f"{sample.path} after a lost connection: {out.describe()}")
            lookup = out.details.get("lookup", "")
            check("operation resolve" in lookup, f"lookup does not settle the outcome: {lookup!r}")
            again = call(case, sample, argv=argv)
            check(again.code == "E_CONFLICT" and again.details.get("conflict") == "target_locked",
                  f"the target is not locked while the outcome is unknown: {again.describe()}")
            words = lookup.split()
            resolved = case.run(*words[1:])
            check(resolved.ok and resolved.data.get("resolution"), f"the lookup does not settle it: {resolved.describe()}")
            after = call(case, sample, "--dry-run", argv=argv)
            check(after.ok, f"the target stays locked after the outcome was resolved: {after.describe()}")
        notes.append(sample.path)
    return notes


def _fields_of(case: Case, sample: Sample, argv: list[str]) -> list[str]:
    dry = call(case, sample, "--dry-run", argv=argv)
    check(dry.ok, f"{sample.path} dry run: {dry.describe()}")
    return sorted({c["field"] for c in dry.data["preview"]["changes"] if c.get("field")})


def d07(subject: Subject) -> None:
    sample = _changes_fields(subject)
    with Case(subject) as case:
        argv = sample.prepare(case)
        fields = _fields_of(case, sample, argv)
        case.control("fault", rule={"method": "read_back", "command": sample.path, "action": "unreadable", "fields": fields})
        out = _through(case, sample, argv)
        check(out.code == "E_VERIFY_INCOMPLETE" and out.details.get("receipt"), f"{sample.path}: {out.describe()}")


def d08(subject: Subject) -> None:
    sample = _changes_fields(subject)
    with Case(subject) as case:
        argv = sample.prepare(case)
        fields = _fields_of(case, sample, argv)
        case.control("fault", rule={"method": "apply", "command": sample.path, "action": "store",
                                    "values": {f: "conformance-other-value" for f in fields}})
        out = _through(case, sample, argv)
        check(out.code == "E_VERIFY_FAILED", f"{sample.path}: {out.describe()}")
        check(out.details.get("receipt", {}).get("mismatched"), f"{sample.path}: the mismatched fields are not listed")


def d09(subject: Subject) -> None:
    sample = _session_write(subject)
    if sample.path == "doc save":
        raise NotApplicable("no session-mode write command that changes a document has a sample")
    with Case(subject) as case:
        argv = sample.prepare(case)
        out = _through(case, sample, argv)
        check(out.ok, f"{sample.path}: {out.describe()}")
        receipt = out.data["receipt"]
        check(receipt["outcome"]["persistence"] == "unchanged", f"a session-mode change reports persistence {receipt['outcome']['persistence']}")
        doc = case.run("doc", "get", "--session", "fake-1", "--doc", "doc-1")
        check(doc.ok and doc.data["dirty"] is True, f"the document is not dirty after the change: {doc.describe()}")
        save = _through(case, next(s for s in standard_samples(subject) if s.path == "doc save"), ["--session", "fake-1", "--doc", "doc-1"])
        check(save.ok and save.data["receipt"]["outcome"]["persistence"] == "saved", f"doc save: {save.describe()}")


def d10(subject: Subject) -> None:
    with Case(subject) as case:
        case.control("edit", document="doc-1", object="conformance-d10", field="note", value="unsaved")
        out = case.run("doc", "close", "--session", "fake-1", "--doc", "doc-1")
        if out.code == "E_UNSUPPORTED":
            raise NotApplicable("the adapter has no close_doc")
        check(out.code == "E_CONFLICT" and out.details.get("conflict") == "unsaved_changes", f"doc close: {out.describe()}")
        out = case.run("doc", "close", "--session", "fake-1", "--doc", "doc-1", "--discard")
        check(out.exit == 5 and out.details.get("preview", {}).get("tier") == "dangerous", f"doc close --discard: {out.describe()}")
        token = out.details["confirm_token"]
        out = case.run("doc", "close", "--session", "fake-1", "--doc", "doc-1", "--discard", "--confirm", token)
        check(out.exit == 5, f"doc close --discard confirmed without --dangerous: {out.describe()}")
        check(any(d["id"] == "doc-1" for d in case.state()["documents"]), "the document was closed")


def d11(subject: Subject) -> None:
    jobs = [s for s in _own(subject) if "job_status" in subject.registrations[s.path]["adapter_capabilities"]]
    if not jobs:
        raise NotApplicable("no command with long jobs has a sample")
    sample = jobs[0]
    with Case(subject) as case:
        argv = sample.prepare(case)
        case.control("fault", rule={"method": "apply", "command": sample.path, "action": "job", "steps": 50})
        out = _through(case, sample, argv)
        check(out.ok and out.data["result"].get("job", {}).get("id"), f"{sample.path} as a long job: {out.describe()}")
        job = out.data["result"]["job"]
        check(job["poll"].startswith(subject.name) and "--job" in job["poll"], f"the poll command is not complete: {job['poll']!r}")
        cancel = case.run("job", "cancel", "--job", job["id"])
        check(cancel.ok, f"job cancel: {cancel.describe()}")
        first = cancel.data["result"]
        check(first.get("cancel_requested") is True, f"job cancel does not report cancel_requested: {first}")
        check(first.get("state") != "cancelled", "the job is reported cancelled before the application confirmed it")
        got = case.run("job", "get", "--job", job["id"], "--wait", "10s")
        check(got.ok and got.data["state"] == "cancelled", f"job get after the cancel: {got.describe()}")


def d12(subject: Subject) -> None:
    with Case(subject) as case:
        case.control("configure", plugin={"version_on_disk": "9.9.9"})
        doctor = case.run("doctor")
        plugin = next((c for c in doctor.data["checks"] if c["check"] == "plugin"), {})
        check(plugin.get("status") == "fail", f"the plugin check of doctor does not fail: {plugin}")
        sample = _session_write(subject)
        argv = sample.prepare(case)
        out = call(case, sample, argv=argv)
        check(out.code == "E_HUMAN_REQUIRED" and out.details.get("action") == "restart_application", f"{sample.path}: {out.describe()}")
        check(out.details.get("dispatch_state") == "not_started" and not case.applied(), "a write was sent to a stale host component")


def d13(subject: Subject) -> list[str]:
    notes = []
    with Case(subject) as case:
        for sample in _own(subject, halt=None):
            command = subject.commands[sample.path]
            units = {f["name"]: f for f in command["flags"] if f.get("unit")}
            argv = sample.argv(case)
            for i, arg in enumerate(argv[:-1]):
                if arg in units:
                    bare = re.match(r"-?[0-9.]+", argv[i + 1])
                    if not bare:
                        continue
                    changed = argv[:i + 1] + [bare.group(0)] + argv[i + 2:]
                    out = call(case, sample, argv=changed)
                    check(out.code == "E_USAGE", f"{sample.path} {arg} {bare.group(0)}: {out.describe()}")
                    check(units[arg]["unit"] in out.details.get("problem", ""), f"the problem does not list the units: {out.describe()}")
                    notes.append(f"{sample.path} {arg}")
                    break
        out = case.run("job", "get", "--job", "conformance", "--wait", "60")
        check(out.code == "E_USAGE" and "s" in out.details.get("problem", ""), f"job get --wait 60: {out.describe()}")
    return notes


def d14(subject: Subject) -> None:
    samples = _own(subject, effect="physical")
    if not samples:
        raise NotApplicable("no physical command has a sample")
    for sample in samples:
        with Case(subject) as case:
            argv = sample.prepare(case)
            first = call(case, sample, argv=argv)
            check(first.code == "E_CONFIRMATION_REQUIRED", f"{sample.path} without flags: {first.describe()}")
            out = call(case, sample, "--confirm", first.details["confirm_token"], argv=argv)
            check(out.exit == 5, f"{sample.path} confirmed without --dangerous: {out.describe()}")
            effects = ["lifecycle", "change", "artifact", "persist", "configure", "deliver"]
            case.grant(effects=effects)
            out = call(case, sample, argv=argv)
            check(out.code == "E_FORBIDDEN", f"{sample.path} without physical in the scope: {out.describe()}")
            check(not case.applied(), f"{sample.path}: something was dispatched")


def d15(subject: Subject) -> None:
    with Case(subject) as case:
        devices = case.run("device", "list")
        check(devices.ok and devices.data["items"], f"device list: {devices.describe()}")
        for device in devices.data["items"]:
            check(device.get("simulated") is True, f"the simulated device {device.get('id')} does not say so")
        sample = _device_write(subject)
        out = _through(case, sample, sample.prepare(case))
        check(out.ok, f"{sample.path}: {out.describe()}")
        check(out.data["receipt"].get("simulated") is True, "the receipt of a simulated device lacks simulated: true")
        result = out.data.get("result")
        check(not isinstance(result, dict) or result.get("simulated") is True, "the result of a simulated device lacks simulated: true")


def d16(subject: Subject) -> None:
    direct = _direct(subject, _own(subject, "session", "change"))
    if not direct:
        raise NotApplicable("no direct-tier session-mode change has a sample")
    sample = direct[0]
    with Case(subject) as case:
        argv = sample.prepare(case)
        out = call(case, sample, argv=argv)
        check(out.ok, f"{sample.path} in one call: {out.describe()}")
        receipt = out.data["receipt"]
        check(receipt["outcome"]["verification"] == "passed", f"no read-back: {receipt['outcome']}")
        record = case.run("operation", "get", "--id", out.data["operation_id"])
        check(record.ok and record.data["state"] == "completed", f"no operation record: {record.describe()}")
        case.revoke()
        out = call(case, sample, argv=argv)
        check(out.code == "E_FORBIDDEN", f"{sample.path} without a scope: {out.describe()}")


def d17(subject: Subject) -> None:
    direct = [s for s in _own(subject) if subject.tier(s.path, s.mode) == "direct"]
    if not direct:
        raise NotApplicable("no direct-tier write has a sample")
    sample = direct[0]
    with Case(subject) as case:
        argv = sample.prepare(case)
        case.grant(confirm="always")
        out = call(case, sample, argv=argv)
        check(out.code == "E_CONFIRMATION_REQUIRED" and out.details.get("confirm_token"), f"{sample.path} under confirm always: {out.describe()}")
        check(not case.applied(), f"{sample.path} ran without confirmation")


def d18(subject: Subject) -> None:
    sample = _session_write(subject)
    if sample.path == "doc save":
        raise NotApplicable("no session-mode write command that changes a document has a sample")
    with Case(subject) as case:
        out = _through(case, sample, sample.prepare(case))
        check(out.ok, f"{sample.path}: {out.describe()}")
        case.control("edit", document="doc-1", object="conformance-d18", field="note", value="by a person")
        save = case.run("doc", "save", "--session", "fake-1", "--doc", "doc-1")
        check(save.code == "E_CONFIRMATION_REQUIRED", f"doc save: {save.describe()}")
        origins = {c.get("origin") for c in save.details["preview"]["changes"]}
        check({"tool", "external"} <= origins, f"the save preview lists the origins {origins}")


def d19(subject: Subject) -> None:
    recorder = Recorder()
    try:
        with Case(subject) as case:
            env = recorder.env()
            out = case.run("knowledge", "create", "--id", "conformance-web", "--url", "https://example.com/rules",
                           "--title", "Rules", "--kind", "rule", env=env)
            check(out.code == "E_VALIDATION", f"a link that is not Feishu: {out.describe()}")
            listed = case.run("knowledge", "list", "--source", "team", env=env)
            check(listed.ok and listed.data["items"] == [], f"something was registered: {listed.describe()}")
            case.revoke()
            args = ["knowledge", "create", "--id", "conformance-team", "--url", "https://conformance.feishu.cn/wiki/abc",
                    "--title", "Team rules", "--kind", "rule", "--about", "Board rules of the team"]
            first = case.run(*args, env=env)
            check(first.code == "E_CONFIRMATION_REQUIRED", f"knowledge create is not two-step: {first.describe()}")
            done = case.run(*args, "--confirm", first.details["confirm_token"], env=env)
            check(done.ok, f"knowledge create without a scope: {done.describe()}")
            got = case.run("knowledge", "get", "--id", "conformance-team", env=env)
            check(got.ok and got.data["source"] == "team" and got.data["reader"] == "lark-cli", f"knowledge get: {got.describe()}")
            check(got.data["entry"]["url"] == "https://conformance.feishu.cn/wiki/abc", "the link was not kept as given")
            marked = got.envelope["meta"].get("untrusted", [])
            check("$.data.entry.url" in marked and "$.data.entry.about" in marked, f"meta.untrusted is {marked}")
        check(recorder.count == 0, f"{recorder.count} network requests were made")
    finally:
        recorder.close()


def d20(subject: Subject) -> None:
    with Case(subject) as case:
        case.control("configure", protocol_version="2.0.0")
        sample = _session_write(subject)
        out = call(case, sample, argv=sample.prepare(case))
        check(out.code == "E_PROTOCOL", f"{sample.path} with protocol 2.0.0: {out.describe()}")
        check(not case.applied(), "a change was sent after a protocol mismatch")


def d21(subject: Subject) -> None:
    sample = _session_write(subject)
    with Case(subject) as case:
        argv = sample.prepare(case)
        _fault(case, subject, sample, action="close")
        out = _through(case, sample, argv)
        check(out.code == "E_OUTCOME_UNKNOWN", f"{sample.path} when the host closes: {out.describe()}")
        again = call(case, sample, argv=argv)
        check(again.code == "E_CONFLICT" and again.details.get("conflict") == "target_locked", f"the target is not locked: {again.describe()}")
    with Case(subject) as case:
        case.control("fault", rule={"method": "documents", "action": "close", "session": "fake-1"})
        out = case.run("doc", "get", "--session", "fake-1", "--doc", "doc-1")
        check(out.code == "E_BUSY" and "unresponsive" in out.envelope["error"]["message"], f"a read when the host closes: {out.describe()}")


def d22(subject: Subject) -> None:
    with Case(subject) as case:
        case.control("add_session", session="fake-2")
        case.control("set_session", session="fake-2", state="unresponsive")
        started = time.monotonic()
        out = case.run("session", "list")
        took = time.monotonic() - started
        check(out.ok, f"session list: {out.describe()}")
        check(took <= 5 + 1.5, f"session list took {took:.1f} s")
        states = {s["id"]: s["state"] for s in out.data["items"]}
        check(states.get("fake-1") == "ready" and states.get("fake-2") == "unresponsive", f"the states are {states}")


def d23(subject: Subject) -> None:
    sample = _device_write(subject)
    for state in ("emergency_stop", "fault"):
        with Case(subject) as case:
            argv = sample.prepare(case)
            case.control("set_device", device="dev-1", state=state)
            out = _through(case, sample, argv)
            check(out.code == "E_HUMAN_REQUIRED" and out.details.get("action") == "confirm_on_device", f"{state}: {out.describe()}")
            check(out.details.get("dispatch_state") == "not_started" and not case.applied(), f"{state}: something was dispatched")


def d24(subject: Subject) -> None:
    # A dangerous batch stops at the first failure by default (DCLI-064); prefer one that goes on.
    samples = sorted(_own(subject, halt=None), key=lambda s: subject.tier(s.path, s.mode) == "dangerous")
    for sample in samples:
        flags = {f["name"] for f in subject.commands[sample.path]["flags"]}
        if "--ids" not in flags or "--id" not in sample.args:
            continue
        with Case(subject) as case:
            argv = sample.argv(case)
            i = argv.index("--id")
            first = argv[i + 1]
            ids = [first, "conformance-b", "conformance-c"]
            batch = argv[:i] + ["--ids", ",".join(ids)] + argv[i + 2:]
            if "--continue-on-error" in flags:
                batch += ["--continue-on-error", "true"]
            case.control("fault", rule={"method": "apply", "command": sample.path, "target": "conformance-b", "action": "error",
                                        "error": {"code": "E_NATIVE_FAILURE"}})
            out = _through(case, sample, batch)
            check(out.code == "E_PARTIAL", f"{sample.path} with one failing object: {out.describe()}")
            items = out.details.get("batch", {}).get("items", [])
            failed = [i for i in items if i.get("target", "").endswith("conformance-b")]
            check(failed and failed[0].get("code") == "E_NATIVE_FAILURE", f"the failed item is {failed}")
            others = [i for i in items if i not in failed]
            check(others and all(i["ok"] for i in others), f"the other objects are {others}")
            return
    raise NotApplicable("no write command with a sample takes --ids")


def d25(subject: Subject) -> None:
    halts = _own(subject, halt=True)
    if not halts:
        raise NotApplicable("no halt command has a sample")
    for sample in halts:
        with Case(subject) as case:
            argv = sample.prepare(case)
            if sample.mode == "device":
                case.control("set_device", device="dev-1", state="busy")
            else:
                case.control("set_session", session="fake-1", state="busy")
            case.grant(effects=["change"], confirm="always")
            out = call(case, sample, argv=argv)
            check(out.ok and out.data.get("receipt"), f"{sample.path} while busy: {out.describe()}")


TESTS: dict[str, Any] = {
    "D01": d01, "D02": d02, "D03": d03, "D04": d04, "D05": d05, "D06": d06, "D07": d07, "D08": d08, "D09": d09,
    "D10": d10, "D11": d11, "D12": d12, "D13": d13, "D14": d14, "D15": d15, "D16": d16, "D17": d17, "D18": d18,
    "D19": d19, "D20": d20, "D21": d21, "D22": d22, "D23": d23, "D24": d24, "D25": d25,
}

