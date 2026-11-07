# ShiftPatch — submission answers

Not entered into the form. This is the text to review before the entrant submits manually.

## Project title
ShiftPatch

## Track
Best Business Workflow

## Project description
A teammate drops a shift. One colleague can take the first two hours, another can cover the rest. The answers are in chat, but someone still has to check who actually agreed and update the roster.

ShiftPatch handles that handoff inside a Switch room. It reads each person's availability, proposes a split and waits for each person to accept their own hours. The manager then confirms the plan. If one person later becomes unavailable, only those hours reopen; the rest of the confirmed plan stays in place.

The demo follows a small customer-support team covering Monday, November 9. Jian takes 13:00–15:00 and Taeo takes 15:00–17:00. When Jian drops out, the board reopens 13:00–15:00 and keeps Taeo's shift. A CSV export records the same version of the board.

To get started, the manager imports a CSV or a simple roster image, checks the extracted cells and links the names to chat accounts. Free-form replies go through an AI reader and back to the sender for confirmation. Availability, acceptance and manager confirmation remain separate steps.

## Public GitHub repository
PENDING — no publication authorized or performed.

## Demo video (under 3 minutes, YouTube or Loom; public/unlisted)
PENDING — no video uploaded.

## Optional live demo
No hosted demo. The application and Switch stack run on this Mac only.

## How did you use Switch?
ShiftPatch is a custom agent connected to a self-hosted Switch 0.31.0 server over the documented WebSocket agent protocol. Four fictional teammates use a private Mattermost channel connected through Switch. The agent receives Switch message events, uses the sender identity supplied by Switch and sends its replies back into that channel.

Each state change is tied to a room, message and linked staff account. A person can accept only their own part; the manager alone can confirm the complete plan. Redelivered messages are ignored, and an old proposal cannot overwrite a later change. The browser board and exports read the resulting roster state.

We ran the full handoff through that local Switch stack, including the partial dropout after confirmation. We also sent a free-form sentence through the real AI reader and confirmed the interpreted hours from the same chat account. The four roles were operated by one developer with synthetic shifts; this was an integration test, not a trial with a working support team.

## What did you like about Switch, and what would you improve?
Switch let the workflow stay in the chat room. Our agent received a stable sender identity and message ID, which made it possible to separate a person's acceptance from a manager's confirmation and ignore duplicate deliveries. WebSocket heartbeat frames also kept the connection responsive while the AI reader was working.

For a first self-hosted setup, I would add one tested example that starts the chat bridge, creates a private room, exposes the participant IDs and connects an agent. During the local setup, those steps were spread across several pages. The event stream worked in our local run; seeing one complete control frame and one complete message frame in the connection guide would have made the adapter easier to check. I would also make the current WebSocket guidance more visible wherever older SSE examples still appear.

## Development and data disclosure
The prototype, tests and documentation were developed with AI coding tools, including Claude and Codex. The optional in-product reader calls the locally signed-in Claude CLI. Roster images are read locally with Apple Vision. All people, rosters and chat messages in the demo are synthetic. No real employee data was used.
