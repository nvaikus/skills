#!/usr/bin/env node
// Browser driver for `gdrive onboard --mode auto` (optional: Node + Playwright + Chrome).
// It ONLY drives the browser. All gdrive state lives in the Python job (src/api/autoconsole.py):
//   events -> stdout, one JSON object per line: {ev: state|email|project|audience|done|warn|
//             client_file|need_consent_url|redirect|fail, ...}
//   answers <- stdin, one JSON object per line: {consent_url} | {quit, close}
// `node console-auto.mjs --check` prints {ok, reason, chrome, playwright} and exits.
//
// Google sign-in refuses automated browsers ("This browser or app may not be secure"), so
// Chrome is started as a plain process with its own profile dir and a DevTools port; Playwright
// attaches over CDP only after the user is past sign-in (detected by polling /json/list over
// HTTP, which does not attach to the page).
// Console UI changes are the expected failure: every step looks for elements by role/label
// text, waits generously, and on a mismatch reports {ev: fail, step, msg, screenshot} so the
// Python side shows the manual text for that step.
import { createRequire } from 'node:module';
import { spawn, execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import readline from 'node:readline';

const require = createRequire(import.meta.url);
const MIN = 60_000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const emit = (obj) => process.stdout.write(JSON.stringify(obj) + '\n');
const log = (...a) => process.stderr.write(`[${new Date().toISOString()}] ${a.join(' ')}\n`);

class StepError extends Error {
  constructor(step, msg) { super(msg); this.step = step; }
}
class SignInNeeded extends Error {}

// ---- environment -----------------------------------------------------------------------------

function loadPlaywright() {
  const cands = [];
  if (process.env.GDRIVE_PLAYWRIGHT) cands.push(process.env.GDRIVE_PLAYWRIGHT);
  cands.push('playwright-core', 'playwright');
  let roots = [];
  try {
    roots.push(execFileSync('npm', ['root', '-g'], { encoding: 'utf8', timeout: 15000, stdio: ['ignore', 'pipe', 'ignore'] }).trim());
  } catch { /* npm missing: try the usual places */ }
  roots.push('/opt/homebrew/lib/node_modules', '/usr/local/lib/node_modules', '/usr/lib/node_modules',
    path.join(os.homedir(), '.npm-global/lib/node_modules'));
  if (process.env.APPDATA) roots.push(path.join(process.env.APPDATA, 'npm', 'node_modules'));
  for (const r of roots) {
    for (const sub of ['playwright-core', 'playwright', '@playwright/cli/node_modules/playwright-core',
      '@playwright/cli/node_modules/playwright', '@playwright/test/node_modules/playwright-core',
      '@playwright/mcp/node_modules/playwright-core']) cands.push(path.join(r, sub));
  }
  for (const c of cands) {
    try {
      const pw = require(c);
      if (pw?.chromium?.connectOverCDP) return { pw, where: c };
    } catch { /* next */ }
  }
  return null;
}

function findChrome(pw) {
  const env = process.env.GDRIVE_CHROME;
  const c = env ? [env] : [];
  if (process.platform === 'darwin') {
    for (const app of ['Google Chrome', 'Chromium', 'Microsoft Edge', 'Brave Browser']) {
      c.push(`/Applications/${app}.app/Contents/MacOS/${app}`, path.join(os.homedir(), `Applications/${app}.app/Contents/MacOS/${app}`));
    }
  } else if (process.platform === 'win32') {
    for (const base of [process.env.PROGRAMFILES, process.env['PROGRAMFILES(X86)'], process.env.LOCALAPPDATA]) {
      if (base) c.push(path.join(base, 'Google/Chrome/Application/chrome.exe'), path.join(base, 'Microsoft/Edge/Application/msedge.exe'));
    }
  } else {
    for (const bin of ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'microsoft-edge']) {
      for (const dir of (process.env.PATH || '').split(':')) c.push(path.join(dir, bin));
    }
  }
  try { if (pw) c.push(pw.chromium.executablePath()); } catch { /* not downloaded */ }
  return c.find((p) => p && fs.existsSync(p)) || null;
}

async function check() {
  const pw = loadPlaywright();
  const chrome = findChrome(pw?.pw);
  const reason = !pw ? 'Playwright not found (npm install -g @playwright/cli or playwright)' :
    !chrome ? 'no Chrome/Chromium browser found' : null;
  emit({ ok: !reason, reason, chrome, playwright: pw?.where || null });
}

// ---- stdin answers ---------------------------------------------------------------------------

const answers = [];
let waiter = null;
let stdinClosed = false;
readline.createInterface({ input: process.stdin }).on('line', (line) => {
  let obj;
  try { obj = JSON.parse(line); } catch { return; }
  answers.push(obj);
  if (waiter) { waiter(); waiter = null; }
}).on('close', () => { stdinClosed = true; if (waiter) { waiter(); waiter = null; } });

async function answer(key, timeoutMs) {
  const end = Date.now() + timeoutMs;
  for (;;) {
    const i = answers.findIndex((a) => key in a || a.quit);
    if (i >= 0) return answers.splice(i, 1)[0];
    if (stdinClosed || Date.now() > end) return { quit: true, close: false };
    await new Promise((r) => { waiter = r; setTimeout(r, 1000); });
  }
}

// ---- browser ---------------------------------------------------------------------------------

async function cdpJson(port, p, method = 'GET') {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 3000);
  try {
    const r = await fetch(`http://127.0.0.1:${port}${p}`, { method, signal: ctl.signal });
    return await r.json();
  } finally { clearTimeout(t); }
}

function portOf(dir) {
  try { return Number(fs.readFileSync(path.join(dir, 'DevToolsActivePort'), 'utf8').split('\n')[0]) || null; } catch { return null; }
}

// Google refuses to sign in a browser started with --remote-debugging-port ("Couldn't sign you in -
// this browser or app may not be secure", live 2026-10-01). So sign-in happens in a PLAIN Chrome
// (no debug port), we watch its cookie DB for the Google session cookie, then restart the same
// profile with the debug port - the session survives the restart.
function signedInCookie(dir) {
  const dbs = ['Default/Network/Cookies', 'Default/Cookies'].map((f) => path.join(dir, f)).filter((f) => fs.existsSync(f));
  if (!dbs.length) return false;
  const py = "import sqlite3,sys\nn=0\nfor f in sys.argv[1:]:\n  try:\n    c=sqlite3.connect('file:'+f+'?immutable=1',uri=True)\n    n+=c.execute(\"select count(*) from cookies where host_key='.google.com' and name in ('SID','__Secure-1PSID')\").fetchone()[0]\n  except Exception: pass\nprint(n)";
  try { return Number(execFileSync(process.env.GDRIVE_PYTHON || 'python3', ['-c', py, ...dbs], { encoding: 'utf8', timeout: 10_000 }).trim()) > 0; } catch { return false; }
}

function alive(pid) { try { process.kill(pid, 0); return true; } catch { return false; } }

async function plainSignIn(dir, chrome, startUrl, timeoutMs) {
  if (portOf(dir) || signedInCookie(dir)) return;
  const child = spawn(chrome, [`--user-data-dir=${dir}`, '--no-first-run', '--no-default-browser-check',
    '--lang=en-US', startUrl], { detached: true, stdio: 'ignore' });
  child.unref();
  emit({ ev: 'state', state: 'signin', step: 'signin', msg: 'waiting for you to sign in' });
  const end = Date.now() + timeoutMs;
  while (!signedInCookie(dir)) {
    if (!alive(child.pid)) throw new StepError('signin', 'the browser window was closed');
    if (Date.now() > end) throw new StepError('signin', `nobody signed in within ${Math.round(timeoutMs / MIN)} min`);
    await sleep(2000);
  }
  await sleep(5000); // let the post-login redirects settle and Chrome write its state
  try { process.kill(child.pid, 'SIGTERM'); } catch { /* gone */ }
  const stop = Date.now() + 20_000;
  while (alive(child.pid) && Date.now() < stop) await sleep(500);
  if (alive(child.pid)) try { process.kill(child.pid, 'SIGKILL'); } catch { /* gone */ }
  await sleep(1000);
}

async function openBrowser(plan, chrome, startUrl) {
  const dir = plan.browserDir;
  let port = portOf(dir);
  if (port) {
    try {
      await cdpJson(port, '/json/version');
      await cdpJson(port, `/json/new?${startUrl}`, 'PUT').catch(() => null);
      log('reusing the running browser on port', port);
      return { port, pid: null };
    } catch { /* stale file */ }
  }
  try { fs.unlinkSync(path.join(dir, 'DevToolsActivePort')); } catch { /* none */ }
  const child = spawn(chrome, [`--user-data-dir=${dir}`, '--remote-debugging-port=0', '--no-first-run',
    '--no-default-browser-check', '--lang=en-US', startUrl], { detached: true, stdio: 'ignore' });
  child.unref();
  const end = Date.now() + 45_000;
  while (Date.now() < end) {
    port = portOf(dir);
    if (port) {
      try { await cdpJson(port, '/json/version'); return { port, pid: child.pid }; } catch { /* starting */ }
    }
    await sleep(500);
  }
  throw new StepError('browser', `Chrome did not start (${chrome})`);
}

// Signed in = a console page that STAYS on console.cloud.google.com for ~8 s with no sign-in page
// open (live: a signed-out console URL shows for a moment before it redirects to sign-in).
async function waitSignedIn(port, timeoutMs) {
  const end = Date.now() + timeoutMs;
  let announced = false;
  let stable = 0;
  while (Date.now() < end) {
    let pages;
    try { pages = (await cdpJson(port, '/json/list')).filter((t) => t.type === 'page'); } catch {
      throw new StepError('signin', 'the browser window was closed');
    }
    if (!pages.length) throw new StepError('signin', 'the browser window was closed');
    const onConsole = pages.some((p) => p.url.startsWith('https://console.cloud.google.com'));
    const onSignin = pages.some((p) => p.url.startsWith('https://accounts.google.com'));
    stable = onConsole && !onSignin ? stable + 1 : 0;
    if (stable >= 4) return;
    if (!announced && onSignin) {
      emit({ ev: 'state', state: 'signin', step: 'signin', msg: 'waiting for you to sign in' });
      announced = true;
    }
    await sleep(2000);
  }
  throw new StepError('signin', `nobody signed in within ${Math.round(timeoutMs / MIN)} min`);
}

// ---- page helpers ----------------------------------------------------------------------------

let page;
let plan;
const vis = (loc) => loc.filter({ visible: true }).first();
const btn = (name) => vis(page.getByRole('button', { name }));

async function shown(loc, ms = 10_000) {
  try { await loc.waitFor({ state: 'visible', timeout: ms }); return true; } catch { return false; }
}

async function bodyText() {
  try { return await page.locator('body').innerText({ timeout: 10_000 }); } catch { return ''; }
}

async function shot(step) {
  const p = path.join(plan.shotsDir, `${step}-${Date.now()}.png`);
  try { await page.screenshot({ path: p, fullPage: false, timeout: 15_000 }); } catch { /* the dump still helps */ }
  // page dump next to the screenshot: what the agent reads to see where it is stuck
  let tree = '';
  try { tree = await page.locator('body').ariaSnapshot({ timeout: 10_000 }); } catch { tree = await bodyText(); }
  const title = await page.title().catch(() => '');
  try { fs.writeFileSync(p.replace(/\.png$/, '.txt'), `url: ${page.url()}\ntitle: ${title}\n\n${tree}\n`); } catch { /* disk */ }
  return p;
}

// stall watchdog: a step whose page has not changed for its expected time leaves a dump once per page
const STALL_MS = { project: 60_000, apis: 90_000, consent: 60_000, branding: 60_000, publish: 60_000, client: 90_000, login: 30_000 };
let current = { step: null, since: 0, page: '', dumped: '' };
async function watchdog() {
  if (!page || !current.step) return;
  const fp = `${page.url()}|${(await bodyText()).length}`;
  if (fp !== current.page) { current.page = fp; current.since = Date.now(); return; }
  if (Date.now() - current.since < (STALL_MS[current.step] || 60_000) || current.dumped === fp) return;
  current.dumped = fp;
  const p = await shot(`${current.step}-stall`);
  emit({ ev: 'warn', step: current.step, msg: `page unchanged for ${Math.round((Date.now() - current.since) / 1000)} s on ${page.url().slice(0, 120)} - dump ${p && p.replace(/\.png$/, '.txt')}`, screenshot: p });
}

function withHl(url) {
  return url + (url.includes('?') ? '&' : '?') + 'hl=en';
}

async function go(url) {
  await page.goto(withHl(url), { waitUntil: 'domcontentloaded', timeout: 90_000 });
  await page.waitForLoadState('load', { timeout: 30_000 }).catch(() => null);
  await sleep(2500);
  if (page.url().startsWith('https://accounts.google.com')) throw new SignInNeeded('signed out');
  await handleTerms();
  // live 2026-10-01: the cookie bar at the bottom swallows clicks on SAVE
  await clickIf(vis(page.locator('.glue-cookie-notification-bar').getByRole('button')), 1500).catch(() => false);
}

async function reloaded() {
  await page.reload({ waitUntil: 'domcontentloaded', timeout: 90_000 });
  await page.waitForLoadState('load', { timeout: 30_000 }).catch(() => null);
  await sleep(4000);
}

const inputValues = () => page.locator('input').evaluateAll((els) => els.map((e) => e.value)).catch(() => []);

async function fillBox(loc, value) {
  await loc.click({ timeout: 15_000 });
  await loc.fill('');
  await loc.fill(value);
}

async function clickIf(loc, ms = 8000) {
  if (!(await shown(loc, ms))) return false;
  await loc.click({ timeout: 15_000 });
  return true;
}

async function chooseOption(box, re) {
  await box.click({ timeout: 15_000 });
  const opt = vis(page.getByRole('option', { name: re }));
  if (!(await shown(opt, 10_000))) return false;
  await opt.click();
  return true;
}

// New Cloud users get a "Welcome / Terms of Service" dialog: that agreement is the user's own
// click (we only wait for it).
async function handleTerms() {
  const dlg = vis(page.getByRole('dialog').filter({ hasText: /terms of service/i }));
  if (!(await shown(dlg, 2000))) return;
  emit({ ev: 'state', state: 'terms', step: 'terms', msg: 'waiting for you to accept the Google Cloud terms' });
  try {
    await dlg.waitFor({ state: 'hidden', timeout: 10 * MIN });
  } catch { throw new StepError('terms', 'the Google Cloud terms were not accepted within 10 minutes'); }
  emit({ ev: 'state', state: 'working', step: 'project', msg: 'continuing' });
  await sleep(2000);
}

async function detectEmail() {
  if (plan.email) return plan.email;
  try {
    const labels = await page.locator('[aria-label*="@"]').evaluateAll((els) => els.map((e) => e.getAttribute('aria-label')));
    for (const l of labels) {
      const m = /[\w.+-]+@[\w-]+(\.[\w-]+)+/.exec(l || '');
      if (m) return m[0];
    }
  } catch { /* fall through */ }
  return null;
}

function working(step, msg) {
  current = { step, since: Date.now(), page: '', dumped: '' };
  emit({ ev: 'state', state: 'working', step, msg });
  log('step', step, msg);
}

// ---- console steps ---------------------------------------------------------------------------

async function stepProject() {
  working('project', 'creating the project');
  await go(`${plan.console}/projectcreate`);
  const name = vis(page.getByLabel(/project name/i));
  if (!(await shown(name, 60_000))) throw new StepError('project', 'the "New Project" form did not appear');
  await fillBox(name, plan.projectName);
  await sleep(3000);
  const m = /Project ID:?\s*([a-z][a-z0-9-]{4,28}[a-z0-9])/.exec(await bodyText());
  if (!m) throw new StepError('project', 'could not read the Project ID on the form');
  const id = m[1];
  const create = btn(/^\s*create\s*$/i);
  if (!(await shown(create, 15_000))) throw new StepError('project', 'no CREATE button');
  await create.click();
  const end = Date.now() + 3 * MIN;
  while (Date.now() < end && page.url().includes('/projectcreate')) await sleep(1000);
  if (page.url().includes('/projectcreate')) {
    const t = await bodyText();
    const quota = /quota|limit/i.test(t) ? ' (Google says the project limit is reached)' : '';
    throw new StepError('project', `the project was not created${quota}`);
  }
  await sleep(10_000); // a new project needs a moment before APIs can be enabled
  plan.projectId = id;
  emit({ ev: 'project', id });
}

async function stepApis() {
  working('apis', 'switching on Drive, Docs and Sheets');
  const url = `${plan.console}/flows/enableapi?apiid=${plan.apis.join(',')}&project=${plan.projectId}`;
  for (let attempt = 1; attempt <= 4; attempt++) {
    await go(url);
    await clickIf(btn(/^\s*next\s*$/i), 30_000);
    const enable = btn(/^\s*enable\s*$/i);
    if (await shown(enable, 30_000)) {
      await enable.click();
      try { await enable.waitFor({ state: 'hidden', timeout: 3 * MIN }); } catch { /* checked below */ }
    }
    await sleep(3000);
    const t = await bodyText();
    if (!page.url().includes('/flows/enableapi') || /\b(enabled|already enabled)\b/i.test(t) && !(await shown(btn(/^\s*enable\s*$/i), 2000))) {
      emit({ ev: 'done', step: 'apis' });
      return;
    }
    log('apis attempt', attempt, 'not confirmed yet; retrying in 20 s');
    await sleep(20_000);
  }
  throw new StepError('apis', 'Google did not confirm the APIs as enabled');
}

async function stepConsent() {
  working('consent', 'naming the app (consent screen)');
  await go(`${plan.console}/auth/overview?project=${plan.projectId}`);
  // live 2026-10-01: "Get started" is a LINK, and the unconfigured page also says "OAuth Overview"
  const start = vis(page.getByRole('button', { name: /get started/i }).or(page.getByRole('link', { name: /get started/i })));
  if (!(await shown(start, 45_000))) {
    const body = await bodyText();
    if (!/not configured yet/i.test(body) && /create oauth client|metrics/i.test(body)) {
      emit({ ev: 'done', step: 'consent' });
      return;
    }
    throw new StepError('consent', 'no GET STARTED button on the OAuth overview page');
  }
  await start.click();
  const appName = vis(page.getByLabel(/app name/i));
  if (!(await shown(appName, 30_000))) throw new StepError('consent', 'the "App name" box did not appear');
  await fillBox(appName, plan.appName);
  const support = vis(page.getByLabel(/user support email/i));
  if (!(await shown(support, 10_000))) throw new StepError('consent', 'no "User support email" box');
  const email = plan.email;
  if (!(await chooseOption(support, email ? new RegExp(email.replace(/[.+]/g, '\\$&'), 'i') : /@/))) {
    if (!(await chooseOption(support, /@/))) throw new StepError('consent', 'could not choose the support email');
  }
  if (!plan.email) {
    const m = /[\w.+-]+@[\w-]+(\.[\w-]+)+/.exec(await support.innerText().catch(() => '') || await bodyText());
    if (m) { plan.email = m[0]; emit({ ev: 'email', email: plan.email }); }
  }
  if (!(await clickIf(btn(/^\s*next\s*$/i), 10_000))) throw new StepError('consent', 'no NEXT after App information');
  // Audience: Internal exists only for Workspace accounts (disabled otherwise)
  const internal = vis(page.getByRole('radio', { name: /internal/i }));
  const external = vis(page.getByRole('radio', { name: /external/i }));
  if (!(await shown(external, 20_000))) throw new StepError('consent', 'no Internal/External choice');
  let kind = 'external';
  if (await shown(internal, 2000) && await internal.isEnabled().catch(() => false)) {
    await internal.check({ timeout: 10_000 }).catch(() => internal.click());
    kind = (await internal.isChecked().catch(() => false)) ? 'internal' : 'external';
  }
  if (kind === 'external') await external.check({ timeout: 10_000 }).catch(() => external.click());
  if (!(await clickIf(btn(/^\s*next\s*$/i), 10_000))) throw new StepError('consent', 'no NEXT after Audience');
  const contact = vis(page.getByLabel(/email address|text field for emails/i));
  if (!(await shown(contact, 20_000))) throw new StepError('consent', 'no contact "Email addresses" box');
  if (!plan.email) throw new StepError('consent', 'could not find your email address on the page');
  await contact.fill(plan.email);
  await contact.press('Enter');
  await sleep(800);
  if (!(await clickIf(btn(/^\s*next\s*$/i), 10_000))) throw new StepError('consent', 'no NEXT after Contact information');
  const agree = vis(page.getByRole('checkbox', { name: /i agree/i }));
  if (await shown(agree, 15_000)) await agree.check().catch(() => agree.click());
  else throw new StepError('consent', 'no "I agree" box');
  await clickIf(btn(/^\s*continue\s*$/i), 5000);
  const create = btn(/^\s*create\s*$/i);
  if (!(await clickIf(create, 15_000))) throw new StepError('consent', 'no CREATE at the end of the wizard');
  try { await create.waitFor({ state: 'hidden', timeout: 90_000 }); } catch { throw new StepError('consent', 'CREATE did not finish'); }
  await sleep(4000);
  await go(`${plan.console}/auth/branding?project=${plan.projectId}`);
  await sleep(5000);
  if (/not configured yet/i.test(await bodyText())) throw new StepError('consent', 'the consent screen wizard did not save');
  emit({ ev: 'audience', kind });
  emit({ ev: 'done', step: 'consent' });
  return kind;
}

async function stepBranding() {
  working('branding', 'home page and privacy policy');
  await go(`${plan.console}/auth/branding?project=${plan.projectId}`);
  const home = vis(page.getByLabel(/application home page/i));
  if (!(await shown(home, 45_000))) throw new StepError('branding', 'no "Application home page" box');
  await fillBox(home, plan.home);
  const privacy = vis(page.getByLabel(/privacy policy/i));
  if (!(await shown(privacy, 10_000))) throw new StepError('branding', 'no "Application privacy policy link" box');
  await fillBox(privacy, plan.privacy);
  // live 2026-10-01: the domain boxes carry no label and no type attribute; ADD DOMAIN appends one,
  // so mark the inputs that exist before the click and fill the one that is new
  const plain = 'input:not([aria-label]):not([type=file]):not([type=search]):not([type=hidden])';
  if (!(await inputValues()).includes(plan.domain)) {
    await page.locator(plain).evaluateAll((els) => els.forEach((e) => { e.dataset.pdOld = '1'; }));
    if (!(await clickIf(btn(/add domain/i), 10_000))) throw new StepError('branding', 'no ADD DOMAIN button');
    const box = vis(page.locator(`${plain}:not([data-pd-old])`));
    if (!(await shown(box, 10_000))) throw new StepError('branding', 'no new "Authorised domain" box after ADD DOMAIN');
    await fillBox(box, plan.domain);
  }
  if (!(await clickIf(btn(/^\s*save\s*$/i), 10_000))) throw new StepError('branding', 'no SAVE button');
  await sleep(6000);
  await reloaded();
  const kept = await inputValues();
  const lost = [plan.home, plan.privacy, plan.domain].filter((v) => !kept.includes(v));
  if (lost.length) {
    const t = await bodyText();
    const err = /(must|invalid|not (a )?valid|error)[^\n]{0,120}/i.exec(t);
    throw new StepError('branding', `not saved: ${lost.join(', ')}${err ? ` (${err[0]})` : ''}`);
  }
  emit({ ev: 'done', step: 'branding' });
}

async function stepPublish() {
  working('publish', 'publishing the app');
  await go(`${plan.console}/auth/audience?project=${plan.projectId}`);
  if (!(await shown(vis(page.getByText(/publishing status|test users/i)), 45_000))) {
    throw new StepError('publish', 'the Audience page did not load');
  }
  const status = async () => /publishing status\s*in production/i.test((await bodyText()).replace(/\s+/g, ' '));
  if (await status()) return emit({ ev: 'done', step: 'publish' });
  const pub = btn(/publish app/i);
  if (!(await shown(pub, 15_000))) throw new StepError('publish', 'no PUBLISH APP button');
  if (!(await pub.isEnabled())) throw new StepError('publish', 'PUBLISH APP is greyed out (Branding not accepted)');
  await pub.click();
  // live 2026-10-01: "Push to production?" is an alertdialog
  const dlg = page.getByRole('alertdialog').or(page.getByRole('dialog'));
  if (!(await clickIf(vis(dlg.getByRole('button', { name: /^\s*confirm\s*$/i })), 15_000))) {
    throw new StepError('publish', 'no CONFIRM in the "Push to production?" window');
  }
  await sleep(6000);
  await reloaded();
  if (!(await status())) throw new StepError('publish', 'the app still does not show "In production"');
  emit({ ev: 'done', step: 'publish' });
}

async function stepClient() {
  working('client', 'creating the key');
  await go(`${plan.console}/auth/clients/create?project=${plan.projectId}`);
  const type = vis(page.getByLabel(/application type/i)).or(vis(page.getByRole('combobox', { name: /application type/i })));
  if (!(await shown(vis(type), 45_000))) throw new StepError('client', 'no "Application type" box');
  if (!(await chooseOption(vis(type), /desktop app/i))) throw new StepError('client', 'could not choose "Desktop app"');
  const name = vis(page.getByRole('textbox', { name: /^\s*name/i }));
  if (await shown(name, 15_000)) await fillBox(name, plan.appName);
  if (!(await clickIf(btn(/^\s*create\s*$/i), 10_000))) throw new StepError('client', 'no CREATE button');
  const dlg = vis(page.getByRole('dialog').filter({ hasText: /client/i }));
  if (!(await shown(dlg, 90_000))) throw new StepError('client', 'the "OAuth client created" window did not appear');
  await sleep(1500);
  const out = path.join(plan.outDir, 'client.json');
  let ok = false;
  try {
    const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 20_000 }),
      vis(dlg.getByRole('button', { name: /download json/i }).or(dlg.getByRole('link', { name: /download json/i }))).click()]);
    await dl.saveAs(out);
    ok = fs.existsSync(out);
  } catch (e) { log('download failed:', e.message.split('\n')[0]); }
  if (!ok) { // the dialog shows the id and the secret once: write the same JSON Google would
    const text = await page.evaluate(() => document.body.innerText + ' ' +
      [...document.querySelectorAll('input,textarea')].map((i) => i.value).join(' ')).catch(() => '');
    const id = /\d+-[a-z0-9]+\.apps\.googleusercontent\.com/.exec(text);
    const secret = /GOCSPX-[A-Za-z0-9_-]+/.exec(text);
    if (!id || !secret) throw new StepError('client', 'neither DOWNLOAD JSON nor the shown client secret worked');
    fs.writeFileSync(out, JSON.stringify({ installed: { client_id: id[0], client_secret: secret[0], project_id: plan.projectId,
      auth_uri: 'https://accounts.google.com/o/oauth2/auth', token_uri: 'https://oauth2.googleapis.com/token',
      redirect_uris: ['http://localhost'] } }), { mode: 0o600 });
  }
  fs.chmodSync(out, 0o600);
  await clickIf(vis(dlg.getByRole('button', { name: /^\s*ok\s*$/i })), 3000);
  emit({ ev: 'client_file', path: out });
}

async function stepLogin(context) {
  working('login', 'opening the access page');
  emit({ ev: 'need_consent_url' });
  const a = await answer('consent_url', 2 * MIN);
  if (!a.consent_url) throw new StepError('login', 'no consent URL from gdrive');
  let got = null;
  const seen = (u) => {
    if (!got && u && u.startsWith(plan.redirect) && /[?&](code|error)=/.test(u)) {
      got = u;
      emit({ ev: 'redirect', url: u });
    }
  };
  context.on('request', (r) => seen(r.url()));
  context.on('page', (p) => p.on('framenavigated', (f) => seen(f.url())));
  page.on('framenavigated', (f) => seen(f.url()));
  await page.goto(a.consent_url, { waitUntil: 'domcontentloaded', timeout: 90_000 }).catch(() => null);
  const end = Date.now() + 10 * MIN;
  let errors = 0;
  let announced = false;
  while (!got && Date.now() < end) {
    seen(page.url());
    if (got) break;
    if (/accounts\.google\.com\/signin\/oauth\/error/.test(page.url())) {
      const why = (await bodyText()).split('\n').map((l) => l.trim()).find((l) => /access blocked|error/i.test(l));
      throw new StepError('login', `Google refused the access page: ${why || 'access denied'}`);
    }
    const t = await bodyText();
    if (/\b500\b/.test(t) && /that.s an error/i.test(t)) { // Google, first minutes after publishing
      if (++errors > 5) throw new StepError('login', 'Google keeps answering "500. That\'s an error"');
      working('login', 'Google needs a minute after publishing - retrying');
      await sleep(60_000);
      await page.goto(a.consent_url, { waitUntil: 'domcontentloaded', timeout: 90_000 }).catch(() => null);
      announced = false;
      continue;
    }
    if (/choose an account/i.test(t) && plan.email) {
      await clickIf(vis(page.getByText(plan.email, { exact: false })), 3000);
    } else if (/hasn.t verified this app/i.test(t)) {
      if (!(await clickIf(btn(/^\s*continue\s*$/i), 2000))) {
        await clickIf(vis(page.getByText(/^\s*advanced\s*$/i)), 3000);
        await clickIf(vis(page.getByText(/go to .*\(unsafe\)/i)), 5000);
      }
    } else {
      const drive = vis(page.getByRole('checkbox', { name: /google drive|see, edit, create/i }));
      const all = vis(page.getByRole('checkbox', { name: /select all/i }));
      let boxes = false;
      if (await shown(drive, 1500)) { boxes = true; if (!(await drive.isChecked())) await drive.check().catch(() => drive.click()); }
      else if (await shown(all, 500)) { boxes = true; if (!(await all.isChecked())) await all.check().catch(() => all.click()); }
      // any other Google page here is the user's turn (Continue / sign-in confirm / scopes): say so at once,
      // never wait silently on a page variant we failed to recognise (live 2026-10-01: "Sign in to <app>")
      if (!announced && (boxes || page.url().startsWith('https://accounts.google.com'))) {
        emit({ ev: 'state', state: 'consent', step: 'login', msg: 'waiting for you to click Continue' });
        announced = true;
      }
    }
    await sleep(1500);
  }
  if (!got) throw new StepError('login', 'nobody clicked "Continue" on the access page within 10 minutes');
}

// ---- main ------------------------------------------------------------------------------------

async function main() {
  if (process.argv[2] === '--check') return check();
  plan = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const found = loadPlaywright();
  const chrome = findChrome(found?.pw);
  if (!found || !chrome) throw new StepError('browser', !found ? 'Playwright not found' : 'no Chrome found');
  fs.mkdirSync(plan.browserDir, { recursive: true });
  fs.mkdirSync(plan.shotsDir, { recursive: true });
  const startUrl = plan.projectId ? `${plan.console}/home/dashboard?project=${plan.projectId}&hl=en` : `${plan.console}/projectcreate?hl=en`;
  const signinMs = Number(process.env.GDRIVE_SIGNIN_MIN || 15) * MIN;
  await plainSignIn(plan.browserDir, chrome, startUrl, signinMs);
  const { port, pid } = await openBrowser(plan, chrome, startUrl);
  await waitSignedIn(port, signinMs);
  emit({ ev: 'state', state: 'working', step: 'project', msg: 'signed in - starting' });
  let browser;
  let context;
  const attach = async () => {
    browser = await found.pw.chromium.connectOverCDP(`http://127.0.0.1:${port}`);
    context = browser.contexts()[0];
    page = context.pages().find((p) => p.url().startsWith('https://console.cloud.google.com')) || await context.newPage();
    await page.bringToFront().catch(() => null);
  };
  await attach();
  const dog = setInterval(() => { watchdog().catch(() => null); }, 5000);
  let step = 'project';
  try {
    await handleTerms();
    const email = await detectEmail();
    if (email && !plan.email) { plan.email = email; emit({ ev: 'email', email }); }
    let kind = null;
    const run = async (s) => {
      if (s === 'project') await stepProject();
      else if (s === 'apis') await stepApis();
      else if (s === 'consent') kind = await stepConsent();
      else if (s === 'branding' || s === 'publish') {
        if (kind === 'internal') return;
        await (s === 'branding' ? stepBranding() : stepPublish());
      } else if (s === 'client') await stepClient();
      else if (s === 'login') await stepLogin(context);
    };
    for (step of plan.todo) {
      for (let tries = 0; ; tries++) {
        try { await run(step); break; } catch (e) {
          if (!(e instanceof SignInNeeded) || tries >= 3) throw e;
          // the console sent us to sign-in: let go of the page (Google refuses automated
          // sign-in), wait for the user, attach again and redo the step
          await browser.close().catch(() => null);
          await waitSignedIn(port, signinMs);
          await attach();
        }
      }
    }
  } catch (e) {
    const s = e instanceof StepError ? e.step : e instanceof SignInNeeded ? 'signin' : step;
    const msg = (e instanceof StepError ? e.message : e instanceof SignInNeeded ? 'Google keeps asking to sign in'
      : `unexpected page (${e.message.split('\n')[0]})`).slice(0, 300);
    emit({ ev: 'fail', step: s, msg, screenshot: await shot(s) });
    clearInterval(dog);
    await browser.close().catch(() => null); // disconnects; the window stays for the manual step
    return;
  }
  clearInterval(dog);
  current.step = null;
  const a = await answer('quit', 5 * MIN);
  if (a.close) {
    try { const s = await browser.newBrowserCDPSession(); await s.send('Browser.close'); } catch { /* gone */ }
    if (pid) try { process.kill(pid); } catch { /* gone */ }
  } else {
    await browser.close().catch(() => null);
  }
}

// stdout to a pipe is asynchronous on macOS: exit only after the last line is flushed
const end = () => process.stdout.write('', () => process.exit(0));
main().then(end).catch((e) => {
  emit({ ev: 'fail', step: e.step || 'browser', msg: String(e.message || e).split('\n')[0].slice(0, 300) });
  end();
});
