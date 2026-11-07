# Scope and remaining work

Updated 2026-11-07, 21:30 KST, after the six fixes from the final three-model review (final code `9325ac3`). Live check: [qa/LIVE_SWITCH_REPORT.md](../qa/LIVE_SWITCH_REPORT.md). Tests: [qa/TEST_REPORT.md](../qa/TEST_REPORT.md).

## Current scope

- One room, one duty and one date: Monday, November 9, 2026, Asia/Seoul. The four people (Seoyeon, Minsu, Jian, Taeo) are built into `shiftpatch/roster.py`. Another team or date needs a code change there. Hours use 30-minute boundaries; overnight and multi-day shifts are refused.
- Four fictional accounts were driven by one operator. Live messages were posted through Mattermost's API as each synthetic account and read in the native channel. No working support team participated.
- The board opens on the host Mac only. It has a localhost Host check and a per-process token for writes; no remote staff login or membership checks.
- CSV/ICS files are local snapshots. They do not sync a calendar or upload themselves into the chat. ICS event UIDs include the snapshot version, so importing two snapshots into one calendar can leave the older events in place. ICS writes a 24:00 end as 00:00 of the next day; the file content is tested, but no calendar client imported it.
- A roster can be imported, and account links changed, only before coordination starts.

## Delivery and connection

- Replies are delivered at least once, not exactly once. If ShiftPatch stops after Switch accepted a reply but before marking it sent, that reply is posted again once its 60-second lease runs out. The Switch message endpoint has no idempotency key we could use.
- A reply that fails six times is parked and shown on the board with a send-again button; later replies in the room continue, so a resent reply can arrive after newer ones (it is marked "Delayed reply").
- Malformed frames, a non-integer sequence or cursor, and 15 silent seconds trigger a reconnect from the processed cursor. These, reconnect, gap, eviction and handler-failure halt are tested against fake sockets and the contract double only. None was triggered on a live server.
- A message that fails five times halts the bridge before its sequence is acknowledged. Restart ShiftPatch to replay it; there is no button for this.
- An export interrupted by a stopped process gets a closing "did not finish, send export again" reply at the next start. The export itself is not retried automatically.
- Which question a `yes`/`no` can answer is decided by the platform's message timestamps: a reply written before the message a question is about leaves that question alone. This is tested with chosen timestamps. How Switch's delivery sequence relates to those timestamps was not measured; two messages with the same millisecond, or a platform clock that jumps, are not handled specially.
- The local demo room handles one message at a time per room. Up to 8 can wait; more are refused with `DEMO_ROOM_BUSY`, and a message that cannot start within 180 s is refused too. Its text then stays in the transcript without a reply.
- On Ctrl-C or SIGTERM a reply that is being sent gets up to 15 s. If it is still running, the stop line says so and the process exits anyway; that reply follows the at-least-once rule above.

## Setup

- `manage.py register-agent`, `set-room`, `senders` and `link` ran against local Switch 0.31.0 on 2026-11-07 in four runs (`a70ae7e` and `9325ac3`); `import-links` ran in the earlier check. `manage.py set-addressing anyone` got HTTP 403 each time; the room's addressing rule was set in the Gateway instead. The wrapper exits with an error and says so.
- The manager links each person from one real message: `manage.py senders` lists the sender IDs that reached the agent unlinked in the last hour, and `manage.py link` accepts only those. Self-linking is not implemented. The list keeps the ID, display name, times and a count, not the text.
- Mattermost must be opened at its configured SiteURL (`http://localhost:18065` in the check); its WebSocket origin check rejects the 127.0.0.1 form.
- Managed/cloud Switch and other chat platforms were not tested. OCR was tested on simple synthetic table images on macOS, not camera photos with perspective or handwriting.

## AI and messages

Free-form text is interpreted by an already signed-in Claude CLI. The sender must confirm before the suggested action applies. A small synthetic check matched 7/7 cases, the browser trace of the AI script passed 6/6 on 2026-11-07 (code `9325ac3`), and the earlier live run at `c65b2ec` included real model calls. None of this is an accuracy estimate for a working team. With AI off, the demo script uses exact commands.

The application stores structured actions, a body hash and its own replies, not people's messages. Chat history remains in Switch/Mattermost under their normal storage. The local demo transcript is in memory and clears on restart.

## Before submission

The source, the review package and an English demo video cut from the recorded live run of `9325ac3` are prepared locally. There is no public GitHub repository, no YouTube or Loom URL and no submission. The entrant enters the form manually under the official rules. MIT is the prepared license and should be confirmed before publication.
