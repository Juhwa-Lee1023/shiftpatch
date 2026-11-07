# Demo video

`ShiftPatch_Demo_EN_live_9325ac3.mp4`: 122 seconds, 1920×1080, H.264, silent, burned-in English captions and a separate WebVTT file. It is in the task deliverables and has not been uploaded. The official submission needs an under-three-minute public or unlisted YouTube or Loom URL.

It is cut from one live run of `9325ac3` on 2026-11-07, 21:21–21:23 KST (run D in `qa/LIVE_SWITCH_REPORT.md`). The final code `3e6c861` differs only in how confirmation questions from before the upgrade are handled, which the video does not show. Run D: ShiftPatch connected to a local self-hosted Switch 0.31.0 with Mattermost, a new private room, AI reading off. Playwright recorded the native Mattermost channel, signed in as Seoyeon, and the ShiftPatch board while the run happened. The operator's script posted each message through Mattermost's API as that fictional person, so messages appear in the channel without anyone typing; the video says so on its first card.

The recording kept a 1600×712 area of each 1600×800 window, so board scenes whose content fell below that line use the same run's full-size screenshots. A chat scene may end by holding its last real frame for a few seconds so the caption can be read. Nothing in the chat or the app was redrawn. `edit-manifest.json` lists each scene's source and times.

| Time | Scene | Source | Caption |
|---|---|---|---|
| 0–7 s | Title card (text only) | card | — |
| 7–15 s | Channel: the four identity probes and the "not linked" replies | recording | Setup. Each person writes once to the agent in the Switch room. They are not linked yet, so ShiftPatch changes nothing and says so. |
| 15–23 s | Connection page: the four sender IDs as Switch delivered them | still capture | ShiftPatch lists each sender ID exactly as Switch delivered it. The manager links them on this Mac with manage.py link. No ID is guessed. |
| 23–28 s | Connection page after `manage.py link` | still capture | Four people, four linked IDs, all taken from real messages. |
| 28–39 s | Import screen for this Switch room: roster image read by Apple Vision, account links confirmed, import | recording | The manager reads the day's roster image on this Mac (Apple Vision), checks which Switch account is each person, and approves the import. |
| 39–48 s | Channel: Minsu's hedged message, the question (read by rule), `yes`, "now uncovered" | recording | Minsu can't cover Monday 13:00–17:00. The hedged wording gets a question first. Nothing changes until Minsu replies yes. |
| 48–58 s | Channel: `available 13:60-15:00` refused; Jian's availability and P1 | recording | Jian's 13:60 is refused. Then Jian offers 13:00–15:00. Being available is not the same as taking the shift. |
| 58–65 s | Channel: Taeo's availability; P2 with `accept P2-a` / `accept P2-b` | recording | Taeo offers 15:00–17:00. ShiftPatch splits the gap into P2-a and P2-b and tells each person which part to accept. |
| 65–78 s | Channel: both acceptances; `confirm P2` | recording | Jian and Taeo each accept their own part. Seoyeon, the manager, confirms P2. No gaps remain. |
| 78–88 s | Channel: Jian's inability; the refused re-confirmation | recording | Later Jian can't do 13:00–15:00. Only those hours reopen; Taeo's stay confirmed. Sending confirm P2 again is refused, and the reply says why. |
| 88–102 s | Channel: `export`, `export ics`, `status` | recording | Seoyeon exports a CSV and a calendar file of the confirmed shifts, both version 8. status lists the coverage and links to this room's board. |
| 102–114 s | Board for the same room after the run (slow pan over its full-page capture) | still capture | The board: 13:00–15:00 has nobody assigned. P2 stays confirmed in the history, marked “confirmed earlier · 13:00–15:00 reopened”, and lists the same two files. |
| 114–122 s | End card (text only) | card | — |

The free-text AI reader is not in this video; the run had AI reading off. It was checked separately with `node e2e/ai_trace.mjs` and in live run E over Switch (not recorded), and is described in the README. The earlier 105-second and 77-second videos are kept unchanged in the working project.

Re-recording: use explicit `2026-11-09` dates in a Switch room, which runs on the real clock. The local demo room has a synthetic clock set to Sunday 11/8.
