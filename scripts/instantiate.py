#!/usr/bin/env python3
"""Generate a new driver tool project from the template: instantiate.

    python scripts/instantiate.py <new project directory> --tool kicad-cli --package @acme/kicad-cli \\
        --application KiCad --versions ">=9.0 <11" --modes file,session \\
        [--host-component] [--platforms windows,macos,linux] [--repo acme/kicad-cli] \\
        [--author "Acme Ltd"] [--version 0.1.0]

It copies ``template/`` with the values filled in, pins this specification release with
``sync_spec`` and writes the generated content. ``check_project`` then lists only what the
next steps fill in: the placeholders (DREPO-019) and the domain commands to register (DREPO-062).
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_project  # noqa: E402
import sync_spec  # noqa: E402

TEMPLATE = check_project.BUNDLE / "template"
NPM_OS = {"windows": "win32", "macos": "darwin", "linux": "linux"}
OS_ROWS = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}


def parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--tool", required=True, help="the command name, such as kicad-cli")
    parser.add_argument("--package", required=True, help="the npm package name, such as @acme/kicad-cli")
    parser.add_argument("--application", required=True, help="the application the tool drives, such as KiCad")
    parser.add_argument("--versions", required=True, help='the supported application versions, such as ">=9.0 <11"')
    parser.add_argument("--modes", required=True, help="file, session and device, comma-separated")
    parser.add_argument("--host-component", action="store_true", help="the tool installs code into the application")
    parser.add_argument("--platforms", default="windows,macos,linux", help="the systems to ship, comma-separated")
    parser.add_argument("--repo", help="the GitHub repository owner/name; default <package scope>/<tool>")
    parser.add_argument("--author", default="The {tool} authors", help="the copyright holder")
    parser.add_argument("--version", default="0.1.0", help="the first tool version")
    args = parser.parse_args(argv)
    problems = []
    if not re.fullmatch(r"[a-z][a-z0-9]*(-[a-z0-9]+)*", args.tool):
        problems.append("--tool is lowercase words joined by hyphens, such as kicad-cli")
    if not re.fullmatch(r"(@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*", args.package):
        problems.append("--package is an npm package name, such as @acme/kicad-cli")
    args.modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    if not args.modes or any(m not in ("file", "session", "device") for m in args.modes):
        problems.append("--modes takes file, session and device")
    args.platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]
    if not args.platforms or any(p not in NPM_OS for p in args.platforms):
        problems.append("--platforms takes windows, macos and linux")
    if not check_project.SEMVER.match(args.version):
        problems.append("--version is a SemVer version")
    if args.repo is None:
        scope = args.package.split("/")[0][1:] if args.package.startswith("@") else "owner"
        args.repo = f"{scope}/{args.tool}"
    if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", args.repo):
        problems.append("--repo is owner/name")
    if problems:
        parser.error("; ".join(problems))
    args.author = args.author.format(tool=args.tool)
    return args


def facts_for(args: argparse.Namespace, root: Path) -> check_project.Facts:
    facts = check_project.Facts(root=root, contract=check_project.load_contract())
    facts.package = {"name": args.package, "repository": {"url": f"git+https://github.com/{args.repo}.git"}}
    facts.tool = args.tool
    facts.pkg = args.tool.replace("-", "_")
    facts.prefix = args.tool.upper().replace("-", "_")
    facts.version = args.version
    facts.spec_version = check_project.bundle_version()
    facts.reference = {"driver": {"application": args.application, "versions": args.versions, "modes": args.modes,
                                  "host_component": args.host_component}, "commands": []}
    return facts


def copy_template(args: argparse.Namespace, root: Path) -> None:
    facts = facts_for(args, root)
    values = {**facts.variables(), "author": args.author, "year": str(datetime.date.today().year),
              "modes": json.dumps(args.modes), "host_component": str(args.host_component)}
    for source in sorted(TEMPLATE.rglob("*")):
        if source.is_dir() or "__pycache__" in source.parts:
            continue
        rel = source.relative_to(TEMPLATE).as_posix()
        if rel.startswith("plugin/") and not args.host_component:
            continue
        for key in ("tool", "pkg", "product"):
            rel = rel.replace("{{%s}}" % key, values[key])
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = check_project.read(source)
        except UnicodeDecodeError:
            shutil.copyfile(source, dest)
            continue
        text = check_project.render(text, facts)
        for key in ("author", "year", "modes", "host_component"):
            text = text.replace("{{%s}}" % key, values[key])
        dest.write_text(text, encoding="utf-8", newline="\n")
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    package["optionalDependencies"] = {f"{args.package}-{NPM_OS[p]}-x64": args.version for p in args.platforms}
    (root / "package.json").write_text(json.dumps(package, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for name in ("docs/APPLICATION.md", "docs/APPLICATION_zh.md"):
        path = root / name
        if path.is_file():
            keep = {OS_ROWS[p] for p in args.platforms}
            lines = [line for line in check_project.read(path).split("\n")
                     if not re.fullmatch(r"\| (Windows|macOS|Linux) \| x64 \|", line.strip())
                     or line.strip().split("|")[1].strip() in keep]
            path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    root = args.directory.resolve()
    if root.exists() and any(root.iterdir()):
        raise SystemExit(f"{root} exists and is not empty")
    root.mkdir(parents=True, exist_ok=True)
    copy_template(args, root)
    sync_spec.sync(root)
    check_project.fix(check_project.gather(root))
    problems = check_project.check(root)
    print(f"Generated {args.tool} in {root}, pinned to tool-driver-cli-spec {check_project.bundle_version()}.")
    left = [p for p in problems if p.clause == "DREPO-019"]
    commands = [p for p in problems if p.clause == "DREPO-061" and p.path == "contract/commands.json"]
    other = [p for p in problems if p not in left and p not in commands]
    print(f"Next: fill {len(left)} placeholder(s) and register the domain commands; `python scripts/spec.py check` lists "
          "what is left.")
    for problem in other:
        print(problem.text())
    return 1 if other else 0


if __name__ == "__main__":
    sys.exit(main())
