"""Synthetic report/trace boundary tests. These are not real Agent task evaluations."""
from pathlib import Path
import copy
import hashlib
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from check_agent_eval import MANDATORY_SCENARIOS, check, main
from contract_io import InputError


class AgentEvalRecordTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='agent-eval-records-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.registry = self.write('registry.json', {'name':'eval-fixture', 'product_version':'0.1.0',
                                   'commands':[{'path':'target inspect'}, {'path':'target apply'}]})
        skill = self.write('skills/eval-fixture/SKILL.md', 'Fixture Skill, never deployed.')
        suite = self.write('skills/eval-fixture/test-prompts.json', [
            {'id':item,'requirements':[name]} for item,name in
            (('read','fresh-agent-read'),('scope','missing-scope'),('lost-reply','lost-reply'))])
        evidence = self.write('evidence/outcome.json', {'fixture':True})
        self.report = {'spec_version':'1.0.0','schema_version':'2.0','tool':'eval-fixture','product_version':'0.1.0',
                       'record_kind':'fixture','source_files':[self.registry], 'skill':skill,'suite':suite,'runs':[],
                       'evaluation_scope':{'claim':'capability_subset','capabilities':['target inspect','target apply'],
                           'requirements':[{'id':name,'disposition':'supported' if name in {'fresh-agent-read','missing-scope','lost-reply'} else 'unsupported',
                                            'reason':'Synthetic applicability fixture.','evidence_files':[self.registry]}
                                           for name in sorted(MANDATORY_SCENARIOS)],'limitations':['Fixture subset.']},
                       'limitations':['Synthetic record structure only; no model was run.']}
        for model in ('fixture-model-a','fixture-model-b'):
            for scenario in ('read','scope','lost-reply'):
                for condition in ('without_skill','with_skill'):
                    run_id = model+'-'+scenario+'-'+condition
                    identity = {'name':model,'version':'test-only'}
                    trace = self.write('traces/'+run_id+'.json', {'run_id':run_id,'model':identity,'scenario_id':scenario,
                                      'condition':condition,'events':[{'type':'tool_call','argv':['reference'], 'exit_code':0,
                                          'stdout':json.dumps({'ok':True,'schema_version':'1.0','data':{},'meta':{'duration_ms':0}}),
                                          'stderr':'','fixture':True}]})
                    self.report['runs'].append({'id':run_id,'model':identity,'scenario_id':scenario,'condition':condition,
                        'recorded_at':'2026-10-04T00:00:00Z','status':'passed','trace':trace,
                        'checks':[{'id':'fixture-format','status':'passed','reason':'Synthetic fixture.'}],
                        'evidence_files':[evidence], 'limitations':['Fixture only.']})

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = (value if isinstance(value,str) else json.dumps(value)).encode()
        path.write_bytes(payload)
        return {'path':relative,'sha256':hashlib.sha256(payload).hexdigest()}

    def test_fixture_format_is_checkable_but_cannot_satisfy_release_gate(self):
        result = check(self.root, self.report, False)
        self.assertEqual((result['models'], result['scenarios']), (2,3))
        self.assertFalse(result['release_gate_satisfied'])
        self.assertFalse(result['origin_authenticated'])
        with self.assertRaisesRegex(InputError, 'fixture or simulated'):
            check(self.root, self.report, True)

    def test_changed_source_skill_or_trace_invalidates_record(self):
        for reference in (self.registry, self.report['skill'], self.report['runs'][0]['trace']):
            with self.subTest(path=reference['path']):
                path = self.root / reference['path']
                original = path.read_bytes()
                path.write_bytes(original+b' ')
                with self.assertRaisesRegex(InputError, 'SHA-256 differs'):
                    check(self.root, self.report, False)
                path.write_bytes(original)

    def test_trace_of_another_run_is_rejected_even_when_hash_matches(self):
        report = copy.deepcopy(self.report)
        report['runs'][0]['trace'] = report['runs'][1]['trace']
        with self.assertRaisesRegex(InputError, 'trace context differs'):
            check(self.root, report, False)

    def test_real_exit_code_and_stdout_are_required_and_must_agree(self):
        report = copy.deepcopy(self.report)
        trace = json.loads((self.root / report['runs'][0]['trace']['path']).read_bytes())
        trace['events'][0]['exit_code'] = 2
        report['runs'][0]['trace'] = self.write(report['runs'][0]['trace']['path'],trace)
        with self.assertRaisesRegex(InputError, 'envelope or exit code'):
            check(self.root,report,False)
        del trace['events'][0]['exit_code']
        report['runs'][0]['trace'] = self.write(report['runs'][0]['trace']['path'],trace)
        with self.assertRaisesRegex(InputError, 'actual exit_code'):
            check(self.root,report,False)

    def test_partial_model_coverage_does_not_pass_gate(self):
        report = copy.deepcopy(self.report)
        report['record_kind'] = 'agent_evaluation'  # forged claim used only to exercise the coverage rejection
        report['runs'].pop()
        with self.assertRaisesRegex(InputError, 'cover every scenario'):
            check(self.root, report, False, True)

    def test_single_model_or_absent_no_skill_baseline_cannot_pass_gate(self):
        report = copy.deepcopy(self.report)
        report['record_kind'] = 'agent_evaluation'
        report['runs'] = [run for run in report['runs'] if run['model']['name']=='fixture-model-a']
        with self.assertRaisesRegex(InputError, 'multiple model'):
            check(self.root, report, False, True)
        report['runs'] = [run for run in self.report['runs'] if run['condition']=='with_skill']
        with self.assertRaisesRegex(InputError, 'no-Skill baseline'):
            check(self.root, report, False, True)

    def test_three_scenarios_cannot_be_claimed_as_full_driver_skill(self):
        report = copy.deepcopy(self.report)
        report['record_kind'] = 'agent_evaluation'  # simulated claim, not actual model evidence
        report['evaluation_scope']['claim'] = 'full_driver_skill'
        with self.assertRaisesRegex(InputError, 'missing mandatory scenarios'):
            check(self.root, report, True)

    def test_mandatory_requirement_cannot_be_deleted_or_waived(self):
        report = copy.deepcopy(self.report)
        report['evaluation_scope']['requirements'][0] = report['evaluation_scope']['requirements'][1]
        with self.assertRaisesRegex(InputError, 'retain every mandatory'):
            check(self.root, report, False)

    def test_supported_requirement_needs_an_actual_scenario(self):
        report = copy.deepcopy(self.report)
        next(item for item in report['evaluation_scope']['requirements'] if item['id']=='modal-dialog')['disposition'] = 'supported'
        with self.assertRaisesRegex(InputError, 'absent from the evaluation suite'):
            check(self.root, report, False)

    def test_capability_subset_does_not_satisfy_release_gate(self):
        report = copy.deepcopy(self.report)
        report['record_kind'] = 'agent_evaluation'
        result = check(self.root, report, False, True)
        self.assertTrue(result['capability_subset_gate_satisfied'])
        self.assertFalse(result['release_gate_satisfied'])
        self.assertIn('modal-dialog', result['unsupported_mandatory_scenarios'])
        with self.assertRaisesRegex(InputError, 'capability subset'):
            check(self.root, report, True)

    def test_report_paths_cannot_read_outside_project(self):
        report = copy.deepcopy(self.report)
        report['source_files'][0]['path'] = '../outside.json'
        with self.assertRaises(ValueError):
            check(self.root, report, False)

    def test_publishable_registry_cannot_skip_missing_eval(self):
        registry = self.root / 'registry.json'
        registry.write_text(json.dumps({'release_readiness':{'level':'stable'}}), encoding='utf-8')
        import contextlib, io
        # emit writes to sys.stdout.buffer; provide a real in-memory buffer interface.
        stream = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')
        with contextlib.redirect_stdout(stream):
            code = main(['--root',str(self.root),'--registry','registry.json','--report','missing.json'])
        self.assertEqual(code,2)


if __name__ == '__main__':
    unittest.main()
