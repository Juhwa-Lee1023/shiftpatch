# Local Switch setup used for verification

Two live checks used the official Switch standalone Docker Compose stack at tag `switch-v0.31.0` with the `collab` and `gateway` profiles and Mattermost (https://github.com/sandbox-quantum/switch, https://docs.switchagents.ai/). Every host port was bound to 127.0.0.1. The Mac ran it in a VM with 2 CPUs and 4 GiB memory; no automatic startup was installed.

This source does not bundle Switch, its images, a password or an agent key.

| | First check (pre-fix source) | Corrected-source check |
|---|---|---|
| Agent | `shiftpatch`, registered by an operator script outside this package | `shiftpatch2`, registered with `manage.py register-agent` |
| Room | private room created in the Gateway | a second private room, created in the Gateway |
| Addressing | Gateway rule for the room | `manage.py set-addressing anyone` → HTTP 403; Gateway rule for the room |
| Links | functions behind `import-links`, called directly | `manage.py import-links` |
| Roster | CSV, functions behind `import-roster` called directly | roster image (`fixtures/ocr/clear.png`) through the review screen for that room |

## Steps

1. In the Gateway, create an agent registration key. Register the agent:
   ```sh
   export SHIFTPATCH_REGISTRATION_KEY=…
   python3 manage.py register-agent --base-url http://127.0.0.1:18000 --name shiftpatch2
   ```
   `config/switch.local.json` (0600, git-ignored) now holds `base_url`, `agent_id`, `api_key` and `agent_name`.
2. Create a private Mattermost room in the Gateway with the agent and the four synthetic accounts. Roles in the check: Seoyeon manager; Minsu, Jian and Taeo staff. Add an addressing rule for the agent in that room that lets every user address it.
3. `python3 manage.py set-room '<room UUID>'`. The transport-room alias is not interchangeable with the room UUID.
4. Link each opaque Switch sender ID to a staff ID. In both checks each account posted one `@agent` probe and the delivered `payload.sender` was recorded; IDs were never built from display names. The first probe in the corrected-source check, sent right after the room was created, was not delivered; resending it worked.
   ```sh
   python3 manage.py import-links config/links.json
   ```
5. `python3 run.py --port 8765`, then open `http://127.0.0.1:8765/?room=<url-encoded room UUID>#/import`. Load a CSV or a roster image. The account list shows the participant ID that will act as each person in this room; a person with no linked ID blocks the import. Confirm each link, tick the approval box and import. (`python3 manage.py import-roster <csv> <mapping.json> --approve` is the command-line alternative.)
6. Open the chat at Mattermost's configured SiteURL, **http://localhost:18065** in the check. The `127.0.0.1` form was rejected by its WebSocket origin check.
7. Use explicit dates (`2026-11-09`) in the room. `@agent status` returns the room's board link, which opens on the host Mac only. The browser demo's role picker cannot send into a Switch room.

## AI and OCR

The optional AI reader needs an already signed-in Claude CLI; no provider credential is shipped. Without it the app says AI reading is unavailable and exact commands still work. `SHIFTPATCH_AI=off` turns it off. `.env` files are not loaded automatically.

Apple Vision OCR runs on macOS through Swift. It reads one simple five-column roster into an editable draft. Roles, accounts and acceptance never come from the image.
