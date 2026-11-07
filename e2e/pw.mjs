// Playwright from ./node_modules after `npm install`. To reuse an install that
// already exists elsewhere on this Mac, put that node_modules folder's path in
// e2e/playwright-dir.local (one line, git-ignored) or SHIFTPATCH_PLAYWRIGHT_DIR.
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const local = path.join(here, "playwright-dir.local");
const dir = process.env.SHIFTPATCH_PLAYWRIGHT_DIR || (existsSync(local) ? readFileSync(local, "utf8").trim() : null);
const require = createRequire(dir ? path.join(dir, "noop.js") : import.meta.url);
export const { chromium, webkit } = require("playwright");
