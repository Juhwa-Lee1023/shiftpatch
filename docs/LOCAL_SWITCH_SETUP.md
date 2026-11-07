# Local Switch setup used for verification

This prototype was checked with the official Switch standalone Docker Compose stack at tag `switch-v0.31.0`. The task used the `collab` and `gateway` profiles with Mattermost. Source: https://github.com/sandbox-quantum/switch and https://docs.switchagents.ai/.

The submitted source does not bundle Switch, its images, an account password or an agent key. Start your own Switch stack using its self-host instructions. For a local-only installation, bind its host ports to 127.0.0.1 rather than all interfaces. The verified Mac used 2 CPUs and 4 GiB memory; its two virtual disks total 20 GiB. No automatic startup was installed.

## Connect the workflow

1. In the local Switch Gateway, create an agent registration key and a private Mattermost room. Add the agent and the four fictional accounts. The local test used these roles: Seoyeon, manager; Minsu, Jian and Taeo, staff.
2. Save the agent configuration privately as `config/switch.local.json` (chmod 600). Use the field names in `config/switch.example.json`. Set `base_url` to your local Switch API, `agent_id`, `api_key`, `room_id` to its room UUID and `agent_name` to its addressing name. The transport-room alias is not interchangeable with the room UUID.
3. Link each opaque Switch sender ID to a staff ID. The verified setup observed `payload.sender` from a probe posted by each native account; it did not construct IDs from display names. Import links before the roster:

   ```sh
   python3 manage.py import-links config/links.json
   python3 manage.py import-roster fixtures/roster_sample.csv config/mapping.example.json --approve
   python3 run.py
   ```

   Initial roster import can also use the application’s image/CSV review screen for the selected room. The direct CSV import into the Switch room and the image-review UI for a local fixture were independently tested. The image UI has not yet been independently used to initialize a real Switch room.

4. Open the native chat using Mattermost’s configured SiteURL. In the verified setup this is **http://localhost:18065**. A different origin (`127.0.0.1` instead of `localhost`) was rejected by its WebSocket origin check and required refresh to see replies. Use the correct origin; do not disable that check.
5. Open the board using `http://127.0.0.1:8766/?room=<url-encoded room UUID>#/board` for the verification instance, or your own app port. From the chat, `@shiftpatch status` returns the room-specific board link. The board is local to the host Mac.
6. For the recorded scenario, use explicit November9 dates. Send the availability, acceptance and confirmation messages as the correct native accounts; the browser demo’s role picker cannot send into a Switch room.

Agent registration in the actual test used an operator setup script outside this source package. The source `manage.py register-agent` and `set-addressing` commands are provided but have not themselves been exercised against the live server. No existing worker roster, real employee or external service account was changed.

## AI and OCR

The optional AI reader requires an already authenticated Claude CLI. No provider credential is shipped. Without it, the app says AI reading is unavailable; exact commands remain available. `SHIFTPATCH_AI=off` deliberately turns the reader off. Environment examples are not automatically loaded from a `.env` file.

Apple Vision OCR runs on macOS using Swift. It reads one simple five-column roster into an editable draft. Review dates, hours, duty and account links before import; roles and acceptance never come from the image.
