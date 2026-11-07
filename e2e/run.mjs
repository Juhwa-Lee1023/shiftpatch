// Browser end-to-end: starts its own ShiftPatch server (fresh temp data,
// AI off for determinism), drives system Chrome through the real UI, saves
// screenshots to docs/screenshots and a result file to qa/e2e-result.json.
// Usage: node e2e/run.mjs
import { chromium } from "./pw.mjs";
import { execFileSync, spawn } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const APP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SHOTS = path.join(APP, "docs", "screenshots");
mkdirSync(SHOTS, { recursive: true });
const PORT = 8790 + Math.floor(Math.random() * 100);
const DATA = mkdtempSync(path.join(tmpdir(), "shiftpatch-e2e-"));
const BASE = `http://127.0.0.1:${PORT}`;
const steps = [];
const t0 = Date.now();

const server = spawn("python3", [path.join(APP, "run.py"), "--port", String(PORT), "--data", DATA,
  "--switch-config", path.join(DATA, "none.json")],
  { env: { ...process.env, SHIFTPATCH_AI: "off", PYTHONWARNINGS: "always::ResourceWarning" }, stdio: ["ignore", "pipe", "pipe"] });
let serverOut = "", serverErr = "";
server.stderr.on("data", (d) => { serverErr += String(d); });
const serverExit = new Promise((res) => server.on("exit", (code, signal) => res({ code, signal })));
await new Promise((res, rej) => {
  const to = setTimeout(() => rej(new Error("server did not start")), 15000);
  server.stdout.on("data", (d) => { serverOut += String(d); if (String(d).includes("ShiftPatch on")) { clearTimeout(to); res(); } });
});

const browser = await chromium.launch({ channel: "chrome", headless: true });
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true });
const page = await ctx.newPage();
const consoleErrors = [];
page.on("pageerror", (e) => consoleErrors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });

async function step(name, fn) {
  const s = Date.now();
  try { await fn(); steps.push({ name, ok: true, ms: Date.now() - s }); }
  catch (e) { steps.push({ name, ok: false, ms: Date.now() - s, error: String(e.message).split("\n")[0] }); throw e; }
}
const shot = (name, full = true) => page.screenshot({ path: path.join(SHOTS, name), fullPage: full });
async function send(actorLabel, text) {
  await page.locator(".actors").getByRole("button", { name: new RegExp("^" + actorLabel) }).click();
  await page.fill("#msg", text);
  const n = await page.locator(".bubble.agent").count();
  await page.getByRole("button", { name: /^보내기$|^Send$/ }).click();
  await page.waitForFunction((k) => document.querySelectorAll(".bubble.agent").length > k, n, { timeout: 15000 });
  return (await page.locator(".bubble.agent .tx").last().innerText());
}
const expectIn = (hay, needle, what) => { if (!hay.includes(needle)) throw new Error(`${what}: expected "${needle}" in "${hay.slice(0, 160)}"`); };
// Test-only setup and fault injection straight on this run's temp database
// (a Switch room with imported links, a reply marked undelivered). The app
// itself has no endpoint for either.
function py(code) {
  return execFileSync("python3", ["-c", `import sys; sys.path.insert(0, ${JSON.stringify(APP)})\nfrom shiftpatch.db import Store\nfrom shiftpatch import roster\nstore = Store(${JSON.stringify(path.join(DATA, "shiftpatch.db"))})\n${code}`], { encoding: "utf8" });
}
const SW = "!e2e-switch:localhost";

let exitCode = 0;
const scriptRuns = {};
try {
  await step("landing renders (ko + en)", async () => {
    await page.goto(BASE + "/");
    await page.getByRole("heading", { name: /11월 9일\(월\) 13–17시 담당자가/ }).waitFor();
    await shot("01-landing-ko.png");
    await page.getByRole("button", { name: "English" }).click();
    await page.getByRole("heading", { name: /Minsu can't cover Monday 13:00–17:00/ }).waitFor();
    await shot("01b-landing-en.png");
    await page.getByRole("button", { name: "한국어" }).click();
  });

  await step("OCR: ambiguous synthetic image is flagged and import stays blocked", async () => {
    await page.goto(BASE + "/#/import");
    await page.setInputFiles("#imgfile", path.join(APP, "fixtures", "ocr", "ambiguous.png"));
    await page.locator(".grid input").first().waitFor({ timeout: 90000 });
    const checks = await page.locator(".checks").innerText();
    expectIn(checks, "연도", "missing-year warning");
    expectIn(checks, "오전·오후", "am/pm warning");
    if (!(await page.getByRole("button", { name: "초기 근무표 등록" }).isDisabled())) throw new Error("approve should be disabled");
    await shot("02-ocr-review-ambiguous.png");
    await page.getByRole("button", { name: "버리기" }).click();
  });

  await step("OCR: unsupported layout falls back to CSV/manual", async () => {
    await page.setInputFiles("#imgfile", path.join(APP, "fixtures", "ocr", "unsupported.png"));
    await page.getByText("이 표 모양은 아직 읽지 못합니다").waitFor({ timeout: 90000 });
    await page.getByRole("button", { name: "버리기" }).click();
  });

  await step("OCR: clear image → confirm account links → explicit approval → board", async () => {
    await page.setInputFiles("#imgfile", path.join(APP, "fixtures", "ocr", "clear.png"));
    await page.locator(".grid input").first().waitFor({ timeout: 90000 });
    const vals = await page.locator(".grid input").evaluateAll((ns) => ns.map((n) => n.value));
    if (vals.join("|") !== "지안|2026-11-09|09:00|13:00|일반 문의|민수|2026-11-09|13:00|17:00|일반 문의|태오|2026-11-09|17:00|18:00|일반 문의")
      throw new Error("OCR values differ: " + vals.join("|"));
    expectIn(await page.locator(".checks").innerText(), "계정 연결을 확인하지 않았습니다", "mapping must be confirmed");
    const opts = await page.locator(".maprow select").first().locator("option").allInnerTexts();
    if (!opts.some((o) => o.includes("local:jian"))) throw new Error("local room should list synthetic local accounts: " + opts.join("|"));
    expectIn(await page.locator("#review").innerText(), "고정된 합성 계정", "local accounts labelled synthetic");
    for (const cb of await page.locator(".maprow input[type=checkbox]").all()) { await cb.check(); await page.waitForTimeout(150); }
    await page.locator(".grid input").first().waitFor();
    await shot("03-ocr-review-clear.png");
    await page.getByRole("button", { name: "초기 근무표 등록" }).click();
    await page.getByRole("alert").filter({ hasText: "확인했습니다" }).waitFor();   // blocked until the box is ticked
    await page.locator("#approve").check();
    await page.getByRole("button", { name: "초기 근무표 등록" }).click();
    await page.getByText("빈 시간이 없습니다").waitFor();
    await shot("04-board-initial.png");
  });

  await step("chat: tentative inability asks first, then yes opens 13–17", async () => {
    await page.goto(BASE + "/#/room");
    await page.locator("#msg").waitFor();
    const script = await page.locator(".script").innerText();
    if (script.includes("?")) throw new Error("demo script shows a placeholder: " + script);
    let r = await send("민수", "@ShiftPatch 월요일 13~17시 고객문의 응대 못 할 것 같아요");
    expectIn(r, "'불가'로 기록할까요", "clarification");
    r = await send("민수", "@ShiftPatch 네");
    expectIn(r, "13:00–17:00이 비었습니다", "gap opened (first notice, not 'again')");
    if (r.includes("다시 비었습니다")) throw new Error("first notice must not say 다시: " + r);
  });

  await step("chat: invalid clock time and ranged withdrawal change only what was asked", async () => {
    let r = await send("지안", "@ShiftPatch 가능 13:60-15:00");
    expectIn(r, "분은 00–59", "13:60 refused");
    r = await send("지안", "@ShiftPatch 가능 13:00-17:00");
    expectIn(r, "가능으로 기록했습니다", "availability 13–17");
    r = await send("지안", "@ShiftPatch 가능 취소 15:00-17:00");
    expectIn(r, "남은 가능 시간: 13:00–15:00", "only 15–17 withdrawn");
  });

  await step("chat: availability, proposal, self acceptance, proxy refused, manager confirms", async () => {
    let r = await send("지안", "@ShiftPatch 점심 먹고 두 시간은 돼요");
    expectIn(r, "AI 해석이 지금 꺼져", "AI-off notice (no fake AI)");
    r = await send("태오", "@ShiftPatch 가능 2026-11-09 15:00-17:00");
    const pid = (r.match(/새 대체안 (P\d+)/) || [])[1];
    if (!pid) throw new Error("no proposal id in: " + r);
    expectIn(r, `지안: \`수락 ${pid}-a\` · 태오: \`수락 ${pid}-b\``, "reply names the real part IDs");
    r = await send("서연", `@ShiftPatch 수락 ${pid}-a`);
    expectIn(r, "본인에게 제안된 구간만", "proxy acceptance refused");
    r = await send("지안", `@ShiftPatch 수락 ${pid}-a`);
    expectIn(r, "남은 수락: 태오", "waiting for Taeo");
    r = await send("서연", `@ShiftPatch 확정 ${pid}`);
    expectIn(r, "아직 수락하지 않은 구간", "confirm blocked until all accept");
    r = await send("태오", `@ShiftPatch 수락 ${pid}-b`);
    expectIn(r, "필요한 수락이 모두 모였습니다", "all accepted");
    r = await send("서연", `@ShiftPatch 확정 ${pid}`);
    expectIn(r, "빈 시간이 없습니다", "confirmed");
    await shot("05-room-after-confirm.png", false);
    globalThis.PID = pid;
  });

  await step("board + CSV show the same confirmed coverage", async () => {
    let r = await send("서연", "@ShiftPatch 내보내기");
    await page.waitForFunction(() => [...document.querySelectorAll(".bubble.agent .tx")].some((n) => n.innerText.includes("파일을 만들었습니다")), null, { timeout: 15000 });
    await page.goto(BASE + "/#/board");
    await page.locator(".banner.clear").waitFor();
    await shot("06-board-confirmed.png");
    const table = await page.locator("table tbody tr").evaluateAll((rs) => rs.map((r) => [...r.children].map((c) => c.innerText.trim()).join("|")));
    const [dl] = await Promise.all([page.waitForEvent("download"), page.locator(".exports a").first().click()]);
    const csv = readFileSync(await dl.path(), "utf8").replace(/^﻿/, "").trim().split(/\r?\n/).slice(1).map((l) => l.split(","));
    const fromCsv = csv.map((c) => `${c[2]}–${c[3]}|${c[4] || "—"}|${c[6]}`);
    if (JSON.stringify(fromCsv) !== JSON.stringify(table)) throw new Error(`CSV ${JSON.stringify(fromCsv)} != board ${JSON.stringify(table)}`);
    writeFileSync(path.join(APP, "qa", "e2e-download-sample.csv"), readFileSync(await dl.path()));
  });

  await step("after confirmation Jian drops 13–15: only that interval reopens, old plan cannot re-confirm", async () => {
    await page.goto(BASE + "/#/room");
    await page.locator("#msg").waitFor();
    let r = await send("지안", "@ShiftPatch 불가 2026-11-09 13:00-15:00");
    expectIn(r, "13:00–15:00이 다시 비었습니다", "reopened");
    expectIn(r, "태오님의 15:00–17:00은 유지됩니다", "Taeo kept");
    r = await send("서연", `@ShiftPatch 확정 ${globalThis.PID}`);
    expectIn(r, "앞서 확정됐습니다", "old plan refused");
    expectIn(r, "지안님의 13:00–15:00이 빠져서", "refusal says what changed");
    await shot("07-room-after-drop.png", false);
    await page.goto(BASE + "/#/board");
    await page.locator(".banner.gap").getByText("13:00–15:00 담당자가 없습니다").waitFor();
    const badge = await page.locator(".prop.confirmed .reopened").innerText();
    expectIn(badge, "앞서 확정 · 13:00–15:00 다시 모집", "derived reopened badge");
    expectIn(await page.locator(".prop.confirmed .tag.okk").first().innerText(), "확정됨", "history kept as confirmed");
    const rows = await page.locator("table tbody tr").evaluateAll((rs) => rs.map((r) => r.innerText.replace(/\s+/g, " ").trim()));
    const want = ["09:00–13:00 지안 원 근무", "13:00–15:00 — 미해결", "15:00–17:00 태오 대체 확정", "17:00–18:00 태오 원 근무"];
    if (JSON.stringify(rows) !== JSON.stringify(want)) throw new Error("rows " + JSON.stringify(rows));
    await shot("08-board-gap-reopened.png");
    await page.getByRole("button", { name: "English" }).click();
    await page.getByText("13:00–15:00 has nobody assigned").waitFor();
    expectIn(await page.locator(".prop.confirmed .reopened").innerText(), "confirmed earlier · 13:00–15:00 reopened", "EN badge");
    expectIn(await page.locator(".boardhead").first().innerText(), "General customer support", "EN duty name");
    await shot("08b-board-gap-reopened-en.png");
    await page.getByRole("button", { name: "한국어" }).click();
  });

  await step("board: an undelivered reply is shown and sent again without changing the record", async () => {
    const before = await page.evaluate(async () => (await (await fetch("/api/state")).json()));
    // synthetic fault: mark the newest delivered reply as failed, as if the chat server had refused it six times
    py("with store.tx() as c:\n    c.execute(\"UPDATE outbox SET state='failed', attempts=6, last_error='OSError: synthetic outage (e2e)' WHERE id=(SELECT MAX(id) FROM outbox WHERE room_id='local-demo')\")");
    await page.goto(BASE + "/#/board");
    await page.locator("#delivery").getByText("채팅방에 전달되지 않았습니다").waitFor();
    expectIn(await page.locator("#delivery").innerText(), "synthetic outage (e2e)", "error shown");
    await shot("12-board-delivery-failed.png");
    await page.locator("#delivery").getByRole("button", { name: "답장 다시 보내기" }).click();
    await page.waitForFunction(() => !document.getElementById("delivery"), null, { timeout: 15000 });
    const delayed = (st) => st.transcript.filter((m) => m.kind === "agent" && m.body.startsWith("(늦게 전달되는 답장입니다)"));
    let after;
    for (let i = 0; i < 50; i++) {
      after = await (await fetch(BASE + "/api/state")).json();
      if (delayed(after).length) break;
      await page.waitForTimeout(300);
    }
    if (after.room.version !== before.room.version) throw new Error(`version changed ${before.room.version} → ${after.room.version}`);
    if (after.history.length !== before.history.length) throw new Error("history changed on reply retry");
    if (delayed(after).length !== 1) throw new Error("expected one delayed reply, got " + delayed(after).length + " outbox=" + JSON.stringify(after.outbox));
  });

  await step("Switch room review lists the linked participant IDs and blocks an unlinked person", async () => {
    py(`roster.create_room(store, ${JSON.stringify(SW)}, "switch", "e2e Switch room (synthetic, no server)")\nroster.import_switch_links(store, ${JSON.stringify(SW)}, {"@e2e-seoyeon:localhost": "seoyeon", "@e2e-minsu:localhost": "minsu", "@e2e-jian:localhost": "jian"})`);
    const q = "?room=" + encodeURIComponent(SW);
    await page.goto(BASE + "/" + q + "#/import");
    expectIn(await page.locator("h1 + p + p").innerText(), "Switch 방", "import target shown");
    await page.getByRole("button", { name: "합성 예시 CSV" }).click();
    await page.locator(".maprow").first().waitFor();
    const opts = (await page.locator(".maprow select").first().locator("option").allInnerTexts()).join("|");
    expectIn(opts, "@e2e-jian:localhost", "real linked ID shown");
    expectIn(opts, "Switch 계정 연결 없음", "unlinked person marked");
    if (opts.includes("local:")) throw new Error("Switch room must not show local: accounts: " + opts);
    for (const cb of await page.locator(".maprow input[type=checkbox]").all()) { await cb.check(); await page.waitForTimeout(150); }
    expectIn(await page.locator(".checks").innerText(), "연결된 Switch 계정이 없습니다", "unlinked blocks import");
    if (!(await page.getByRole("button", { name: "초기 근무표 등록" }).isDisabled())) throw new Error("approve should be disabled");
    await shot("13-switch-review-unlinked.png");
    await page.getByRole("button", { name: "버리기" }).click();
    py(`roster.import_switch_links(store, ${JSON.stringify(SW)}, {"@e2e-seoyeon:localhost": "seoyeon", "@e2e-minsu:localhost": "minsu", "@e2e-jian:localhost": "jian", "@e2e-taeo:localhost": "taeo"})`);
    await page.getByRole("button", { name: "합성 예시 CSV" }).click();
    await page.locator(".maprow").first().waitFor();
    for (const cb of await page.locator(".maprow input[type=checkbox]").all()) { await cb.check(); await page.waitForTimeout(150); }
    await page.locator("#approve").check();
    await page.getByRole("button", { name: "초기 근무표 등록" }).click();
    await page.getByText("빈 시간이 없습니다").waitFor();
    expectIn(await page.locator(".boardhead").first().innerText(), "Switch 방", "board names the Switch room");
    await page.goto(BASE + "/" + q + "#/room");
    await page.getByText("이 화면에서 대신 보낼 수 없습니다").waitFor();
    // Same request the actor picker would make, with the page's own token, sent from Node so the
    // expected 403 does not show up as a browser console error.
    const token = await page.evaluate(() => document.querySelector('meta[name="shiftpatch-token"]').content);
    const res = await fetch(`${BASE}/api/demo/message?room=${encodeURIComponent(SW)}`, { method: "POST",
      headers: { "X-ShiftPatch-Token": token, "Content-Type": "application/json", Origin: BASE },
      body: JSON.stringify({ actor: "seoyeon", body: "@ShiftPatch 확정 P1" }) });
    if (res.status !== 403) throw new Error("actor picker reached a Switch room: HTTP " + res.status);
  });

  // The room's own numbered script, AI off, clicked exactly as a first-time
  // reviewer would: press the script line, press Send, repeat. No command is
  // typed by the test; disabled lines are skipped only if the page marks them
  // skipped. Ends at the split confirmation and Jian's 13–15 reopening.
  async function runScriptAsShown(L) {
    page.once("dialog", (d) => d.accept());
    await page.goto(BASE + "/#/room");
    await page.getByRole("button", { name: L.reset }).click();
    await page.getByRole("button", { name: L.sample }).click();
    await page.locator(".maprow").first().waitFor();
    for (const cb of await page.locator(".maprow input[type=checkbox]").all()) { await cb.check(); await page.waitForTimeout(150); }
    await page.locator("#approve").check();
    await page.getByRole("button", { name: L.approve }).click();
    await page.getByText(L.noGap).first().waitFor();
    await page.goto(BASE + "/#/room");
    await page.locator("#msg").waitFor();
    expectIn(await page.locator("#script-mode").innerText(), L.modeOff, "script says AI is off");
    const log = [];
    const total = await page.locator(".script li").count();
    if (total !== 13) throw new Error("script has " + total + " lines");
    for (let i = 0; i < total; i++) {
      const btn = page.locator(".script li").nth(i).locator("button");
      const label = await btn.innerText();
      if (await btn.isDisabled()) {
        if (!label.includes(L.skipped)) throw new Error(`line ${i + 1} is disabled but not marked skipped: ${label}`);
        log.push({ line: i + 1, skipped: label });
        continue;
      }
      await btn.click();
      const text = await page.inputValue("#msg");
      const n = await page.locator(".bubble.agent").count();
      await page.getByRole("button", { name: L.send, exact: true }).click();
      await page.waitForFunction((k) => document.querySelectorAll(".bubble.agent").length > k, n, { timeout: 15000 });
      await page.getByRole("button", { name: L.send, exact: true }).waitFor();          // Send is back (not "Sending…")
      log.push({ line: i + 1, sent: text, reply: (await page.locator(".bubble.agent .tx").last().innerText()).slice(0, 200) });
    }
    const skipped = log.filter((x) => x.skipped).map((x) => x.line);
    if (JSON.stringify(skipped) !== "[4,8]") throw new Error("skipped lines " + JSON.stringify(skipped));
    expectIn(log[11].reply, L.oldRefused, "line 12: earlier plan cannot be confirmed again");
    await page.goto(BASE + "/#/board");
    await page.locator(".banner.gap").getByText(L.gap).waitFor();
    expectIn(await page.locator(".prop.confirmed .reopened").innerText(), L.badge, "reopened badge");
    const rows = await page.locator("table tbody tr").evaluateAll((rs) => rs.map((r) => r.innerText.replace(/\s+/g, " ").trim()));
    if (JSON.stringify(rows) !== JSON.stringify(L.rows)) throw new Error("rows " + JSON.stringify(rows));
    return log;
  }
  await step("AI off: the room's own Korean script, clicked line by line, reaches split confirm and reopens only Jian 13–15", async () => {
    scriptRuns.ko = await runScriptAsShown({ reset: "시연 초기화", sample: "합성 예시 CSV로 시작", approve: "초기 근무표 등록",
      noGap: "빈 시간이 없습니다", modeOff: "AI 해석이 꺼져", skipped: "건너뜀", send: "보내기", oldRefused: "앞서 확정됐습니다",
      gap: "13:00–15:00 담당자가 없습니다", badge: "앞서 확정 · 13:00–15:00 다시 모집",
      rows: ["09:00–13:00 지안 원 근무", "13:00–15:00 — 미해결", "15:00–17:00 태오 대체 확정", "17:00–18:00 태오 원 근무"] });
    await shot("14-room-script-ai-off-ko.png", false);
  });
  await step("AI off: the same script in English reaches the same result", async () => {
    await page.getByRole("button", { name: "English" }).click();
    scriptRuns.en = await runScriptAsShown({ reset: "Reset demo", sample: "Start with the synthetic CSV", approve: "Import initial roster",
      noGap: "No gaps", modeOff: "AI reading is off", skipped: "skipped", send: "Send", oldRefused: "confirmed earlier",
      gap: "13:00–15:00 has nobody assigned", badge: "confirmed earlier · 13:00–15:00 reopened",
      rows: ["09:00–13:00 Jian original", "13:00–15:00 — uncovered", "15:00–17:00 Taeo confirmed", "17:00–18:00 Taeo original"] });
    await page.getByRole("button", { name: "한국어" }).click();
  });

  await step("narrow viewport and connection page", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(BASE + "/#/board");
    await page.locator(".banner.gap").waitFor();
    await shot("09-board-mobile.png", false);   // viewport only: full-page capture tiles at this width
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(BASE + "/#/connect");
    await page.getByText("막힘(BLOCKED)").waitFor();
    // Let layout settle after the viewport change; a full-page capture taken
    // at once sometimes repeated the top of the page halfway down.
    await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
    await shot("10-connect-blocked.png");
  });

  await step("no browser console errors", async () => {
    if (consoleErrors.length) throw new Error(consoleErrors.join(" | "));
  });
} catch (e) {
  exitCode = 1;
  await page.screenshot({ path: path.join(APP, "qa", "e2e-failure.png"), fullPage: true }).catch(() => {});
} finally {
  await browser.close();
  server.kill("SIGTERM");
}
// The server must stop cleanly on SIGTERM: exit 0, a "stopped" line, and
// nothing on stderr but its request log (ResourceWarnings are switched on).
const exited = await Promise.race([serverExit, new Promise((r) => setTimeout(() => r({ code: null, signal: "timeout" }), 20000))]);
const unexpected = serverErr.split("\n").filter((l) => l.trim() && !/^(GET|POST|PUT|DELETE|HEAD|OPTIONS) \//.test(l));
const shutdown = { exit: exited, stopped_line: serverOut.includes("ShiftPatch stopped"), stderr_unexpected: unexpected.slice(0, 20) };
if (exited.code !== 0 || !shutdown.stopped_line || unexpected.length) exitCode = 1;
const result = { at: new Date().toISOString(), command: "node e2e/run.mjs", browser: "system Google Chrome via Playwright channel=chrome (headless)",
  ai: "off (SHIFTPATCH_AI=off) for determinism", port: PORT, duration_ms: Date.now() - t0, exit_code: exitCode, steps, console_errors: consoleErrors,
  script_runs: scriptRuns,
  server_shutdown: shutdown };
writeFileSync(path.join(APP, "qa", "e2e-result.json"), JSON.stringify(result, null, 2) + "\n");
console.log(JSON.stringify({ exit_code: exitCode, passed: steps.filter((s) => s.ok).length, failed: steps.filter((s) => !s.ok),
  server_shutdown: shutdown }, null, 1));
process.exit(exitCode);
