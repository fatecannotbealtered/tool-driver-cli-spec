# Host component

Use this file in steps 5 and 6 when the project was generated with `--host-component`: the survey found an interface that works only inside the application's process or on its main thread (DCLI-262).

Read: DCLI-240, DCLI-262, DCLI-270 to DCLI-281, DSEC-050 to DSEC-053.

## What to build

- The source goes in `plugin/`, in a language the application supports. Describe how it is built and loaded in `plugin/README.md`.
- It speaks the host protocol: a named pipe on Windows or a Unix socket elsewhere, for the current user only; `Content-Length` framing; `hello` first; the instance-side methods with their deadlines; `dispatch_state` in every write reply; calls to the application on its main thread, `E_BUSY` at once when it is busy; the list of external changes since the last save; only the host error codes of DCLI-279.
- An error the host recognizes, such as a known dialog, puts the IDs of the matching knowledge entries in `data.knowledge` (DCLI-279, DSKL-124).
- At start it writes a discovery file to `hosts/` in the state directory, and deletes it on exit (DCLI-271).
- Reference implementation: `<spec>/conformance/fakehost/`. `transport.py` opens the pipe or socket, `framing.py` reads and writes messages, `server.py` answers `hello` and the instance-side methods and writes the discovery files. The messages are defined in `<spec>/contract/schemas/host-protocol.schema.json`, the request and reply of each method in `<spec>/contract/schemas/adapter.schema.json`. When the release has a host library for your language, use it instead (DCLI-281).

## Manifest

`plugin/manifest.json` describes the host component (DCLI-240). Write only `methods`: the instance-side capabilities the host implements, such as `["documents", "open_doc", "close_doc", "save_doc", "read", "preview", "apply", "read_back"]`. `python scripts/spec.py generate` writes `version`, `protocol_version` and `files`, the SHA-256 of every file in `plugin/` except `manifest.json` and `README.md`. Run it after every change in `plugin/`; `python scripts/spec.py check` compares. The template already passes the manifest to the runtime, and `scripts/build.py` bundles `plugin/` into the native program. `plugin install` refuses files whose hash differs (DSEC-051).

## Session IDs

- The CLI-side adapter's `sessions` lists the running instances. Build each ID with `session_id(prefix, pid)` from `<pkg>._driver.adapter` (DCLI-203).
- The runtime overlays each host's state from the discovery files in `hosts/`, and sends instance-side calls to the host whose `hello` reply returned that `session.id`. The host MUST return exactly the same ID, or its instance gets no calls.
- A host running in an embedded Python can copy `start_time` and `session_id` from `<spec>/sdk/python/_driver/adapter.py`; they use only the standard library.
- A host in another language must reproduce `start_time` on each platform exactly as that file computes it: on Windows the process creation time in whole seconds of the `FILETIME`; on Linux field 22 of `/proc/<pid>/stat`; on macOS the first ten hex digits of the SHA-256 of what `ps -p <pid> -o lstart=` prints, trimmed. Test it against `session_id` on every shipped platform.

## Installing for live runs

`plugin install` is a two-step write with the `configure` effect, so it needs a scope the person wrote that allows `configure` (DSEC-050). It writes the state directory into the host's configuration (DCLI-271), so run it with the same `<PREFIX>_STATE_DIR` that the live runs use:

1. `python -m <pkg> plugin install`, then the same with `--confirm <token>`.
2. Ask the person to start the application. The tool never restarts or reloads a person's instance to load the host (DSEC-052).
3. Run `python -m <pkg> session list` and confirm that the instance shows `plugin_loaded` with the version on disk.

After a change in `plugin/`, run `generate`, install again and ask the person to restart the application; until then, writes to that instance are refused with `restart_application` (DSEC-053).
