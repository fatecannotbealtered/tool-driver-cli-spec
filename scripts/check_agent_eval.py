"""Check recorded Agent evaluations offline; never run a model, CLI or transcript instructions.

This checks coverage, bindings and retained trace bytes. It does not authenticate
the recorder or establish that a model really produced a transcript.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import sys
import time

sys.dont_write_bytecode = True
from contract_io import canonical_relative_path, parse_json, read_regular_file
from check_spec import code_table
from validate_contract import InputError, Parser, UsageError, emit, validate_value

MANDATORY_SCENARIOS = frozenset({
    'fresh-agent-read', 'missing-scope', 'no-save-requested', 'lost-reply',
    'ambiguous-target', 'injected-note', 'modal-dialog', 'dangerous-command',
})
ADDITIONAL_SCENARIOS = frozenset({'write-dry-run-confirm', 'untrusted-content', 'self-update'})


def pinned_file(root: Path, reference: dict) -> bytes:
    relative = canonical_relative_path(reference['path'])
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise InputError('evaluation file escapes the declared project root: ' + relative)
    for parent in [path, *path.parents]:
        if parent == root.parent:
            break
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise InputError('evaluation files cannot use links: ' + relative)
    payload = read_regular_file(path, 8 * 1024 * 1024)
    if hashlib.sha256(payload).hexdigest() != reference['sha256']:
        raise InputError('evaluation file SHA-256 differs: ' + relative)
    return payload


def check(root: Path, report: dict, require_pass: bool, require_subset_pass: bool = False) -> dict:
    errors = validate_value('agent-eval', report)
    if errors:
        raise InputError('invalid Agent evaluation report: ' + '; '.join(errors[:8]))
    if (require_pass or require_subset_pass) and report['record_kind'] != 'agent_evaluation':
        raise InputError('fixture or simulated evaluation records cannot satisfy a release gate')
    if report['spec_version'] != (Path(__file__).resolve().parents[1] / 'VERSION').read_text(encoding='utf-8').strip():
        raise InputError('evaluation specification version differs from the pinned checker')
    source_paths = set()
    for reference in report['source_files']:
        if reference['path'] in source_paths:
            raise InputError('duplicate evaluation source file')
        source_paths.add(reference['path'])
        pinned_file(root, reference)
    if 'registry.json' not in source_paths:
        raise InputError('evaluation source files must bind registry.json')
    registry = parse_json(read_regular_file(root / 'registry.json', 8 * 1024 * 1024))
    if (registry['name'], registry['product_version']) != (report['tool'], report['product_version']):
        raise InputError('evaluation report belongs to a different tool or version')
    codes = {**code_table(), **registry.get('error_codes', {})}
    suite = parse_json(pinned_file(root, report['suite']))
    pinned_file(root, report['skill'])
    if not isinstance(suite, list) or any(not isinstance(item, dict) or not isinstance(item.get('id'), str) for item in suite):
        raise InputError('the evaluation suite must be an array of named scenarios')
    scenarios = {item['id'] for item in suite}
    if len(scenarios) != len(suite) or len(scenarios) < 3:
        raise InputError('the evaluation suite needs at least three unique scenarios')
    scope = report['evaluation_scope']
    requirements = {item['id']: item for item in scope['requirements']}
    if len(requirements) != len(scope['requirements']) or set(requirements) != MANDATORY_SCENARIOS:
        raise InputError('evaluation applicability must retain every mandatory driver Skill scenario exactly once')
    capabilities = {item['path'] for item in registry.get('commands', [])}
    if not set(scope['capabilities']).issubset(capabilities):
        raise InputError('evaluation capability scope names an undeclared product command')
    evaluated = set()
    for item in suite:
        names = item.get('requirements')
        if (not isinstance(names, list) or not names or any(not isinstance(name, str) for name in names)
                or len(names) != len(set(names)) or not set(names).issubset(MANDATORY_SCENARIOS | ADDITIONAL_SCENARIOS)):
            raise InputError('every scenario must name its recognized Skill requirements')
        evaluated.update(names)
    for item in requirements.values():
        for reference in item['evidence_files']:
            pinned_file(root, reference)
        if item['disposition'] == 'supported' and item['id'] not in evaluated:
            raise InputError('a supported mandatory scenario is absent from the evaluation suite')
    if require_pass:
        if scope['claim'] != 'full_driver_skill' or evaluated & MANDATORY_SCENARIOS != MANDATORY_SCENARIOS:
            raise InputError('full driver Skill evaluation is missing mandatory scenarios; a capability subset cannot satisfy this gate')
        if any(item['disposition'] != 'supported' for item in requirements.values()):
            raise InputError('unsupported mandatory scenarios cannot be waived to satisfy the full driver Skill gate')
    runs, covered, baseline, models = set(), set(), set(), set()
    for run in report['runs']:
        if run['id'] in runs or run['scenario_id'] not in scenarios:
            raise InputError('duplicate evaluation run or unknown scenario')
        runs.add(run['id'])
        trace = parse_json(pinned_file(root, run['trace']))
        expected = {'run_id': run['id'], 'model': run['model'], 'scenario_id': run['scenario_id'], 'condition': run['condition']}
        if not isinstance(trace, dict) or any(trace.get(key) != value for key, value in expected.items()):
            raise InputError('trace context differs from its evaluation run')
        events = trace.get('events')
        if not isinstance(events, list) or not events or not all(isinstance(event, dict) for event in events):
            raise InputError('an evaluation trace needs retained events')
        if not any(event.get('type') == 'tool_call' for event in events):
            raise InputError('an evaluation trace must contain an actual tool-call record')
        for event in events:
            if event.get('type') != 'tool_call':
                continue
            if (not isinstance(event.get('argv'), list) or not event['argv']
                    or any(not isinstance(value, str) for value in event['argv'])
                    or type(event.get('exit_code')) is not int
                    or not isinstance(event.get('stdout'), str) or not isinstance(event.get('stderr'), str)):
                raise InputError('tool-call records need argv, actual exit_code, stdout and stderr')
            if ('--help' not in event['argv'] and '--format=text' not in event['argv']
                    and not ('--format' in event['argv'] and 'text' in event['argv'])):
                response = parse_json(event['stdout'].encode('utf-8'))
                if validate_value('response', response):
                    raise InputError('tool-call response is inconsistent with the public envelope or exit code')
                expected_exit = 0 if response['ok'] else codes.get(response['error']['code'], {}).get('exit')
                if expected_exit is None or expected_exit != event['exit_code']:
                    raise InputError('tool-call response is inconsistent with the public envelope or exit code')
        for evidence in run['evidence_files']:
            pinned_file(root, evidence)
        model = (run['model']['name'], run['model']['version'])
        if run['condition'] == 'without_skill':
            baseline.add(run['scenario_id'])
        else:
            models.add(model)
            covered.add((model, run['scenario_id']))
            if (require_pass or require_subset_pass) and (run['status'] != 'passed' or any(item['status'] != 'passed' for item in run['checks'])):
                raise InputError('a required with-Skill scenario failed or is incomplete')
    if require_pass or require_subset_pass:
        if report['record_kind'] != 'agent_evaluation':
            raise InputError('fixture or simulated evaluation records cannot satisfy a release gate')
        if len(models) < 2 or len(baseline) < 3:
            raise InputError('release evaluation needs multiple model identities and three no-Skill baseline scenarios')
        if covered != {(model, scenario) for model in models for scenario in scenarios}:
            raise InputError('with-Skill evaluation does not cover every scenario on every recorded model')
    if require_subset_pass and scope['claim'] != 'capability_subset':
        raise InputError('the subset gate requires an explicit capability_subset claim')
    return {'scope': 'recorded_agent_evaluation_bindings', 'tool': report['tool'], 'record_kind': report['record_kind'],
            'runs': len(runs), 'models': len(models), 'scenarios': len(scenarios), 'baseline_scenarios': len(baseline),
            'evaluation_claim': scope['claim'], 'mandatory_scenarios_covered': sorted(evaluated & MANDATORY_SCENARIOS),
            'unsupported_mandatory_scenarios': sorted(name for name, item in requirements.items() if item['disposition'] == 'unsupported'),
            'unevaluated_mandatory_scenarios': sorted(name for name, item in requirements.items() if item['disposition'] == 'not_evaluated'),
            'release_gate_satisfied': require_pass, 'capability_subset_gate_satisfied': require_subset_pass,
            'origin_authenticated': False,
            'limitations': ['A hash-consistent report does not prove a model produced the trace or a grader was independent.',
                            'Only the declared source files are bound; loaded native services and engineering outcomes require their own evidence.']}


def main(argv=None):
    started = time.monotonic()
    parser = Parser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--registry', type=Path)
    parser.add_argument('--require-pass', action='store_true')
    parser.add_argument('--require-subset-pass', action='store_true',
                        help='Check a recorded capability subset without claiming full Skill or release readiness.')
    try:
        args = parser.parse_args(argv)
        root = args.root.resolve()
        required = args.require_pass
        if args.registry:
            registry = parse_json(read_regular_file(root / args.registry, 8 * 1024 * 1024))
            required = required or registry.get('release_readiness', {}).get('level', 'unpublishable') in {'stable', 'beta'}
        if not args.report.is_absolute():
            args.report = root / args.report
        if not args.report.exists() and not required and not args.require_subset_pass:
            return emit(True, started, data={'scope': 'recorded_agent_evaluation_bindings', 'status': 'not_recorded',
                                             'required_for_declared_readiness': False, 'release_gate_satisfied': False,
                                             'limitations': ['No Agent evaluation was executed or certified by this check.']})
        report = parse_json(read_regular_file(args.report, 8 * 1024 * 1024))
        return emit(True, started, data=check(root, report, required, args.require_subset_pass))
    except UsageError as error:
        return emit(False, started, code='E_USAGE', message=str(error), details={'next_action': 'Use --help for arguments.'})
    except (InputError, OSError, ValueError, KeyError, TypeError) as error:
        return emit(False, started, code='E_VALIDATION', message=str(error),
                    details={'next_action': 'Record actual model runs and their source, Skill, suite, traces and outcome evidence; do not upgrade readiness yet.'})


if __name__ == '__main__':
    raise SystemExit(main())
