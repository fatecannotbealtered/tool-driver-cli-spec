# Notice

{{tool}}

Copyright {{year}} {{author}}

Licensed under the Apache License, Version 2.0. The license text is in `LICENSE`.

## Trademarks

{{tool}} drives {{application}}. {{application}} is a trademark of its owner. {{tool}} is not affiliated with, endorsed by or sponsored by the owner of {{application}}.

## Third-party components

| Component | Where | License |
|---|---|---|
| CPython runtime | Bundled in the native program | Python Software Foundation License |
| PyInstaller bootloader | Bundled in the native program | GNU General Public License 2.0 or later, with an exception that allows distributing programs built with it |
| tool-driver-cli-spec {{spec_version}} | `.agent/` and `contract/driver-contract.json` | See `licenses/` |
| Driver runtime | `{{pkg}}/_driver/` | See `licenses/` |

{{fill: every other component the native program or the host component bundles, with its license; or delete this line when there is none}}
