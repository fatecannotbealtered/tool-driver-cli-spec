#!/usr/bin/env node
"use strict";

// The launcher: runs the native program from the platform package npm installed for this
// machine. `{{tool}} update` points the command entry at the native program directly, which
// starts much faster; this launcher then stays as the fallback (DCLI-075).
const { spawnSync } = require("child_process");
const path = require("path");

const root = require("../package.json");
const tool = Object.keys(root.bin)[0];
const platformPackage = `${root.name}-${process.platform}-${process.arch}`;

if (!Object.prototype.hasOwnProperty.call(root.optionalDependencies || {}, platformPackage)) {
  process.stderr.write(`${tool} has no npm platform package for ${process.platform}-${process.arch}.\n`);
  process.exit(1);
}

let program;
try {
  const manifest = require.resolve(`${platformPackage}/package.json`);
  program = path.join(path.dirname(manifest), "bin", tool + (process.platform === "win32" ? ".exe" : ""));
} catch {
  process.stderr.write(`${tool}: the platform package ${platformPackage} is not installed.\n` +
    `Install again with: npm install -g ${root.name} --include=optional\n`);
  process.exit(1);
}

const result = spawnSync(program, process.argv.slice(2), { stdio: "inherit", windowsHide: true });
if (result.error) {
  process.stderr.write(`${tool}: cannot start ${program}: ${result.error.message}\n`);
  process.exit(1);
}
if (result.signal) {
  process.kill(process.pid, result.signal);
}
process.exit(result.status === null ? 1 : result.status);
