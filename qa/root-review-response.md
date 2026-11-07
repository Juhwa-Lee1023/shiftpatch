# Response to root review (findings at 2026-11-07 17:03 KST)

All four findings are valid and fixed in `app/`. No servers, containers or runtime files were touched, and nothing was installed, pushed or uploaded.

| ID | Fix | Test |
|---|---|---|
| R01 | `switch_bridge._work`: after 5 failed attempts on one sequence, `_halt` stops the bridge. It sets state `halted`, keeps the cursor before the failed sequence, closes the socket and stops reconnecting. Later queued frames are never handled, persisted or ponged. `status()` names the failed sequence and says to restart. Related gap, also fixed: with no prior cursor, the head cursor from `connection_state` was kept only in memory. After a failure on the very first message, a restart would have opened at `head` and skipped it, so that cursor is now persisted. | `test_switch_contract.test_persistent_handler_failure_halts_before_later_sequences`. Head 10, seq 11 always fails, seq 12 valid. Result: halted, cursor and DB stay 10, version unchanged, no pong for 11/12, no reconnect. A restart opens with `start_from=10`, and the replayed 11 and 12 each apply once (gaps 09–17). On the old code this test fails at the `halted` wait. |
| R02 | `agent.board_link` adds `?room=<url-encoded id>` to the board URL. It replaces any existing `room` and keeps the `#/board` fragment. `status_text` uses it. | `test_switch_server.test_status_reply_links_the_same_switch_room` checks the real reply posted through the App and contract double: `http://127.0.0.1:0/?room=%21room%3Alocalhost#/board`. `test_board_link_replaces_room_and_keeps_fragment` covers the replace case. |
| R03 | `web/app.js`: new `iga()` helper picks 이 or 가 from the last syllable's final consonant. Non-Hangul names such as ShiftPatch get 가. It is used for roster import, accepted, acceptance withdrawn and confirmed history lines. | `test_web_text`: no `${who}이` left, and four call sites use the helper. The extracted helper runs under Node (no browser) and returns 태오가, 지안이, 민수가, 서연이, ShiftPatch가. |
| R04 | README: removed the BLOCKED banner, added one verification table, added a Switch setup section that says root registered the agent outside `manage.py`, and fixed the board link format. Also updated: KNOWN_ISSUES, STORY, DEMO_SCRIPT, TEST_REPORT and STATUS.json. The connection page now says an unconfigured instance has no Switch config, instead of saying Switch never ran. New: [LIVE_SWITCH_REPORT.md](LIVE_SWITCH_REPORT.md), a sanitized summary of root's trace with no keys, passwords, tokens or ids. | doc review only |

## Tests actually run (this pass)

- Targeted: `cd tests && python3 -m unittest test_web_text test_switch_server test_switch_contract -v`. 15 OK, 15.1 s.
- Full suite, once: `python3 -m unittest discover -s tests`. **89 OK**, 24.1 s, exit 0. That is 84 earlier tests plus 5 new.
- Not run: browser E2E, the AI checks, any UI automation, and any live Switch run. Root owns those.

## Limits that remain

- Root's live trace ran on the code **before** these fixes. R01 and R02 are verified only against the contract double. Root's 8766 server and the 8765 dev server still run the old code until someone restarts them.
- Recovering from a halt needs a manual restart of ShiftPatch. There is no retry button and no chat notice.
- `manage.py register-agent` and `set-addressing` are still untested. The docs call them manual instructions.
- Korean particles after proposal and part ids in `messages.py` (for example `P2은`) were not changed. That falls outside R03, which is about names.
- Still required and missing: a public GitHub repo and a demo video under 3 minutes (YouTube or Loom, public or unlisted). There is no real staff trial, no public deployment and no managed/cloud Switch test. Final submission is manual, by the user.

## Changed files

`shiftpatch/switch_bridge.py`, `shiftpatch/agent.py`, `web/app.js`, `tests/test_switch_contract.py`, `tests/test_switch_server.py`, `tests/test_web_text.py` (new), `README.md`, `docs/KNOWN_ISSUES.md`, `submission/STORY.md`, `submission/DEMO_SCRIPT.md`, `qa/TEST_REPORT.md`, `qa/STATUS.json`, `qa/LIVE_SWITCH_REPORT.md` (new), `qa/root-review-response.md` (new).
