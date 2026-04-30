// Headless-browser verification of the legacy frontend's auth flow.
// Drives prototype/frontend/index.html through real Chromium, asserts
// against computed CSS + bounding boxes (catches `display:` vs `[hidden]`
// specificity bugs that string-only DOM inspection would miss).
//
// Usage:
//   URL=http://127.0.0.1:8765/ node verify-login.mjs

import puppeteer from 'puppeteer';

const URL = process.env.URL ?? 'http://127.0.0.1:8765/';

let failures = 0;
const ASSERT = (cond, label) => {
  if (cond) {
    console.log(`  PASS  ${label}`);
  } else {
    console.log(`  FAIL  ${label}`);
    failures++;
  }
};

async function visibleState(page) {
  return await page.evaluate(() => {
    const login = document.querySelector('#login-view');
    const app = document.querySelector('#app-view');
    const adminTab = document.querySelector('[data-tab="admin"]');
    const who = document.querySelector('#who')?.textContent?.trim() ?? '';
    const cs = (el) => (el ? getComputedStyle(el).display : 'missing');
    const rect = (el) => {
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { w: Math.round(r.width), h: Math.round(r.height) };
    };
    return {
      login: { hiddenAttr: !!login?.hasAttribute('hidden'), display: cs(login), rect: rect(login) },
      app:   { hiddenAttr: !!app?.hasAttribute('hidden'),   display: cs(app),   rect: rect(app) },
      adminTab: adminTab
        ? { hiddenAttr: adminTab.hasAttribute('hidden'), display: cs(adminTab) }
        : null,
      who,
    };
  });
}

async function signIn(page, email) {
  await page.evaluate((e) => {
    const input = document.querySelector('#login-email');
    input.value = e;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    document.querySelector('#login-form').requestSubmit();
  }, email);
  await page.waitForFunction(
    () => (document.querySelector('#who')?.textContent?.trim().length ?? 0) > 0,
    { timeout: 5000 },
  );
}

async function signOut(page) {
  await page.click('#logout-btn');
  await page.waitForFunction(
    () => !document.querySelector('#login-view')?.hasAttribute('hidden'),
    { timeout: 5000 },
  );
}

async function run(email, role, expectAdmin) {
  console.log(`\n=== ${role} (${email}) ===`);
  const browser = await puppeteer.launch({
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
    defaultViewport: { width: 414, height: 896 },
  });
  try {
    const page = await browser.newPage();
    page.on('pageerror', (e) => {
      console.log(`  [pageerror] ${e.message}`);
      failures++;
    });

    await page.goto(URL, { waitUntil: 'networkidle0' });

    // 1. Initial state: login form visible, app hidden.
    let s = await visibleState(page);
    ASSERT(!s.login.hiddenAttr, 'initial: login section has no [hidden]');
    ASSERT(s.login.display !== 'none', `initial: login is laid out (display=${s.login.display})`);
    ASSERT(s.login.rect.w > 0 && s.login.rect.h > 0,
      `initial: login has non-zero size (${s.login.rect.w}x${s.login.rect.h})`);
    ASSERT(s.app.hiddenAttr, 'initial: app section has [hidden]');
    ASSERT(s.app.display === 'none', 'initial: app computed display is none');
    ASSERT(s.who === '', 'initial: #who is empty');

    // 2. Sign in.
    await signIn(page, email);
    s = await visibleState(page);
    ASSERT(s.who.length > 0, `after sign-in: #who populated ("${s.who}")`);
    ASSERT(s.who.toLowerCase().includes(role.toLowerCase()),
      `after sign-in: #who shows role "${role}"`);
    ASSERT(s.login.hiddenAttr, 'after sign-in: login section has [hidden]');
    ASSERT(
      s.login.display === 'none',
      `after sign-in: login computed display is none (got ${s.login.display})`,
    );
    ASSERT(s.login.rect.w === 0 && s.login.rect.h === 0,
      `after sign-in: login has zero size (got ${s.login.rect.w}x${s.login.rect.h})`);
    ASSERT(!s.app.hiddenAttr, 'after sign-in: app section has no [hidden]');
    ASSERT(s.app.display !== 'none', `after sign-in: app is laid out (display=${s.app.display})`);

    if (expectAdmin) {
      ASSERT(s.adminTab && !s.adminTab.hiddenAttr && s.adminTab.display !== 'none',
        'admin: Admin tab is visible');
    } else {
      ASSERT(s.adminTab && (s.adminTab.hiddenAttr || s.adminTab.display === 'none'),
        'standard user: Admin tab is hidden');
    }

    // 3. Sign out.
    await signOut(page);
    s = await visibleState(page);
    ASSERT(!s.login.hiddenAttr, 'after sign-out: login section has no [hidden]');
    ASSERT(s.login.display !== 'none',
      `after sign-out: login is laid out again (display=${s.login.display})`);
    ASSERT(s.login.rect.w > 0 && s.login.rect.h > 0,
      `after sign-out: login has non-zero size again (${s.login.rect.w}x${s.login.rect.h})`);
    ASSERT(s.app.hiddenAttr, 'after sign-out: app section has [hidden]');
    ASSERT(s.app.display === 'none', 'after sign-out: app computed display is none');
  } finally {
    await browser.close();
  }
}

await run('alice@mjs-packaging.example', 'Standard.User', false);
await run('tom@mjs-packaging.example', 'Admin', true);

if (failures) {
  console.log(`\n${failures} assertion(s) failed`);
  process.exit(1);
} else {
  console.log('\nALL PASS');
}
