/**
 * Optional: parse every generated .mmd with the real mermaid parser.
 *
 *   npm i mermaid playwright        # or point at copies you already have
 *   node tests/validate_mermaid.mjs design-explorer/assets
 *
 * Resolution order for both dependencies: CLI flag, env var, local
 * node_modules, then the global node_modules directory. Exits non-zero on the
 * first diagram that does not parse, and prints the parser's own message.
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const args = process.argv.slice(2);
const dir = args.find((a) => !a.startsWith("--")) || "assets";
const flag = (name) => {
  const hit = args.find((a) => a.startsWith(`--${name}=`));
  return hit ? hit.slice(name.length + 3) : "";
};

function resolveFile(candidates, what) {
  for (const c of candidates) {
    if (c && fs.existsSync(c)) return c;
  }
  console.error(`could not find ${what}. Tried:\n  ${candidates.filter(Boolean).join("\n  ")}`);
  process.exit(2);
}

const globalModules = "/opt/node22/lib/node_modules";
const mermaidPath = resolveFile([
  flag("mermaid"),
  process.env.MERMAID_LIB,
  "node_modules/mermaid/dist/mermaid.min.js",
  path.join(globalModules, "mermaid/dist/mermaid.min.js"),
], "mermaid.min.js");
const playwrightPath = resolveFile([
  flag("playwright"),
  process.env.PLAYWRIGHT_LIB,
  "node_modules/playwright/index.mjs",
  path.join(globalModules, "playwright/index.mjs"),
], "playwright");

const { chromium } = await import(playwrightPath);
const files = fs.readdirSync(dir).filter((f) => f.endsWith(".mmd")).sort();
if (!files.length) {
  console.error(`no .mmd files in ${dir}`);
  process.exit(2);
}
const defs = Object.fromEntries(files.map((f) => [f, fs.readFileSync(path.join(dir, f), "utf8")]));

const browser = await chromium.launch();
const page = await browser.newPage();
await page.setContent("<!doctype html><html><body></body></html>");
await page.addScriptTag({ content: fs.readFileSync(mermaidPath, "utf8") });
const results = await page.evaluate(async (defs) => {
  mermaid.initialize({ startOnLoad: false, securityLevel: "loose" });
  const out = [];
  for (const [name, code] of Object.entries(defs)) {
    try {
      await mermaid.parse(code);
      out.push([name, "OK"]);
    } catch (e) {
      out.push([name, String((e && e.message) || e).split("\n").slice(0, 4).join(" | ")]);
    }
  }
  return out;
}, defs);
await browser.close();

let failed = 0;
for (const [name, result] of results) {
  if (result === "OK") console.log(`  ok   ${name}`);
  else { failed++; console.log(`  FAIL ${name}\n       ${result}`); }
}
console.log(`\n${results.length - failed}/${results.length} diagrams parse`);
process.exit(failed ? 1 : 0);
