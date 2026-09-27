const { chromium } = require('playwright');
const fs = require('node:fs');

(async () => {
  const outputRoot = process.argv[2];
  const outputFile = process.argv[3];
  if (!outputRoot || !outputFile) throw new Error('usage: render.cjs OUTPUT_ROOT OUTPUT_FILE');
  const deviceScaleFactor = Number(process.env.RENDER_SCALE || 1);
  if (!Number.isFinite(deviceScaleFactor) || deviceScaleFactor < 1 || deviceScaleFactor > 4) {
    throw new Error('RENDER_SCALE must be between 1 and 4');
  }
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROME_PATH,
  });
  const page = await browser.newPage({viewport: {width: 920, height: 620}, deviceScaleFactor});
  page.on('console', (message) => console.log(`browser:${message.type()}: ${message.text()}`));
  page.on('pageerror', (error) => console.error(`pageerror: ${error.stack || error}`));
  await page.goto('file://' + outputRoot + '/actual.html');
  await page.waitForTimeout(1000);
  console.log(await page.evaluate(() => ({done: window.__renderDone, error: window.__renderError})));
  const sceneJson = await page.evaluate(() => window.__sceneJson);
  const packingAudit=await page.evaluate(()=>window.__packingAudit);
  fs.writeFileSync(`${outputFile}.packing-audit.json`,JSON.stringify(packingAudit,null,2));
  if (sceneJson) fs.writeFileSync(`${outputFile}.scene.json`, sceneJson + '\n');
  const collisionAudit = await page.evaluate(() => {
    const residuePattern = /^(Ala|Arg|Asn|Asp|Cys|Gln|Glu|Gly|His|Ile|Leu|Lys|Met|Phe|Pro|Ser|Thr|Trp|Tyr|Val)\d+[A-Za-z]?/;
    const visibleTexts = [...document.querySelectorAll('#draw-area text')].filter(node => {
      const style = getComputedStyle(node);
      return style.display !== 'none' && style.visibility !== 'hidden' && !node.closest('[id*="_dbg"],[id*="_sc"]');
    });
    const targets = visibleTexts.filter(node =>
      node.parentElement?.id === 'draw-area_annotations' || residuePattern.test(node.textContent.trim())
    );
    const boxes = visibleTexts.map((node, index) => ({index,node,text:node.textContent.trim(),box:node.getBoundingClientRect()}));
    const overlaps = [];
    for (const target of targets) {
      const a = boxes.find(item => item.node === target);
      for (const b of boxes) {
        if (a.index >= b.index || !a.text || !b.text) continue;
        const x = Math.min(a.box.right,b.box.right)-Math.max(a.box.left,b.box.left);
        const y = Math.min(a.box.bottom,b.box.bottom)-Math.max(a.box.top,b.box.top);
        if (x > 1 && y > 1) overlaps.push({first:a.text,second:b.text,overlapArea:x*y});
      }
    }
    return {labelCount:targets.length,visibleTextCount:visibleTexts.length,overlapCount:overlaps.length,overlaps};
  });
  fs.writeFileSync(`${outputFile}.collision-audit.json`, JSON.stringify(collisionAudit, null, 2) + '\n');
  const crop = await page.evaluate(() => {
    const drawable = [...document.querySelectorAll('#draw-area path,#draw-area line,#draw-area polyline,#draw-area polygon,#draw-area circle,#draw-area text')]
      .filter(node => {
        const style = getComputedStyle(node);
        if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
        if (node.closest('[id*="selector"],[id*="mouse"],[id*="_dbg"],[id*="_sc"]')) return false;
        const visiblePaint = node.tagName.toLowerCase() === 'text' ||
          !['none', 'rgba(0, 0, 0, 0)'].includes(style.stroke) ||
          !['none', 'rgba(0, 0, 0, 0)'].includes(style.fill);
        const box = node.getBoundingClientRect();
        return visiblePaint && box.width > 0 && box.height > 0;
      });
    const boxes = drawable.map(node => node.getBoundingClientRect());
    const legendNode = document.getElementById('legend');
    if (legendNode && boxes.length) {
      const contentBottom = Math.max(...boxes.map(box => box.bottom));
      legendNode.style.bottom = 'auto';
      legendNode.style.top = `${Math.ceil(contentBottom + 12)}px`;
    }
    const legend = legendNode?.getBoundingClientRect();
    if (legend) boxes.push(legend);
    const pad = 10;
    const viewport = {width: innerWidth, height: innerHeight};
    const left = Math.max(0, Math.floor(Math.min(...boxes.map(box => box.left)) - pad));
    const top = Math.max(0, Math.floor(Math.min(...boxes.map(box => box.top)) - pad));
    const right = Math.min(viewport.width, Math.ceil(Math.max(...boxes.map(box => box.right)) + pad));
    const bottom = Math.min(viewport.height, Math.ceil(Math.max(...boxes.map(box => box.bottom)) + pad));
    return {x:left,y:top,width:right-left,height:bottom-top,topWhitespace:top,bottomWhitespace:viewport.height-bottom};
  });
  fs.writeFileSync(`${outputFile}.crop-audit.json`, JSON.stringify(crop, null, 2) + '\n');
  await page.screenshot({path: outputFile, clip:{x:crop.x,y:crop.y,width:crop.width,height:crop.height}});
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
