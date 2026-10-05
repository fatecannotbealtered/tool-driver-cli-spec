"""Run local specification acceptance and retain actual logs and an independent browser experiment.

No native application, installation, commit or publication is performed.
Without a verified bundle, release readiness remains false even if local checks pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
HIDDEN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def identity():
    files = {}
    suffixes = {'.py', '.md', '.json', '.toml', '.yml', '.txt', '.svg', ''}
    for folder in ('base', 'contract', 'docs', 'schemas', 'scripts', 'packages', 'starter', 'examples', 'tests'):
        for path in sorted((ROOT / folder).rglob('*')):
            if path.is_file() and path.suffix in suffixes and '__pycache__' not in path.parts:
                files[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ('README.md', 'AGENTS.md', 'VERSION', 'STATUS', 'CHANGELOG.md', 'requirements-dev.txt', 'requirements-workflow.txt'):
        files[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True,
                            timeout=10, creationflags=HIDDEN)
    status = subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True,
                            timeout=10, creationflags=HIDDEN)
    top = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=ROOT, capture_output=True, text=True,
                         timeout=10, creationflags=HIDDEN)
    own_checkout = top.returncode == 0 and Path(top.stdout.strip()).resolve() == ROOT.resolve()
    return {'source_commit': commit.stdout.strip() if own_checkout and commit.returncode == 0 else None,
            'source_dirty': bool(status.stdout.strip()) if own_checkout and status.returncode == 0 else None,
            'fingerprint_sha256': digest, 'files': files,
            'origin_authenticated': False}


def main(argv=None):
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--browser', required=True, type=Path)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--expected-sha256')
    parser.add_argument('--audit', action='store_true', help='Use preinstalled ruff and pip-audit; no dependency resolution, installation or fixes.')
    args = parser.parse_args(argv)
    if bool(args.bundle) != bool(args.expected_sha256):
        parser.error('--bundle and --expected-sha256 must be supplied together')
    output = args.output.resolve()
    if output.exists():
        parser.error('--output must be a new directory; existing evidence is never replaced')
    if not args.browser.is_file():
        parser.error('--browser must name an existing Chrome or Edge executable')
    output.mkdir(parents=True, exist_ok=False)
    before = identity()
    checks = []
    work_root = ROOT
    bundle_check = None
    if args.bundle:
        from verify_spec_bundle import verify_bundle
        try:
            checked = verify_bundle(args.bundle.resolve(), args.expected_sha256)
            package = output / 'package'
            package.mkdir()
            for relative, payload in checked.files.items():
                path = package / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open('xb') as stream:
                    stream.write(payload)
            work_root = package
            bundle_check = {'id': 'bundle-integrity', 'passed': True, **checked.summary(),
                            'matches_source': checked.manifest['source_commit'] == before['source_commit']
                            and before['source_dirty'] is False
                            and all(path in checked.files and hashlib.sha256(checked.files[path]).hexdigest() == digest
                                    for path, digest in before['files'].items())}
        except (OSError, ValueError) as error:
            bundle_check = {'id': 'bundle-integrity', 'passed': False, 'problem': str(error), 'matches_source': False}
        checks.append(bundle_check)
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
    commands = [('static', ['scripts/check_spec.py'], 60),
                ('regression', ['-m', 'unittest', 'discover', '-s', 'tests', '-v'], 600),
                ('independent-consumption', ['scripts/run_file_consumer_probe.py', '--browser', str(args.browser.resolve()),
                                             '--output', str(output / 'consumer')], 120)]
    if args.audit:
        commands.insert(1, ('dependency-audit', ['-m', 'pip_audit', '--no-deps', '--disable-pip', '--strict',
                                               '--progress-spinner', 'off', '--timeout', '15',
                                               '--cache-dir', str(output / 'audit-cache'), '-r', 'requirements-dev.txt',
                                               '-f', 'json'], 120))
        commands.insert(1, ('code-check', ['-m', 'ruff', 'check', '--isolated', '--select', 'E9,F63,F7,F82',
                                         'scripts', 'packages', 'tests', 'examples/engineering', 'starter/common'], 60))
    if bundle_check and not bundle_check['passed']:
        commands = []
    for name, arguments, timeout in commands:
        command = [sys.executable, '-B', *arguments]
        print('Running ' + name, file=sys.stderr, flush=True)
        try:
            result = subprocess.run(command, cwd=work_root, env=environment, capture_output=True,
                                    timeout=timeout, creationflags=HIDDEN)
            stdout, stderr, exit_code = result.stdout, result.stderr, result.returncode
            problem = None
        except (OSError, subprocess.TimeoutExpired) as error:
            stdout, stderr, exit_code, problem = b'', str(error).encode('utf-8'), None, str(error)
        (output / (name + '.stdout.log')).write_bytes(stdout)
        (output / (name + '.stderr.log')).write_bytes(stderr)
        item = {'id': name, 'argv': command, 'exit_code': exit_code, 'passed': exit_code == 0,
                'stdout_sha256': hashlib.sha256(stdout).hexdigest(), 'stderr_sha256': hashlib.sha256(stderr).hexdigest(),
                'problem': problem}
        checks.append(item)
    after = identity()
    unchanged = before == after
    local_passed = unchanged and all(item['passed'] for item in checks)
    report = {'spec_version': (ROOT / 'VERSION').read_text(encoding='utf-8').strip(),
              'schema_version': '2.0', 'recorded_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
              'scope': 'specification_local_acceptance', 'source': before, 'source_unchanged': unchanged,
              'checks': checks, 'local_passed': local_passed,
              'release_ready': bool(local_passed and bundle_check and bundle_check.get('matches_source')
                                    and args.audit and (ROOT / 'STATUS').read_text().strip() == 'stable'),
              'not_verified': ['Native Xpedition, KiCad and Creo product tasks', 'SkillHub installation and upgrade',
                               'Publisher authentication and published Release asset identity'],
              'limitations': ['Local acceptance does not graduate each adapter.',
                              'A dirty source is identified by every recorded file hash, not by its HEAD alone.',
                              'A release still requires an immutable clean source, matching package and release authorization.']}
    (output / 'acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    payload = {'report': str(output / 'acceptance.json'), 'local_passed': local_passed, 'release_ready': report['release_ready']}
    response = {'ok': local_passed, 'schema_version': '1.0', 'meta': {'duration_ms': round((time.monotonic()-started)*1000, 3)}}
    if local_passed:
        response['data'] = payload
    else:
        response['error'] = {'code': 'E_VERIFY_FAILED', 'message': 'Specification acceptance failed.', 'retryable': False,
                             'details': {**payload, 'next_action': 'Inspect the retained logs and fix or disclose each failed check.'}}
    print(json.dumps(response, ensure_ascii=False))
    return 0 if local_passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
