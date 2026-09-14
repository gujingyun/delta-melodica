// 使用本地静态页面与明确的接口样例验证后台，不访问线上计数接口。
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const root = __dirname;
const output = path.join(root, '..', 'work', 'platform-download-stats');

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const fakePackage = Buffer.from('仅用于验证浏览器重定向下载的测试包');
  const server = http.createServer((req, res) => {
    const pathname = new URL(req.url, 'http://localhost').pathname;
    // 下载交给浏览器网络栈跟随真实本机 302，不依赖下载阶段的路由拦截。
    if (pathname === '/api/download/android') {
      res.writeHead(302, { Location: '/downloads/test.apk', 'Cache-Control': 'no-store' }).end(); return;
    }
    if (pathname === '/downloads/test.apk') {
      res.writeHead(200, { 'Content-Type': 'application/vnd.android.package-archive', 'Content-Disposition': 'attachment; filename="test.apk"' }).end(fakePackage); return;
    }
    const file = path.resolve(root, '.' + (pathname === '/admin/' ? '/admin/index.html' : pathname));
    if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      res.writeHead(404).end(); return;
    }
    const mime = { '.html': 'text/html; charset=utf-8', '.css': 'text/css', '.js': 'text/javascript', '.png': 'image/png', '.jpg': 'image/jpeg' };
    res.writeHead(200, { 'Content-Type': mime[path.extname(file)] || 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({ channel: 'chrome', headless: true });
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const base = `http://127.0.0.1:${server.address().port}`;
    let data = { views: 285, downloads: 192, downloads_windows: 185, downloads_android: 7, updated_at: '2026-09-14T09:04:22Z' };
    let fail = false;
    await page.route('**/api/stats?*', route => route.fulfill({ status: fail ? 503 : 200, contentType: 'application/json', body: JSON.stringify(data) }));
    for (const width of [320, 390, 768, 1440]) {
      await page.setViewportSize({ width, height: 1100 });
      await page.goto(base + '/admin/');
      await page.waitForFunction(() => document.getElementById('downloads-android').textContent === '7');
      assert.equal(await page.locator('#downloads-windows').innerText(), '185');
      assert.equal(await page.locator('#downloads').innerText(), '192');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${width}px 后台横向溢出`);
      if ([390, 1440].includes(width)) await page.screenshot({ path: path.join(output, `admin-${width}.png`), fullPage: true });
    }
    data.downloads_android = 8; data.downloads = 193;
    await page.getByRole('button', { name: '刷新数据' }).click();
    await page.waitForFunction(() => document.getElementById('downloads-android').textContent === '8');
    assert.equal(await page.locator('#downloads').innerText(), '193');
    data = { views: 285, downloads: 185 };
    await page.reload();
    await page.waitForFunction(() => document.getElementById('downloads-windows').textContent === '185');
    assert.equal(await page.locator('#downloads-android').innerText(), '0');
    fail = true;
    await page.getByRole('button', { name: '刷新数据' }).click();
    await page.waitForFunction(() => document.getElementById('status').classList.contains('error'));
    fail = false;
    await page.getByRole('button', { name: '刷新数据' }).click();
    await page.waitForFunction(() => document.getElementById('status').textContent.includes('最后更新'));
    await page.goto(base + '/android.html');
    assert.equal(await page.locator('a[download]').getAttribute('href'), 'api/download/android');
    const downloaded = page.waitForEvent('download');
    await page.locator('a[download]').click();
    const download = await downloaded;
    assert.equal(download.suggestedFilename(), 'test.apk');
    assert.equal(await download.failure(), null);
    assert.deepEqual(fs.readFileSync(await download.path()), fakePackage);
    assert.deepEqual(errors, []);
    console.log('通过：后台四种宽度、两端与总数、刷新、旧数据、失败重试、安卓入口和浏览器跳转下载（模拟接口）。');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
