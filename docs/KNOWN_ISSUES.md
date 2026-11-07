# Scope and remaining work

Updated 2026-11-07. The final source completed the local Switch scenario after the review fixes; see [the live report](../qa/LIVE_SWITCH_REPORT.md) and [89-test result](../qa/root-final-unit.json).

## Current scope

- One room, one duty and one date: November 9, 2026, Asia/Seoul. Hours use 30-minute boundaries. Overnight and multi-day shifts are refused.
- Four fictional accounts were driven by one operator. The final trace uses native Mattermost sessions through real self-hosted Switch 0.31.0. Separate status/proposal checks were typed in the browser. No working support team participated.
- The companion board opens on the host Mac only. It has a localhost Host check and per-process token for writes; it has no remote staff login or membership checks. OCR draft image access is local and uses a random draft ID.
- CSV/ICS files are local snapshots. They do not sync a calendar or upload themselves into the chat. The ICS includes only existing/confirmed segments, not uncovered hours.
- A roster can be imported before coordination starts. Staff identities and roles cannot be changed during this one-day session.

## Connection and setup

- Reconnect, gap, eviction and forced handler-failure recovery are tested against the contract double, not deliberately triggered on the real server. A message that fails five times halts the bridge before its sequence is acknowledged. Restart ShiftPatch to replay it; there is no recovery button.
- The verified setup used a private-room addressing rule. The `manage.py register-agent` and `set-addressing` wrappers have not themselves run against the server; root registered the test agent separately. The import wrappers call the same roster/link functions used in the verified setup.
- The manager currently obtains opaque participant IDs from Switch probe events. Self-linking is not implemented.
- Mattermost must be opened at its configured SiteURL, `http://localhost:18065` for this setup. Its WebSocket origin check rejects the 127.0.0.1 variant. The ShiftPatch board uses 127.0.0.1:8766.
- Managed/cloud Switch and other chat platforms were not tested. OCR was tested on simple synthetic table images on macOS, not camera photos with perspective or handwriting.

## AI and messages

Free-form text is interpreted by an already authenticated Claude CLI. The sender must confirm before the suggested action applies. A small synthetic quality check matched 7/7 cases, and the final Switch trace includes a real model call; these are not estimates of accuracy in a working team.

The application stores structured actions and a body hash, not original messages. Native chat history remains in Switch/Mattermost under their normal storage behaviour. The local demo transcript is in memory and clears on restart. Equal/older timestamps from one person are refused conservatively and require a new message.

## Before submission

The source and 77-second local video are prepared. Public GitHub and public/unlisted YouTube or Loom URLs are still absent. No push, public deployment or upload has occurred. Final entry must be made manually by the entrant under the official rules. MIT is the prepared source license and should be confirmed before publication.
