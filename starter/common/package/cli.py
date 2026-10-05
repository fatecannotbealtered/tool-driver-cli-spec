"""{{NAME}} entry point: load the generated contract and serve one call through the driver SDK."""

from __future__ import annotations

import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parent
SPEC = ROOT / ".agent" / "driver"
SDK = ROOT / ".agent" / "vendor" / "sdk"


def main(argv=None) -> int:
    if str(SDK) not in sys.path:
        sys.path.insert(0, str(SDK))
    from tool_driver_sdk import load_contract, serve

    from .adapter import Adapter

    contract = load_contract(PACKAGE / "generated" / "product_contract.json")
    return serve(contract, Adapter(), vendor_root=SPEC, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
