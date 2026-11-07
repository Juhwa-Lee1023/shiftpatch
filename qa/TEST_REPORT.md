# Test report — 2026-11-07 KST

Machine: macOS (Darwin 27), Python 3.14.5, Node 24.19, Google Chrome via Playwright 1.56.1 `channel: "chrome"`, Apple Vision via `swift`.

## Socket and thread cleanup (2026-11-07, 19:00–19:25 KST)

The 125-test runs below passed, but their logs also printed ResourceWarnings: twelve `Implicitly cleaning up <HTTPError …>` and, during the R02 test, two `unclosed <socket.socket …>`. A run with `-X tracemalloc` traced each one to where it was allocated. Every socket was the fake Switch's listening socket (`tests/fake_switch.py` called `shutdown()` but never `server_close()`), and every HTTPError came from `tests/test_http.py` reading an error body without closing it. The `agent.py:184` in the old log is only where garbage collection happened to run.

The same patterns were in production code, plus two more. Fixed in `9dd3a1b`:

- `switch_bridge._http` and `manage.post` close HTTPError bodies.
- `WebSocket.connect` closes its socket when the handshake fails. Before, every retried failed handshake left a socket for the garbage collector.
- The bridge's reader thread owns the WebSocket and closes it; `stop()` and the halt path only send a close frame and shut the connection down. With the old cross-thread `close()`, the reader stayed blocked in `recv` in 5 of 6 start/stop cycles in one process on this Mac. With the change, 12 of 12 cycles stopped at once.
- `SwitchBridge.stop` and `Dispatcher.stop` join their threads and return whether they finished. `run.py` now closes its listening socket and both threads on SIGTERM or Ctrl-C, then prints `ShiftPatch stopped`.

| Command (HEAD `9dd3a1b`) | Exit | Duration | Result |
|---|---|---|---|
| `python3 -m unittest discover -s tests -v` | 0 | 37.0 s | **136 tests OK**, no warning line on stdout or stderr |
| same with `-X dev -X tracemalloc=30 -W always::ResourceWarning` | 0 | 55.9 s | 136 OK, no warning line |
| same with `-X dev -W error::ResourceWarning` | 0 | 35.0 s | 136 OK, no `Exception ignored` line |
| the 37 socket/thread tests, `-X dev -W always::ResourceWarning`, three times | 0, 0, 0 | 29–30 s each | 37 OK each time, no warning line |
| `node e2e/run.mjs` | 0 | 11.0 s | **13/13 steps**; server exit 0 on SIGTERM, `ShiftPatch stopped`, stderr only request lines (ResourceWarnings on) |
| live smoke check: `run.py` with a new data dir connected to local Switch 0.31.0 as `shiftpatch2`, then SIGTERM | 0 | 8 s | connected in 4.1 s, 4 pings answered, nothing posted, stopped in 0.01 s, no stderr warnings; the demo instance on 8766 stayed connected with 0 reconnects |

The new file `tests/test_resource_cleanup.py` (11 tests) checks the resource itself: the socket fd after a refused upgrade, a wrong accept header and an early close; the HTTPError body after a 401 in `post_reply` and `manage.post`; the fixture's listening socket; that `stop()` joins and closes, including a reader blocked with no read timeout; that `App.close()` ends every thread; and that `run.py`, connected to the contract double, exits 0 on SIGTERM with nothing on stderr but request lines. Run against the pre-fix modules, 10 of the 11 fail. The fixture test passes there because the fixture stays fixed. The contract and app-wiring tests now assert in tearDown that `stop()` finished.

A Python warning is not proof of a production leak, and its absence is not proof there is none. These runs show only that this suite and the E2E no longer leave sockets, error bodies or threads for the garbage collector.

## After the review fixes (2026-11-07, about 18:30–18:50 KST)

Run from the repository root. Receipts with command, start time, duration, exit code and git HEAD are in the remediation folder's `deliverables/evidence/`.

| Command | HEAD | Exit | Duration | Result |
|---|---|---|---|---|
| `python3 -m unittest discover -s tests -v` | `f306c1c` (clean) | 0 | 33.9 s | **125 tests OK**: the 89 earlier tests and 36 new ones |
| `node e2e/run.mjs` | `f306c1c` (clean) | 0 | 11.7 s | **13/13 steps**, 0 console errors (`qa/e2e-result.json`) |
| `node e2e/ai_trace.mjs` | `f306c1c` | 0 | 16.4 s | **5/5 replies** matched, real Claude CLI reader (`qa/e2e-ai-result.json`) |
| critique reproductions re-run (`tools/rerun_root_reproductions.py`) | code of `f306c1c` | 0 | 1.2 s | all 10 cases now come out the corrected way |
| live local Switch check | code of `c65b2ec` | — | — | see [LIVE_SWITCH_REPORT.md](LIVE_SWITCH_REPORT.md) |

Single runs, not repeated for flakiness. The AI checks are a tiny synthetic sample, not a quality measurement.

Four earlier tests were edited. Three changed wording assertions because the replies changed on purpose: the first inability now says "is now uncovered" / "이 비었습니다" instead of "again" (`test_l05`, the contract-double reply test, the app-wiring test), and `test_l05` also expects the all-accepted reply to name the manager. `test_x8` now advances a clock between dispatcher passes, because a failed reply is no longer retried in the same instant. `tests/fake_switch.py` gained a raw-frame push and a silent mode for the new bridge tests.

### New tests (`tests/test_critique_regressions.py`, 36)

| Finding | What is checked |
|---|---|
| C01 clock times | `13:60`, `13:90`, end `14:75`, `15:60`, `24:01`, `24:30`, `25:00`, English `13:60` leave version, availability, proposal and history unchanged; `13:30` and end `24:00` still work |
| C02 ranged withdrawal | leading, middle, trailing pieces kept; the new proposal never reaches the withdrawn hour; disjoint range changes nothing; bare withdraw removes all; an earlier inability still cuts the remainder; reply lists what is left; the same rule through an AI-read message confirmed with `yes` |
| K_S1 question lifetime | 11- and 14-minute-late messages can be confirmed at once; closed 10 min + 1 s after receipt; the "until" label uses receive time; >15 min still refused with no question; ordering still uses message time |
| K_S4 relink | relink closes the open question, link revision rises above every earlier one, other links keep theirs, the new account's `yes Q1` / `yes` change nothing; a question stays bound to the account it was asked to even if a link row is swapped directly; an unchanged relink keeps the question |
| C08 / K_S3 outbox | five instant passes make one attempt; row 1 retried with 1/2/4 s backoff and delivered before row 2; overlapping passes on one dispatcher and two dispatchers on one file send each row once; six failures park the row as failed, later rows continue, the failed-reply view shows it, send-again delivers it once with a "delayed reply" note and no domain change; a crash after a successful send leads to a second send after the lease (documented at-least-once) |
| C03 export | an exporter raising OSError gets a failure reply with a retry instruction; redelivery stays a duplicate; a new `export` succeeds at the same version; folder-creation and snapshot-stage failures are reported, not raised; a restart closes an export that never finished |
| C09 bridge | malformed JSON reconnects from the processed cursor and keeps processing; a non-integer sequence never reaches the pipeline; a silent socket is not left "connected" and reconnects; the critique's mocked-socket case; frame parsing rules |
| KimiS5 accounts | a Switch room lists linked participant IDs and no `local:` accounts; an unlinked person blocks validation and import; the local room keeps its synthetic accounts |
| C06 text | new-proposal reply and `proposal` list real part IDs, no `?`; reopen says "다시"; the old-plan refusal says what changed; history keeps P2 confirmed with its cut; Korean particles; English AM/PM hint keeps the sender's verb |

### Browser E2E steps (`qa/e2e-result.json`)

1. landing (ko + en) · 2. OCR ambiguous image flagged, approve disabled · 3. unsupported layout falls back · 4. clear image → `local:` synthetic accounts labelled as such → links confirmed → approval → board · 5. demo script shows no placeholder; hedged inability asks first, `네` says the gap is new · 6. `13:60` refused; ranged withdrawal keeps the rest · 7. AI-off notice, proposal reply names the real part IDs, proxy acceptance refused, confirm blocked until both accept, confirm · 8. downloaded CSV equals the board table · 9. Jian drops 13–15: refusal explains the change, board shows "앞서 확정 · 13:00–15:00 다시 모집" next to "확정됨", rows exact, English board with "General customer support" · 10. a reply marked undelivered (synthetic database fault) shows on the board; **Send replies again** delivers it once; version and history unchanged · 11. a Switch-room record (no server behind it) shows the linked participant IDs, marks the unlinked person and blocks import until linked; then imports; the actor picker gets 403 for that room · 12. narrow viewport and connection page · 13. no console errors.

## Before the review fixes

| Command | Exit | Duration | Result |
|---|---|---|---|
| `python3 -m unittest discover -s tests` (root review pass, 17:08 KST) | 0 | 24.1 s | 89 tests OK ([root-final-unit.json](root-final-unit.json)) |
| `node e2e/run.mjs` (initial build) | 0 | 7.0 s | 10/10 steps |
| `python3 qa/ai_live_check.py` | 0 | ~27 s | 7/7 suggestions matched (`qa/ai-live.json`) |

## Not tested

Fault paths on a live Switch server (malformed frames, silent sockets, reconnect, gap, eviction, failed reply delivery) — fake sockets and the contract double only. Managed/cloud Switch. Real phone photos. Python versions other than 3.14.5; browsers other than Chrome. Concurrent writers from more than one ShiftPatch process beyond the outbox lease test. An ICS file re-imported into a calendar client.
