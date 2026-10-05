"""The required payload is defined by the consumer, never by a package manifest."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_FILES = {
    'README.md', 'AGENTS.md', 'VERSION', 'STATUS', 'CHANGELOG.md', 'requirements-dev.txt',
    'base/base-lock.json', 'contract/driver-contract.json',
    'docs/LAYERING.md', 'docs/CORE-SPEC.md', 'docs/DRIVER-SPEC.md',
    'docs/VERIFICATION-SPEC.md', 'docs/DELIVERY-SPEC.md', 'docs/SKILL-ADDENDUM.md',
    'docs/VERIFICATION-RESULTS.md',
    'docs/ADOPTION-GUIDE.md', 'docs/DEVELOPMENT-GUIDE.md',
    'docs/ENGINEERING-ACCEPTANCE.md', 'examples/engineering/README.md',
    'docs/SOFTWARE-SPEC-MAPPING.md',
    'docs/AGENT-EVAL-RUNBOOK.md',
    'scripts/check_spec.py', 'scripts/contract_io.py', 'scripts/validate_contract.py',
    'scripts/generate_product.py', 'scripts/instantiate_starter.py',
    'scripts/verify_spec_bundle.py', 'scripts/check_adoption.py', 'scripts/bundle_layout.py',
    'scripts/check_graduation.py', 'scripts/run_file_consumer_probe.py',
    'scripts/check_agent_eval.py', 'requirements-workflow.txt',
    'scripts/prepare_svg_agent_eval.py', 'scripts/record_eval_call.py', 'scripts/grade_svg_agent_run.py',
    'examples/engineering/svg_title_driver.py', 'examples/engineering/registry.json',
    'examples/engineering/CHANGELOG.md',
}


def required_payload() -> set[str]:
    """Require the supported structure's entire public schema, SDK and starter surface.

    These paths come from this installed verifier. An attacker removing entries
    from the embedded manifest cannot redefine what constitutes a usable package.
    Tests and optional examples may extend the inventory.
    """
    paths = set(CORE_FILES)
    for folder, pattern in (('schemas', '*.schema.json'), ('packages/tool_driver_sdk', '*.py'),
                            ('starter/common', '**/*'), ('base/ai-native-cli-spec', '*')):
        for path in (ROOT / folder).glob(pattern):
            if path.is_file() and '__pycache__' not in path.parts:
                paths.add(path.relative_to(ROOT).as_posix())
    return paths
