"""The driver conformance suite: D01 to D26 (DVER-010).

A test is not applicable only for a reason taken from the registration; a sample or a
capability the test needs and does not find is a failure.
"""
from __future__ import annotations

import time
from typing import Any

from .harness import Case, NotApplicable, Outcome, Recorder, Subject, check
from .samples import Sample, as_batch, batchable, call, confirm, mode_of, own_samples, standard_samples, through, token_for


# ------------------------------------------------------------------ choosing samples


def _own(subject: Subject, mode: str | None = None, effect: str | None = None, halts: bool | None = False) -> list[Sample]:
    out = []
    for sample in own_samples(subject):
        reg = subject.registrations[sample.path]
        if mode and sample.mode != mode or effect and effect not in reg["effects"]:
            continue
        if halts is not None and reg["halt"] != halts:
            continue
        out.append(sample)
    return out


def _std(subject: Subject, path: str) -> Sample:
    found = [s for s in standard_samples(subject) if s.path == path]
    check(found, f"the tool offers no {path}")
    return found[0]


def _session_changes(subject: Subject) -> list[Sample]:
    found = _own(subject, "session", "change")
    if not found:
        raise NotApplicable("the registration has no session-mode command with the change effect")
    return sorted(found, key=lambda s: subject.tier(s.path, s.mode) != "direct")


def _device_writes(subject: Subject) -> list[Sample]:
    return _own(subject, "device")


def _field_samples(subject: Subject) -> list[Sample]:
    """The writes whose verification reads fields back rather than files."""
    found = [s for s in _own(subject) if "artifact" not in subject.registrations[s.path]["effects"]
             and not subject.registrations[s.path].get("verify_after_save")]  # those are verified at the save
    if not found:
        raise NotApplicable("the registration has no write that changes fields")
    return found


def _no_apply(case: Case, what: str) -> None:
    check(not case.calls("apply") and not case.applied(), f"{what}: a change was dispatched")


def _locked(out: Outcome, what: str) -> None:
    check(out.code == "E_CONFLICT" and out.details.get("conflict") == "target_locked", f"{what}: {out.describe()}")


def _session_target(subject: Subject) -> Sample:
    """A session-mode write to try state changes on: a domain change, or doc save."""
    try:
        return _session_changes(subject)[0]
    except NotApplicable:
        return _std(subject, "doc save")


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
        token = token_for(case, sample, argv)
        change(case)
        out = confirm(case, sample, argv, token)
        check(out.code == "E_CONFLICT" and out.details.get("conflict") == conflict, f"{sample.path}: {out.describe()}")
        _no_apply(case, sample.path)
        check(not case.calls("save_doc"), f"{sample.path}: the save was sent")


def d02(subject: Subject) -> None:
    _token_then(subject, _std(subject, "doc save"), lambda case: case.control("restart_session", session="fake-1"), "session_changed")
    if subject.host_component:
        def reload(case: Case) -> None:
            items = []
            for inst in case.state()["instances"]:
                view = {k: v for k, v in inst.items() if k != "values"}
                if view["id"] == "fake-1":
                    view["plugin_loaded"] = "9.9.9"
                items.append(view)
            case.control("fault", rule={"method": "sessions", "action": "result", "result": {"items": items}, "times": 0})
            case.control("configure", plugin={"version_on_disk": "9.9.9"})  # installed and reloaded: no mismatch, only a change
        _token_then(subject, _std(subject, "doc save"), reload, "plugin_changed")


def d03(subject: Subject) -> list[str]:
    targets = []
    if "session" in subject.modes:
        targets.append((_std(subject, "doc save"), "doc-1"))
    files = [s for s in _own(subject, "file") if subject.tier(s.path, "file") != "direct"]
    if files:
        targets.append((files[0], "file-1"))
    check(targets, "no confirmable write on a document has a sample")
    for sample, doc in targets:
        _token_then(subject, sample, lambda case, d=doc: case.control("edit", document=d, object="conformance-d03",
                                                                      field="note", value="changed"), "document_changed")
    if "session" in subject.modes:
        sample = _session_target(subject)
        with Case(subject) as case:
            argv = sample.prepare(case)
            case.control("set_disk", document="doc-1", disk="changed")
            out = through(case, sample, argv)
            check(out.code == "E_CONFLICT" and out.details.get("conflict") == "file_changed_on_disk",
                  f"{sample.path} on a document changed on disk: {out.describe()}")
            _no_apply(case, sample.path)
            check(not case.calls("save_doc"), f"{sample.path}: the save was sent")
    file_only = [s for s in _own(subject, "file") if subject.registrations[s.path]["modes"] == ["file"]]
    if file_only and "session" in subject.modes:
        sample = file_only[0]
        with Case(subject) as case:
            argv = sample.argv(case)
            i = argv.index("--doc")
            argv[i + 1] = case.doc_path("doc-1")
            out = through(case, sample, argv)
            check(out.code == "E_CONFLICT" and out.details.get("conflict") == "file_open_in_session",
                  f"{sample.path} on a file an instance has open: {out.describe()}")
            _no_apply(case, sample.path)
    return [s.path for s, _ in targets]


def _busy(out: Outcome, what: str) -> None:
    check(out.code == "E_BUSY" and out.envelope["error"]["retryable"], f"{what}: {out.describe()}")
    check(isinstance(out.details.get("retry_after_ms"), int), f"{what}: no retry_after_ms")
    check(out.details.get("dispatch_state") == "not_started", f"{what}: dispatch_state is not not_started")


def _unreachable(out: Outcome, what: str) -> None:
    check(out.code == "E_BACKEND_UNAVAILABLE", f"{what}: {out.describe()}")
    check(out.details.get("dispatch_state") == "not_started", f"{what}: dispatch_state is not not_started")


def _refused_then_usable(subject: Subject, sample: Sample, bad: Any, good: Any, judge: Any, what: str) -> None:
    """A state that refuses a call, set first before the call and then between the token and
    the confirm; once the state clears, the same token still runs the write (DCLI-055)."""
    with Case(subject) as case:
        argv = sample.prepare(case)
        bad(case)
        judge(call(case, sample, argv=argv), f"{sample.path} {what}")
        _no_apply(case, f"{sample.path} {what}")
    with Case(subject) as case:
        argv = sample.prepare(case)
        token = token_for(case, sample, argv)
        bad(case)
        judge(confirm(case, sample, argv, token), f"{sample.path} {what} after the dry run")
        _no_apply(case, f"{sample.path} {what} after the dry run")
        check(not case.calls("save_doc"), f"{sample.path}: the save was sent")
        refused = confirm(case, sample, argv, token)
        good(case)
        resume = refused.details.get("resume")
        if resume:
            check(token in resume, f"{sample.path}: resume does not carry the token that is still usable: {resume!r}")
            out = case.run_line(resume)
        else:
            out = confirm(case, sample, argv, token)
        check(out.ok, f"{sample.path}: the token did not stay usable after a refusal that sent nothing: {out.describe()}")


def d04(subject: Subject) -> list[str]:
    notes = []
    if "session" in subject.modes:
        sample = _std(subject, "doc save")
        _refused_then_usable(subject, sample, lambda c: c.control("set_session", session="fake-1", state="busy"),
                             lambda c: c.control("set_session", session="fake-1", state="ready"), _busy, "on a busy instance")
        # An instance the tool cannot drive refuses the write and sends nothing (DCLI-204).
        _refused_then_usable(subject, sample, lambda c: c.control("set_session", session="fake-1", state="unreachable"),
                             lambda c: c.control("set_session", session="fake-1", state="ready"), _unreachable,
                             "on an instance the tool cannot drive")
        with Case(subject) as case:
            # The application itself answers busy to the dispatch: nothing began, the token stays usable.
            argv = sample.prepare(case)
            token = token_for(case, sample, argv)
            case.control("fault", rule={"method": "save_doc", "action": "error", "error": {"code": "E_BUSY"}})
            _busy(confirm(case, sample, argv, token), f"{sample.path} answered busy at dispatch")
            out = confirm(case, sample, argv, token)
            check(out.ok, f"{sample.path}: the token did not stay usable after the application answered busy: {out.describe()}")
        for sample in _own(subject, "session")[:1]:
            with Case(subject) as case:
                argv = sample.prepare(case)
                case.control("set_session", session="fake-1", state="busy")
                _busy(call(case, sample, argv=argv), f"{sample.path} on a busy instance")
                _no_apply(case, sample.path)
        notes.append("session")
    for sample in _device_writes(subject)[:1]:
        _refused_then_usable(subject, sample, lambda c: c.control("set_device", device="dev-1", state="busy"),
                             lambda c: c.control("set_device", device="dev-1", state="ready"), _busy, "on a busy device")
        notes.append(f"device: {sample.path}")
    return notes


def _human(action: str | None = None) -> Any:
    def judge(out: Outcome, what: str) -> None:
        check(out.code == "E_HUMAN_REQUIRED" and out.details.get("action"), f"{what}: {out.describe()}")
        if action:
            check(out.details["action"] == action, f"{what}: the action is {out.details['action']}, not {action}")
        check(out.details.get("dispatch_state") == "not_started", f"{what}: dispatch_state is not not_started")
        resume = out.details.get("resume", "")
        check("operation resolve" not in resume, f"{what}: resume must run the call again, not settle it: {resume!r}")
    return judge


def d05(subject: Subject) -> None:
    sample = _std(subject, "doc save")
    _refused_then_usable(subject, sample, lambda c: c.control("set_session", session="fake-1", state="blocked", title="Conformance dialog"),
                         lambda c: c.control("set_session", session="fake-1", state="ready"), _human(), "behind a dialog")
    with Case(subject) as case:
        argv = sample.prepare(case)
        case.control("set_session", session="fake-1", state="blocked", title="Conformance dialog")
        out = call(case, sample, argv=argv)
        check("$.error.details.title" in out.envelope.get("meta", {}).get("untrusted", []), "the dialog title is not marked untrusted")
        check(sample.path in out.details.get("resume", ""), f"resume does not run the call again: {out.details.get('resume')!r}")
    target = _session_target(subject)
    method = "save_doc" if target.path == "doc save" else "apply"
    with Case(subject) as case:
        argv = target.prepare(case)
        rule = {"method": method, "action": "error", "apply_first": True, "error": {"code": "E_HUMAN_REQUIRED", "action": "dismiss_dialog"}}
        if method == "apply":
            rule["command"] = target.path
        case.control("fault", rule=rule)
        out = through(case, target, argv)
        check(out.code == "E_HUMAN_REQUIRED", f"a dialog after dispatch: {out.describe()}")
        resume = out.details.get("resume", "")
        check("operation resolve" in resume, f"after dispatch, resume must settle the outcome, not write again: {resume!r}")
        _locked(call(case, target, argv=argv), "the target after a dialog opened by the change")


def _unknown(case: Case, subject: Subject, sample: Sample, argv: list[str]) -> None:
    case.control("fault", rule={"method": "apply", "command": sample.path, "action": "close", "apply_first": True})
    out = through(case, sample, argv)
    check(out.exit == 8 and out.code == "E_OUTCOME_UNKNOWN", f"{sample.path} after a lost connection: {out.describe()}")
    lookup = out.details.get("lookup", "")
    check("operation resolve" in lookup, f"lookup does not settle the outcome: {lookup!r}")
    _locked(call(case, sample, argv=argv), f"{sample.path} while the outcome is unknown")
    resolved = case.run(*lookup.split()[1:])
    check(resolved.ok and resolved.data.get("resolution"), f"the lookup does not settle it: {resolved.describe()}")
    after = call(case, sample, "--dry-run", argv=argv)
    check(after.ok, f"the target stays locked after the outcome was resolved: {after.describe()}")


def d06(subject: Subject) -> list[str]:
    notes = []
    samples = _own(subject, "session")[:1] + _device_writes(subject)[:1]
    check(samples, "no session-mode or device-mode write has a sample")
    for sample in samples:
        with Case(subject) as case:
            _unknown(case, subject, sample, sample.prepare(case))
        notes.append(sample.path)
    batches = sorted([s for s in _own(subject) if s.mode in ("session", "device") and batchable(subject, s)],
                     key=lambda s: subject.tier(s.path, s.mode) == "dangerous")
    for sample in batches[:1]:
        with Case(subject) as case:
            argv = as_batch(sample, sample.prepare(case), ["conformance-b", "conformance-c"])
            case.control("fault", rule={"method": "apply", "command": sample.path, "target": "conformance-b", "action": "close",
                                        "apply_first": True})
            out = through(case, sample, argv)
            check(out.code == "E_OUTCOME_UNKNOWN", f"a batch with one lost reply: {out.describe()}")
            lookup = out.details.get("lookup", "")
            check("operation list" in lookup and "--batch" in lookup and "unknown" in lookup, f"the batch lookup is {lookup!r}")
            single = as_batch(sample, sample.argv(case), [])
            i = single.index("--ids")
            single[i + 1] = "conformance-b"
            _locked(call(case, sample, argv=single), "an object of a batch whose outcome is unknown")
        notes.append(f"batch: {sample.path}")
    return notes


def _fields_of(case: Case, sample: Sample, argv: list[str]) -> list[str]:
    dry = call(case, sample, "--dry-run", argv=argv)
    check(dry.ok, f"{sample.path} dry run: {dry.describe()}")
    return sorted({c["field"] for c in dry.data["preview"]["changes"] if c.get("field")})


def d07(subject: Subject) -> list[str]:
    for sample in _field_samples(subject):
        with Case(subject) as case:
            argv = sample.prepare(case)
            fields = _fields_of(case, sample, argv)
            case.control("fault", rule={"method": "read_back", "command": sample.path, "action": "unreadable", "fields": fields})
            out = through(case, sample, argv)
            check(out.code == "E_VERIFY_INCOMPLETE" and out.details.get("receipt"), f"{sample.path}: {out.describe()}")
    return [s.path for s in _field_samples(subject)]


def d08(subject: Subject) -> list[str]:
    samples = _field_samples(subject)
    for sample in samples:
        with Case(subject) as case:
            argv = sample.prepare(case)
            fields = _fields_of(case, sample, argv)
            case.control("fault", rule={"method": "apply", "command": sample.path, "action": "store",
                                        "values": {f: "conformance-other-value" for f in fields}})
            out = through(case, sample, argv)
            check(out.code == "E_VERIFY_FAILED", f"{sample.path}: {out.describe()}")
            check(out.details.get("receipt", {}).get("mismatched"), f"{sample.path}: the mismatched fields are not listed")
    for sample in [s for s in _own(subject) if "artifact" in subject.registrations[s.path]["effects"]][:1]:
        with Case(subject) as case:
            argv = sample.prepare(case)
            output = next(a for a in argv if str(case.dir) in a)
            missing = output + ".missing"
            case.control("fault", rule={"method": "apply", "command": sample.path, "action": "result",
                                        "result": {"files": [{"path": output}, {"path": missing}]}})
            out = through(case, sample, argv)
            mismatched = out.details.get("receipt", {}).get("mismatched", [])
            check(out.code == "E_VERIFY_FAILED" and any(m.startswith("exists@") for m in mismatched),
                  f"{sample.path} reported a file that does not exist: {out.describe()}")
    for sample in samples:
        tolerances = subject.registrations[sample.path]["tolerances"]
        if not tolerances:
            continue
        for factor, ok in ((2.0, False), (0.5, True)):
            with Case(subject) as case:
                argv = sample.prepare(case)
                dry = call(case, sample, "--dry-run", argv=argv)
                values = {c["field"]: c["after"] + factor * tolerances[c["field"]] for c in dry.data["preview"]["changes"]
                          if c.get("field") in tolerances and isinstance(c.get("after"), (int, float))}
                if not values:
                    continue
                case.control("fault", rule={"method": "apply", "command": sample.path, "action": "store", "values": values})
                out = through(case, sample, argv)
                if ok:
                    check(out.ok, f"{sample.path} stored within its tolerance: {out.describe()}")
                else:
                    check(out.code == "E_VERIFY_FAILED", f"{sample.path} stored outside its tolerance: {out.describe()}")
        break
    for sample in [s for s in samples if batchable(subject, s)][:1]:
        with Case(subject) as case:
            argv = sample.prepare(case)
            fields = _fields_of(case, sample, argv)
            batch = as_batch(sample, argv, ["conformance-b"])
            case.control("fault", rule={"method": "apply", "command": sample.path, "target": "conformance-b", "action": "store",
                                        "values": {f: "conformance-other-value" for f in fields}})
            out = through(case, sample, batch)
            items = out.details.get("batch", {}).get("items", [])
            wrong = [i for i in items if i.get("target", "").endswith("conformance-b")]
            check(wrong and wrong[0].get("code") == "E_VERIFY_FAILED", f"a batch item read back wrong: {out.describe()}")
    return [s.path for s in samples]


def d09(subject: Subject) -> None:
    sample = _session_changes(subject)[0]
    with Case(subject) as case:
        out = through(case, sample, sample.prepare(case))
        check(out.ok, f"{sample.path}: {out.describe()}")
        receipt = out.data["receipt"]
        check(receipt["outcome"]["persistence"] == "unchanged", f"a session-mode change reports persistence {receipt['outcome']['persistence']}")
        doc = case.run("doc", "get", "--session", "fake-1", "--doc", "doc-1")
        check(doc.ok and doc.data["dirty"] is True, f"the document is not dirty after the change: {doc.describe()}")
        save = through(case, _std(subject, "doc save"), ["--session", "fake-1", "--doc", "doc-1"])
        check(save.ok and save.data["receipt"]["outcome"]["persistence"] == "saved", f"doc save: {save.describe()}")


def d10(subject: Subject) -> None:
    with Case(subject) as case:
        case.control("edit", document="doc-1", object="conformance-d10", field="note", value="unsaved")
        out = case.run("doc", "close", "--session", "fake-1", "--doc", "doc-1")
        check(out.code == "E_CONFLICT" and out.details.get("conflict") == "unsaved_changes", f"doc close: {out.describe()}")
        out = case.run("doc", "close", "--session", "fake-1", "--doc", "doc-1", "--discard")
        check(out.exit == 5 and out.details.get("preview", {}).get("tier") == "dangerous", f"doc close --discard: {out.describe()}")
        token = out.details["confirm_token"]
        out = case.run("doc", "close", "--session", "fake-1", "--doc", "doc-1", "--discard", "--confirm", token)
        check(out.exit == 5, f"doc close --discard confirmed without --dangerous: {out.describe()}")
        check(any(d["id"] == "doc-1" for d in case.state()["documents"]), "the document was closed")


def d11(subject: Subject) -> None:
    jobs = [s for s in _own(subject, halts=None) if "job_status" in subject.registrations[s.path]["adapter_capabilities"]]
    check(jobs, "no command with long jobs has a sample")
    sample = jobs[0]
    with Case(subject) as case:
        argv = sample.prepare(case)
        case.control("fault", rule={"method": "apply", "command": sample.path, "action": "job", "steps": 50})
        out = through(case, sample, argv)
        check(out.ok and out.data["result"].get("job", {}).get("id"), f"{sample.path} as a long job: {out.describe()}")
        job = out.data["result"]["job"]
        check(job["poll"].startswith(subject.name) and "--job" in job["poll"], f"the poll command is not complete: {job['poll']!r}")
        cancel = case.run("job", "cancel", "--job", job["id"])
        check(cancel.ok, f"job cancel: {cancel.describe()}")
        first = cancel.data["result"]
        check(first.get("cancel_requested") is True, f"job cancel does not report cancel_requested: {first}")
        check(first.get("state") != "cancelled", "the job is reported cancelled before the application confirmed it")
        # The application keeps saying the job runs: the job must not be reported cancelled.
        case.control("fault", rule={"method": "job_status", "action": "result", "result": {"state": "running"}, "times": 0})
        still = case.run("job", "get", "--job", job["id"])
        check(still.ok and still.data["state"] == "running" and still.data["cancel_requested"] is True,
              f"job get while the application still runs the job: {still.describe()}")
        case.control("clear_faults")
        got = case.run("job", "get", "--job", job["id"], "--wait", "10s")
        check(got.ok and got.data["state"] == "cancelled", f"job get after the application stopped: {got.describe()}")
        check(got.data.get("ok") is False and got.data.get("code") == "E_INTERRUPTED", f"a cancelled job's outcome: {got.data}")
    if "session" in subject.modes and sample.mode == "session":
        with Case(subject) as case:
            argv = sample.prepare(case)
            case.control("fault", rule={"method": "apply", "command": sample.path, "action": "job", "steps": 50})
            job = through(case, sample, argv).data["result"]["job"]
            case.control("set_session", session="fake-1", state="busy")
            out = case.run("job", "cancel", "--job", job["id"])
            check(out.ok, f"job cancel while the instance is busy: {out.describe()}")
    for label, fault, want in (("read back", None, (True, None)),
                               ("not read back", {"method": "read_back", "command": sample.path, "action": "unreadable"},
                                (False, "E_VERIFY_INCOMPLETE")),
                               ("ended in part", {"method": "job_status", "action": "result",
                                                  "result": {"state": "partial", "change": "applied", "delivery": "not_applicable",
                                                             "persistence": "unchanged"}},
                                (False, "E_PARTIAL"))):
        with Case(subject) as case:
            argv = sample.prepare(case)
            fields = sorted({c["field"] for c in call(case, sample, "--dry-run", argv=argv).data["preview"]["changes"] if c.get("field")})
            case.control("fault", rule={"method": "apply", "command": sample.path, "action": "job", "steps": 2})
            job = through(case, sample, argv).data["result"]["job"]
            if fault is not None:
                if fault["action"] == "unreadable":
                    fault = {**fault, "fields": fields}
                case.control("fault", rule=fault)
            got = case.run("job", "get", "--job", job["id"], "--wait", "10s")
            check(got.ok and got.data["state"] in ("completed", "partial"), f"a job that {label}: {got.describe()}")
            check((got.data.get("ok"), got.data.get("code")) == want, f"a job that {label}: ok {got.data.get('ok')}, code {got.data.get('code')}")


def d12(subject: Subject) -> None:
    with Case(subject) as case:
        case.control("configure", plugin={"version_on_disk": "9.9.9"})
        doctor = case.run("doctor")
        plugin = next((c for c in doctor.data["checks"] if c["check"] == "plugin"), {})
        check(plugin.get("status") == "fail", f"the plugin check of doctor does not fail: {plugin}")
        sample = _session_target(subject)
        argv = sample.prepare(case)
        out = call(case, sample, argv=argv)
        check(out.code == "E_HUMAN_REQUIRED" and out.details.get("action") == "restart_application", f"{sample.path}: {out.describe()}")
        check(out.details.get("dispatch_state") == "not_started", f"{sample.path}: dispatch_state")
        _no_apply(case, f"{sample.path} on a stale host component")
    sample = _std(subject, "doc save")
    with Case(subject) as case:
        argv = sample.prepare(case)
        token = token_for(case, sample, argv)
        case.control("configure", plugin={"version_on_disk": "9.9.9"})
        out = confirm(case, sample, argv, token)
        check(out.code == "E_HUMAN_REQUIRED" and out.details.get("action") == "restart_application",
              f"a confirm after the host component went stale: {out.describe()}")
        check(not case.calls("save_doc"), "the save was sent to a stale host component")


def d13(subject: Subject) -> list[str]:
    import re

    notes = []
    with Case(subject) as case:
        for sample in _own(subject, halts=None):
            units = {f["name"]: f for f in subject.commands[sample.path]["flags"] if f.get("unit")}
            argv = sample.argv(case)
            for i, arg in enumerate(argv[:-1]):
                bare = re.match(r"-?[0-9.]+", argv[i + 1]) if arg in units else None
                if bare:
                    out = call(case, sample, argv=argv[:i + 1] + [bare.group(0)] + argv[i + 2:])
                    check(out.code == "E_USAGE", f"{sample.path} {arg} {bare.group(0)}: {out.describe()}")
                    check(units[arg]["unit"] in out.details.get("problem", ""), f"the problem does not list the units: {out.describe()}")
                    notes.append(f"{sample.path} {arg}")
                    break
        out = case.run("job", "get", "--job", "conformance", "--wait", "60")
        problem = out.details.get("problem", "")
        check(out.code == "E_USAGE" and all(u in problem for u in ("ms", "min", "h")), f"job get --wait 60: {out.describe()}")
    return notes


def d14(subject: Subject) -> None:
    samples = _own(subject, effect="physical")
    if not samples:
        raise NotApplicable("the registration has no physical command")
    for sample in samples:
        with Case(subject) as case:
            argv = sample.prepare(case)
            first = call(case, sample, argv=argv)
            check(first.code == "E_CONFIRMATION_REQUIRED", f"{sample.path} without flags: {first.describe()}")
            token = first.details["confirm_token"]
            out = confirm(case, sample, argv, token, dangerous=False)
            check(out.exit == 5, f"{sample.path} confirmed without --dangerous: {out.describe()}")
            case.grant(effects=["lifecycle", "change", "artifact", "persist", "configure", "deliver"])
            out = confirm(case, sample, argv, token)
            check(out.code == "E_FORBIDDEN" and "physical" in out.details.get("scope", {}).get("missing", {}).get("effects", []),
                  f"{sample.path} without physical in the scope: {out.describe()}")
            case.grant(dangerous=False)
            out = call(case, sample, argv=argv)
            check(out.code == "E_FORBIDDEN" and out.details["scope"]["missing"]["dangerous"], f"{sample.path} with dangerous false: {out.describe()}")
            _no_apply(case, sample.path)


def d15(subject: Subject) -> None:
    with Case(subject) as case:
        devices = case.run("device", "list")
        check(devices.ok and devices.data["items"], f"device list: {devices.describe()}")
        for device in devices.data["items"]:
            check(device.get("simulated") is True, f"the simulated device {device.get('id')} does not say so")
        for sample in _device_writes(subject)[:1]:
            out = through(case, sample, sample.prepare(case))
            check(out.ok, f"{sample.path}: {out.describe()}")
            check(out.data["receipt"].get("simulated") is True, "the receipt of a simulated device lacks simulated: true")
            result = out.data.get("result")
            check(not isinstance(result, dict) or result.get("simulated") is True, "the result of a simulated device lacks simulated: true")


def d16(subject: Subject) -> None:
    direct = [s for s in _session_changes(subject) if subject.tier(s.path, "session") == "direct"]
    if not direct:
        raise NotApplicable("the registration has no direct-tier session-mode change")
    sample = direct[0]
    with Case(subject) as case:
        argv = sample.prepare(case)
        out = call(case, sample, argv=argv)
        check(out.ok, f"{sample.path} in one call: {out.describe()}")
        receipt = out.data["receipt"]
        check(receipt["outcome"]["verification"] == "passed" and receipt["observed"], f"no read-back: {receipt}")
        record = case.run("operation", "get", "--id", out.data["operation_id"])
        check(record.ok and record.data["state"] == "completed" and record.data.get("receipt"), f"no operation record: {record.describe()}")
        case.revoke()
        out = call(case, sample, argv=argv)
        check(out.code == "E_FORBIDDEN", f"{sample.path} without a scope: {out.describe()}")


def d17(subject: Subject) -> None:
    direct = [s for s in _own(subject) if subject.tier(s.path, s.mode) == "direct"]
    direct += [s for s in standard_samples(subject) if s.path in ("doc create", "session open")]
    check(direct, "no direct-tier write has a sample")
    for sample in direct[:2]:
        with Case(subject) as case:
            argv = sample.prepare(case)
            case.grant(confirm="always")
            out = call(case, sample, argv=argv)
            check(out.code == "E_CONFIRMATION_REQUIRED" and out.details.get("confirm_token"), f"{sample.path} under confirm always: {out.describe()}")
            check(not case.applied() and len(case.state()["instances"]) == 1, f"{sample.path} ran without confirmation")


def d18(subject: Subject) -> None:
    sample = _session_changes(subject)[0]
    with Case(subject) as case:
        out = through(case, sample, sample.prepare(case))
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
            for url in ("https://example.com/rules", "https://notfeishu.cn/wiki/x", "http://team.feishu.cn/wiki/x",
                        "https://user@team.feishu.cn/wiki/x", "https://team.feishu.cn:8443/wiki/x", "https://feishu.cn.evil.com/wiki/x",
                        "https://team.feishu.cn/wiki/" + "x" * 2100):
                out = case.run("knowledge", "create", "--id", "conformance-web", "--url", url, "--title", "Rules", "--kind", "rule", env=env)
                check(out.code == "E_VALIDATION", f"the link {url[:60]!r} is not a Feishu link: {out.describe()}")
            builtin = case.run("knowledge", "list", "--source", "builtin", env=env).data["items"]
            if builtin:
                out = case.run("knowledge", "create", "--id", builtin[0]["id"], "--url", "https://team.feishu.cn/wiki/x",
                               "--title", "Clash", "--kind", "guide", env=env)
                check(out.code == "E_VALIDATION", f"a team link with a builtin ID: {out.describe()}")
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
            marked = got.envelope.get("meta", {}).get("untrusted", [])
            check("$.data.entry.url" in marked and "$.data.entry.about" in marked, f"meta.untrusted is {marked}")
        check(recorder.count == 0, f"{recorder.count} network requests were made")
    finally:
        recorder.close()


def d20(subject: Subject) -> None:
    for version in ("2.0.0", "0.9.0"):
        with Case(subject) as case:
            case.control("configure", protocol_version=version)
            sample = _session_target(subject)
            out = call(case, sample, argv=sample.prepare(case))
            check(out.code == "E_PROTOCOL", f"{sample.path} with protocol {version}: {out.describe()}")
            _no_apply(case, f"{sample.path} after a protocol mismatch")


def d21(subject: Subject) -> None:
    sample = _session_target(subject)
    method = "save_doc" if sample.path == "doc save" else "apply"
    with Case(subject) as case:
        argv = sample.prepare(case)
        rule = {"method": method, "action": "close"}
        if method == "apply":
            rule["command"] = sample.path
        case.control("fault", rule=rule)
        out = through(case, sample, argv)
        check(out.code == "E_OUTCOME_UNKNOWN", f"{sample.path} when the host closes: {out.describe()}")
        _locked(call(case, sample, argv=argv), f"{sample.path} after the host closed")
    with Case(subject) as case:
        case.control("fault", rule={"method": "documents", "action": "close", "session": "fake-1"})
        out = case.run("doc", "get", "--session", "fake-1", "--doc", "doc-1")
        check(out.code == "E_BUSY" and out.details.get("dispatch_state") == "not_started", f"a read when the host closes: {out.describe()}")
        check("unresponsive" in out.envelope["error"]["message"], f"the read does not report the session unresponsive: {out.describe()}")


def d22(subject: Subject) -> None:
    with Case(subject) as case:
        case.control("add_session", session="fake-2")
        case.control("set_session", session="fake-2", state="unresponsive")
        started = time.monotonic()
        case.run("--version")
        startup = time.monotonic() - started
        started = time.monotonic()
        out = case.run("session", "list")
        took = time.monotonic() - started - startup
        check(out.ok, f"session list: {out.describe()}")
        check(took <= 2 + 1.0, f"session list waited {took:.1f} s for an instance that does not answer; the limit is 2 s")
        states = {s["id"]: s["state"] for s in out.data["items"]}
        check(states.get("fake-1") == "ready" and states.get("fake-2") == "unresponsive", f"the states are {states}")


def d23(subject: Subject) -> list[str]:
    samples = _device_writes(subject)
    check(samples, "no device-mode write has a sample")
    sample = samples[0]
    with Case(subject) as case:
        argv = sample.prepare(case)
        token = token_for(case, sample, argv)
        ready = [{**{k: v for k, v in d.items() if k != "values"}, "state": "ready"} for d in case.state()["devices"]]
        case.control("set_device", device="dev-1", state="emergency_stop")
        # The first read of the device still says ready; the read right before dispatch must not (DSEC-061).
        case.control("fault", rule={"method": "devices", "action": "result", "result": {"items": ready}})
        out = confirm(case, sample, argv, token)
        check(out.code == "E_HUMAN_REQUIRED", f"{sample.path} when the emergency stop is pressed during the confirm: {out.describe()}")
        _no_apply(case, f"{sample.path} when the emergency stop is pressed during the confirm")
    for state in ("emergency_stop", "fault"):
        _refused_then_usable(subject, sample, lambda c, s=state: c.control("set_device", device="dev-1", state=s),
                             lambda c: c.control("set_device", device="dev-1", state="ready"), _human("confirm_on_device"),
                             f"in {state}")
    return [sample.path]


def d24(subject: Subject) -> None:
    samples = sorted([s for s in _own(subject, halts=None) if batchable(subject, s)],
                     key=lambda s: subject.tier(s.path, s.mode) == "dangerous")
    if not samples:
        if not any("--ids" in {f["name"] for f in r["flags"]} for r in subject.registrations.values()):
            raise NotApplicable("the registration has no write command that takes --ids")
        check(False, "a write command takes --ids, but its sample selects no object with --id or --ids")
    sample = samples[0]
    flags = {f["name"] for f in subject.commands[sample.path]["flags"]}
    with Case(subject) as case:
        batch = as_batch(sample, sample.prepare(case), ["conformance-b", "conformance-c"])
        if "--continue-on-error" in flags:
            batch += ["--continue-on-error", "true"]
        case.control("fault", rule={"method": "apply", "command": sample.path, "target": "conformance-b", "action": "error",
                                    "error": {"code": "E_NATIVE_FAILURE"}})
        out = through(case, sample, batch)
        check(out.code == "E_PARTIAL", f"{sample.path} with one failing object: {out.describe()}")
        items = out.details.get("batch", {}).get("items", [])
        failed = [i for i in items if i.get("target", "").endswith("conformance-b")]
        check(failed and failed[0].get("code") == "E_NATIVE_FAILURE", f"the failed item is {failed}")
        others = [i for i in items if i not in failed]
        if subject.tier(sample.path, sample.mode) != "dangerous" or "--continue-on-error" in flags:
            check(others and all(i["ok"] for i in others), f"the other objects are {others}")
    for sample in [s for s in samples if subject.tier(s.path, s.mode) == "dangerous"][:1]:
        with Case(subject) as case:
            batch = as_batch(sample, sample.prepare(case), ["conformance-b", "conformance-c"])
            case.control("fault", rule={"method": "apply", "command": sample.path, "target": "conformance-b", "action": "error",
                                        "error": {"code": "E_NATIVE_FAILURE"}})
            out = through(case, sample, batch)
            last = [i for i in out.details.get("batch", {}).get("items", []) if i.get("target", "").endswith("conformance-c")]
            check(last and last[0].get("skipped") is True, f"a dangerous batch went on after a failure: {out.describe()}")
    with Case(subject) as case:
        sample = samples[0]
        batch = as_batch(sample, sample.prepare(case), ["conformance-b", "conformance-c"])
        case.control("fault", rule={"method": "apply", "command": sample.path, "target": "conformance-b", "action": "error",
                                    "error": {"code": "E_BUSY"}})
        out = through(case, sample, batch)
        check(out.code == "E_PARTIAL", f"a batch stopped by a busy instance after one change: {out.describe()}")
        items = {i["target"].rsplit("/", 1)[-1]: i for i in out.details["batch"]["items"]}
        check(items["conformance-c"].get("skipped") is True, f"the batch did not stop when the instance was busy: {items}")
        resume = out.details.get("resume", "")
        check("conformance-b" in resume and "conformance-c" in resume and argv_id(sample, case) not in resume,
              f"resume must cover only the unfinished objects: {resume!r}")
    with Case(subject) as case:
        sample = samples[0]
        batch = as_batch(sample, sample.prepare(case), ["conformance-b"])
        case.control("fault", rule={"method": "apply", "command": sample.path, "action": "error", "times": 0,
                                    "error": {"code": "E_VALIDATION"}})
        out = through(case, sample, batch)
        check(out.code == "E_VALIDATION", f"a batch where every object fails takes the first object's code: {out.describe()}")


def argv_id(sample: Sample, case: Case) -> str:
    argv = sample.argv(case)
    flag = "--id" if "--id" in argv else "--ids"
    return argv[argv.index(flag) + 1].split(",")[0]


def d25(subject: Subject) -> None:
    halts = _own(subject, halts=True)
    check(halts, "a halt command has no sample")
    for sample in halts:
        with Case(subject) as case:
            argv = sample.prepare(case)
            states = ["busy", "fault", "emergency_stop"] if sample.mode == "device" else ["busy", "blocked"]
            case.grant(effects=["change"], confirm="always")
            for state in states:
                if sample.mode == "device":
                    case.control("set_device", device="dev-1", state=state)
                else:
                    case.control("set_session", session="fake-1", state=state)
                sent = len(case.calls("apply"))
                out = call(case, sample, argv=argv)
                check(out.ok and out.data.get("receipt"), f"{sample.path} while {state}: {out.describe()}")
                check(len(case.calls("apply")) > sent, f"{sample.path} was not sent while {state}")


def d26(subject: Subject) -> list[str]:
    """A long command returns a job at once; its worker settles it like any write, or returns
    the read's result; a long read needs no scope (DCLI-065)."""
    longs = [p for p, r in subject.registrations.items() if r.get("long") and p in subject.samples]
    check(longs, "a long command has no sample in the normal row of its behavior matrix")
    for path in longs:
        reg = subject.registrations[path]
        sample = Sample(path, subject.samples[path], mode_of(subject, path, subject.samples[path]), True)
        writes = reg["effects"] != ["observe"]
        for mismatch in ((False, True) if writes else (False,)):
            with Case(subject) as case:
                argv = sample.prepare(case)
                if not writes:
                    case.revoke()
                if mismatch:
                    fields = _fields_of(case, sample, argv)
                    case.control("fault", rule={"method": "apply", "command": path, "action": "store",
                                                "values": {f: "conformance-other-value" for f in fields}})
                out = through(case, sample, argv)
                job = (out.data or {}).get("result", {}).get("job") if writes else (out.data or {}).get("job")
                check(out.ok and job and job.get("poll"), f"{path} did not return a long job at once: {out.describe()}")
                done = case.run("job", "get", "--job", job["id"], "--wait", "60s")
                data = done.data or {}
                check(data.get("state") in ("completed", "failed", "partial", "unknown", "cancelled"),
                      f"{path}: the job did not end: {done.describe()}")
                if not writes:
                    check(data.get("ok") and "result" in data and data.get("operation_id") is None,
                          f"{path}: the read job gave no result: {done.describe()}")
                elif mismatch:
                    check(data.get("code") == "E_VERIFY_FAILED", f"{path}: a mismatch in the worker was not reported: {done.describe()}")
                else:
                    check(data.get("ok") and data.get("receipt", {}).get("outcome", {}).get("verification") == "passed",
                          f"{path}: the worker did not verify the change: {done.describe()}")
                    check(len(case.applied()) == 1, f"{path}: the worker applied the change {len(case.applied())} times")
    return longs


TESTS: dict[str, Any] = {
    "D01": d01, "D02": d02, "D03": d03, "D04": d04, "D05": d05, "D06": d06, "D07": d07, "D08": d08, "D09": d09,
    "D10": d10, "D11": d11, "D12": d12, "D13": d13, "D14": d14, "D15": d15, "D16": d16, "D17": d17, "D18": d18,
    "D19": d19, "D20": d20, "D21": d21, "D22": d22, "D23": d23, "D24": d24, "D25": d25, "D26": d26,
}
