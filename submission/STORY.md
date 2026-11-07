# ShiftPatch — submission answers

Not entered into the form. This is the text to review before the entrant submits manually.

## Project title
ShiftPatch

## Track
Best Business Workflow

## Project description
A teammate drops a shift. One colleague can take the first two hours, another can cover the rest. The answers are in chat, but someone still has to check who actually agreed and update the roster.

ShiftPatch handles that handoff inside a Switch room. Minsu can't cover Monday, November 9, 13:00–17:00. Jian offers 13:00–15:00 and Taeo offers 15:00–17:00. ShiftPatch replies with a proposal that names each part (`Jian: accept P2-a · Taeo: accept P2-b`). Each person accepts their own part and Seoyeon, the manager, confirms. When Jian later drops out, only 13:00–15:00 reopens; Taeo's confirmed hours stay, and the board and CSV export show the same version.

Claude reads a free-form message such as "I might be unable to cover Monday 13–17" and suggests one action. Nothing changes until the sender replies `yes`. Exact commands like `accept P2-a` skip the AI. Code checks every step: only the owner of a part can accept it, only the manager can confirm, and a confirmed plan that later changed cannot be confirmed again.

This prototype has one fixed four-person team and one day. The manager loads that day's roster from a CSV or a simple roster image (read locally with Apple Vision) and confirms which chat account belongs to each person.

## Public GitHub repository
PENDING — no publication authorized or performed.

## Demo video (under 3 minutes, YouTube or Loom; public/unlisted)
PENDING — a revised local video is prepared; nothing is uploaded.

## Optional live demo
No hosted demo. The application and Switch stack run on this Mac only.

## How did you use Switch?
ShiftPatch is a custom Python agent connected to a self-hosted Switch 0.31.0 server over the documented WebSocket agent protocol. Four fictional teammates share a private Mattermost channel connected through Switch. The agent receives Switch message events, takes the actor from the sender identity Switch supplies, and posts its replies back into the channel.

Each state change is tied to a room, a message and a linked staff account. Redelivered messages are ignored, replies go out in order, and a reply that cannot be delivered is shown on the board with a button to send it again without repeating the change.

I ran the full handoff on the corrected source through that local stack: a new agent registered with ShiftPatch's own setup command, a new private room, and a roster read from an image and imported for that room. A hedged message went through the real AI reader and was confirmed from the same chat account; then two availability replies, two self-acceptances, the manager's confirmation, Jian's partial dropout, the refused re-confirmation and a CSV export. One developer operated the four roles with synthetic shifts. It was an integration check, not a trial with a working support team.

## What did you like about Switch, and what would you improve?
Switch let the workflow stay in the chat room. The agent received a stable sender identity and message ID, which made it possible to separate a person's acceptance from a manager's confirmation and ignore duplicate deliveries. WebSocket heartbeats kept the connection alive while the AI reader was working.

For a first self-hosted setup, I would add one tested example that starts the chat bridge, creates a private room, shows the participant IDs and connects an agent; those steps were spread across several pages. In my setup, changing the agent's addressing with the agent's own key returned HTTP 403, and the Gateway's room rule worked. Saying which of the two is expected would help. One complete control frame and one complete message frame in the connection guide would have made the adapter easier to check, and the WebSocket guidance could be more visible where older SSE examples still appear.

## Development and data disclosure
The prototype, tests and documentation were developed with AI coding tools, Claude and Codex, directed by the entrant. The optional in-product reader calls the locally signed-in Claude CLI. Roster images are read locally with Apple Vision. All people, rosters and chat messages in the demo are synthetic. No real employee data was used.
