# Live Switch run — local self-hosted, synthetic team

## Source after the review fixes: checked 2026-11-07, about 18:35–18:39 KST

This run used the source after the 2026-11-07 review fixes (worktree commit `c65b2ec` plus the `manage.py set-addressing` exit-code change, which the server process does not load). It ran next to the earlier demo without touching it: a new agent `shiftpatch2`, a new private room, a new data directory and ShiftPatch on 127.0.0.1:8786. The earlier instance on 8766 stayed connected with 0 reconnects.

Setup, through ShiftPatch's own commands where they worked:

| Step | Result |
|---|---|
| `manage.py register-agent --base-url http://127.0.0.1:18000 --name shiftpatch2` | exit 0, agent registered; key in the git-ignored 0600 config |
| `manage.py set-addressing anyone` | **HTTP 403**. The Gateway addressing rule for the room was used instead |
| `manage.py set-room` | exit 0 |
| Identity probe, one `@shiftpatch2` message per account | first attempt: Seoyeon's probe, sent right after room creation, was not delivered; second attempt observed all four |
| `manage.py import-links` | exit 0, 4 participants linked |
| Roster | `fixtures/ocr/clear.png` read by Apple Vision on the review screen for this Switch room. The account list showed each person's Switch participant ID (no `local:` accounts). Links confirmed, approval ticked, imported as roster version 1 |

Flow. Messages were posted through Mattermost's REST API as each synthetic account; the native channel shows them with ShiftPatch's replies (captured afterwards as Seoyeon).

| # | Sender | Message (`@shiftpatch2 …`) | Version | Reply / state |
|---|---|---|---|---|
| 1 | minsu | `I might be unable to cover Monday, November 9, 13:00-17:00.` | 1 | question Q1 for 13:00–17:00 unavailable, "until 18:48 · read by AI"; nothing recorded |
| 2 | minsu | `yes Q1` | 2 | "Mon 11/9 13:00–17:00 is now uncovered." |
| 3 | jian | `available 13:60-15:00` | 2 | "That is not a clock time, so nothing was recorded." |
| 4 | jian | `available 2026-11-09 13:00-15:00` | 3 | proposal P1 with `Jian: accept P1-a` |
| 5 | taeo | `available 2026-11-09 15:00-17:00` | 4 | "New proposal P2: Jian 13:00–15:00, Taeo 15:00–17:00. Jian: accept P2-a · Taeo: accept P2-b. Then Seoyeon sends confirm P2." |
| 6 | jian | `accept P2-a` | 5 | still waiting for Taeo |
| 7 | taeo | `accept P2-b` | 6 | waiting for Seoyeon to send `confirm P2` |
| 8 | seoyeon | `confirm P2` | 7 | confirmed, no gaps |
| 9 | jian | `unavailable 2026-11-09 13:00-15:00` | 8 | "13:00–15:00 is uncovered again. Taeo's 15:00–17:00 stays confirmed." |
| 10 | seoyeon | `confirm P2` | 8 | "P2 was confirmed earlier. Since then Jian's 13:00–15:00 reopened, so P2 was not confirmed again. Nothing changed." |
| 11 | seoyeon | `export` | 8 | "Created coverage-2026-11-09-v8-….csv (version #8)"; the board lists the same file; HTTP 200 download |
| 12 | seoyeon | `status` | 8 | coverage lines and the board link for this room |

Final board: 09–13 Jian (original) · 13–15 uncovered · 15–17 Taeo (confirmed P2-b) · 17–18 Taeo (original). P2 stays "confirmed" with "confirmed earlier · 13:00–15:00 reopened" next to it. Every reply reached outbox state `sent`; no failed deliveries. Bridge state at the end: connected, 0 reconnects, 0 bad frames, 0 read timeouts.

Not covered: failures on a live server (all fault paths remain fake-socket or contract-double tests), a second run for repeatability, managed/cloud Switch, other chat platforms, real staff. Sanitized trace and captures: `development/opus-remediation-20261107T090608Z/live-run/` in the working project; no ids, keys or passwords are in this repository.

## Final source before the review fixes: verified 2026-11-07 17:15–17:17 KST

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
