"""Runnable file adapter: edit one existing SVG title, preserve every other byte.

This demonstrates the SDK contract. It is not a CAD or PCB adapter.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import platform
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'packages'), str(ROOT / 'scripts')]
from contract_io import read_regular_file
from generate_product import build_contract
from tool_driver_sdk import DriverError, serve
from tool_driver_sdk.scope import file_path_of

TITLE = re.compile(rb'(<title(?:\s[^<>]*)?>)([^<>]*)(</title\s*>)')


def sha(path):
    return 'sha256:' + hashlib.sha256(read_regular_file(path, 1024 * 1024)).hexdigest()


def snapshot(path, label):
    return {'id': label, 'source': 'disk', 'revision': sha(path),
            'observed_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'), 'dependencies': []}


def load(path):
    try:
        data = read_regular_file(path, 1024 * 1024)
        if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
            raise ValueError('DTD and entity declarations are unsupported')
        root = ET.fromstring(data)
        titles = root.findall('{http://www.w3.org/2000/svg}title')
        if root.tag != '{http://www.w3.org/2000/svg}svg' or len(titles) != 1 or len(list(TITLE.finditer(data))) != 1:
            raise ValueError('require an SVG root with exactly one plain, direct title element')
        return data, root, titles[0].text or ''
    except (OSError, ValueError, ET.ParseError) as error:
        raise DriverError('E_VALIDATION', str(error), dispatch_state='not_started',
                          details={'problem': 'invalid_value', 'next_action': 'Use a regular UTF-8 SVG file with one plain title.'}) from error


class Adapter:
    def environment(self):
        source = Path(__file__).resolve()
        registry = json.loads((source.parent / 'registry.json').read_text(encoding='utf-8'))
        return {'components': [
            {'name': source.name, 'role': 'adapter', 'version': registry['product_version'],
             'build_id': hashlib.sha256(source.read_bytes()).hexdigest(), 'location': 'disk', 'identity_status': 'observed'},
            {'name': 'Python', 'role': 'validator', 'version': platform.python_version(),
             'build_id': hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
             'location': 'running', 'identity_status': 'observed'},
        ], 'connection': {'status': 'not_connected', 'instance_id': None, 'generation': None, 'ownership': None,
                           'reason': 'This file adapter requires no running application connection; native CAD is unsupported.'}}

    def doctor_checks(self):
        # Check the local decoder and loaded adapter source, without creating or modifying a target.
        ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg"><title>probe</title></svg>')
        source = Path(__file__).resolve()
        return [{'check': 'native_backend', 'status': 'pass', 'fix': None,
                 'message': 'Local SVG decoder is available; target validity and permissions are checked for each call. No native CAD service is claimed. Adapter source SHA-256: ' + hashlib.sha256(source.read_bytes()).hexdigest()}]

    def revision(self, target):
        return sha(Path(file_path_of(target['locator'])))

    def run(self, call):
        path = Path(call.params['file']).resolve()
        _, root, title = load(path)
        return {'file': str(path), 'title': title, 'width': root.get('width'), 'height': root.get('height'),
                'element_count': len(list(root.iter())), 'snapshot': snapshot(path, 'read')}

    def plan(self, call):
        path = Path(call.params['file']).resolve()
        load(path)
        try:
            ET.fromstring('<title>' + html.escape(call.params['title'], quote=False) + '</title>')
        except ET.ParseError as error:
            raise DriverError('E_VALIDATION', 'Title contains an invalid XML character.', dispatch_state='not_started',
                              details={'problem': 'invalid_value', 'next_action': 'Use valid XML text.'}) from error
        return {'target': {'mode': 'file', 'engine_id': 'svg-title', 'instance_id': None,
                           'object_id': path.name, 'locator': path.as_uri()},
                'base_snapshot': snapshot(path, 'before'), 'level': 'plan',
                'changes': [{'action': 'set', 'resource': 'title', 'summary': 'Replace only existing SVG title text.'}],
                'outputs': [{'path': str(path), 'effect': 'persist', 'exists': True}]}

    def apply(self, call, plan):
        path = Path(file_path_of(plan['target']['locator']))
        before, _, _ = load(path)
        if sha(path) != plan['base_snapshot']['revision']:
            raise DriverError('E_CONFLICT', 'File changed since planning.', dispatch_state='not_started',
                              details={'reason': 'stale_snapshot', 'next_action': 'Inspect and plan again.'})
        match = TITLE.search(before)
        title = call.params['title']
        # Reject invalid XML characters before writing. Do not expand markup.
        escaped = html.escape(title, quote=False).encode('utf-8')
        after = before[:match.start(2)] + escaped + before[match.end(2):]
        try:
            ET.fromstring(after)
        except ET.ParseError as error:
            raise DriverError('E_VALIDATION', 'Title contains an invalid XML character.', dispatch_state='not_started',
                              details={'problem': 'invalid_value', 'next_action': 'Use valid XML text.'}) from error
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.svg-title-', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(after)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
        actual, _, actual_title = load(path)
        passed = actual == after and actual_title == title
        return {'snapshot_after': snapshot(path, 'after'),
                'outcome': {'execution': 'completed', 'change': 'applied', 'persistence': 'saved',
                            'delivery': 'not_applicable',
                            'verification': {'status': 'passed' if passed else 'failed',
                                             'scope': 'UTF-8 SVG title and unchanged bytes outside title',
                                             'snapshot_id': 'after', 'coverage': 'complete',
                                             'checks': [{'id': 'readback', 'status': 'passed' if passed else 'failed',
                                                         'required': True, 'evidence_ref': path.as_uri()}],
                                             'not_checked': [], 'evidence_refs': [path.as_uri()]}},
                'changed_items': [{'id': 'title', 'change': 'replaced', 'evidence_ref': path.as_uri()}],
                'recovery': {'action': 'none', 'reason': 'Read back saved file; no CAD validation claimed.', 'supported': True}}


def main():
    directory = Path(__file__).resolve().parent
    registry = json.loads((directory / 'registry.json').read_text(encoding='utf-8'))
    contract = build_contract(registry, registry_dir=directory)
    return serve(contract, Adapter(), vendor_root=ROOT)


if __name__ == '__main__':
    raise SystemExit(main())
