// Ad-hoc screenshot: node e2e/shot.mjs <url> <out.png> [width] [lang]
import { chromium } from "./pw.mjs";

const [url, out, width = "1280", lang = "ko"] = process.argv.slice(2);
const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: Number(width), height: 900 } });
await page.addInitScript((l) => localStorage.setItem("sp-lang", l), lang);
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
await page.goto(url);
await page.waitForTimeout(800);
await page.screenshot({ path: out, fullPage: true });
console.log(JSON.stringify({ out, errors }));
await browser.close();
