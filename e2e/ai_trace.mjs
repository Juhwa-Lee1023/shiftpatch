// Browser run of the free-form path with the REAL AI reader on (local
// Claude CLI login). Writes qa/e2e-ai-result.json and one screenshot.
// Usage: node e2e/ai_trace.mjs
import { chromium } from "./pw.mjs";
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const APP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PORT = 8890 + Math.floor(Math.random() * 100);
const DATA = mkdtempSync(path.join(tmpdir(), "shiftpatch-ai-e2e-"));
const BASE = `http://127.0.0.1:${PORT}`;
const t0 = Date.now();
const server = spawn("python3", [path.join(APP, "run.py"), "--port", String(PORT), "--data", DATA,
  "--switch-config", path.join(DATA, "none.json")], { env: { ...process.env, SHIFTPATCH_AI: "on" }, stdio: ["ignore", "pipe", "pipe"] });
await new Promise((res, rej) => {
  const to = setTimeout(() => rej(new Error("server did not start")), 15000);
  server.stdout.on("data", (d) => { if (String(d).includes("ShiftPatch on")) { clearTimeout(to); res(); } });
});
const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const replies = [];
let exitCode = 0;
async function send(actorLabel, text, mustContain) {
  await page.locator(".actors").getByRole("button", { name: new RegExp("^" + actorLabel) }).click();
  await page.fill("#msg", text);
  const n = await page.locator(".bubble.agent").count();
  await page.getByRole("button", { name: "보내기", exact: true }).click();
  await page.waitForFunction((k) => document.querySelectorAll(".bubble.agent").length > k, n, { timeout: 90000 });
  const r = await page.locator(".bubble.agent .tx").last().innerText();
  const ok = mustContain.every((m) => r.includes(m));
  replies.push({ actor: actorLabel, text, reply: r, expected: mustContain, ok });
  if (!ok) exitCode = 1;
  return r;
}
try {
  await page.goto(BASE + "/");
  await page.getByRole("button", { name: "합성 예시 CSV로 시작" }).click();
  await page.locator(".maprow").first().waitFor();
  for (const cb of await page.locator(".maprow input[type=checkbox]").all()) { await cb.check(); await page.waitForTimeout(150); }
  await page.locator("#approve").check();
  await page.getByRole("button", { name: "초기 근무표 등록" }).click();
  await page.locator(".banner").waitFor();
  await page.goto(BASE + "/#/room");
  await page.locator("#msg").waitFor();
  await send("민수", "@ShiftPatch 월요일 13~17시 고객문의 응대 못 할 것 같아요", ["'불가'로 기록할까요", "AI가 읽은 내용"]);
  await send("민수", "@ShiftPatch 네", ["13:00–17:00이 비었습니다"]);
  await send("지안", "@ShiftPatch 점심 먹고 두 시간은 돼요", ["13:00–15:00 가능으로 기록할까요", "AI가 읽은 내용"]);
  await send("지안", "@ShiftPatch 네", ["가능으로 기록했습니다"]);
  await send("서연", "@ShiftPatch 둘 다 된대요", ["대신 기록할 수 없어요"]);
  await page.screenshot({ path: path.join(APP, "docs", "screenshots", "11-room-ai-path.png") });
} catch (e) {
  exitCode = 1;
  replies.push({ error: String(e.message).split("\n")[0] });
} finally {
  await browser.close();
  server.kill("SIGTERM");
}
writeFileSync(path.join(APP, "qa", "e2e-ai-result.json"), JSON.stringify({ at: new Date().toISOString(), command: "node e2e/ai_trace.mjs",
  ai: "on (local Claude CLI login)", duration_ms: Date.now() - t0, exit_code: exitCode, replies }, null, 2) + "\n");
console.log(JSON.stringify({ exit_code: exitCode, ok: replies.filter((r) => r.ok).length, total: replies.length }));
process.exit(exitCode);
