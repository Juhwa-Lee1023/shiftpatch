"""Korean history wording in web/app.js (R03). Runs only the extracted
particle helper under Node; no browser."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

import harness  # noqa: F401  (sys.path)

APP_JS = Path(__file__).resolve().parent.parent / "web" / "app.js"


class KoreanParticle(unittest.TestCase):
    def setUp(self):
        self.src = APP_JS.read_text()

    def test_history_uses_particle_helper(self):
        self.assertNotIn("${who}이 ", self.src)
        self.assertEqual(len(re.findall(r"\$\{iga\(who\)\} ", self.src)), 4)

    @unittest.skipUnless(shutil.which("node"), "node not on PATH")
    def test_particle_follows_final_consonant(self):
        line = re.search(r"^\s*const iga = .*;$", self.src, re.M).group(0)
        names = ["태오", "지안", "민수", "서연", "ShiftPatch"]
        out = subprocess.run(["node", "-e", f"{line}\nconsole.log(JSON.stringify({json.dumps(names)}.map(iga)))"],
                             capture_output=True, text=True, timeout=20, check=True).stdout
        self.assertEqual(json.loads(out), ["태오가", "지안이", "민수가", "서연이", "ShiftPatch가"])
