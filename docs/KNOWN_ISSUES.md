# Scope and remaining work

Updated 2026-11-07 evening, after the review fixes and the socket/thread cleanup. Live check: [qa/LIVE_SWITCH_REPORT.md](../qa/LIVE_SWITCH_REPORT.md). Tests: [qa/TEST_REPORT.md](../qa/TEST_REPORT.md).

## Current scope

- One room, one duty and one date: Monday, November 9, 2026, Asia/Seoul. The four people (Seoyeon, Minsu, Jian, Taeo) are built into `shiftpatch/roster.py`. Another team or date needs a code change there. Hours use 30-minute boundaries; overnight and multi-day shifts are refused.
- Four fictional accounts were driven by one operator. Live messages were posted through Mattermost's API as each synthetic account and read in the native channel. No working support team participated.
- The board opens on the host Mac only. It has a localhost Host check and a per-process token for writes; no remote staff login or membership checks.
- CSV/ICS files are local snapshots. They do not sync a calendar or upload themselves into the chat. ICS event UIDs include the snapshot version, so importing two snapshots into one calendar can leave the older events in place; this was not tried with a calendar client.
- A roster can be imported, and account links changed, only before coordination starts.

## Delivery and connection

- Replies are delivered at least once, not exactly once. If ShiftPatch stops after Switch accepted a reply but before marking it sent, that reply is posted again once its 60-second lease runs out. The Switch message endpoint has no idempotency key we could use.
- A reply that fails six times is parked and shown on the board with a send-again button; later replies in the room continue, so a resent reply can arrive after newer ones (it is marked "Delayed reply").
- Malformed frames, a non-integer sequence or cursor, and 15 silent seconds trigger a reconnect from the processed cursor. These, reconnect, gap, eviction and handler-failure halt are tested against fake sockets and the contract double only. None was triggered on a live server.
- A message that fails five times halts the bridge before its sequence is acknowledged. Restart ShiftPatch to replay it; there is no button for this.
- An export interrupted by a stopped process gets a closing "did not finish, send export again" reply at the next start. The export itself is not retried automatically.
- On Ctrl-C or SIGTERM a reply that is being sent gets up to 15 s. If it is still running, the stop line says so and the process exits anyway; that reply follows the at-least-once rule above.

## Setup

- `manage.py register-agent`, `set-room` and `import-links` ran against local Switch 0.31.0 in the 2026-11-07 check. `manage.py set-addressing anyone` got HTTP 403 there; the room's addressing rule was set in the Gateway instead. The wrapper now exits with an error and says so.
- The manager obtains opaque participant IDs from one probe message per person. Self-linking is not implemented.
- Mattermost must be opened at its configured SiteURL (`http://localhost:18065` in the check); its WebSocket origin check rejects the 127.0.0.1 form.
- Managed/cloud Switch and other chat platforms were not tested. OCR was tested on simple synthetic table images on macOS, not camera photos with perspective or handwriting.

## AI and messages

Free-form text is interpreted by an already signed-in Claude CLI. The sender must confirm before the suggested action applies. A small synthetic check matched 7/7 cases and the live check includes one real model call; neither is an accuracy estimate for a working team.

The application stores structured actions, a body hash and its own replies, not people's messages. Chat history remains in Switch/Mattermost under their normal storage. The local demo transcript is in memory and clears on restart.

## Before submission

The source, the review package and a revised English demo video are prepared locally. There is no public GitHub repository, no YouTube or Loom URL and no submission. The entrant enters the form manually under the official rules. MIT is the prepared license and should be confirmed before publication.
