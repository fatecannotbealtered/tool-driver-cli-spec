"""Recorder and independent grader boundary tests, with no model execution or model pass claims."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from prepare_svg_agent_eval import prepare
import grade_svg_agent_run as grading


class EvaluationHarnessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='eval-harness-fixture-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.batch = self.root / 'batch'
        prepare(self.batch, ['fixture-controller-a', 'fixture-controller-b'])
        self.plan = json.loads((self.batch / 'evaluation-plan.json').read_text(encoding='utf-8'))

    def run_for(self, scenario, condition='without_skill'):
        return next(run for run in self.plan['runs'] if run['scenario_id']==scenario
                    and run['condition']==condition and run['requested_model']=='fixture-controller-a')

    def call(self, run, *arguments):
        return subprocess.run([sys.executable, '-B', str(Path(run['cwd']) / 'invoke.py'), *arguments],
                              capture_output=True, timeout=60, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))

    def test_preparation_only_creates_isolated_inputs_not_model_records(self):
        self.assertEqual((self.plan['executed_model_runs'], len(self.plan['runs'])), (0,12))
        self.assertEqual(len({run['cwd'] for run in self.plan['runs']}),12)
        for run in self.plan['runs']:
            folder = Path(run['cwd'])
            self.assertEqual((folder/'SKILL.md').exists(),run['condition']=='with_skill')
            self.assertTrue((folder/'authorization.json').exists())
            scope=json.loads((folder/'authorization.json').read_text(encoding='utf-8'))
            self.assertEqual('change' in scope['effects'],run['scenario_id']=='write-dry-run-confirm')
            self.assertFalse((folder/'run-evidence').exists())
            self.assertNotIn('expected',Path(run['prompt_file']).read_text(encoding='utf-8').split('User task:')[1].split('The target paths')[0])

    def test_raw_subprocess_recording_and_unauthorized_result_are_preserved(self):
        run = self.run_for('missing-scope')
        result = self.call(run,'drawing','set-title','--file',str(Path(run['cwd'])/'drawing.svg'),
                           '--title','Bracket & mount','--dry-run')
        self.assertEqual(result.returncode,4,result.stderr)
        logs = Path(run['cwd'])/'run-evidence'
        event = json.loads(next(logs.glob('*.event.json')).read_text(encoding='utf-8'))
        self.assertEqual(event['exit_code'],result.returncode)
        self.assertEqual(event['stdout'].encode(),result.stdout)
        self.assertEqual((logs/(event['call_id']+'.stdout.bin')).read_bytes(),result.stdout)
        self.assertEqual(event['before_files']['drawing.svg'],event['after_files']['drawing.svg'])
        scope=json.loads((Path(run['cwd'])/'authorization.json').read_text(encoding='utf-8'))
        self.assertEqual(scope['effects'],['observe'])

    def test_independent_grader_rejects_tampered_raw_logs(self):
        run = self.run_for('fresh-agent-read')
        self.assertEqual(self.call(run,'drawing','inspect','--file',str(Path(run['cwd'])/'drawing.svg')).returncode,0)
        logs = Path(run['cwd'])/'run-evidence'
        next(logs.glob('*.stdout.bin')).write_bytes(b'{}')
        browser = self.root/'fixture-browser'
        browser.write_bytes(b'No browser or model is executed in this boundary test.')
        observed = {'title':'Original','width':'40mm','height':'30mm',
                    'rect':{'id':'protected','x':'5','y':'4','width':'10','height':'6'}}
        with patch.object(grading,'consume',return_value=observed):
            report = grading.grade(self.batch/'evaluation-plan.json',run['run_id'],browser,self.root/'grade')
        self.assertEqual(report['status'],'failed')
        self.assertEqual(next(c['status'] for c in report['checks'] if c['id']=='actual-subprocess-records'),'failed')


if __name__ == '__main__':
    unittest.main()
