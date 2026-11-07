// Which local browser can Playwright drive without downloading one?
import { chromium, webkit } from "./pw.mjs";

const tries = [
  ["chrome", () => chromium.launch({ channel: "chrome", headless: true })],
  ["msedge", () => chromium.launch({ channel: "msedge", headless: true })],
  ["chromium (bundled)", () => chromium.launch({ headless: true })],
  ["webkit (bundled)", () => webkit.launch({ headless: true })],
];
for (const [name, fn] of tries) {
  try {
    const b = await fn();
    console.log(`OK ${name} ${b.version()}`);
    await b.close();
  } catch (e) {
    console.log(`NO ${name}: ${String(e.message).split("\n")[0]}`);
  }
}
