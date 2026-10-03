"""Probe a generated SVG file with a separately launched browser consumer.

This is a controlled file-profile experiment, not an SVG editor or CAD adapter.
Headless reference: https://developer.chrome.com/docs/automation-and-testing/headless-cli
Only generated local SVG/HTML is loaded, with a fresh profile on every launch.
"""
from __future__ import annotations

import argparse
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="40mm" height="30mm" viewBox="0 0 40 30"><rect id="body" x="5" y="4" width="10" height="6" fill="blue"/></svg>'
HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ProbeError(Exception):
    def __init__(self, code, message, status="incomplete"):
        super().__init__(message)
        self.code, self.status = code, status


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_optional(path, value, response):
    try:
        save_json(path, value)
        return True
    except OSError as error:
        response["meta"].setdefault("notices", []).append(f"Could not retain {path.name}: {error}")
        return False


def snapshot(path, label):
    return {"id": label, "source": "disk", "revision": "sha256:" + digest(path),
            "observed_at": now(), "dependencies": []}


def source_commit():
    manifest_path = ROOT / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        component = next((c for c in manifest["components"] if c["path"] == "scripts/run_file_consumer_probe.py"), None)
        if manifest.get("source_dirty") or not component or component["sha256"] != digest(Path(__file__)):
            raise ProbeError("E_CONFIG", "Probe code does not match the extracted specification manifest.")
        commit = manifest["source_commit"]
        if len(commit) not in (40, 64) or any(c not in "0123456789abcdef" for c in commit):
            raise ProbeError("E_CONFIG", "The specification manifest has no valid source commit.")
        return commit
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                            text=True, timeout=10, creationflags=HIDDEN)
    commit = result.stdout.strip()
    if result.returncode or len(commit) not in (40, 64) or any(c not in "0123456789abcdef" for c in commit):
        raise ProbeError("E_CONFIG", "Probe source must have an observable Git commit.")
    return commit


def browser_version(browser):
    if os.name == "nt":
        literal = str(browser).replace("'", "''")
        argv = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                f"(Get-Item -LiteralPath '{literal}').VersionInfo.ProductVersion"]
    else:
        argv = [str(browser), "--version"]
    result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=10, creationflags=HIDDEN)
    version = result.stdout.strip()
    if result.returncode or not version:
        raise ProbeError("E_CONFIG", "Could not observe the selected browser version.")
    return version


class ObservationParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active, self.parts = False, []

    def handle_starttag(self, tag, attrs):
        if tag == "pre" and dict(attrs).get("id") == "observation":
            self.active = True

    def handle_endtag(self, tag):
        if tag == "pre":
            self.active = False

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)


def read_browser(browser, svg_path, output, label, timeout):
    wrapper = output / f"{label}.html"
    wrapper.write_text('''<!doctype html><meta charset="utf-8"><object id="subject" type="image/svg+xml" data="''' + html.escape(svg_path.name, quote=True) + '''"></object><pre id="observation">pending</pre><script>
const out = document.getElementById('observation');
document.getElementById('subject').addEventListener('load', event => {
  try {
    const doc = event.target.contentDocument, root = doc.documentElement;
    const body = doc.getElementById('body'), box = body.getBBox(), vb = root.viewBox.baseVal;
    out.textContent = JSON.stringify({user_agent:navigator.userAgent, id:body.id,
      x:body.getAttribute('x'), width:body.getAttribute('width'), height:body.getAttribute('height'),
      root_width:root.getAttribute('width'), root_height:root.getAttribute('height'),
      bbox:{x:box.x,y:box.y,width:box.width,height:box.height},
      viewbox:{x:vb.x,y:vb.y,width:vb.width,height:vb.height}});
  } catch(error) { out.textContent = JSON.stringify({error:String(error)}); }
});</script>''', encoding="utf-8")
    profile = Path(tempfile.mkdtemp(prefix=".headless-", dir=output)).resolve()
    argv = [str(browser), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
            "--disable-background-networking", "--disable-component-update", "--disable-sync",
            "--disable-extensions", "--disable-default-apps", "--disable-domain-reliability",
            "--disable-features=MediaRouter,OptimizationHints,AutofillServerCommunication",
            "--host-resolver-rules=MAP * ~NOTFOUND", "--proxy-server=http://127.0.0.1:9",
            "--allow-file-access-from-files", "--dump-dom", "--virtual-time-budget=2000",
            f"--timeout={int(timeout * 1000)}", f"--user-data-dir={profile}", wrapper.as_uri()]
    process = None
    try:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, creationflags=HIDDEN)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            if os.name == "nt":
                subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True, timeout=10, creationflags=HIDDEN)
            else:
                process.kill()
            process.communicate(timeout=5)
            raise ProbeError("E_VERIFY_INCOMPLETE", "Browser wait timed out; the SVG may already be written.") from error
        (output / f"{label}-dom.html").write_bytes(stdout)
        (output / f"{label}-stderr.log").write_bytes(stderr)
        parser = ObservationParser()
        parser.feed(stdout.decode("utf-8", errors="replace"))
        try:
            observation = json.loads("".join(parser.parts))
        except (ValueError, TypeError) as error:
            raise ProbeError("E_VERIFY_INCOMPLETE", "Browser returned no usable SVG observation.") from error
        if process.returncode or "error" in observation:
            raise ProbeError("E_VERIFY_INCOMPLETE", "Browser failed to consume the generated SVG.")
        observation["process"] = {"pid": process.pid, "returncode": process.returncode,
                                  "profile": profile.name, "observed_at": now()}
        save_json(output / f"{label}-observation.json", observation)
        return observation
    finally:
        # Only this newly created profile can be removed, never an existing user profile.
        if profile.is_relative_to(output.resolve()):
            shutil.rmtree(profile, ignore_errors=True)


def matches(observation, expected_x):
    expected = {"x": expected_x, "y": 4, "width": 10, "height": 6}
    return (observation.get("id") == "body" and float(observation["x"]) == expected_x
            and observation.get("root_width") == "40mm" and observation.get("root_height") == "30mm"
            and all(abs(observation["bbox"][key] - value) < 1e-7 for key, value in expected.items())
            and observation.get("viewbox") == {"x": 0, "y": 0, "width": 40, "height": 30})


def plan(path, operation_id):
    return {"operation_id": operation_id, "baseline_sha256": digest(path), "path": str(path), "x": 12}


def apply_plan(value):
    path = Path(value["path"])
    if digest(path) != value["baseline_sha256"]:
        raise ProbeError("E_CONFLICT", "The generated file changed after planning.", "failed")
    tree = ET.parse(path)
    tree.find("{http://www.w3.org/2000/svg}rect").set("x", str(value["x"]))
    tree.write(path, encoding="utf-8", xml_declaration=True)


def receipt_for(operation_id, path, before, after, checks, status, change="applied", persistence="saved", execution="completed"):
    return {"operation_id": operation_id,
            "target": {"mode": "file", "engine_id": "svg-file-probe", "instance_id": None,
                       "object_id": "body", "locator": path.as_uri()},
            "authorization_scope_id": "caller-new-output-directory", "effects": ["change", "persist"],
            "snapshot_before": before, "snapshot_after": after,
            "outcome": {"execution": execution, "change": change, "persistence": persistence,
                        "verification": {"status": status, "scope": "generated_svg_file_probe_only",
                                         "snapshot_id": after["id"] if after else None,
                                         "coverage": "complete" if status in ("passed", "failed") else "partial",
                                         "checks": checks, "not_checked": [],
                                         "evidence_refs": [c["evidence_ref"] for c in checks if "evidence_ref" in c]}},
            "changed_items": [{"id": "body", "change": "x:5->12", "evidence_ref": path.as_uri()}] if change == "applied" else [],
            "artifacts": [{"id": "controlled-svg", "path": str(path), "sha256": after["revision"][7:],
                           "source_snapshot_id": after["id"]}] if after else [],
            "recovery": {"action": "none" if status == "passed" else "inspect", "supported": True,
                         "reason": "Fresh browser readback passed." if status == "passed" else "Inspect the retained file and observations; do not blindly replay."}}


def make_evidence(browser, version, browser_sha, code_sha, commit, output, before, after, checks, receipt, consumer_kind, user_agent, identity):
    limitations = ["Development probe; no released package was tested.", "Only self-generated SVG file operations were tested; CAD, GUI sessions and physical devices were not tested.",
                   "State drift and response loss are local fixture injections, not distributed exactly-once or cancellation evidence.",
                   "A fresh isolated browser profile and networking suppression flags were used; this is not a general network sandbox.",
                   "The source commit is read from Git or a locally checked specification manifest; the code fingerprint identifies the actual probe file.",
                   "The local plan and operation record are controlled fixtures; only response, receipt and evidence claim their public Schema shapes."]
    if consumer_kind == "simulated_adapter":
        limitations.append("Browser observations were mocked for contract testing; no real browser validation is claimed.")
    if after is None:
        limitations.append("No final file snapshot is available; this record is bound only to the observed baseline.")
    component = {"name": browser.name, "role": "validator", "version": version,
                 "build_id": browser_sha, "identity_status": "observed"}
    if not identity or not identity["stable"]:
        component.update(version=None, build_id=None, identity_status="unavailable",
                         reason="The browser identity was not verified as stable across the consumer runs; observed metadata is retained separately.")
        limitations.append("Starting executable metadata is not asserted to identify every consumer run.")
    return {"evidence_id": "evidence-" + receipt["operation_id"], "spec_version": (ROOT / "VERSION").read_text().strip(),
            "schema_version": "1.0", "evidence_context": "development", "kind": consumer_kind,
            "source_commit": commit, "source_fingerprint_sha256": code_sha, "package_sha256": None,
            "recorded_at": now(), "environment": {"platform": sys.platform, "arch": platform.machine(), "components": [component]},
            "input_fingerprint_sha256": before["revision"][7:], "target": receipt["target"],
            "snapshot_id": (after or before)["id"], "capabilities": ["controlled-svg-file-probe"], "checks": checks, "limitations": limitations,
            "extensions": {"browser_user_agent": user_agent, "browser_executable": str(browser), "browser_identity": identity,
                           "initial_browser_metadata": {"version": version, "sha256": browser_sha}, "probe_output": str(output),
                           "headless_reference": "https://developer.chrome.com/docs/automation-and-testing/headless-cli"}}


def run_probe(browser, output, timeout=30, *, consumer_kind="artifact_consumer"):
    started = time.monotonic()
    request_id, operation_id = "request-" + uuid.uuid4().hex, "operation-" + uuid.uuid4().hex
    response = {"ok": False, "schema_version": "1.0", "request_id": request_id, "phase": "verify", "data": {}, "meta": {"duration_ms": 0}}
    before, after, checks, path, write_started, write_completed = None, None, [], None, False, False
    user_agent, identity = None, None
    try:
        browser, output = Path(browser).resolve(), Path(output).resolve()
        if not browser.is_file() or browser.name.lower() not in {"chrome.exe", "msedge.exe", "chrome", "chromium", "chromium-browser", "msedge"}:
            raise ProbeError("E_CONFIG", "Provide an existing supported browser executable explicitly.")
        if output.exists() or not 0 < timeout <= 45 or consumer_kind not in {"artifact_consumer", "simulated_adapter"}:
            raise ProbeError("E_VALIDATION", "Output must be a new directory and timeout must be within 45 seconds.")
        version, commit = browser_version(browser), source_commit()
        browser_sha, code_sha = digest(browser), digest(Path(__file__))
        output.mkdir(parents=True, exist_ok=False)
        path = output / "sample.svg"
        path.write_text(SVG, encoding="utf-8")
        before = snapshot(path, "before-" + operation_id)
        planned = plan(path, operation_id)
        save_json(output / "operation-record.json", {"request_id": request_id, "operation_id": operation_id, "state": "planned", "plan": planned})

        def check(label, passed, evidence_path, status="failed"):
            checks.append({"id": label, "status": "passed" if passed else status,
                           "required": True, "evidence_ref": evidence_path.as_uri()})
            if not passed:
                raise ProbeError("E_VERIFY_INCOMPLETE" if status == "incomplete" else "E_VERIFY_FAILED",
                                 f"Probe check failed: {label}", status)

        save_json(output / "plan-case.json", {"baseline_sha256": before["revision"][7:],
                  "planned_sha256": planned["baseline_sha256"], "after_plan_sha256": digest(path), "plan": planned})
        check("plan-does-not-modify", digest(path) == planned["baseline_sha256"] == before["revision"][7:], output / "plan-case.json")
        drift_path = output / "drift.svg"
        drift_path.write_text(SVG, encoding="utf-8")
        drift_plan = plan(drift_path, "operation-drift")
        drift_path.write_text(SVG.replace('x="5"', 'x="6"'), encoding="utf-8")
        drift_hash = digest(drift_path)
        try:
            apply_plan(drift_plan)
            rejected = False
        except ProbeError as error:
            rejected = error.code == "E_CONFLICT"
        save_json(output / "drift-case.json", {"rejected": rejected, "sha256_after_external_edit": drift_hash, "sha256_after_refusal": digest(drift_path)})
        check("state-drift-refused", rejected and digest(drift_path) == drift_hash, output / "drift-case.json")
        save_json(output / "operation-record.json", {"request_id": request_id, "operation_id": operation_id,
                  "state": "running", "write_attempts": 1, "plan": planned})
        write_started = True
        apply_plan(planned)
        write_completed, after = True, snapshot(path, "after-" + operation_id)
        first = read_browser(browser, path, output, "browser-first", timeout)
        user_agent = first["user_agent"]
        check("independent-svg-readback", matches(first, 12), output / "browser-first-observation.json")
        second = read_browser(browser, path, output, "browser-reopened", timeout)
        check("persistent-reopen", matches(second, 12) and digest(path) == after["revision"][7:], output / "browser-reopened-observation.json")
        failure = read_browser(browser, path, output, "browser-failed-expectation", timeout)
        failed_checks = [{"id": "deliberately-wrong-x", "status": "failed", "required": True,
                          "evidence_ref": (output / "browser-failed-expectation-observation.json").as_uri()}]
        failed_receipt = receipt_for(operation_id, path, before, after, failed_checks, "failed")
        save_json(output / "write-after-failed-check.json", {"expected_x": 13, "actual": failure, "receipt": failed_receipt})
        check("failed-check-keeps-written-state", not matches(failure, 13) and matches(failure, 12)
              and failed_receipt["outcome"]["change"] == "applied", output / "write-after-failed-check.json")
        result = receipt_for(operation_id, path, before, after, checks, "passed")
        record = {"request_id": request_id, "operation_id": operation_id, "state": "completed", "writes": 1, "receipt": result}
        save_json(output / "operation-record.json", record)
        # Inject loss by discarding the in-memory response, then query the pre-known ID.
        queried = json.loads((output / "operation-record.json").read_text(encoding="utf-8"))
        check("lost-reply-record-query", queried["operation_id"] == operation_id and queried["writes"] == 1
              and digest(path) == after["revision"][7:], output / "operation-record.json")
        identity = {"before": {"version": version, "sha256": browser_sha}, "after": None, "stable": False}
        try:
            identity["after"] = {"version": browser_version(browser), "sha256": digest(browser), "observed_at": now()}
            identity["stable"] = (identity["after"]["version"] == version and identity["after"]["sha256"] == browser_sha)
        except (ProbeError, OSError, subprocess.SubprocessError) as error:
            identity["error"] = str(error)
        save_json(output / "consumer-identity-case.json", identity)
        check("consumer-identity-stable", identity["stable"], output / "consumer-identity-case.json", "incomplete")
        if digest(Path(__file__)) != code_sha:
            raise ProbeError("E_CONFLICT", "Probe code changed during this experiment.")
        response["data"]["receipt"] = receipt_for(operation_id, path, before, after, checks, "passed")
        response["ok"] = True
    except (ProbeError, OSError, ValueError, subprocess.SubprocessError, KeyError, AttributeError) as error:
        code, status = getattr(error, "code", "E_VERIFY_INCOMPLETE"), getattr(error, "status", "incomplete")
        response["error"] = {"code": code, "message": str(error), "retryable": False,
                             "details": {"next_action": "inspect existing output and operation record; use a different new directory for a new experiment"}}
        if before:
            try:
                after = snapshot(path, "after-" + operation_id)
            except OSError:
                after = None
            diagnostic = output / "probe-error.json"
            retained = save_optional(diagnostic, {"code": code, "message": str(error),
                                     "write_started": write_started, "write_completed": write_completed}, response)
            checks.append({"id": "probe-completion", "status": status, "required": True,
                           "reason": str(error), "evidence_ref": diagnostic.as_uri() if retained else "urn:probe:" + request_id + ":error"})
            response["data"]["receipt"] = receipt_for(operation_id, path, before, after, checks, status,
                "applied" if write_completed else "unknown" if write_started else "not_applied",
                "saved" if write_completed and after else "unknown" if write_started else "unchanged",
                "completed" if write_completed else "failed" if write_started else "not_started")
            save_optional(output / "operation-record.json", {"request_id": request_id, "operation_id": operation_id,
                          "state": "failed" if status == "failed" else "unknown", "receipt": response["data"]["receipt"]}, response)
            save_optional(output / "failure-response.json", response, response)
    response["meta"]["duration_ms"] = round((time.monotonic() - started) * 1000, 3)
    if path:
        if before and "receipt" in response["data"]:
            evidence = make_evidence(browser, version, browser_sha, code_sha, commit, output, before, after, checks,
                                     response["data"]["receipt"], consumer_kind, user_agent, identity)
            save_optional(output / "evidence.json", evidence, response)
            response["data"]["evidence"] = evidence
        save_optional(output / "response.json", response, response)
    return response


class ProbeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ProbeError("E_VALIDATION", message)


def main():
    parser = ProbeParser(description=__doc__)
    parser.add_argument("--browser", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=30)
    try:
        args = parser.parse_args()
        response = run_probe(args.browser, args.output, args.timeout)
    except ProbeError as error:
        response = {"ok": False, "schema_version": "1.0", "request_id": "request-" + uuid.uuid4().hex, "phase": "verify",
                    "error": {"code": error.code, "message": str(error), "retryable": False, "details": {}}, "meta": {"duration_ms": 0}}
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(response, ensure_ascii=False))
    return 0 if response["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
