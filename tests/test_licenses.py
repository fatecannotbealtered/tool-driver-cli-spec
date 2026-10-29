"""License propagation without relicensing a generated product's additions."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from bundle_layout import required_payload
from instantiate_starter import instantiate, vendored


class LicenseTests(unittest.TestCase):
    def test_required_bundle_and_vendored_licenses(self):
        self.assertTrue({'LICENSE', 'THIRD_PARTY_NOTICES.md', 'packages/tool_driver_sdk/LICENSE'} <= required_payload())
        copies = vendored()
        for source, destination in [('LICENSE', '.agent/driver/LICENSE'),
                                    ('THIRD_PARTY_NOTICES.md', '.agent/driver/THIRD_PARTY_NOTICES.md'),
                                    ('packages/tool_driver_sdk/LICENSE', '.agent/vendor/sdk/tool_driver_sdk/LICENSE')]:
            self.assertEqual(copies[destination][1], (ROOT / source).read_bytes())

    def test_candidate_archive_preserves_licenses_and_manifest_hashes(self):
        with tempfile.TemporaryDirectory(prefix='license-package-') as temp:
            project = Path(temp) / 'product'
            instantiate('license-driver', project, 'file')
            self.assertFalse((project / 'LICENSE').exists(), 'Product license is still a maintainer choice')
            spec = importlib.util.spec_from_file_location('candidate_license_test', project / 'scripts/build-package.py')
            builder = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(builder)

            def run(args, **kwargs):
                if args[0] == 'git':
                    return subprocess.CompletedProcess(args, 0, 'a' * 40 if 'rev-parse' in args else '', '')
                output = Path(args[args.index('--distpath') + 1])
                output.mkdir(parents=True)
                (output / 'license-driver').write_bytes(b'synthetic executable; not platform support evidence')
                return subprocess.CompletedProcess(args, 0, '', '')

            with patch.object(builder.subprocess, 'run', side_effect=run), \
                 patch.object(builder.platform, 'system', return_value='Linux'), \
                 patch.object(builder.platform, 'machine', return_value='x86_64'), \
                 patch.dict(builder.os.environ, {}, clear=True):
                builder.main()
            archive = next((project / 'dist').glob('*.tar.gz'))
            with tarfile.open(archive) as bundle:
                manifest = json.load(bundle.extractfile('manifest.json'))
                paths = {item['path'] for item in manifest['components']}
                expected = {'THIRD_PARTY_NOTICES.md', 'LICENSES/tool-driver-cli-spec.txt',
                            'LICENSES/driver-spec-LICENSE', 'LICENSES/driver-spec-NOTICES.md',
                            'LICENSES/driver-sdk-LICENSE'}
                self.assertTrue(expected <= paths)
                for item in manifest['components']:
                    import hashlib
                    self.assertEqual(hashlib.sha256(bundle.extractfile(item['path']).read()).hexdigest(), item['sha256'])
                self.assertIn(b'MIT License', bundle.extractfile('LICENSES/driver-spec-NOTICES.md').read())


if __name__ == '__main__':
    unittest.main()
