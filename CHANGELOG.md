# Changelog

All notable changes to tool-driver-cli-spec are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `job get --output <path>` writes a job, its result included, to a new file, so a result longer than one response is no longer lost (DCLI-008, DCLI-220).
- `{workspace}` in a question's scope targets stands for the Agent's workspace, for a file the Agent makes and then looks at, such as a rendered picture (DSKL-044).

### Fixed

- `--fields` on a read that runs as a long job left out its `job` handle, so the job could not be followed. `--fields` now always keeps it (DCLI-007).
- `reference` could not list a tool with many commands within 8000 characters. When the summaries do not fit, the index lists the paths alone and `summaries` says how to get one command's description (DCLI-031).
- A document path whose backslashes a POSIX shell removed, such as `D:projectsboard.pcb`, gave only "no document". The error now says so and asks for forward slashes (DCLI-011).
- A scope target written from `{documents}`, such as `{documents}../work`, passed `run_eval` but stayed literal in the report, so `check_project` refused the report (DVER-050); and `run_eval` did not check where such a target led. Targets written from `{documents}` or `{workspace}` are now resolved, must stay inside the workspace root, and the report lists only the targets outside it beside the root.
- The report checks of the worked examples missed "the part and the drawing are both saved", `都存了盘` and other ways of saying it, and took "Nothing was saved" for saved.

## [1.2.0] - 2026-11-09

Shared text follows each release, and fixes from the KiCad, Creo and Xpedition tools on 1.1.0. After syncing, `check` names each section whose shared text lacks its `driver:spec-` markers: put the markers around that text as the template shows, move the tool's own lines outside them, and run `python scripts/spec.py generate`; this is needed once. Evaluation results get a new fingerprint, without the Skills' version and the adapter's code, so the questions run once more on 1.2.0 and then stay current across releases and adapter fixes. Anything that reads a batch's items finds each one's `result` there.

### Changed

- Text every tool shares, such as the write recipe, the STOP checkpoints and the driver playbooks of the entry Skill, the sections of `CONTRIBUTING.md` and parts of the README, `SECURITY.md` and `docs/E2E.md`, now sits between `<!-- driver:spec-<name>:start -->` and `<!-- driver:spec-<name>:end -->` markers. `generate` writes it from the pinned release, also when `python scripts/spec.py sync` moves the pin, and `check` reports a region that is missing, edited or moved out of its section (DREPO-036). The lines of the markers do not count against the 150 lines of a Skill. Before, a release changed this text only in the template, `sync_spec` listed the file, and `check` passed while the project kept the old text. A tool's own text goes outside the markers. `sync_spec` no longer lists a file whose only changes are inside such regions.

### Fixed

- Every release made every evaluation result stale, because the fingerprint of a result covered the `version` in the Skills' front matter, which each release changes; and any fix in the adapter's code did too. A result's fingerprint now leaves out that version and the adapter's code: it covers the question, the commands it lists as `reference` describes them, and the handwritten Skills and knowledge (DSKL-043). Live runs still follow the adapter's code (DVER-043).
- `run_matrix` ended the call of a long job's `job get --wait 600s`, and of a row paused longer than 300 seconds, after 300 seconds, so the row had no result. It now waits as long as the tool may wait.
- When the tool ended its pause before the read-back early, `run_matrix` stopped a `--tamper` command still running, which could leave the application half changed. The command now finishes its steps; one still running 300 seconds after the row ended is stopped, and the row's notes say so.
- A batch returned only each item's code, so what a change produced, such as what a moved track end connects to, was lost; `operation get` of an item gave only its receipt. Each item that succeeded now carries its `result`, as a call for that object alone returns it, and its record keeps it; when the results do not fit in the response, `more_results` names the `operation get` command that gives them (DCLI-064).
- `reference` marked a parameter `required` although `--input`, or `--ids` for `--id`, gives it instead, so an Agent added it beside `--input` and the call was refused. Such a parameter now shows `required_without` with those flags (DCLI-031).
- The example of `reference` named `session list`, which a tool that works only on files does not have. It names `context` now.
- The fake host gave every call a fault matched the same injected value, so a value changed in one reply changed the next ones.
- A flag of a mode the command does not work in, such as `--session` for a command that works only on files, got the hint of a flag with a near name, such as `--json`. The error now says which modes the command works in, and for a command that works on files, to name the file with `--doc`.
- `spec.py sync` listed the template files that changed only in the run that moved the pin; a second run said nothing. `spec.py sync <version> --since <earlier version>` lists them again, and a run that changes nothing says so.
- A save read back the fields of an object that a later write in the same session deleted, such as a note created and deleted before the save, and failed with `E_VERIFY_FAILED` although the document was right. A target whose last change deletes it is now checked only for being absent (DCLI-057).
- The verb table did not say where a computation that only reads goes, such as working out a routing plan. It is `run`, declared `observe` (DCLI-022).

## [1.1.0] - 2026-11-09

Evidence follows what it depends on, not the version number, from the Xpedition tool's 1.2.0 release. After syncing, new live runs and evaluation results carry fingerprints and keep counting across versions until the command, the adapter's code or the guidance they depend on changes. Records and reports written before keep counting for their minor version; run the matrices and questions once more to give them fingerprints. `python scripts/spec.py check` names what to run again, and `python scripts/spec.py eval --workspace-root <folder> --stale` runs only the questions that need it.

### Changed

- Evidence goes stale when what it depends on changes, no longer when the version number moves (DVER-043, DSKL-043). A live run carries a `fingerprint` of the command, by what changes what it does, and of the adapter's code and the Python packages it depends on; it counts while that matches, in any version. An evaluation result carries a `fingerprint` of its question file, the commands it lists as an Agent sees them and the tool's handwritten Skills and knowledge; the results of several reports count together, so stable needs every question's newest current result to have passed, not one run of all questions. `run_eval --stale` runs only the questions without a current passed result, and every run on the real application writes a report. Records and reports without a fingerprint keep counting while their tool version has the tool's major and minor version.
- `run_matrix --kind` keeps the `normal` row's evidence of each document kind in `kind_evidence`, so the newest run on each kind decides: an older pass no longer counts after a later run on that kind failed (DVER-030).
- `check_project` says why a row or a command's evidence does not count, such as a change to the adapter since the run.

### Fixed

- `scripts/spec.py` downloaded the release once, from one link. When GitHub answered that link with HTTP 504 for some minutes, every tool's check and release stopped. It now tries a failed download again after 2, 4 and 8 seconds, and then fetches the same file through the GitHub API; the bundle's SHA-256 is checked as before.
- `run_matrix` refused a live run that named no document, folder or device, even when the rows it ran used none, such as a row that takes only the session. It now asks only for the values the rows use; the record of such a run lists every authorized target, since its scope held them all.
- The English-only check of `CHANGELOG.md` also flagged a character quoted in code, such as the ideographic comma in `、`. Code spans are skipped now (DREPO-018).

## [1.0.10] - 2026-11-08

Fixes from the Creo tool's live run and the 1.0.9 release bundle. After syncing, a tool copies the long-job sentence of the template's entry Skill again, and anything that reads `job get` finds a failed job's error in `code`, `message` and `details`.

### Fixed

- The release bundle took every file in its folders, so the 1.0.9 bundle also held a local ruff cache, `template/.ruff_cache/`, and `sync_spec` listed its files as template changes. The bundle now holds only the files git tracks; tools ignore those cache files.
- A long job that ended with `ok: false` gave only its error code, so the Agent learned that a write such as a save had failed, but not why or what to do next. Such a job, write or read, now carries the error the call would have returned: `code`, `message` and `details`, such as `conflict`, `native_message`, `knowledge` and `next_action`, with the parts from outside the tool listed in `meta.untrusted`, also in the result of `job cancel`. A write job that changed nothing has spent its token, so a command to run in its `details` is the write's first call, never the worker's own call. A job a dialog stopped after dispatch carries `action`, `title`, `knowledge` and `resume` in `details`, as the call's error does, no longer beside them (DCLI-220).
- The receipt of a job noted the runtime's own words as "The application said: ...": a refusal the runtime made in the worker, a worker that ended without a result, and a job the runtime could no longer follow. Only the application's own words are noted that way now.
- `doc save` read back the changes since the last save without their tolerances, so a move that passed within its declared tolerance failed the next save with `E_VERIFY_FAILED`, although the file was saved. A save now compares each field with the tolerance of the command whose write left the value. The record of `doc undo` keeps the tolerances of the change it takes back, so `operation resolve` of an undo and the save after it compare the same way (DCLI-057). Conformance test D08 also saves after a write within its tolerance.

## [1.0.9] - 2026-11-08

Changes from the Xpedition tool's 1.0.8 release and the Creo tool's live run. After syncing, a tool whose application has several kinds of document lists them in `doc_kinds` of its `Tool` in `<pkg>/__init__.py`, where the template shows it. A tool that copied `_report.py` from the worked examples copies it again.

### Added

- A tool lists the kinds of document its application has in `Tool(doc_kinds=[...])`. `--kind` of `session open` and `doc create` then takes only those, `reference` shows them, and a wrong kind is refused with `E_USAGE` before anything starts. Before, `session open` started its long job first and failed with `E_VALIDATION` only when the job ran, so Agents read the exit code 0 as a started instance. A command's `doc_kinds` must be among the tool's (DCLI-029, DCLI-210).

### Fixed

- `operation resolve` settled a write only by reading changed fields back, so for a standard write with no such field, such as `session open`, `doc open`, `doc close` or `session close`, the `resume` and `lookup` it gave always failed once with `E_UNSUPPORTED`. A standard write is now settled by what it changes: `session open` and `doc create` in an instance by comparing the instances and documents with those there before it was sent, the others by the instances, documents, files, job or host component version now; a file the application wrote under a numbered name counts. `doc save`, which read back the fields it held and so found them whether or not the save happened, is now settled by whether the document is clean and its revision. An instance that is starting, busy or shows a dialog says so first. When the state does not tell the outcome, such as no new instance listed yet, resolve says so and never guesses (DCLI-035).
- Before the Agent's first question, `run_eval` checked the scripted `right` answer only on the fake host, so a question with `FAKE_HOST = None` reached the Agent unchecked. In a run on the real application, such a question's `right` answer now runs there first (DSKL-044).
- `run_eval --check` showed only the first failed check of each `wrong` run; it now shows all of them, so the author sees whether the run failed for the reason it was written for.
- `run_matrix` asked for `--kind` even for a command with a single document kind; it now uses that kind (DVER-030).
- The worked examples' `says_verified` accepted only a form of "verified", in English or Chinese, and failed reports that said the read-back matched in other words, such as "read-back confirmed all three changes" or "checked against the board". It now also accepts read-back agreement, and still fails its negations (DSKL-042).
- The template's `CONTRIBUTING.md`, `run_eval`'s help and errors and the specification said the evaluation workspace root must be listed under Authorized Targets; a folder inside a listed folder is enough, as `run_eval` already checked (DSKL-044, DVER-050).

## [1.0.8] - 2026-11-08

Changes from the live run of the Creo tool on 1.0.7 and from the release evaluation. After syncing, copy the entry Skill's new sentences from the template: the save sentences of the save playbook and the sentences on jobs that end with `E_HUMAN_REQUIRED`.

### Changed

- The save playbook says to save only when the person asks for it: a grant to change a document is not a request to save it. Otherwise the change stays unsaved and the report says so. Agents given a grant in chat saved the document as well, and widened their scope file to do it. The `granted_in_chat` question now also fails when the document was saved (DSKL-009, DSKL-040).

### Fixed

- A long write job that a dialog stopped after dispatch ended with `E_OUTCOME_UNKNOWN` and lost the dialog, so the Agent was not told that a person had to act and the `dialog` row of a long command could not pass. The job now ends as the call would: `unknown`, with `code` `E_HUMAN_REQUIRED`, `action`, the dialog's `title`, `knowledge` and `resume`, the `operation resolve` command (DCLI-066, DCLI-220). `job list` marks the title and the receipt's text as untrusted, and driver test D05 follows a long command to its end.
- `operation resolve` run while the dialog was still open answered `E_BUSY` and suggested recording the outcome by hand. It now returns `E_HUMAN_REQUIRED` with the dialog's `action` and `title`, and `resume` is the same `operation resolve` command (DCLI-066).

## [1.0.7] - 2026-11-08

Changes from the live runs of the Creo and Xpedition tools on 1.0.6, and authorization given once. After syncing, copy the template's new fixed texts: the Authorization Rules of `docs/E2E.md`, item 6 of `AGENTS.md`, the `scope.json` row of the State Directory table in `SECURITY.md`, and the two scope sentences of the entry Skill; the Procedure steps of `docs/E2E.md` and the Authorization section of `SECURITY.md` changed too. Delete the narrow scope files kept for `no_scope` rows, and any `actual` that `run_matrix` wrote for a crash. Check that the scope files for real work cover the documents that `session open --doc` opens and the documents open in an instance that `session close` closes. A tool with a host component runs `python scripts/spec.py generate`, which writes host protocol 1.3.0 into its manifest. An Authorized Targets entry that covers a whole drive or the home folder is now refused; replace it with the folders made for testing.

### Changed

- Authorization is given once. A folder listed under Authorized Targets is a work folder: inside it, the coding Agent makes practice copies, starts the instances it tests on and closes only those, and writes its own scope files that grant only listed targets, without asking. Live runs may use instances the coding Agent started, so `session open` and `session close` can run live. A target is added when the person's own message grants it, and the Agent reports the line it added. `check_project` and `run_matrix` refuse a target that covers a whole drive or the home folder (DSEC-011, DVER-050).
- `run_matrix` writes the scope file of each run itself: every effect, `dangerous` included, on the listed targets and on the new documents of the instance `--set session=` names. The `no_scope` row runs with no scope file, and a `<PREFIX>_SCOPE_FILE` in the runner's environment is not used (DVER-030).
- In real work, when the person's own message grants targets, such as "change anything in this copy", the Agent writes a scope file that holds only that grant, with `confirm: always` when the scope in force sets it, and tells the person what it wrote. It never changes or adds to a scope file it did not write for that grant, because a file's effects, `dangerous` and expiry apply to all its targets. A request to do a task is not a grant, and neither is a message relayed by another Agent. The `E_FORBIDDEN` snippet is now a scope file that grants just the refused write, ready to write as it is, with an expiry eight hours ahead and `confirm: always` when the scope in force sets it; `missing` still lists what the scope lacks. The new evaluation scenario `granted_in_chat` checks this (DSEC-011, DSEC-015, DSKL-008, DSKL-040).
- `session close` is covered only when the scope covers every document open in the instance, so a scope cannot close an instance that holds documents outside it (DSEC-014).
- `session open --doc` has the document it opens as its target, like `doc open`, so the scope file must cover it; without `--doc` only the effects count, as before. The specification now also says that `doc create --path` has the file it creates as its target, as the runtime already did (DSEC-014, DCLI-054).
- When the application writes a file under another name than the call gave, such as the numbered version `part.prt.1` for `part.prt`, the adapter lists it in `files` with `requested_path`, and the file counts for the given path; `doc create --path` and `doc save-as` failed verification on such applications before. Host protocol 1.3.0 adds the field (DCLI-057, DCLI-280).

### Fixed

- A success envelope over the size limit told the Agent to use `--limit` and `--output` whatever the command had, so `job get` sent the Agent to a flag it does not take, and after a write that ran it invited the Agent to send the write again. The `E_USAGE` now names only what the command offers: `--fields`, `--limit` for a list, `--output` for a read that has it, and `operation get --output` for a long job's record, which now holds the job's result; after a write that ran, it names the operation, or for a batch `operation list --batch`, and says not to send it again. A dry run's preview is shortened first, as a confirmation's is, and one that still does not fit asks for fewer objects (DCLI-008).
- `run_matrix` compared listed targets as percent-encoded URLs, so a target whose path has a space or a non-ASCII character, listed as the runtime writes it, was refused. A listed target now matches in either form (DVER-050).
- `run_eval`, `run_matrix`, `sync_spec` and `instantiate` stopped with `UnicodeEncodeError` when they printed a character the console code page lacks, such as `mm³` on a Windows set to Chinese; like `check_project`, they now print UTF-8.
- A long write's receipt named the document as it was when the job started, so in session mode the next `doc save` preview listed a change made outside the tool after every long write, and the entry Skill's STOP checkpoint stopped the Agent. The receipt now names the document as the job left it, for jobs in the runtime's worker and jobs the application runs. When the document cannot be read again after a write, long or not, the save skips the comparison for it instead of listing a change from outside, and the comparison uses the tool's last write that completed on the document in that session, not the last one planned. A receipt whose document was not read again keeps the revision from before the write with `dirty: null`, since the change may have made it dirty (DCLI-058, DCLI-061).
- `doc undo` undoes the tool's last completed write on the document in that session, long jobs included; a long job's write never counted as the last one before (DCLI-067).
- `run_matrix` asked `job get` again without pause, for up to an hour, when it failed; a failed `job get` now ends the row, and a busy one is asked again after `retry_after_ms` (DVER-030).
- `run_matrix` wrote `actual: {exit: 1}` for a run that failed with no error code, such as a crash, and the next run refused the matrix because the schema needs a code; an error code outside the contract had the same effect. Such a run now gives no actual result: the live record marks it failed, and the row loses its actual result and evidence, so it counts as not run (DVER-030).
- The `--tamper` command of the `read_back_mismatch` row inherited `<PREFIX>_TEST_PAUSE_BEFORE_READ_BACK`, so a tamper that called the tool paused itself and overwrote `pause.json`. It now runs without that variable, and `run_matrix` drops the variable from its own environment, so only the row's own call waits (DVER-030).

## [1.0.6] - 2026-11-07

Changes from the live runs and releases of the Creo, KiCad and Xpedition tools on 1.0.4 and 1.0.5. After syncing, check that the adapter's `sessions` returns within 2.5 seconds with one instance hung, and that a host component queues the tool's own requests for up to 1.5 seconds.

### Added

- A command whose change the application writes to the file at once, in session mode too, such as rules written straight into a project database, declares `persist` with `change`: it is two-step, its receipt reports `persistence: saved`, and the next save does not list it. The fake host writes such a change to the file at once, and the entry Skill says that a session change is unsaved while its receipt says `persistence: unchanged` (DCLI-051, DCLI-058, DSKL-009).
- Before the Agent's first question, `run_eval` runs on the fake host the scripted `right` agent of each question that has one and stops, naming the question, when that right answer fails, so no model credits go to a broken question (DSKL-044).

### Changed

- `docs/E2E.md` has a new first section, Authorization Rules, with fixed text from the template: who adds a target to Authorized Targets, how a target is written, and who writes the scope files for live runs and for evaluations on the real application. `check_project` compares it with the template and `generate` keeps it in step, so a change to these rules reaches every tool. Authorized Targets now holds only the list, one item per target, and `check_project` reports any other text there: copy the new section from the template and remove the old rules paragraph from Authorized Targets (DREPO-017).
- The 5 seconds of a session read are split: the adapter's `sessions` has 2.5 seconds (`session_read_deadline.adapter_sessions_ms`), and the runtime probes the host components meanwhile, connecting and reading the hello within 2 seconds together. Before, the probe came after the adapter's 5 seconds and could take up to 4 seconds more. An adapter in the CLI's process whose `sessions` takes longer than 2.5 seconds now ends the call, so it must ask the instances at the same time: check that `session list` returns within 2.5 seconds with one instance hung (DCLI-205).
- A host component runs one instance-side request at a time. A request that finds the main thread running an earlier request of the tool waits for it up to 1.5 seconds (`host_protocol.busy_wait_ms`) before it replies `E_BUSY`, because the tool's own requests often overlap, such as a long job's worker and a read the Agent runs meanwhile; `E_BUSY` comes at once only when the application itself holds the main thread, and `hello`, `cancel` and the `apply` of a halt command never wait. A host component that replied `E_BUSY` at once to any request that met another now queues it. The fake host does the same, and its new fault `slow` makes a call take longer (DCLI-276, DVER-020).
- An adapter reports a dialog as `busy` only when it knows the dialog comes from the tool's own running work, such as by a title that work expects; any other dialog makes the session `blocked` (DCLI-204).
- A long job's worker that meets `E_BUSY` before its dispatch tries again after `retry_after_ms`, for up to 10 seconds (`jobs.busy_retry_seconds`), before the job fails with `E_BUSY`; nothing was dispatched, so trying again is safe (DCLI-065).

### Fixed

- An `artifact` command that would overwrite a file no `output` flag names, such as a new document named by `--doc`, can be made two-step: the runtime registers `target_exists` for every `artifact` command, and the preview names it in `tier_raises` when the file exists. Before, such a preview was refused with `E_PROTOCOL`, and only output flags were checked (DCLI-051).
- A long job is read back on the same terms as a call: also when its reply reports no lasting effect but its preview or the files it names expect one. A host that reported an export with `persistence: unchanged` had its job end `completed` with verification `not_applicable`, even with the file missing (DCLI-057, DCLI-058).
- The error for a preview that cannot be applied no longer ends with two periods when a reason in `blocked_by` ends with one.
- On the real application, `run_eval` also stops when an Agent's Skill folder in the person's home, such as `~/.agents/skills`, holds a copy of the tool's Skill at another version: the tool keeps the person's home there, and its doctor would report the copy and tell the Agent to run `update` (DSKL-044).
- `sync` lists the template files that changed since the release pinned before even when that release is no longer in the download cache: it downloads the release first, checked against `.agent/SPEC_SHA256`. `scripts/spec.py` has the download as a function of its own.
- The onboarding guide and the error of `run_matrix` for a target that is not listed no longer say that only a person adds targets or writes the scope file; a coding Agent does when the person explicitly asks in their own message and agrees to what it shows (DSEC-011).

## [1.0.5] - 2026-11-06

A fix from syncing the Xpedition tool to 1.0.4.

### Fixed

- An `output` flag may name a folder that the command writes its files into, such as a set of fabrication files. Since 1.0.4 the runtime checked such a folder as a file and reported `E_VERIFY_FAILED` although every file was written. A folder counts as made when it holds a file or folder, the files in it are checked from `files`, and an empty folder does not raise the tier to two-step (DCLI-029, DCLI-051, DCLI-057).

## [1.0.4] - 2026-11-06

Changes from syncing the KiCad, Creo and Xpedition tools to 1.0.3.

### Added

- The scripts that are the same in every tool, `scripts/spec.py`, `build.py`, `pack.py`, `platforms.py` and `release_gate.py`, are pinned copies: `sync_spec` replaces them and `check_project` compares their hashes. `smoke.py` stays the author's. The template's AGENTS.md rule 1 lists them; `generate` updates it (DREPO-035, DREPO-034).
- `sync_spec` lists the other template files that changed since the release the project pinned before, with both template folders, when that release is in the download cache of `scripts/spec.py`, so the author can carry over changes such as those in `docs/E2E.md`. A file whose only change is fixed text that `generate` writes is left out.
- The `normal` row of a behavior matrix may give `kind_arguments`, the arguments for one document kind keyed by that kind, for a command whose objects differ between kinds; `run_matrix --kind` uses them and runs only the `normal` row on such a kind, and `check_project` checks that each key is one of the command's `doc_kinds` (DVER-030).
- `FAKE_HOST = None` marks an evaluation question that runs only on the real application, such as one that reads values from a real file; `run_eval --fake-host` skips it and says so (DSKL-044).
- The fake host gives a document the kind its instance was opened or it was created with, and an evaluation question's `FAKE_HOST` may give each file extension its kind with `kinds` (DVER-020).

### Changed

- A call of a command that makes a file only in some calls, and declares `artifact`, is verified by its other changes when it made no file: no file in `files`, in its preview or in an `output` flag. A file that an `output` flag or a file target of the preview names is checked even when the adapter does not report it, in a long job too (DCLI-051, DCLI-057).
- When `apply` has replied and only a read after it, such as the read-back, passes its deadline in the CLI's process, the runtime records the change with verification `incomplete` before the watchdog ends the process, for an item of a batch, whose later items are then skipped, and in a long job's worker too; the target is not left locked as outcome unknown (DCLI-278).
- An adapter looks for dialogs on every `sessions` call, also while the application answers its automation interface; a dialog the tool's own running work answers itself leaves the session `busy`. An adapter in the CLI's process keeps the session read limits itself (DCLI-204, DCLI-205).
- A read may report `E_CONFLICT` with `application_state` when the application's state stands in its way (DCLI-012). The runtime no longer turns a read's `E_CONFLICT` or `E_AMBIGUOUS` without `dispatch_state` into `E_PROTOCOL`: a read sends no change.
- `run_eval` lets Claude Code load only the tool's own Skills, and stops when a personal Skill of the same name differs from the project's, because Claude Code would load the personal one in its place.

### Fixed

- Several `run_matrix` runs of one matrix no longer overwrite each other's rows: each writes back only its own rows, under a lock, and records started in the same second get different names.

## [1.0.3] - 2026-11-05

Changes from syncing the KiCad, Xpedition and Creo tools to 1.0.2.

### Added

- The conflict value `application_state` for a conflict inside the application that no preview can report, such as `doc open` while another model of that name is open, or `doc close` of a model another one uses; `message` says what stands in the way. A domain command's preview still reports such a conflict with `can_apply: false` (DCLI-012, DCLI-279).
- A read result and the facts of a write may carry `notices`; the runtime puts them in `meta.notices` with the type `application` and marks their text untrusted, keeps one copy of a notice every item of a batch gives and at most five, and drops them first when an envelope is too long. Notices from a long job's worker are shown by `job get`. A tool that runs only in file mode adds the notice of DCLI-201 this way (DCLI-004, DCLI-260).
- A job the runtime runs shows as `blocked` while a dialog holds its session, with the `action` and `knowledge` of the session's blocker, in `job get` and `job list`. `job get --wait` returns when a job becomes blocked, whoever runs it, and `run_matrix` then waits for the person instead of asking again at once (DCLI-220).
- `{python}` in a `run_matrix --tamper` command stands for the interpreter `run_matrix` runs on (DVER-030).
- A coding Agent that prepares live runs may write the scope file and the Authorized Targets, and point `<PREFIX>_SCOPE_FILE` at that file, when the person explicitly asks in their own message and agrees to the content it showed (DSEC-011, DVER-050). The template's AGENTS.md rule 6 says so; copy the new text.
- An `artifact` command whose file the application names has no `output` flag; its preview names the file or the document it goes into, and its apply reports the file (DCLI-051).

### Changed

- A live record keeps the envelope as the tool wrote it: `check_project` no longer checks it against the current envelope schema, and `envelope_sha256` is accepted again, so records from 1.0.1 and earlier count as evidence again (DVER-042).
- The runtime refuses a `list` result without an `items` list with `E_PROTOCOL`, a long list's too, because `--limit` and `--offset` page the items (DCLI-006).
- A job has `finished_at` once it has ended; a running read job no longer shows `finished_at: null` (DCLI-220).
- The tool's own state directory and the host component copy that belongs to it are not authorized targets (DVER-050).
- The fake host makes its documents of the kind a test sets, and the suites set the first kind of a command registered with `doc_kinds`; an `artifact` command without an `output` flag makes a file the fake host names; a file that is not a fake host document opens as an empty document (DVER-020).
- D04, D09 and G04 follow a `doc save` listed in `long_commands` to its end. D08 and D26 cause the mismatch of a command that only makes files with a missing file. R04 reads with `--fields all` and can put its text into a list field such as `lines[*]`.
- The template's entry Skill tells the Agent what to do with a `blocked` job, and that a write job that ended with `E_BUSY` starts again from its first call.

### Fixed

- The `schema` of a `json` flag is exempt from the snake_case check of R04, like `output_schema`.
- A tool that cannot report itself gets only the DREPO-031 problem from `check_project`, without problems that depend on its modes or host component.
- The conformance suites repeat the failed tests and their reasons at the end of their output.
- `scripts/spec.py` writes `.agent/SPEC_SHA256` with LF, as do the build and smoke scripts of the template.

## [1.0.2] - 2026-11-05

Changes from rebuilding the Xpedition and Creo tools on the real applications, and a sweep that removes what no command or Agent acts on.

### Added

- Slow standard writes as long jobs (DCLI-065): a tool lists in `long_commands` the standard writes its application takes over a minute for, such as `doc open` of a large project or `session close`; the runtime runs them in its worker with the command's own checks and read-back, and `job get` returns their result, such as the new session.
- The session state `unreachable`: the process runs but the tool cannot drive it, such as a second instance when the application lets a tool reach only one. Writes are refused with `E_BACKEND_UNAVAILABLE` and nothing is sent (DCLI-204, D04).
- `session open --kind` starts the program that handles that kind of document (DCLI-206).
- The adapter names knowledge entries in a blocked preview and in a dialog's `blocker`; the runtime puts them in the error (DSKL-124).
- A receipt and a result list at most 10 produced files, missing ones first, and `more_files` gives the number left out and the `operation get --output` command that writes the whole record to a new file (DCLI-061).
- The sample placeholders `{job}` and `{inputs}` (DVER-002): `run_matrix` fills `{job}` from `--set job=` or a job it starts with `--job-from`; `{inputs}` is the project's `tests/inputs/`, whose files a command only reads need no authorization (DVER-050).

### Changed

- `doc save` checks that the save reached the file on disk: its read-back includes the document's field `saved`. When the application can read the saved file only after closing and opening the document again, the adapter reads the fields from the instance and reports `saved: true` only when it saw the file change (DCLI-057).
- Every list, domain lists included, pages with `--limit` default 20 and at most 100; the runtime adds `--limit` and `--offset` to every `list` command (DCLI-026).
- The installed host component lives where the application loads it, one copy per state directory where the application allows (DSEC-050).
- A coding Agent preparing live runs may propose the scope file and the Authorized Targets in chat; the person writes them (DSEC-011).
- The host protocol is version 1.2.0: `open_session` takes `kind`, a preview and a blocker may carry `knowledge`.
- Conformance R04 checks every read with untrusted fields, and a read of a whole document on a document-level field.
- Clauses that only repeated another now point to it: DCLI-085, DCLI-213, DCLI-261, DCLI-263, DSEC-033, DSEC-042, DSEC-054 and DSEC-060. The rule on `knowledge create` and `knowledge delete` lives only in DSKL-123.

### Removed

- From every envelope: `schema_version` and `meta.duration_ms`; `meta` appears only when it holds notices or untrusted paths (DCLI-003, DCLI-004).
- From previews: the `inputs` echo; the token still binds the inputs (DCLI-054).
- From `reference`: `effects` and `tier` in the index, and the fixed error list and `departures` in a command; adapter capabilities and evidence appear only in `reference --all` (DCLI-031).
- From receipts: `failed_stage`. From live records: `envelope_sha256`.
- From registrations: `adapter_capabilities`, which the runtime derives (a command whose application runs a job registers `jobs: true`), `survey_ids` and `departures` (DCLI-029).
- `knowledge/index.json`, and the knowledge fields `lang`, `based_on`, `updated_on`, `provider` and `added_at` (DSKL-120 to DSKL-122).
- The Skill field `metadata.requires` (DSKL-002, DSKL-024), and the COMPATIBILITY sections "Client and Host" and "Host Component Versions" (DREPO-016).

### Fixed

- A required flag left out returns `E_USAGE`, for standard and built-in commands too (`doc open`, `doc get`, `job get`).
- `run_matrix` ends the whole process tree on a timeout, and writes its files with LF.

## [1.0.1] - 2026-11-05

Changes from reworking three tools onto 1.0.0. Every change serves the same goals: fast, accurate and steady, and the Agent knows the result of a change from the structured return.

### Added

- DCLI-068: the result of a write shows what the change made, such as a track's end points, net and connections, with only the direct effects and nothing that takes long to compute. DSKL-011: Skills check results as data, never by recognizing a screenshot.
- Long jobs the runtime runs itself (DCLI-065): a command registered `long: true` returns a job at once and runs its work in a worker of the same tool, which claims the job once and runs the same checks before dispatch. A long read, such as a design rule check of a large board, needs no scope and returns its result through `job get`. A write job the tool runs cannot be cancelled midway (DCLI-221). Driver conformance test D26 checks it.
- Document kinds (DCLI-029, DCLI-210): a command lists the kinds of document it works on in `doc_kinds`. It refuses a document of another kind, and its normal row must pass on every kind (DVER-030, DVER-040). `run_matrix --kind` records the kind of each run.
- Verification after the save (DCLI-057): a command registered `verify_after_save` reports verification `deferred` in session mode, and the next `doc save` verifies it; closing without a save settles it as `not_run`.
- `doc create --path` and `--template`, in file mode too; with `--path` the file exists when the call returns (DCLI-212).
- The flag type `json` for structured values such as pad tables, and batch items of a `create` command without `id` (DCLI-029, DCLI-064).
- Conditions a command registers in `tier_when`, which the adapter's preview raises with `tier_raises` (DCLI-052).
- The adapter may answer `E_AMBIGUOUS`, `E_CONFLICT`, `E_BACKEND_UNAVAILABLE` and `E_TIMEOUT` (DCLI-279). The host protocol is now version 1.1.0.

### Changed

- The `read_back_mismatch` row is caused from outside: `run_matrix --row read_back_mismatch` makes the tool wait before its read-back, and a person or `--tamper` changes the result meanwhile (DVER-030). `run_matrix` now confirms two-step rows with their token and judges a long command by how its job ends.
- A file-mode write is refused while an instance has the file open only when it changes or saves the file; an export goes ahead, with a notice (DCLI-201).
- `dirty` may be `null` when the application cannot tell, and then counts as possibly unsaved (DCLI-210).
- The adapter and the host component mix capability by capability (DCLI-262).
- A write that makes files and changes a document verifies both (DCLI-057).
- `plugin/source/` is not installed. A vendor-built binary may be committed, with how it was built (DCLI-240).
- Clarified: hyphenated nouns (DCLI-023); what is irreversible, in file mode too (DCLI-051); the reference index (DCLI-031); flows that cross Skills belong in the entry Skill (DSKL-021); rename stubs do not apply to a rebuild from scratch (DSKL-028); instances the tool started itself (DSEC-052); `provided` counts standard commands (DREPO-060); where the schemas come from (DVER).

### Fixed

- `instantiate` no longer leaves `__pycache__` in the new project.

## [1.0.0] - 2026-11-04

### Added

- Five specifications, each in English and Chinese: DRIVER-CLI-SPEC, DRIVER-SEC-SPEC, DRIVER-SKILL-SPEC, DRIVER-VERIFY-SPEC and DRIVER-REPO-SPEC.
- The machine contract `contract/driver-contract.json`, twenty-one JSON Schemas (including the adapter payloads, behavior matrices, evaluation reports and command registrations), and valid and invalid examples for each schema.
- `scripts/check_spec.py`, which checks clause format, numbering, language pairs, cross-references, contract tables, schema enums, the clauses each conformance test checks, schemas and examples.
- `scripts/build_spec_bundle.py`, which builds the release ZIP with a manifest and prints release notes from this file.
- The fake host `conformance/fakehost/`, which stands in for the application in tests and is the reference implementation of the host protocol: a named pipe on Windows and a Unix socket elsewhere, Content-Length framing, the handshake, discovery files, a generic answer to domain commands and injectable faults.
- The Python driver runtime `sdk/python/_driver/`: the envelope, errors and limits, argument and unit parsing, command registration checks and tiers, the built-in commands, the session, document, job, device, plugin and knowledge commands, the whole write flow with scope, previews, confirm tokens, confirm-time review, records, locks, read-back, receipts, batches and long jobs, the CLI side of the host protocol and the fake host switch.
- The general and driver conformance suites `conformance/suites/`, and the sample tool `tests/sample/` they run against in CI, with and without a host component.
- `update` in the driver runtime: versions asked through npm with npm's own settings, the downgrade guard, moving the running program aside on Windows, npm run without a shell, the version check with a return to the earlier version when it fails, the provenance check through npm's registry signatures and attestations, direct command entries for cmd, PowerShell and Git Bash, and the sync of installed Skills.
- The project template `template/`: every root file and document in English and Chinese with its fixed text, the entry Skill, two knowledge entries, the Python package with an empty adapter, the npm launcher, scripts that build the native program, pack and check the npm packages, run platform delivery against a local registry and gate the release, and the CI and release workflows.
- The project scripts, which run from the release bundle: `instantiate` generates a tool project, `sync_spec` pins a release into it, `check_project` checks it and with `--fix` writes the generated content, and `run_matrix` runs a behavior matrix on the real application and writes the live record.
- `tests/e2e_template.py`, which generates, fills in, checks, tests, builds, packs, delivers and updates a tool from the template, and runs in CI on Windows, macOS and Linux.
- The evaluation suite `conformance/eval/`: one question for each of the eighteen scenarios, each with a grader and a right and a wrong scripted agent, run with the template tool on the fake host by `tests/eval_template.py`; CI checks on Windows, macOS and Linux that every grader passes the right agent and fails the wrong ones.
- The evaluation runner `scripts/run_eval.py`, which runs Python question files with Claude Code or with their scripted agents: a fresh workspace per question, the documents beside it, the tool on PATH behind a shim that records every run, and an evaluation report tied to each question file by its SHA-256. `check_project` checks the question files, and accepts a stable command only with the newest report from the real application that covers every current question, all passed.
- The development Skill `skills/build-driver-cli/`, shipped in the release bundle: it guides an Agent through the eight onboarding steps with the clauses to read, what to fill and the check to run, then reviews the tool against the specification; its reference files cover command registrations and behavior matrices, domain Skills and rename stubs, knowledge entries and evaluation questions. The onboarding guide `docs/ONBOARDING.md`, in English and Chinese, for a person who wants a new driver tool.
- Pointers from errors to knowledge: an adapter error with `knowledge=[...]`, or a host error with `data.knowledge`, puts the entry IDs in `details.knowledge` and the `knowledge get` command in `next_action`, also for write errors and dialogs after dispatch. The host component manifest `plugin/manifest.json`, whose version, protocol version and file hashes `check_project` writes, with the `methods` the author lists. Rename stubs name the Skill to read instead in `metadata.replaced_by`. `check_project` asks behavior matrices only for the standard commands whose adapter capabilities the tool implements.
- Check and release workflows for Windows, macOS and Linux.
