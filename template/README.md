# {{tool}}

{{fill: one-line pitch: what the tool lets an Agent do in {{application}}}}

<!-- driver:badges:start -->
<!-- driver:badges:end -->

English | [中文](README_zh.md)

<!-- driver:info-card:start -->
<!-- driver:info-card:end -->

## Install

1. Install {{tool}} from npm:

   ```bash
   npm install -g {{package}}
   ```

2. Run `update` once. The installed version is already current, so `update` only points the command entry at the native program, so that no call has to start Node.js first:

   ```bash
   {{tool}} update
   ```

3. Install the Skills from the installed package; they never come from the network. Copy them into your Agent's Skill folder. With bash:

   ```bash
   mkdir -p ~/.agents/skills
   cp -r "$(npm root -g)/{{package}}/skills/"* ~/.agents/skills/
   ```

   With PowerShell:

   ```powershell
   New-Item -ItemType Directory -Force "$HOME\.agents\skills" | Out-Null
   Copy-Item -Recurse "$(npm root -g)\{{package}}\skills\*" "$HOME\.agents\skills\"
   ```

   Other Agent Skill folders, such as `~/.claude/skills/`, work the same way. Later runs of `{{tool}} update` keep the copies in those folders in step with the tool.
{{#host_component}}

4. Install the host component into {{application}}. This is a two-step write that needs a scope file allowing `configure` (see Authorization). The first call changes nothing and returns a preview and a confirm token; the second call installs:

   ```bash
   {{tool}} plugin install
   {{tool}} plugin install --confirm <token>
   ```

   Start or restart {{application}} afterwards so that it loads the host component.
{{/host_component}}

## Capabilities

Every command of {{tool}}, generated from its command registration; `(dangerous)` marks a command in the dangerous tier, and `{{tool}} reference --command "<path>"` describes one in full.

<!-- driver:command-map:start -->
<!-- driver:command-map:end -->

## How It Works

{{tool}} prints one JSON envelope for every call. `{{tool}} reference` lists every command, and `{{tool}} reference --command "<path>"` describes one, with its flags, its effects and its confirmation tier in each mode.
{{#session}}

**Instances and documents.** {{tool}} drives running instances of {{application}}. `{{tool}} session list` shows each instance with its session ID, its state and its open documents, and `{{tool}} doc list` shows the documents. Name the instance with `--session <id>` and the document with `--doc <path-or-id>`. When several instances run and a command names none, it returns `E_AMBIGUOUS` with the candidates: {{tool}} never picks an instance by window focus or by recent use. A `--doc` that exactly one instance has open selects that instance. A file that an instance has open is changed only through that instance; a direct write to the file is refused with `E_CONFLICT`.
{{/session}}
{{#file}}

**Files.** {{tool}} reads and writes {{application}} files directly, without a running instance. `--doc <path>` names the file.
{{/file}}
{{#device}}

**Devices.** {{tool}} drives devices through their controller. `{{tool}} device list` shows each device with its state and whether it is simulated; name one with `--device <id>`. A device in `fault` or `emergency_stop` needs a person on site: every command that acts on it returns `E_HUMAN_REQUIRED`, except the commands that only stop work.
{{/device}}

**Confirmation tiers.** Every write checks the scope, builds a preview, checks the state again just before dispatch, locks its target, reads the change back and returns a receipt. Only the confirmation depends on the tier, which {{tool}} derives from the effects the command declares:

| Tier | Applies to | How to call |
|---|---|---|
| direct | Changes held in memory until they are saved; starting instances; creating and opening documents; new files that overwrite nothing; stopping work | One call runs it |
| two-step | Saving and overwriting files; changes in file and device mode; settings; host components | The first call changes nothing and returns `E_CONFIRMATION_REQUIRED` with a preview and a confirm token; the same command with `--confirm <token>` runs it |
| dangerous | Physical actions; handing content to outside people or systems; irreversible changes; discarding unsaved changes; closing an instance {{tool}} did not start | As two-step, and the confirming call also carries `--dangerous`; the scope must allow dangerous operations |

`--dry-run` shows the preview of any write and changes nothing. A confirm token works once, within 10 minutes, and only for the change it previewed. When the scope file sets `"confirm": "always"`, every write except stopping work is two-step, so that a person can approve each preview.
{{#session}}

**Saving in session mode.** A change is not a save. After a change, the receipt reports `persistence: unchanged` and the document stays dirty; only `{{tool}} doc save` writes the document's file. Its preview lists every change since the last save, including changes a person made in {{application}} (`origin: external`) and writes whose outcome is still unknown.
{{/session}}
{{#file}}

**Saving in file mode.** Writing the file is the save: the receipt reports `persistence: saved`, and {{tool}} reads the file again to verify the change.
{{/file}}
{{#device}}

**Device mode** has nothing to save: the device acts at once, and {{tool}} reads the result back from the device.
{{/device}}

**Receipts.** Every write returns a receipt that reports separately whether the change ran, took effect, was delivered, was saved and was verified. When the reply to a write is lost, {{tool}} returns `E_OUTCOME_UNKNOWN` with the command that settles the outcome, and the write is never sent twice.

## Authorization

{{tool}} reads without asking, but it writes only what a person has granted in a scope file. The person writes this JSON file by hand; no command writes it, and an Agent never creates or changes it. {{tool}} reads it from the path in `{{PREFIX}}_SCOPE_FILE`, or from `scope.json` in the state directory when the variable is not set, and from nowhere else.

```json
{
  "scope_id": "demo-rework",
  "effects": ["change", "persist"],
  "dangerous": false,
  "targets": ["file:///D:/projects/demo/"],
  "expires_at": "2027-01-31T18:00:00Z"
}
```

| Field | Meaning |
|---|---|
| `scope_id` | Names the grant; operation records carry it |
| `effects` | The effects writes may have; reads need no scope |
| `dangerous` | Whether operations in the dangerous tier are allowed |
| `targets` | Target-key prefixes of the objects writes may touch: `file:///D:/projects/demo/` covers every file under that folder, `untitled:` covers new documents and `device:<id>` covers one device |
| `expires_at` | When the grant ends, in UTC |
| `confirm` | Optional; `always` makes every write except stopping work wait until a person approves its preview |

A write the scope does not cover changes nothing and returns `E_FORBIDDEN`, with what is missing and a snippet the person can paste into the file. `{{tool}} context` shows the scope in force, and `SECURITY.md` describes the scope in full.

{{fill: the effects the commands of {{tool}} need, and which commands need each, for example as a table of effect and commands}}

## About This Tool

{{fill: the domain of {{application}}, the typical tasks an Agent does with {{tool}}, and screenshots or short examples}}

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `{{PREFIX}}_STATE_DIR` | `~/.{{tool}}` | The state directory: operation records, locks, the update cache and team knowledge registrations |
| `{{PREFIX}}_SCOPE_FILE` | `scope.json` in the state directory | The scope file (see Authorization) |
| `HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY` | not set | Proxies for `update` and `doctor`, the only commands that contact the npm registry |
| `{{PREFIX}}_FAKE_HOST` | not set | For tests only: sends every call to the fake host instead of {{application}} and marks every result as simulated |

### Finding {{application}}

{{fill: how {{tool}} finds {{application}}: install location, version detection, running instances, and any setting the user can change}}

## Uninstall
{{#host_component}}

Remove the host component first, while {{tool}} is still installed. Like installing, removing is a two-step write that needs a scope allowing `configure`. A version that a running instance still has loaded stays on disk; close {{application}} and run the command again to remove it.

```bash
{{tool}} plugin remove
{{tool}} plugin remove --confirm <token>
```
{{/host_component}}

Remove the installed Skills while the package still lists them. With bash:

```bash
for skill in "$(npm root -g)/{{package}}/skills/"*; do rm -rf ~/.agents/skills/"$(basename "$skill")"; done
```

With PowerShell:

```powershell
Get-ChildItem "$(npm root -g)\{{package}}\skills" | ForEach-Object { Remove-Item -Recurse -Force "$HOME\.agents\skills\$($_.Name)" -ErrorAction SilentlyContinue }
```

Do the same in every other Agent Skill folder you copied them to, such as `~/.claude/skills/`. Then remove the npm package:

```bash
npm uninstall -g {{package}}
```

Last, delete the state directory: `~/.{{tool}}`, or the folder that `{{PREFIX}}_STATE_DIR` names. It holds the operation records, the locks, the default scope file and the team knowledge registrations, so keep it if you want the records.

```bash
rm -rf ~/.{{tool}}
```

```powershell
Remove-Item -Recurse -Force "$HOME\.{{tool}}"
```

## Development

{{tool}} is written in Python on the driver runtime in `{{pkg}}/_driver/`, a pinned copy that is never edited. Domain commands live in `{{pkg}}/commands/` and the adapter layer in `{{pkg}}/adapter/`.
{{#host_component}}
The host component source lives in `plugin/`.
{{/host_component}}

```bash
python -m pip install --require-hashes --no-deps -r requirements-dev.txt
python scripts/spec.py check
python -m unittest discover -s tests
python scripts/spec.py suites
```

The tests and the conformance suites use the fake host and never need {{application}}. `CONTRIBUTING.md` describes the workflow, the behavior matrices and live runs.

## Links

- Specification: [tool-driver-cli-spec {{spec_version}}](.agent/), pinned in `.agent/`
- [CHANGELOG.md](CHANGELOG.md): the changes in each version
- [SECURITY.md](SECURITY.md): the security model and how to report a vulnerability
- [CONTRIBUTING.md](CONTRIBUTING.md): how to contribute
- [docs/APPLICATION.md](docs/APPLICATION.md): the capability survey of {{application}}
- [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md): where {{tool}} works
- [docs/E2E.md](docs/E2E.md): live acceptance and its records
- Issues: <https://github.com/{{repo}}/issues>
