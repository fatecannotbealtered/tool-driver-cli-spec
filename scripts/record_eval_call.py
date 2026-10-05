"""Record actual CLI subprocess bytes for one preconfigured Agent evaluation run.

This does not invoke a model or certify its identity. The task controller must
retain the platform task ID and public task events separately.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True
HIDDEN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def json_file(path, value):
    with path.open('xb') as stream:
        stream.write((json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def record(config_path, expected_sha256, arguments):
    if digest(config_path) != expected_sha256:
        raise ValueError('The controller run configuration changed; refusing to dispatch.')
    config = json.loads(config_path.read_text(encoding='utf-8'))
    frozen = Path(config['frozen_root'])
    for relative, expected in config['frozen_files'].items():
        path = frozen / relative
        if not path.resolve().is_relative_to(frozen.resolve()) or digest(path) != expected:
            raise ValueError('Frozen evaluation source changed: ' + relative)
    run = Path(config['run_root'])
    logs = run / 'run-evidence'
    logs.mkdir(exist_ok=True)
    key = uuid.uuid4().hex
    lock = logs / '.invocation-lock'
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(descriptor)
    try:
        def observation():
            return {name: digest(run / name) if (run / name).is_file() else None
                    for name in ('drawing.svg', 'protected.svg', 'authorization.json', 'SKILL.md')}
        before = observation()
        if arguments == ['--eval-read-skill']:
            path = run / 'SKILL.md'
            if config['condition'] != 'with_skill' or not path.is_file():
                raise ValueError('This run has no Skill input.')
            payload = path.read_bytes()
            (logs / (key + '.read.bin')).write_bytes(payload)
            json_file(logs / (key + '.event.json'), {
                'type': 'file_read', 'recorded_at': now(), 'path': str(path),
                'sha256': hashlib.sha256(payload).hexdigest(), 'before_files': before,
                'after_files': observation(), 'run_id': config['run_id'],
            })
            sys.stdout.buffer.write(payload)
            return 0
        argv = [sys.executable, '-B', str(frozen / 'examples/engineering/svg_title_driver.py'), *arguments]
        intent = {'run_id': config['run_id'], 'call_id': key, 'started_at': now(), 'argv': argv,
                  'cwd': str(run), 'before_files': before,
                  'run_config_sha256': expected_sha256, 'frozen_source_fingerprint': config['frozen_source_fingerprint']}
        json_file(logs / (key + '.intent.json'), intent)
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8',
                           SAMPLE_DRIVER_SCOPE_FILE=str(run / 'authorization.json'),
                           SAMPLE_DRIVER_STATE_DIR=str(run / 'state'))
        result = subprocess.run(argv, cwd=run, env=environment, capture_output=True, timeout=60, creationflags=HIDDEN)
        for kind, payload in (('stdout', result.stdout), ('stderr', result.stderr)):
            with (logs / (key + '.' + kind + '.bin')).open('xb') as stream:
                stream.write(payload)
        event = {'type': 'tool_call', **intent, 'finished_at': now(), 'exit_code': result.returncode,
                 'stdout': result.stdout.decode('utf-8', errors='replace'),
                 'stderr': result.stderr.decode('utf-8', errors='replace'),
                 'stdout_sha256': hashlib.sha256(result.stdout).hexdigest(),
                 'stderr_sha256': hashlib.sha256(result.stderr).hexdigest(), 'after_files': observation()}
        json_file(logs / (key + '.event.json'), event)
        sys.stdout.buffer.write(result.stdout)
        sys.stderr.buffer.write(result.stderr)
        return result.returncode
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-config', type=Path, required=True)
    parser.add_argument('--config-sha256', required=True)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    arguments = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    try:
        return record(args.run_config.resolve(), args.config_sha256, arguments)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print('Evaluation recorder refused or failed: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
