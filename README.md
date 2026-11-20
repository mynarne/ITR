# ITR · Is This Real?

[English](README.md) · [한국어](README.ko.md) · **1.0.0-rc.2**

When an AI agent reports that a change is complete, which requirements have actually been verified? ITR is an independent software QA skill for answering that question. Before a run, it pins the product revision, goals, selected skill rules and project requirements. Each check names the requirement it covers, what must be observed for it to pass, and which environment can produce that evidence. Agents can share the local record without using the same model or running a server. Times are displayed in KST (UTC+09:00).

![A stick figure studies the letters AI, resting its chin on one hand and holding a blue magnifying glass low in the other](assets/itr-mascot-aligned.svg)

[Open the offline replay](examples/preview/replay.html) · [Read the PDF from the same attempt](examples/preview/report.pdf) · [RC.2 follow-up verification](docs/verification-rc2-followup.ko.md) · [Prior RC.2 verification](docs/verification-rc2.ko.md) · [Skill instructions](SKILL.md)

## What a verification round tells you

The stage map follows checks from unit through integration, system and acceptance scenarios, with system-to-system integration where relevant. Lanes show the stage and review role. Select a failed check to see the requirement it missed and follow the saved log or available capture. The project runner groups failures by the plan's predeclared fingerprint, with one group per check by default. Cause and hypothesis start empty. The generated fix and regression text are prompts for the reviewer.

Inspection and execution have distinct results. An unsupported device can leave a check **blocked**, and an out-of-scope check remains **not run**. The report counts both separately from passes and failures. A precision run covers the wider product scope. A delta run follows a change, its dependencies and relevant past defects. Keep the authorized person's acceptance in a separate record.

Each round and each retry or correction gets a new attempt directory. To share an attempt, render its sealed `record.json` to a fresh output directory such as `reports/round-0001/attempt-0002/`. The renderer creates `report.md`, `replay.html` and `print.html` from that record. The optional PDF export writes a new `report.pdf` beside them. Previous reports and the evidence behind a failed or interrupted attempt stay available.

## First run from a clean ZIP

Extract the archive and open a terminal in the directory containing `VERSION`. The runner, live observer and renderers use Python 3.9+ and its standard library. On Windows the launcher may be `py -3`.

1. Inspect the small, local inventory project's checks. Read the listed files and arguments, the expected output markers and the snapshot's `approval_sha256`.

   ```sh
   python3 tools/project.py inspect --workspace examples/project --plan examples/project/plan.json
   ```

2. Replace `COPY_REVIEWED_SHA256` below with the digest **you reviewed**. Approval binds the project location, exact plan, listed source bytes, tools and capabilities. Moving the project or changing a pinned input requires a new inspection.

   ```sh
   python3 tools/project.py run --workspace examples/project --plan examples/project/plan.json --approve COPY_REVIEWED_SHA256 --store itr-runs --round 1 --require-pass
   python3 tools/project.py verify itr-runs/round-0001/attempt-0001/record.json
   python3 views/render.py itr-runs/round-0001/attempt-0001/record.json --out my-first-report
   ```

   The two selected quantities, 5 and 2, pass. Open `my-first-report/replay.html` to inspect the evidence. For the zero-stock defect, inspect and approve `plan-defect.json` separately. In the same store, use `--round 2 --previous round-0001/attempt-0001/record.json`. The boundary check expects `empty` and observes `low`. With `--require-pass`, a completed run that fails its technical gate exits with code 3.

3. To watch the next run, start the observer in a second terminal **before** starting the runner. Open `itr-progress/index.html` locally. No server or listening port is needed. Choose a new output directory for each observer and point it at the runner's store.

   ```sh
   python3 tools/progress.py --store itr-runs --watch --out itr-progress
   ```

   When a Windows reader holds the index open, the observer continues to read the journal and retries publication. Terminal states already observed wait their turn. Ctrl+C and `--once --out` allow up to two seconds to publish before returning exit 2 for a stale index. For a single machine-readable snapshot run `python3 tools/progress.py --store itr-runs --once --json`. The live view polls, so a short-lived state may finish between reads. The sealed replay retains the event sequence. A stalled or interrupted attempt never acquires a passing decision.

## Approve a real project test

Use [the project plan schema](schemas/project-plan.schema.json) and [the example manifest](examples/project/plan.json). For an actual test of **ITR itself**, use `--workspace . --plan examples/itr-selfcheck.json` with a fresh store in the commands above. This invokes the shipped schema validator and ITR's actual regression suite.

- List the source, test and fixture files in `files`, relative to the project root. Declare the requirements, baseline versions, selection, role, method, required capabilities and observable pass condition for every check.
- For a check's trusted local executable, register an argument array in `commands` and specify its timeout. Use the optional literal `pass_marker` for a runner that may exit successfully with zero tests discovered. The runner looks for the marker in the full decoded stdout stream. If the exit code itself is the oracle, the plan may omit the marker.
- Each selected check gets a fresh copy of the listed files. The runner launches the approved command directly with a minimal environment. Only register trusted tests. File copying and a clean environment do not isolate the program from the host filesystem or network.
- Exit 0 is pass under the check's contract, exit 1 is fail, and exit 77 is not run. Timeouts, missing required capabilities, unsupported exit codes and unconfirmed required markers block the check. Evidence records the exit code, timing, bounded stdout/stderr and truncation indicators. Technical gate precedence is failed, blocked, not run, then passed. Customer acceptance is a separate human decision.
- `--retry` links a new attempt in the same round; `--corrects` requires the original record path and a reason. A new revision belongs in a new round linked by `--previous`. Keep interrupted attempts, including any evidence already written.

Both streams default to UTF-8. Use `"output_encoding": "cp949"` for a command that emits CP949 bytes. Each retained decoded prefix starts with at most 64 KiB of raw stream data. A match beyond that prefix is recorded as `stdout_marker_excerpt`, with the matched text (at most 256 UTF-8 bytes) and its zero-based decoded character offset. Byte counts and truncation flags describe the original streams. For full logs, run a separately approved capture; the local runner stores bounded excerpts. By default a `{python}` child runs in UTF-8 mode (`-X utf8`), so `open()` also defaults to UTF-8. [Project evidence 2.0](schemas/project-evidence.schema.json) stores `launch_argv`, the arguments passed to the process launcher. The field is `null` when the check blocks before the call. RC.1 and original RC.2 evidence still verify under their original rules and show that actual arguments were never recorded. Review local evidence before sharing it because it can contain actual executable paths and arguments. `"output_encoding": "cp949"` selects the decoder and turns off automatic `-X utf8` for `{python}`. The child's actual locale still depends on its environment and command.

On Windows, use `{python}` with `-m pytest` or a trusted absolute `.exe` (for example, Node with an explicitly listed local test script). A bare executable name resolves on the controlled path (Python's directory and Windows System32). Batch wrappers and the user's PATH are outside that interface. The runner supplies task-local `TEMP`, `TMP` and `TMPDIR`, with no inherited user profile, APPDATA or credentials. Only the listed files, at most 64 MiB total, are copied. Virtual environments and installed dependencies are not copied with them. RC.2 binds the execution policy to approval; inspect again before running. Use a linked correction with a reason or a new round to follow an RC.1 attempt when approval has changed. `itr.py`, `project.py`, and `progress.py` write UTF-8 when redirected. In Windows PowerShell 5.1, set `[Console]::OutputEncoding = [Text.Encoding]::UTF8` before capturing output into a variable or pipe. For a UTF-8 text file, use `| Set-Content -Encoding UTF8 result.txt`. This adds a BOM in Windows PowerShell 5.1, and `>` follows separate encoding rules. Inspect again before a new run because evidence 2.0 changes the approval digest.

## Automated runner and reviewer responsibilities

- The runner aggregates command outcomes by role. The bundled demonstration illustrates the six roles. For independent review, assign separate reviewers or isolated sessions with only their allowed inputs. Preserve first verdicts before sharing them with an integrator.
- Record confirmed causes, hypotheses and acceptance as separate reviewer or human records linked to the sealed record's SHA-256. The CLI creates neither annotations nor stakeholder approvals. The ANDA adapter and its Notion and Discord delivery are designs.
- The local capability probe covers `local_command` and the current supported OS label. A browser, simulator, or device requires a separate adapter. `verify` checks internal consistency and never reruns commands. For independent evidence, use an authorized operator and anchor the sealed digest separately under their control.

## Compatibility and reproduction

| Area | Evidence |
|---|---|
| Linux x86_64, Python 3.12 | Executed local project checks, ITR's own tests, integrity verification, interruptions and concurrent writers. See the RC verification report for results. |
| Browser | Replay and live-map behavior tested using a DOM test double. The actual Chromium launch was blocked by the host's socket policy before navigation; pixel layout, mobile rendering and animation frames remain unverified. |
| Other operating systems and AI clients | The JSON contract, capability selection and adapter design are portable. Linux simulations cover Windows sharing failures and CP949 output. The native Windows reader-lock test runs only on Windows. macOS, devices and independent third-party AI sessions were outside this cloud run. |
| Reporting and integrations | Markdown, self-contained replay, print HTML and an actual PDF were checked. Only optional PDF generation/QA needs PyMuPDF. The optional ANDA adapter design calls for separate authorization after first verdicts are sealed. |

```sh
python3 -B qa/check_project.py
python3 -B qa/check_progress.py
python3 -B tools/check_itr.py
python3 -B qa/check_views.py examples/runs/round-0001/attempt-0001/record.json examples/preview --pdf
node qa/check_replay.cjs examples/preview/replay.html
```

The first three commands use the standard library. Generate a fresh PDF with `python3 qa/print_pdf.py my-first-report/print.html my-first-report/report.pdf`. The optional local Playwright/Chromium visual check is `python3 qa/check_browser.py examples/preview/replay.html --out NEW_BROWSER_QA`.

## Standards and handoff

[Assessment design and official ISO summaries](docs/assessment.ko.md) map ISO/IEC 25010:2023 to product quality, 25019:2023 to quality in a specified context of use, ISO/IEC/IEEE 29119-1 through -4 to testing concepts, processes, documentation and design techniques, and ISO/IEC 20246 to work product reviews. ISO/IEC 25040 is an optional evaluation framework. Record each standard's applicability and rationale in the plan. These mappings guide evaluation and make no certification claim.

[Canonical record schema](schemas/record.schema.json) · [Storage and adapter design](docs/architecture.ko.md) · [Release gates](docs/gates.ko.md) · [Source and publication checks](docs/release.ko.md). Security quality checks in this package are limited to defensive source and configuration review.
