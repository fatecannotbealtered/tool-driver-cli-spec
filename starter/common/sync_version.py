"""Synchronize product metadata from registry.json; never edit pinned rules or generated contracts."""
from __future__ import annotations
import json
from pathlib import Path
import re
import stat
import sys
import tomllib

ROOT = Path(__file__).resolve().parent


def source_text(root, path):
    info = path.lstat()
    if (not path.resolve().is_relative_to(root.resolve()) or not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0) & 0x400):
        raise ValueError('version metadata must be a regular file inside the project')
    return path.read_text(encoding='utf-8')


def locations(root=ROOT):
    registry = json.loads(source_text(root, root / 'registry.json'))
    name, version = registry['name'], registry['product_version']
    if not re.fullmatch(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*', name):
        raise ValueError('registry product name must be kebab-case')
    project = root / 'pyproject.toml'
    skill = root / 'skills' / name / 'SKILL.md'
    project_text, skill_text = source_text(root,project), source_text(root,skill)
    sections = skill_text.split('---', 2)
    if len(sections) != 3 or sections[0].strip():
        raise ValueError('Skill needs YAML frontmatter')
    front = sections[1]
    skill_version = re.search(r'^version:\s*"([^"]+)"\s*$', front, re.M)
    metadata = re.search(r'^metadata:\s*(\{.*\})\s*$', front, re.M)
    if not skill_version or not metadata:
        raise ValueError('Skill must have quoted frontmatter version and JSON metadata')
    minimum = json.loads(metadata.group(1))['requires']['min_version']
    values = {'pyproject.toml': tomllib.loads(project_text)['project']['version'],
              'Skill.version':skill_version.group(1), 'Skill.requires.min_version':minimum}
    return version, values, [(project, project_text, r'^(version\s*=\s*")[^"]+("\s*)$'),
                            (skill, skill_text, r'^(version:\s*")[^"]+("\s*)$'),
                            (skill, skill_text, r'("min_version"\s*:\s*")[^"]+(")')]


def version_drift(root=ROOT):
    version, values, _ = locations(root)
    name = json.loads(source_text(root,root/'registry.json'))['name']
    reference = json.loads(source_text(root,root/name.replace('-','_')/'generated/reference.json'))
    values['generated/reference.version'] = reference['version']
    return [key for key, value in values.items() if value != version]


def synchronize(root=ROOT):
    version, _, descriptions = locations(root)
    outputs = {}
    for path, text, pattern in descriptions:
        current = outputs.get(path, text)
        revised, count = re.subn(pattern, lambda match: match.group(1)+version+match.group(2), current, flags=re.M)
        if count != 1:
            raise ValueError('version location must occur exactly once: '+path.name)
        outputs[path] = revised
    changed = []
    for path, revised in outputs.items():
        if source_text(root,path) != revised:
            path.write_text(revised, encoding='utf-8', newline='\n')
            changed.append(path.relative_to(root).as_posix())
    return {'version':version, 'changed':changed,
            'next_action':'Update CHANGELOG, regenerate contracts with --update, then run check_project.py and tests.'}


def main():
    try:
        response = {'ok':True,'schema_version':'1.0','data':synchronize(),'meta':{'duration_ms':0}}
        code = 0
    except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
        response = {'ok':False,'schema_version':'1.0','meta':{'duration_ms':0},
                    'error':{'code':'E_CONFIG','message':str(error),'retryable':False,
                             'details':{'next_action':'Fix registry.json and the declared version locations; nothing is downloaded.'}}}
        code = 4
    sys.stdout.buffer.write((json.dumps(response, ensure_ascii=False)+'\n').encode('utf-8'))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
