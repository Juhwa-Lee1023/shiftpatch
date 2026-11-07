# Live Switch run — local self-hosted, synthetic team

## Final corrected source: verified 2026-11-07 17:15–17:17 KST

The final source was run again after the review fixes. A new QA database preserved the earlier runs. Four synthetic Mattermost sessions posted through the real local Switch stack. The browser showed the replies without refresh at the configured Mattermost SiteURL, `http://localhost:18065`.

The final trace includes a real AI-read tentative message from Minsu, his explicit `yes Q1`, two availability replies, both self-acceptances, the manager confirmation, Jian’s later 13–15 inability, refusal of the old P2 confirmation and a CSV export. The first AI interpretation did not change the roster. The final board was version8 with only 13–15 uncovered; Taeo’s 15–17 and both original shifts remained. All12 replies were sent, and the CSV download returned HTTP200. A separately generated ICS contained three existing/confirmed segments and excluded the gap.

See [sanitized final evidence](final-live-evidence.json) and [independent 89-test result](root-final-unit.json). Actual browser captures were recorded for the local demo video. The operator drove the four fictional accounts by API; separate `status` and `proposal` checks were also typed through the native chat UI. No working support team participated.

The following section preserves the earlier baseline run. Its pre-fix limits describe that run, not the final verification.


Run on 2026-11-07, 16:58 KST, by the root operator. This was an independent run, separate from the coding agent's build. This report is a sanitized summary: it contains no agent API key, no account passwords, no session tokens and no room, agent or post ids.

## Setup

| Item | Value |
|---|---|
| Switch | self-hosted Switch v0.31.0 on the same Mac (Docker via Colima), every host port bound to 127.0.0.1 |
| Chat platform | Mattermost, bundled with the local Switch stack |
| Team | four synthetic Mattermost accounts: seoyeon (manager), minsu, jian, taeo |
| ShiftPatch | `run.py` on 127.0.0.1:8766 with a separate QA database, bridge config in a private 0600 file outside `app/` |
| Protocol source | official agent protocol on docs.switchagents.ai, fetched 2026-11-07 (copies in [the official documentation](https://docs.switchagents.ai/)): WebSocket `/agents/{id}/connection/ws`, `filter=addressed`, pong with cursor, `POST /agents/{id}/message` |
| Data | fictional: roster [`../fixtures/roster_sample.csv`](../fixtures/roster_sample.csv) for Mon 2026-11-09, Asia/Seoul |

How it was set up:

- Root registered the agent and created the room outside ShiftPatch. ShiftPatch's `manage.py register-agent` and `manage.py set-addressing` were **not** used, so they are still untested against a server.
- To map accounts, each synthetic account posted one addressed probe message, and root recorded the opaque `payload.sender` that Switch delivered for it. Those observed ids became the account links. The room, links and roster were then written by calling `roster.create_room`, `roster.import_switch_links` and `roster.import_roster` directly. These are the same functions behind `manage.py import-links` and `import-roster`, but the CLI wrappers themselves were not run.
- Each message was posted by a script through the Mattermost REST API, logged in as that synthetic account. Nobody typed these messages in a chat UI, and no real staff took part.

## Trace

Every message started with `@shiftpatch`. The date is written as an absolute ISO date. The run happened on Sat 11/7, so `내일` (tomorrow) would have meant 11/8, not the roster day.

| # | Sender (Switch-delivered) | Message | Board version | Result on the board | Post → state |
|---|---|---|---|---|---|
| 1 | minsu | `불가 2026-11-09 13:00-17:00` | 2 | 13:00–17:00 uncovered; Jian 09–13 and Taeo 17–18 unchanged | 0.21 s |
| 2 | jian | `가능 2026-11-09 13:00-15:00` | 3 | availability recorded (not an acceptance), proposal P1: Jian 13–15 | 0.22 s |
| 3 | taeo | `가능 2026-11-09 15:00-17:00` | 4 | P1 superseded; P2: P2-a Jian 13–15, P2-b Taeo 15–17 | 0.22 s |
| 4 | jian | `수락 P2-a` | 5 | Jian's own part accepted | 0.22 s |
| 5 | taeo | `수락 P2-b` | 6 | Taeo's own part accepted | 0.23 s |
| 6 | seoyeon | `확정 P2` | 7 | confirmed by the manager; no gaps | 0.22 s |
| 7 | jian | `불가 2026-11-09 13:00-15:00` | 8 | only 13:00–15:00 reopens; Taeo 15–17 stays confirmed; history keeps all of it | 0.22 s |

"Post → state" is the time from the Mattermost post request to the first poll of `/api/state` that showed the expected change. The poll ran every 0.2 s, so these numbers are coarse.

Final board: 09–13 Jian (original) · 13–15 uncovered · 15–17 Taeo (confirmed P2-b) · 17–18 Taeo (original).

## Observations from the bridge

- Bridge state at the end: `connected`, with 0 gap frames and 0 reconnects. It handled 110 frames: 102 pings, all 102 answered with a pong, and 7 messages.
- All 7 delivered messages had `addressed=true`. The agent's own 7 replies were not delivered back on the `filter=addressed` stream.
- Every message timestamp passed ShiftPatch's freshness window (2 min future / 15 min past). That fits `payload.timestamp` being in milliseconds.
- Root's identity probe read the `connection_state` cursor under `data`. The bridge also picked up generation, cursor and the covered room from that frame, and its status showed the configured room.
- All 7 replies reached outbox state `sent`, meaning `POST /agents/{id}/message` returned 2xx. This trace does not record how the replies looked in the Mattermost channel.
- Root's first attempt changed real state but then stopped on an error in the verification script: it expected gap objects, while the API returns `[start, end]` pairs. That attempt is **not** counted as a pass. Its database was kept, and the run above used a fresh one.

## Not covered by this run

- **Code version:** this trace ran on the code before the R01, R02 and R03 fixes (see [`root-review-response.md`](root-review-response.md)). Those fixes are covered by unit tests against the contract double and have not been re-run live.
- Managed or cloud Switch, and platforms other than the local Mattermost.
- Reconnects, `gap`, eviction and handler-failure paths on a live server. These are covered only by [`../tests/test_switch_contract.py`](../tests/test_switch_contract.py).
- AI-read free text over Switch, OCR roster import over Switch, and CSV delivery into the room.
- Real staff, phones, a public deployment, or anything published outside this Mac.

Root's raw trace JSON and the QA databases stay in root's development workspace and are not part of this package.
