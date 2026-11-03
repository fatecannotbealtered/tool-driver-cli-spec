"""Write samples: the tool's own, from the normal row of each behavior matrix (DVER-002), and
the ones the suites bring for the standard commands."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .harness import Case, Outcome, Subject


@dataclass
class Sample:
    path: str
    args: list[str]
    mode: str
    domain: bool
    needs_scope: bool = True
    setup: Callable[[Case], None] | None = None

    @property
    def file_mode(self) -> bool:
        return self.mode == "file"

    def prepare(self, case: Case) -> list[str]:
        """Set the case up for the sample once, and return its arguments."""
        if self.setup is not None:
            self.setup(case)
        return self.argv(case)

    def argv(self, case: Case) -> list[str]:
        return case.fill(self.args, self.file_mode)


def mode_of(subject: Subject, path: str, args: list[str]) -> str:
    modes = subject.registrations.get(path, subject.commands.get(path, {})).get("modes", subject.modes)
    if "{session}" in args and "session" in modes:
        return "session"
    if "{device}" in args and "device" in modes:
        return "device"
    if "file" in modes:
        return "file"
    return modes[0]


def _edit(case: Case) -> None:
    case.control("edit", document="doc-1", object="conformance", field="note", value="edited")


def standard_samples(subject: Subject) -> list[Sample]:
    """The samples the suites bring for the standard writes (DVER-002)."""
    out = [Sample("knowledge create", ["--id", "conformance-link", "--url", "https://conformance.feishu.cn/wiki/conformance",
                                       "--title", "Conformance link", "--kind", "guide"], subject.modes[0], False, needs_scope=False)]
    if "session" in subject.modes:
        out.append(Sample("doc save", ["--session", "{session}", "--doc", "{doc}"], "session", False, setup=_edit))
        out.append(Sample("doc create", ["--session", "{session}"], "session", False))
        out.append(Sample("session open", [], "session", False))
    if subject.host_component:
        out.append(Sample("plugin install", [], subject.modes[0], False))
    return [s for s in out if s.path in subject.commands]


def own_samples(subject: Subject) -> list[Sample]:
    return [Sample(path, args, mode_of(subject, path, args), True) for path, args in subject.samples.items()
            if path in subject.registrations]


def all_samples(subject: Subject) -> list[Sample]:
    return own_samples(subject) + standard_samples(subject)


def tier(subject: Subject, sample: Sample) -> str:
    """The tier the rules give the sample, never the one the tool reports."""
    return subject.tier(sample.path, sample.mode)


def call(case: Case, sample: Sample, *extra: str, argv: list[str] | None = None) -> Outcome:
    return case.run(*sample.path.split(" "), *(argv if argv is not None else sample.argv(case)), *extra)


def confirm(case: Case, sample: Sample, argv: list[str], token: str, dangerous: bool = True) -> Outcome:
    extra = ["--confirm", token] + (["--dangerous"] if dangerous else [])
    return call(case, sample, *extra, argv=argv)


def token_for(case: Case, sample: Sample, argv: list[str]) -> str:
    from .harness import check

    out = call(case, sample, "--dry-run", argv=argv)
    check(out.ok and (out.data or {}).get("confirm_token"), f"{sample.path}: the dry run gave no token: {out.describe()}")
    return out.data["confirm_token"]


def through(case: Case, sample: Sample, argv: list[str]) -> Outcome:
    """Run a write to its end, confirming it when it asks for confirmation."""
    out = call(case, sample, argv=argv)
    if out.code == "E_CONFIRMATION_REQUIRED":
        dangerous = out.details["preview"]["tier"] == "dangerous"
        out = confirm(case, sample, argv, out.details["confirm_token"], dangerous)
    return out


def effects_of(subject: Subject, sample: Sample) -> list[str]:
    reg = subject.registrations.get(sample.path)
    if reg is not None:
        return list(reg["effects"])
    return list(subject.commands[sample.path]["effects"])


def halt(subject: Subject, sample: Sample) -> bool:
    return bool(subject.registrations.get(sample.path, {}).get("halt"))


def batchable(subject: Subject, sample: Sample) -> bool:
    flags = {f["name"] for f in subject.commands[sample.path]["flags"]}
    return sample.domain and "--ids" in flags and ("--id" in sample.args or "--ids" in sample.args)


def as_batch(sample: Sample, argv: list[str], extra_ids: list[str]) -> list[str]:
    """The sample turned into a batch of its own object and ``extra_ids``."""
    flag = "--id" if "--id" in argv else "--ids"
    i = argv.index(flag)
    ids = argv[i + 1].split(",") + extra_ids
    return argv[:i] + ["--ids", ",".join(ids)] + argv[i + 2:]

