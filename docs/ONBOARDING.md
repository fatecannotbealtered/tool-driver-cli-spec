# Onboarding: Get a Driver Tool for Your Application

English | [中文](ONBOARDING_zh.md)

This guide is for a team member who wants a driver tool: a command-line tool that lets an AI Agent operate a professional desktop application or a device, such as `kicad-cli` for KiCad. Your Agent usually builds the tool. You make the decisions only a person can make.

## What You Get

- A command-line tool, installed with npm, that an Agent uses to read and change the application. Every change is previewed and checked before it runs, needs confirmation by risk, is read back afterwards and is reported honestly: what changed, what was saved and what was verified.
- Agent Skills and a knowledge base that ship with the tool and stay in step with it.
- A project that passes the specification's checks on every merge, with conformance tests, behavior matrices and evidence that show how far each command can be trusted.
- A tool that behaves like every other driver tool, so an Agent that knows one knows them all.

## What You Need

- Python 3.12 or later
- Node.js with npm
- Git, and a GitHub repository for the tool
- An Agent that can use Skills, such as Claude Code
- Claude Code for the evaluation runs, whichever Agent builds the tool; the runs use model credits
- The application, installed, with a license that allows automation
- A person who authorizes targets: the files, folders and devices that tests on the real application may use. Often this is you.
- For publishing, an npm account or organization that will own the package

## Install the Development Skill

Each release of tool-driver-cli-spec on GitHub Releases holds the development Skill `build-driver-cli`. It guides your Agent through the eight steps below and, at the end, reviews the tool against the specification.

1. From <https://github.com/fatecannotbealtered/tool-driver-cli-spec/releases>, download `tool-driver-cli-spec-<version>.zip` and `tool-driver-cli-spec-<version>.sha256`.
2. Check the download. With bash, `sha256sum -c tool-driver-cli-spec-<version>.sha256` must print `OK` (on macOS, `shasum -a 256 -c` instead). With PowerShell, `Get-FileHash tool-driver-cli-spec-<version>.zip` must print the value in the `.sha256` file; upper or lower case does not matter. If the values differ, delete the files and do not use them.
3. Unpack the ZIP with `python -m zipfile -e tool-driver-cli-spec-<version>.zip .`.
4. Copy `skills/build-driver-cli/` into your Agent's Skill folder, such as `~/.claude/skills/` for Claude Code or `~/.agents/skills/`.

   With bash:

   ```bash
   mkdir -p ~/.claude/skills
   cp -r tool-driver-cli-spec-<version>/skills/build-driver-cli ~/.claude/skills/
   ```

   With PowerShell:

   ```powershell
   New-Item -ItemType Directory -Force "$HOME\.claude\skills" | Out-Null
   Copy-Item -Recurse -Force "tool-driver-cli-spec-<version>\skills\build-driver-cli" "$HOME\.claude\skills\"
   ```

5. Start your Agent and ask, for example: "Build a driver tool for KiCad with the build-driver-cli Skill."

## The Eight Steps at a Glance

| Step | What the Agent does | What you do |
|---|---|---|
| 1 Survey | Writes the capability survey `docs/APPLICATION.md`: what the application can do, how it can be automated, its limits and risks | Answer what the manuals leave open, and read the survey |
| 2 Choose modes | Proposes the modes: file (reads and writes files), session (drives a running instance) or device; a host component when needed; the platforms to support | Decide the modes |
| 3 Generate the project | Generates the project from the template and checks it | Decide the tool name, the npm package name under a scope you own, the GitHub repository and the author |
| 4 Register commands | Registers the domain commands, each traced to the survey | Review the command list: the names, and what each one may change, which sets how it is confirmed |
| 5 Implement the adapter | Writes the code that talks to the application | Nothing, unless asked |
| 6 Test | Runs the conformance suites against the fake host, then the behavior matrices on the real application | Authorize targets and write the scope file for them |
| 7 Write Skills and knowledge | Writes the Skills, the knowledge entries and the evaluation questions, and runs the evaluation | Authorize a folder for the evaluation, and review the Skills |
| 8 Publish | Builds and packs the packages and runs the delivery test on this machine with `scripts/smoke.py`; prepares the release | Approve the merge and the release, and push the tag |

## Authorizing Targets

Tests on the real application make real changes. They use only the targets you list.

- Prepare targets made for testing: a copy of a project, or a device set up for testing. Never a production project or machine.
- List each target under Authorized Targets in the tool's `docs/E2E.md`, as one list item: the target in backticks, written as a `file://` URL of a file or folder or as `device:<id>`, then a colon and a description. That section is the only list, and the Agent never adds to it. For example:

  ```markdown
  - `file:///D:/e2e/demo-board/`: a copy of the demo board, made for live runs
  ```

- Instances of the application are not listed, because they have no lasting ID. Start an instance yourself for the run, and open in it only files from the list.
- Write the scope file yourself. The tool, not the Agent, reads it: from the path in the environment variable `<PREFIX>_SCOPE_FILE`, where `<PREFIX>` is the tool name in capitals with `_` for `-`, such as `KICAD_CLI_SCOPE_FILE`. Give the Agent its path. A minimal scope file that allows changes and saves under the folder above until a set time:

  ```json
  {
    "scope_id": "live-runs",
    "effects": ["lifecycle", "change", "persist"],
    "dangerous": false,
    "targets": ["file:///D:/e2e/demo-board/"],
    "expires_at": "2026-12-31T18:00:00Z"
  }
  ```

- The Agent never writes or changes a scope file, even when asked in chat. When a write is refused with `E_FORBIDDEN`, the error carries a snippet that would grant it; the Agent shows it to you, and you paste it into the file if you agree. The tool's `docs/E2E.md` describes the whole procedure.
- For the evaluation, list one folder for the evaluation workspaces, and any other target a question's `SCOPE` names, such as a device. The evaluation runner writes each question's scope file itself.

## Evidence and Maturity

Each command is `draft`, `verified` or `stable`, and `<tool> reference` shows the level with its evidence. `verified` needs a passing run of the command's behavior matrix on the real application, and `stable` also a passing evaluation with a real Agent. Evidence counts only for the same major and minor tool version, and results from the fake host never count.

## Publishing

- Only the release workflow of the tool's repository publishes. It starts when an annotated tag `vX.Y.Z`, equal to the version in `package.json`, is pushed. It runs every check and the platform delivery test for every platform package, and publishes to npm with provenance only when all of them pass. A version such as `1.2.0-rc.1` is published under the npm tag `next`.
- You, or a maintainer, create the npm scope or organization and make the `merge gate passed` check required for the main branch. For the first release, add the `NPM_TOKEN` secret to the repository; after it, set up npm trusted publishing for the package and disallow token publishing.
- The Agent never publishes, tags or pushes without your approval. When it asks, approve the merge, then push the tag yourself, or let the Agent run these two commands after you approve:

  ```bash
  git tag -a vX.Y.Z -m "vX.Y.Z"
  git push origin vX.Y.Z
  ```

- Users then install the tool with `npm install -g <package>`, run `<tool> update` once and copy its Skills, as the tool's README says.

## Moving to a New Specification Release

Install the new release's development Skill first: copy its `skills/build-driver-cli/` over your installed copy, as in Install the Development Skill. Then ask your Agent to move the tool to the new release. It pins the new release, fixes what the checks report and reviews the tool again; do not run the sync yourself.
