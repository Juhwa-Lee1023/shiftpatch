"""Local admin CLI for the Switch path (the web UI's import screen targets the
local demo room). Nothing here prints a credential.

  python3 manage.py register-agent --base-url http://localhost:8000 --name shiftpatch
      POST /agents with SHIFTPATCH_REGISTRATION_KEY (env). Writes agent_id and
      the returned api_key to config/switch.local.json (mode 0600).
  python3 manage.py set-addressing anyone
      POST /agents/{id}/ops/update_agent_detail {"agent_id", "addressing"} so
      staff (not only the owner) can address the agent.
  python3 manage.py set-room <room_id>
  python3 manage.py import-links links.json        {"@switch-user-…:server": "jian", …}
  python3 manage.py import-roster roster.csv mapping.json --approve
  python3 manage.py status
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))

from shiftpatch import engine, roster  # noqa: E402
from shiftpatch.db import Store  # noqa: E402
from shiftpatch.switch_bridge import SwitchConfig  # noqa: E402

CFG = APP / "config" / "switch.local.json"


def load_cfg():
    return json.loads(CFG.read_text()) if CFG.exists() else {}


def save_cfg(data):
    CFG.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(CFG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(CFG, 0o600)


def post(url, body, bearer):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {bearer}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode("utf-8", "replace")[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(APP / "data"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register-agent")
    r.add_argument("--base-url", required=True)
    r.add_argument("--name", default="shiftpatch")
    sub.add_parser("set-addressing").add_argument("mode", choices=["owner_only", "owner_and_owner_agents", "anyone"])
    sub.add_parser("set-room").add_argument("room_id")
    sub.add_parser("import-links").add_argument("file")
    ir = sub.add_parser("import-roster")
    ir.add_argument("csv")
    ir.add_argument("mapping")
    ir.add_argument("--approve", action="store_true")
    sub.add_parser("status")
    a = ap.parse_args()
    cfg = load_cfg()

    if a.cmd == "register-agent":
        key = os.environ.get("SHIFTPATCH_REGISTRATION_KEY")
        if not key:
            sys.exit("Set SHIFTPATCH_REGISTRATION_KEY (a registration key from the Gateway's API Keys page).")
        body = {"name": a.name, "description": "Fills a sudden shift gap: availability, self acceptance, manager confirmation.",
                "connector_type": "shiftpatch-python", "display_name": "ShiftPatch",
                "integration_profile": {"connection_model": "always_on", "message_exchange": True,
                                        "pre_invocation_mediation": [], "post_invocation_mediation": [], "event_reporting": []}}
        status, out = post(a.base_url.rstrip("/") + "/agents", body, key)
        if status >= 300 or "api_key" not in out:
            sys.exit(f"registration failed: HTTP {status} {out.get('error', '')}")
        cfg.update(base_url=a.base_url.rstrip("/"), agent_id=out["id"], api_key=out["api_key"], agent_name=a.name)
        save_cfg(cfg)
        print(f"registered agent {out['id']}; key saved to {CFG} (0600, not printed)")
        return
    if a.cmd == "set-addressing":
        status, out = post(f"{cfg['base_url']}/agents/{cfg['agent_id']}/ops/update_agent_detail",
                           {"agent_id": cfg["agent_id"], "addressing": a.mode}, cfg["api_key"])
        print(f"HTTP {status}")
        if not 200 <= status < 300:
            # Seen on local Switch 0.31.0: 403 with the agent's own key. Set the room's
            # addressing rule in the Gateway instead (docs/LOCAL_SWITCH_SETUP.md).
            sys.exit("set-addressing was refused; set the addressing rule in the Switch Gateway instead")
        return
    if a.cmd == "set-room":
        cfg["room_id"] = a.room_id
        save_cfg(cfg)
        print(f"room_id set to {a.room_id}")
        return

    store = Store(Path(a.data) / "shiftpatch.db")
    sc, fields = SwitchConfig.load(CFG)
    room_id = cfg.get("room_id")
    if a.cmd == "status":
        print(json.dumps({"config_fields_present": fields}, indent=2))
        if room_id:
            with store.snapshot() as c:
                rm = c.execute("SELECT room_id, kind, roster_version, events_started, version FROM rooms WHERE room_id=?",
                               (room_id,)).fetchone()
                n = c.execute("SELECT COUNT(*) FROM links WHERE room_id=?", (room_id,)).fetchone()[0]
            print(json.dumps({"room": dict(rm) if rm else None, "links": n}, indent=2))
        return
    if not room_id:
        sys.exit("run set-room first")
    roster.create_room(store, room_id, "switch", "Switch room")
    try:
        if a.cmd == "import-links":
            links = json.loads(Path(a.file).read_text())
            res = roster.import_switch_links(store, room_id, links)
            print(f"linked {res['linked']} Switch participants")
            if res["closed_questions"]:
                print("closed open confirmation questions for relinked staff: " + ", ".join(res["closed_questions"]))
        elif a.cmd == "import-roster":
            rows = roster.parse_csv(Path(a.csv).read_bytes())
            mapping = json.loads(Path(a.mapping).read_text())
            res = roster.import_roster(store, room_id, rows, mapping, set(mapping), a.approve, "cli_csv")
            print(f"imported roster v{res['roster_version']} ({res['rows']} rows)")
    except engine.Rejected as e:
        sys.exit(f"refused: {e.code} {e.info}")


if __name__ == "__main__":
    main()
