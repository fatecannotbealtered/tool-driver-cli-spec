"""Run the conformance suites against a tool.

    python -m suites --project <tool project> [--only G01,D05] [--report report.json] -- <command that starts the tool>

Run it from ``conformance/``. Every test starts the tool as a process (DVER-011). A test that
applies and fails, or applies and does not run, fails the run (DVER-001).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

from . import driver, general, schemas
from .harness import Failure, NotApplicable, Subject


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--" not in args:
        print(__doc__, file=sys.stderr)
        return 2
    cut = args.index("--")
    parser = argparse.ArgumentParser(prog="python -m suites")
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--only", default="")
    parser.add_argument("--report", type=Path)
    options = parser.parse_args(args[:cut])
    command = args[cut + 1:]
    subject = Subject(command, options.project.resolve())
    facts = subject.facts()
    contract = schemas.contract()
    titles = {t["id"]: t["title"] for t in contract["conformance"]["general"] + contract["conformance"]["driver"]}
    applies = {t["id"]: t["applies_when"] for t in contract["conformance"]["driver"]}
    only = {x.strip() for x in options.only.split(",") if x.strip()}
    results = []
    failed = 0
    # R04 runs last, so it checks the envelopes of both suites.
    for test_id, test in list(general.TESTS.items()) + list(driver.TESTS.items()) + list(general.LAST.items()):
        if only and test_id not in only:
            continue
        when = applies.get(test_id, ["always"])
        started = time.monotonic()
        entry = {"id": test_id, "title": titles[test_id]}
        if not any(facts.get(w) for w in when):
            entry.update(status="not_applicable", condition=f"applies when: {', '.join(when)}")
        else:
            try:
                notes = test(subject)
                entry.update(status="pass", notes=notes or [])
            except NotApplicable as exc:
                entry.update(status="not_applicable", condition=str(exc))
            except Failure as exc:
                entry.update(status="fail", reason=str(exc))
            except Exception as exc:  # noqa: BLE001 - a test that could not run counts as failed
                entry.update(status="fail", reason=f"the test could not run: {type(exc).__name__}: {exc}",
                             trace=traceback.format_exc()[-2000:])
        entry["seconds"] = round(time.monotonic() - started, 2)
        failed += entry["status"] == "fail"
        results.append(entry)
        mark = {"pass": "PASS", "fail": "FAIL", "not_applicable": "n/a "}[entry["status"]]
        print(f"{mark} {test_id} {entry['title']} ({entry['seconds']}s)" + (f"\n     {entry.get('reason') or entry.get('condition')}"
              if entry["status"] != "pass" else ""), flush=True)
    report = {"tool": subject.name, "spec_version": contract["version"], "simulated": True, "results": results}
    if options.report:
        options.report.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(results) - failed} of {len(results)} passed or not applicable; {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
