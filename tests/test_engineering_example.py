"""Actual subprocess calls and an independent saved-file reader for the worked adapter."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HIDDEN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="40mm" height="30mm"><title>Original</title><!--keep--><rect id="protected" x="5" y="4" width="10" height="6"/></svg>'


class EngineeringExampleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='engineering-example-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / 'drawing.svg'
        self.path.write_bytes(SVG)
        self.scope = self.root / 'scope.json'
        self.environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', SAMPLE_DRIVER_STATE_DIR=str(self.root / 'state'),
                                SAMPLE_DRIVER_SCOPE_FILE=str(self.scope))

    def grant(self):
        self.scope.write_text(json.dumps({'scope_id': 'test-scope', 'tool': 'sample-driver', 'granted_by': 'fixture-owner',
                                         'granted_at': '2026-10-04T00:00:00Z', 'expires_at': None,
                                         'effects': ['observe', 'change', 'persist'], 'dangerous': False,
                                         'roots': [str(self.root)], 'outputs': [str(self.root)]}), encoding='utf-8')

    def call(self, *argv, code=0):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'examples/engineering/svg_title_driver.py'), *argv],
                                env=self.environment, capture_output=True, timeout=30, creationflags=HIDDEN)
        self.assertEqual(result.returncode, code, result.stdout.decode('utf-8') + result.stderr.decode('utf-8'))
        return json.loads(result.stdout)

    def edit(self, *args, code=0, title='Bracket & mount'):
        return self.call('drawing', 'set-title', '--file', str(self.path), '--title', title, *args, code=code)

    def test_cross_process_plan_apply_lookup_and_independent_reader(self):
        self.grant()
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        plan = self.edit('--dry-run')['data']
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)
        result = self.edit('--confirm', plan['confirm_token'])['data']['receipt']
        self.assertEqual(result['outcome']['persistence'], 'saved')
        self.assertEqual(self.path.read_bytes(), SVG.replace(b'Original', b'Bracket &amp; mount'))
        independent = subprocess.run([sys.executable, '-B', '-c',
            "import json,sys,xml.etree.ElementTree as E; r=E.parse(sys.argv[1]).getroot(); print(json.dumps({'title':r.find('{http://www.w3.org/2000/svg}title').text,'width':r.get('width'),'rect':r.find('{http://www.w3.org/2000/svg}rect').attrib}))",
            str(self.path)], capture_output=True, timeout=30, creationflags=HIDDEN)
        self.assertEqual(independent.returncode, 0)
        observed = json.loads(independent.stdout)
        self.assertEqual(observed['title'], 'Bracket & mount')
        self.assertEqual(observed['width'], '40mm')
        self.assertEqual(observed['rect'], {'id': 'protected', 'x': '5', 'y': '4', 'width': '10', 'height': '6'})
        record = self.call('operation', 'show', '--id', result['operation_id'])['data']['operation_status']
        self.assertEqual(record['receipt']['operation_id'], result['operation_id'])

    def test_default_scope_refuses_writes_before_dispatch(self):
        response = self.edit('--dry-run', code=4)
        self.assertEqual(response['error']['code'], 'E_FORBIDDEN')
        self.assertEqual(response['error']['details']['dispatch_state'], 'not_started')
        self.assertEqual(self.path.read_bytes(), SVG)

    def test_preflight_observes_the_file_backend_without_claiming_a_native_session(self):
        context = self.call('context')['data']
        self.assertEqual(context['environment']['connection']['status'], 'not_connected')
        adapter = next(c for c in context['environment']['components'] if c['role']=='adapter')
        self.assertEqual(adapter['build_id'],hashlib.sha256((ROOT/'examples/engineering/svg_title_driver.py').read_bytes()).hexdigest())
        doctor = self.call('doctor')['data']
        self.assertEqual(next(c for c in doctor['checks'] if c['check']=='native_backend')['status'],'pass')
        self.assertEqual(self.path.read_bytes(),SVG)

    def test_external_edit_invalidates_plan_without_overwriting_user_content(self):
        self.grant()
        plan = self.edit('--dry-run')['data']
        updated = SVG.replace(b'Original', b'User edit')
        self.path.write_bytes(updated)
        response = self.edit('--confirm', plan['confirm_token'], code=6)
        self.assertEqual(response['error']['code'], 'E_CONFLICT')
        self.assertEqual(self.path.read_bytes(), updated)

    def test_invalid_xml_title_is_rejected_without_writing(self):
        self.grant()
        title = 'invalid\x01title'
        response = self.edit('--dry-run', code=2, title=title)
        self.assertEqual(response['error']['code'], 'E_VALIDATION')
        self.assertEqual(self.path.read_bytes(), SVG)


if __name__ == '__main__':
    unittest.main()
