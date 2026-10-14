// Renders signal-trace.html frame by frame (deterministic, by seeking the CSS animations).
// Usage: node render.mjs <outDir> <width> <height> <fps> "<query string>" [transparent]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const [outDir, w, h, fps, query = '', transparent] = process.argv.slice(2);
const loop = Number(new URLSearchParams(query).get('t') || 5);
const frames = Math.round(loop * Number(fps));
mkdirSync(outDir, { recursive: true });

const page = await (await chromium.launch()).newPage({ viewport: { width: +w, height: +h } });
const here = path.dirname(fileURLToPath(import.meta.url));
await page.goto(pathToFileURL(path.join(here, 'signal-trace.html')).href + '?' + query);
await page.evaluate(() => document.getAnimations().forEach(a => a.pause()));

for (let i = 0; i < frames; i++) {
  const ms = (i / Number(fps)) * 1000;
  await page.evaluate(ms => document.getAnimations().forEach(a => { a.currentTime = ms; }), ms);
  await page.screenshot({ path: `${outDir}/f${String(i).padStart(4, '0')}.png`, omitBackground: !!transparent });
}
console.log(`${frames} frames -> ${outDir}`);
process.exit(0);
