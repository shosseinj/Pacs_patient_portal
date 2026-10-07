'use strict';
const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.PACS_TEST_URL;
const password = process.env.PACS_TEST_PASSWORD;
if (!base || !password) throw new Error('Set PACS_TEST_URL and PACS_TEST_PASSWORD for the isolated live fixture.');
const output = process.env.PACS_TEST_ARTIFACTS || path.join(__dirname, '..', 'test-artifacts');
fs.mkdirSync(output,{recursive:true});
const study = '1.2.826.0.1.3680043.10.543.9001';
async function login(page,username) {
  await page.goto(base+'/portal/login');
  await page.locator('[name=username]').fill(username);
  await page.locator('[name=password]').fill(password);
  await page.getByRole('button',{name:'ورود به حساب'}).click();
  await page.waitForURL(base+'/portal');
}
(async () => {
  const browser = await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE || chromium.executablePath(),args:['--no-sandbox']});
  const context = await browser.newContext({viewport:{width:1440,height:1000}});
  const page = await context.newPage();
  const errors = [], failed = [], frames = [];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('response',r=>{ if(r.url().includes('/dicom-web/') && r.status()>=400) failed.push({url:r.url(),status:r.status()}); if(r.url().includes('/frames/') && r.ok()) frames.push(r.url()); });
  try {
    await login(page,'operator.live');
    assert(await page.getByRole('heading',{name:'پرونده‌های تصویربرداری'}).isVisible());
    await page.screenshot({path:path.join(output,'operator.png'),fullPage:true});
    await page.getByRole('link',{name:'+ ثبت بیمار'}).click();
    const suffix=Date.now();
    for (const [name,value] of Object.entries({name:'بیمار تست مرورگر',record_number:'BROWSER-'+suffix,dicom_id:'BROWSER',issuer:'DEMO',username:'browser.'+suffix,password})) await page.locator(`[name=${name}]`).fill(value);
    await page.getByRole('button',{name:'ساخت پرونده و حساب بیمار'}).click();
    await page.waitForURL(/\/portal\/patients\/\d+$/);
    assert(await page.getByRole('heading',{name:'بیمار تست مرورگر'}).isVisible());
    await page.goto(base+'/portal/patients/1');
    await page.locator('#upload-files').setInputFiles(path.join(__dirname,'../examples/synthetic/demo-study.zip'));
    await page.getByRole('button',{name:'بارگذاری و پردازش'}).click();
    await page.waitForURL(/\/portal\/jobs\//);
    await page.getByRole('button',{name:'تأیید و نمایش به بیمار'}).waitFor({timeout:120000});
    const hiddenContext=await browser.newContext(); const hidden=await hiddenContext.newPage();
    await login(hidden,'patient.live');
    assert.equal((await hiddenContext.request.get(base+'/dicom-web/studies/'+study+'/metadata')).status(),404);
    await hiddenContext.close();
    await page.getByRole('button',{name:'تأیید و نمایش به بیمار'}).click();
    await page.getByText('این تصاویر در حساب بیمار قابل مشاهده‌اند.').waitFor();
    await page.getByRole('button',{name:'خروج'}).click();
    assert.equal((await context.request.get(base+'/api/session')).status(),401);
    await login(page,'patient.live');
    await page.getByRole('link',{name:'مشاهدهٔ تصاویر'}).click();
    await page.locator('iframe.viewer').waitFor();
    const viewer=page.frameLocator('iframe.viewer');
    await viewer.locator('canvas').first().waitFor({timeout:120000,state:'visible'});
    const confirm=viewer.getByRole('button',{name:'Confirm and hide'}); if(await confirm.isVisible()) await confirm.click();
    const skip=viewer.getByText('Skip all',{exact:true}); if(await skip.isVisible()) await skip.click();
    const started=Date.now();
    while(!frames.length && Date.now()-started<45000) await page.waitForTimeout(500);
    assert(frames.length>0,'OHIF must retrieve actual DICOM frames');
    await page.waitForTimeout(2500);
    if(await confirm.isVisible()) await confirm.click();
    await page.waitForTimeout(500);
    if(await skip.isVisible()) await skip.click();
    await page.waitForTimeout(300);
    await page.screenshot({path:path.join(output,'patient-viewer.png'),fullPage:true});
    // Inspect actual drawn pixels rather than treating an empty viewport as success.
    const image=await viewer.locator('canvas').first().evaluate(canvas=>{
      const copy=document.createElement('canvas');copy.width=canvas.width;copy.height=canvas.height;
      const ctx=copy.getContext('2d');ctx.drawImage(canvas,0,0);
      const data=ctx.getImageData(0,0,copy.width,copy.height).data;
      const levels=new Set();for(let i=0;i<data.length;i+=4) levels.add(data[i]+','+data[i+1]+','+data[i+2]);
      return {width:canvas.width,height:canvas.height,levels:levels.size};
    });
    assert(image.levels>20,'Viewport must contain rendered image pixels');
    await viewer.locator('canvas').first().hover();
    await page.mouse.wheel(0,150);
    let scrolled=false; for(let attempt=0;attempt<20;attempt++) { if(/I:\d+ \([2-8]\/8\)/.test(await viewer.locator('body').innerText())) { scrolled=true;break; } await page.waitForTimeout(200); }
    if(!scrolled) { fs.writeFileSync(path.join(output,'scroll-debug.txt'),await viewer.locator('body').innerText()); await page.screenshot({path:path.join(output,'scroll-debug.png'),fullPage:true}); }
    assert(scrolled,'Mouse wheel must select another slice');
    await page.setViewportSize({width:390,height:844});
    await page.goto(base+'/portal');
    assert(await page.getByRole('link',{name:'مشاهدهٔ تصاویر'}).isVisible());
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1));
    await page.screenshot({path:path.join(output,'patient-mobile.png'),fullPage:true});
    const otherContext=await browser.newContext();const other=await otherContext.newPage();
    await login(other,'other.live');
    assert.equal((await otherContext.request.get(base+'/portal/studies/'+study+'/view')).status(),404);
    assert.equal((await otherContext.request.get(base+'/dicom-web/studies/'+study+'/metadata')).status(),404);
    assert.equal((await otherContext.request.get(frames[0])).status(),404);
    await otherContext.close();
    assert.deepEqual(errors,[],'No browser JavaScript errors');
    assert.deepEqual(failed,[],'No authorized DICOMweb errors');
    fs.writeFileSync(path.join(output,'browser-result.json'),JSON.stringify({passed:true,scenarios:['operator login','create patient','ZIP upload','real Orthanc import','quarantine before release','explicit release','logout revocation','patient login','OHIF rendering','slice scrolling','mobile layout','other patient metadata/frame denial'],image,frameRequests:frames.length,errors,failed},null,2));
    console.log(JSON.stringify({passed:true,frameRequests:frames.length,image,errors,failed}));
  } finally {
    fs.writeFileSync(path.join(output,'browser-diagnostics.json'),JSON.stringify({errors,failed,frames},null,2));
    await browser.close();
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
