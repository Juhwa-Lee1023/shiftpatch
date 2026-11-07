# Demo video (revised)

A 105-second silent screencast with burned-in English captions and a separate WebVTT file: `ShiftPatch_Demo_EN_revised.mp4` in the remediation deliverables. It has not been uploaded. The official submission needs an under-three-minute public or unlisted YouTube or Loom URL.

Every scene is a crop of a real capture from the 2026-11-07 live check of the corrected source: the native Mattermost channel (connected through local Switch 0.31.0) and the ShiftPatch board for that room. Crops are scaled up, with a label bar above and a caption bar below; no chat or app content is redrawn. The chat messages were posted through Mattermost's API as each synthetic account, and the channel was captured after the run, so the video shows the real conversation rather than someone typing.

| Time | Scene | Caption |
|---|---|---|
| 0–13 s | Channel name; Minsu's hedged message, the AI-read question, `yes Q1`, "now uncovered" | Minsu can't cover Monday 13:00–17:00 and says so in the team's Switch room. Claude reads the hedged message. Nothing changes until Minsu replies yes Q1. |
| 13–24 s | `available 13:60-15:00` refused; Jian's availability and P1 | Jian types 13:60 by mistake: refused, nothing recorded. Then Jian offers 13:00–15:00. Being available is not taking the shift. |
| 24–35 s | Taeo's availability; P2 with `accept P2-a` / `accept P2-b` | Taeo offers 15:00–17:00. ShiftPatch splits the gap into P2-a and P2-b and tells each person which part to accept. |
| 35–47 s | Both acceptances; `confirm P2` | Jian and Taeo each accept their own part. Seoyeon, the manager, confirms P2. No gaps remain. |
| 47–61 s | Jian's inability; the refused re-confirmation | Later Jian can't do 13:00–15:00. Only those hours reopen; Taeo's stay confirmed. Sending confirm P2 again is refused, and the reply says why. |
| 61–73 s | Board, version 8, "Switch room · connected", reopened badge | The board shows the one open interval. P2 stays confirmed in the history, marked "confirmed earlier · 13:00–15:00 reopened". |
| 73–85 s | Export reply and the board's export list | Seoyeon sends export. The chat reply and the board list the same file. |
| 85–96 s | Roster-image review for this Switch room with the participant IDs | Before the chat, the manager read a roster image on this Mac and confirmed which Switch account is each person. That is how this room's roster was loaded. |
| 96–105 s | `status` reply with the room's board link | status links to this room's board, which opens on the host Mac only. One developer played all four fictional people. No real team has used it yet. |

The earlier 77-second video (pre-fix source, OCR scene from a local fixture) is kept unchanged in the working project's `video/` folder.

Re-recording: use explicit `2026-11-09` dates in a Switch room, which runs on the real clock. The local demo room has a synthetic clock set to Sunday 11/8.
