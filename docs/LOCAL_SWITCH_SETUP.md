# Local Switch setup used for verification

The live checks used the official Switch standalone Docker Compose stack at tag `switch-v0.31.0` with the `collab` and `gateway` profiles and Mattermost (https://github.com/sandbox-quantum/switch, https://docs.switchagents.ai/). Every host port was bound to 127.0.0.1. The Mac ran it in a VM with 2 CPUs and 4 GiB memory; no automatic startup was installed.

This source does not bundle Switch, its images, a password or an agent key.

| | First check (pre-fix source) | Corrected-source check (`c65b2ec`) | Final checks (`a70ae7e`, `9325ac3`) |
|---|---|---|---|
| Agent | `shiftpatch`, registered by an operator script outside this package | `shiftpatch2`, registered with `manage.py register-agent` | `shiftpatch3`, registered with `manage.py --config <file> register-agent` |
| Room | private room created in the Gateway | a second private room, created in the Gateway | a new private room per run, four runs |
| Addressing | Gateway rule for the room | `manage.py set-addressing anyone` → HTTP 403; Gateway rule for the room | same, HTTP 403 every time |
| Links | functions behind `import-links`, called directly | `manage.py import-links` with IDs read from the stream | each account wrote once; `manage.py senders` listed the IDs; `manage.py link` linked them |
| Roster | CSV, functions behind `import-roster` called directly | roster image (`fixtures/ocr/clear.png`) through the review screen for that room | same |

## Steps

1. In the Gateway, create an agent registration key. Register the agent:
   ```sh
   export SHIFTPATCH_REGISTRATION_KEY=…
   python3 manage.py register-agent --base-url http://127.0.0.1:18000 --name shiftpatch3
   ```
   `config/switch.local.json` (0600, git-ignored) now holds `base_url`, `agent_id`, `api_key` and `agent_name`. `--config <file>` before the command writes it elsewhere; give the same file to `run.py --switch-config` and to later `manage.py` commands.
2. Create a private Mattermost room in the Gateway with the agent and the four synthetic accounts. Roles in the check: Seoyeon manager; Minsu, Jian and Taeo staff. Add an addressing rule for the agent in that room that lets every user address it.
3. `python3 manage.py set-room '<room UUID>'`. The transport-room alias is not interchangeable with the room UUID.
4. Start ShiftPatch: `python3 run.py --port 8765`.
5. Link each opaque Switch sender ID to a staff ID. Each account sends one message to the agent in the room (`@shiftpatch3 status`); ShiftPatch answers "not linked" and keeps the sender ID and display name for one hour, without the text. Then:
   ```sh
   python3 manage.py senders                          # the IDs exactly as Switch delivered them
   python3 manage.py link '<sender id from senders>' jian
   ```
   `link` refuses an ID that has not written to the agent in this room. IDs are never built from display names or from another account's ID. In the corrected-source check the first probe, sent right after the room was created, was not delivered and was resent; in the four final runs every first probe arrived.
6. Open `http://127.0.0.1:8765/?room=<url-encoded room UUID>#/import`. Load a CSV or a roster image. The account list shows the participant ID that will act as each person in this room; a person with no linked ID blocks the import. Confirm each link, tick the approval box and import. (`python3 manage.py import-roster <csv> <mapping.json> --approve` is the command-line alternative.)
7. Open the chat at Mattermost's configured SiteURL, **http://localhost:18065** in the check. The `127.0.0.1` form was rejected by its WebSocket origin check.
8. Use explicit dates (`2026-11-09`) in the room. `@agent status` returns the room's board link, which opens on the host Mac only. The browser demo's role picker cannot send into a Switch room.

## AI and OCR

The optional AI reader needs an already signed-in Claude CLI; no provider credential is shipped. Without it the app says AI reading is unavailable and exact commands still work. `SHIFTPATCH_AI=off` turns it off. `.env` files are not loaded automatically.

Apple Vision OCR runs on macOS through Swift. It reads one simple five-column roster into an editable draft. Roles, accounts and acceptance never come from the image.
