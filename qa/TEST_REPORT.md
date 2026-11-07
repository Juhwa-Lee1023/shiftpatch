# Test report — 2026-11-07 KST

Machine: macOS (Darwin 27), Python 3.14.5, Node 24.19, Google Chrome 157 (system install, driven by Playwright 1.56.1 `channel: "chrome"`), Apple Vision via `swift` interpreter mode.

| Command (run from `app/`) | Exit | Duration | Result |
|---|---|---|---|
| `python3 -m unittest discover -s tests` (root review pass, 17:08 KST) | 0 | 24.1 s (unittest-reported) | **89 tests OK**, 0 skipped. Console only, not saved to a log |
| `python3 -m unittest discover -s tests -v` (initial build) | 0 | 16.3 s | 84 tests OK. Log: `qa/unittest.log` |
| `node e2e/run.mjs` | 0 | 7.0 s (`qa/e2e-result.json`) | **10/10 steps**, 0 console errors |
| `node e2e/ai_trace.mjs` | 0 | see `qa/e2e-ai-result.json` | **5/5 replies** matched, real Claude CLI reader |
| `python3 qa/ai_live_check.py` | 0 | ~27 s total, 3.2–4.8 s per call | **7/7** suggestions matched expectations (`qa/ai-live.json`) |

Browser E2E and the AI checks ran in the initial build. They were not re-run after this pass's history-wording change in `web/app.js`. Runs are single runs, not repeated for flakiness. AI results are a small synthetic sample, not a quality measurement.

## What the 89 tests cover

| File | Count | Plan IDs / topics |
|---|---|---|
| `test_main_trace.py` | 2 | D01 main trace (only 13–15 reopens, Taeo kept, history kept, old plan re-confirm refused), D02 acceptance doesn't self-invalidate |
| `test_domain.py` | 19 | D03 withdrawal before confirm + partial preservation, D04 carry with visible link, D05 widened interval needs fresh acceptance, D06 changed facts block carry, D07/D08 confirm then partial inability, D09 inability then stale confirm, D10/D16 duplicate confirm and duplicate source, D11 adjacency, D12 clip to gap, D13 no candidate, D14 partial availability, D17 proxy/other's part, staff can't confirm, D20 revoke one acceptance, revoked consent never carried, revoke-after-confirm distinct from inability, D24 unknown refs, D25 reversed/overnight/non-30-min, wrong date, D26 160 random events keep invariants (no double coverage, contiguous, gaps consistent) |
| `test_pipeline.py` | 23 | X3 hedged → question only (rule reader), no → nothing changes, X4 two open confirmations need a number, X5 changed facts re-ask, expiry, others' confirmation refused, X2/D19 availability `yes` ≠ acceptance, X6 older/equal timestamp never overwrites, X7 future/stale timestamps, L03 ambiguous hour, C03 quote/forward/edit/bot marker, unlinked/not-addressed, D18/X1 context bound to message+actor and expiry, web actor can't reach Switch room, D15 injected failure rolls back everything then single retry, X8 reply failure + restart sends once without re-running state, L05 English, B08 message words absent from DB/WAL; fake-AI: suggestion needs self ack + context has no ids, proxy claim refused, AI can't point at another's part, clarify, L04 injection doesn't change roles; AI unavailable is stated |
| `test_roster_ocr.py` | 16 | import blocked without approval / without confirmed links, suggestion ≠ confirmation, no overwrite after events, roles never from file, validation flags (missing year, AM/PM, unknown name, collision, duty mismatch, formula-like, wrong date), two names one account, CSV bounds; file type/size/pixel bounds, unsupported layout; **real Vision**: clear+small read exactly (15/15 fields each) but stay unimported, ambiguous flagged, unknown name + collision flagged, unsupported layout refused, private temp 0700/0600 removed on discard |
| `test_export.py` | 6 | B01 CSV = board + version, B02 confirm committed during export cannot mix versions, B03 publish failure keeps state/no partial file then retry, chat export failure message, B04 formula neutralisation, B06 versions kept + ICS confirmed-only |
| `test_http.py` | 8 | token in page, B05 wrong Host 403, write without token / foreign Origin 403, unknown room 404, approval must be literal `true`, blocking issues, bad mapping; demo flow + export download, path traversal/unrecorded file 404, BLOCKED status; actor must be synthetic; upload bounds |
| `test_switch_contract.py` | 10 | **contract double, not live**: R01 persistent handler failure halts with the cursor before the failed sequence, later sequence not consumed or ponged, restart resumes from the head cursor persisted at connect and replays both once; health probe, open params (rooms, filter=addressed, start_from), pongs with processed cursor, addressed message → state + reply POST, safeguards (unaddressed, unlinked agent, auto_reply marker, own name, other room), reconnect with start_from/expected_generation/same connection_id + replay dedup, restart keeps id/cursor, gap → cursor + reply note, taken_over final, bad key 4401 stops, status hides key |
| `test_switch_server.py` | 3 | whole App wiring (config file → bridge → pipeline → outbox → POST) against the contract double; R02 status reply link is `/?room=<url-encoded room>#/board`; `board_link` replaces an existing room and keeps the fragment |
| `test_web_text.py` | 2 | R03 history uses the 이/가 helper; under Node the helper gives 태오가, 지안이, 민수가, 서연이, ShiftPatch가 (helper only, no browser) |

## Browser E2E steps (`qa/e2e-result.json`)

1. landing renders (ko + en) · 2. OCR ambiguous image flagged, approve disabled · 3. unsupported layout → fallback message · 4. clear image read exactly → links must be confirmed → approval checkbox required → board · 5. hedged inability asks first, `네` opens 13–17 · 6. AI-off notice, availability, proposal, proxy refused, confirm blocked until both accept, confirm · 7. downloaded CSV rows equal the board table · 8. Jian drops 13–15: only that reopens, Taeo kept, old plan refused, board rows exact, English board · 9. narrow viewport + connection page shows BLOCKED · 10. no console errors.

## Failures seen and fixed during the build (not hidden)

- duplicate result merged its old `status` over `"duplicate"` (test_d10)
- history detail keys `kind`/`version` collided with `log()` arguments (export tests)
- roster import wiped a Switch room's account links (contract tests)
- export list lacked its CSS class, so the download link wasn't found (E2E)
- CSP blocked inline `style` attributes; switched to CSSOM (screenshot console errors)
- table cell class collided with a landing-page class (visual check)
- connection page assumed Docker absent; a Docker CLI is on PATH, status wording corrected (visual check)

## Not tested

By this build agent: a live Switch server. Root ran both a baseline and a final corrected-source trace separately: [LIVE_SWITCH_REPORT.md](LIVE_SWITCH_REPORT.md). Also not tested: `manage.py register-agent` / `set-addressing` against a server; managed/cloud Switch; real phone photos; Python versions other than 3.14.5; browsers other than Chrome 157; concurrent multi-process writers (single process by design).

## Independent final-source verification

Root ran the full suite again after the correction pass: **89 tests, exit 0, 23.357 seconds reported by unittest**. See [root-final-unit.json](root-final-unit.json) and [root-final-unit.log](root-final-unit.log). Root then ran the final source through local Switch 0.31.0 and native Mattermost again: actual AI interpretation and self-confirmation, two availability replies, own-part acceptance, manager confirmation, partial inability, stale-confirm rejection and CSV download all completed. [Final live evidence](final-live-evidence.json).

Chrome through CUA independently checked OCR upload of a synthetic clear fixture, editable fields, account confirmations, required approval and import into the local fixture; native chat replies without refresh; the room-bound status link; actual CSV download matching its hash; and ICS generation. The CSV route initially returned 404 in the old long-running process. Reloading the corrected source resolved it, and both API and browser download succeeded. Mattermost browser WebSocket rejected a 127.0.0.1 origin; opening its configured localhost SiteURL fixed live updates without changing security settings.

The 77-second video was encoded from real browser captures. Full H.264 decoding and direct review of one frame from every scene completed. The MP4 is local; there is no video URL or contest submission.
