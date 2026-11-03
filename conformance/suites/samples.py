"""Write samples: the tool's own, from the normal row of each behavior matrix (DVER-002), and
the ones the suites bring for the standard commands."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .harness import Case, Subject


@dataclass
class Sample:
    path: str
    args: list[str]
    mode: str
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
    out = [Sample("knowledge create", ["--id", "conformance-link", "--url", "https://conformance.feishu.cn/wiki/conformance",
                                       "--title", "Conformance link", "--kind", "guide"], subject.modes[0], needs_scope=False)]
    if "session" in subject.modes:
        out.append(Sample("doc save", ["--session", "{session}", "--doc", "{doc}"], "session", setup=_edit))
        out.append(Sample("doc create", ["--session", "{session}"], "session"))
        out.append(Sample("session open", [], "session"))
    if subject.host_component:
        out.append(Sample("plugin install", [], subject.modes[0]))
    return [s for s in out if s.path in subject.commands]


def all_samples(subject: Subject) -> list[Sample]:
    own = [Sample(path, args, mode_of(subject, path, args)) for path, args in subject.samples.items() if path in subject.registrations]
    return own + standard_samples(subject)


def tier_of(case: Case, sample: Sample) -> tuple[str | None, Any]:
    """The tier of a prepared sample, from its dry run, or None when the tool cannot do it."""
    out = case.run(*sample.path.split(" "), *sample.argv(case), "--dry-run")
    if out.code == "E_UNSUPPORTED":
        return None, out
    if not out.ok:
        return "error", out
    return out.data["preview"]["tier"], out


def call(case: Case, sample: Sample, *extra: str, argv: list[str] | None = None) -> Any:
    words = sample.path.split(" ")
    return case.run(*words, *(argv if argv is not None else sample.argv(case)), *extra)
