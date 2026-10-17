import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const require=createRequire(import.meta.url);
const {chromium}=require('../libexec/docking_universal/poseedit_renderer/node_modules/playwright');
const browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
try {
  const page=await browser.newPage({viewport:{width:1200,height:1000},deviceScaleFactor:1});
  await page.route(/^https?:/,route=>route.abort());
  await page.goto(pathToFileURL(process.argv[2]).href);
  await page.screenshot({path:process.argv[3],fullPage:true});
} finally {await browser.close();}
