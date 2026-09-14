// 只访问本机候选网站，检查实际下载、资源、校验值和窄屏布局。
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || '../website/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const base = process.env.ANDROID_SITE_TEST_URL || 'http://127.0.0.1:8767/';
assert.ok(['127.0.0.1', 'localhost'].includes(new URL(base).hostname));
const output = path.join(__dirname, '..', 'work', 'android-release-v060');
(async () => {
  const browser = await chromium.launch({channel:'chrome', headless:true});
  try {
    const page = await browser.newPage();
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    const response = await page.request.get(base + 'android-version.json');
    assert.equal(response.status(), 200); const manifest = await response.json();
    const apk = await page.request.get(new URL(manifest.file, base).href);
    assert.equal(apk.status(), 200); const bytes = await apk.body();
    assert.equal(bytes.length, manifest.size);
    assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'), manifest.sha256);
    for (const width of [320, 390, 768, 1440]) {
      await page.setViewportSize({width, height:1000});
      for (const filename of ['android.html', 'android-data.html']) {
        await page.goto(base + filename);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${filename} 在 ${width}px 横向溢出`);
        assert.ok(!(await page.locator('body').innerText()).includes('@@'));
        for (const img of await page.locator('img').all()) { await img.evaluate(image => image.decode()); }
        for (const href of await page.locator('a').evaluateAll(links => links.map(link => link.getAttribute('href')))) {
          if (href.startsWith('#')) { assert.equal(await page.locator(href).count(), 1); continue; }
          const url = new URL(href, page.url());
          if (url.origin !== new URL(base).origin) continue;
          // 静态预览没有统计 API；接口由 Linux 回归和上线检查独立验证。
          if (href === 'api/download/android') continue;
          assert.equal((await page.request.get(url.href)).status(), 200, `缺失资源：${href}`);
        }
        if (filename === 'android.html') {
          assert.equal(await page.locator('a[download]').getAttribute('href'), 'api/download/android');
          if ([390,1440].includes(width)) await page.screenshot({path:path.join(output, `website-${width}.png`), fullPage:true});
        }
      }
    }
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, 'website-result.json'), JSON.stringify({status:'passed', widths:[320,390,768,1440], apkSha256:manifest.sha256, pages:2}, null, 2));
    console.log('通过：两页四种宽度、图片、所有站内链接、APK 大小和 SHA-256、页面错误检查。');
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode=1;});
