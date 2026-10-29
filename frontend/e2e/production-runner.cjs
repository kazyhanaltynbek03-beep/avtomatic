// Browser acceptance with an isolated database; no provider credentials or live API.
const { chromium } = require('playwright');
const { spawn, execFileSync } = require('node:child_process');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const http = require('node:http');
const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'qor-browser-'));
const backend=path.resolve(__dirname,'../../backend');
const python=process.env.QOR_E2E_PYTHON || 'python3';
const password=process.env.QOR_E2E_PASSWORD;
if(!password) throw Error('QOR_E2E_PASSWORD required');
const env={...process.env,DATABASE_URL:`sqlite:///${tmp}/test.db`,OWNER_EMAIL:'browser@qor.test',OWNER_PASSWORD:password,COOKIE_SECURE:'false',DEMO_MODE:'false',QOR_E2E_FIXTURE:'1',FRONTEND_DIST:path.resolve(__dirname,'../dist')};
const external=process.env.QOR_E2E_EXTERNAL_SERVER==='1';
if (!external) for(const args of [['-m','alembic','upgrade','head'],['-m','app.seed'],['-m','tests.e2e_seed']]) execFileSync(python,args,{cwd:backend,env,stdio:'pipe'});
const server=external ? null : spawn(python,['-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8012'],{cwd:backend,env,stdio:['ignore','pipe','pipe']});
let logs='';if (server) { server.stderr.on('data',x=>logs+=x);server.stdout.on('data',x=>logs+=x); }
const base='http://127.0.0.1:8012';
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const healthy=()=>new Promise(resolve=>{const req=http.get(base+'/api/health',r=>{r.resume();resolve(r.statusCode===200)});req.on('error',()=>resolve(false));req.setTimeout(1000,()=>{req.destroy();resolve(false)})});
(async()=>{
 let browser;
 try{
  for(let i=0;i<60 && !await healthy();i++) await sleep(200);
  assert(await healthy(),'Startup failed: '+logs);
  browser=await chromium.launch({headless:true});
  const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  page.on('response',r=>{if(r.url().includes('/api/')&&r.status()>=500)errors.push(r.url()+':'+r.status())});
  await page.goto(base);
  await page.getByLabel('Email').fill(env.OWNER_EMAIL);await page.getByLabel('Пароль').fill(password);
  await page.getByRole('button',{name:'Войти в систему'}).click();
  await page.getByRole('heading',{name:'Обзор бизнеса',exact:true}).waitFor();
  assert.equal(await page.getByText('ДЕМО-ДАННЫЕ',{exact:true}).count(),0);
  const auth=await (await page.request.get(base+'/api/auth/me')).json();
  const headers={'X-CSRF-Token':auth.csrf};
  let response=await page.request.post(base+'/api/admin/reconcile-marketplaces',{headers});assert.equal(response.status(),200,await response.text());
  await page.reload();await page.getByRole('heading',{name:'Обзор бизнеса',exact:true}).waitFor();
  await page.getByText('Себестоимость не заполнена для',{exact:false}).waitFor();
  const period='start=2026-10-01&end=2026-10-31&company_id=1';
  const report=await (await page.request.get(base+'/api/report?'+period)).json();
  assert.equal(report.revenue,73380800);assert.equal(report.net_profit,null);
  for(const name of ['Все продажи','Wildberries','Прибыль','Единый склад','Интеграции','Импорт / Экспорт']){
   await page.getByRole('button',{name,exact:true}).click();await page.getByRole('heading',{name,exact:true}).waitFor();
   if(name==='Все продажи') await page.getByRole('cell',{name:/Wildberries:1:wb-sale:WB-E2E-SALE/}).waitFor();
  }
  const sales=await (await page.request.get(base+'/api/data/sales')).json();assert.equal(sales.items.length,1);
  const opening={company_id:1,product_id:sales.items[0].product_id,reference:'BROWSER-OPEN',date:'2026-10-01',quantity:13,unit_cost:2000000,evidence:'Synthetic supplier invoice'};
  response=await page.request.post(base+'/api/post/opening',{headers,data:opening});assert.equal(response.status(),200,await response.text());
  const final=await (await page.request.get(base+'/api/report?'+period)).json();
  assert.equal(final.cogs,26000000);assert.equal(final.net_profit,37376285);assert.equal(final.revenue,73380800);
  response=await page.request.get(base+'/api/reports/executive.xlsx?'+period);assert.equal(response.status(),200);
  await page.getByRole('button',{name:'Прибыль',exact:true}).click();await page.reload();
  await page.getByRole('heading',{name:'Прибыль',exact:true}).waitFor();
  await page.getByTitle('Выйти').click();await page.getByRole('heading',{name:'Добро пожаловать'}).waitFor();
  assert.deepEqual(errors,[]);
  console.log('PASS: Chromium login, live badge, WB staging → Sale, all core pages, unknown profit, opening cost → FIFO/profit, XLSX, logout, no JS/HTTP500 errors.');
 }finally{if(browser)await browser.close();if(server)server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});
