// 仅访问本机预览服务，检查布局、导航、键盘访问和播放器入口。
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || './website/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.HOMEPAGE_TEST_URL || 'http://127.0.0.1:8767/melodica/';
assert.ok(['127.0.0.1', 'localhost'].includes(new URL(base).hostname), '测试必须使用本机服务');
const output = path.join(__dirname, 'work', 'ui-refresh');
fs.mkdirSync(output, {recursive:true});
(async () => {
  const browser = await chromium.launch({channel:'chrome', headless:true});
  try {
    const page = await browser.newPage();
    const errors = [];
    const media = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => {
      if (/\.(m3u8|ts|mp4)(\?|$)/.test(request.url())) media.push(request.url());
    });
    await page.route('**/api/view', route => route.fulfill({status:204}));
    for (const width of [320, 390, 768, 1440]) {
      await page.setViewportSize({width, height:1000});
      await page.goto(base);
      await page.locator('.screen-frame img').evaluate(image => image.decode());
      assert.equal(await page.locator('.screen-frame img').evaluate(image => image.naturalWidth > 0), true);
      assert.equal(await page.locator('#demo-video').getAttribute('preload'), 'none');
      assert.ok(await page.locator('#video-start').isVisible());
      assert.equal(await page.locator('a[download]').count(), 2);
      assert.equal(await page.getByRole('link', {name:'下载 Android 版', exact:true}).count(), 2);
      for (const link of await page.getByRole('link', {name:'下载 Android 版', exact:true}).all()) {
        assert.equal(await link.getAttribute('href'), 'android.html');
      }
      for (const href of await page.locator('a[download]').evaluateAll(links => links.map(link => link.getAttribute('href')))) {
        assert.equal(href, 'api/download');
      }
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
      assert.equal(overflow, false, `${width}px 页面横向溢出`);
      const outside = await page.locator('main a, main button, .site-header a').evaluateAll(els => els.filter(el => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && (r.left < -1 || r.right > innerWidth + 1);
      }).map(el => el.textContent.trim()));
      assert.deepEqual(outside, [], `${width}px 操作入口被裁切`);
      for (const target of await page.locator('a[href^="#"]').evaluateAll(links => links.map(link => link.getAttribute('href')))) {
        assert.equal(await page.locator(target).count(), 1, `缺失锚点 ${target}`);
      }
      if (width === 1440 || width === 390) {
        for (const image of await page.locator('main img').all()) {
          await image.scrollIntoViewIfNeeded();
          await image.evaluate(element => element.decode());
        }
        await page.evaluate(() => window.scrollTo({top:0, behavior:'instant'}));
        const suffix = width === 1440 ? 'desktop' : 'mobile';
        await page.screenshot({path:path.join(output, `homepage-${suffix}.png`)});
        await page.screenshot({path:path.join(output, `homepage-${suffix}-full.png`), fullPage:true});
      }
    }
    assert.equal(media.length, 0, '点击前不应加载视频');
    await page.keyboard.press('Tab');
    assert.equal(await page.locator('.skip-link').evaluate(el => el === document.activeElement), true);
    await page.locator('.site-nav a[href="#guide"]').click();
    await page.waitForFunction(() => location.hash === '#guide');
    // 模拟媒体暂不可用，验证重试和兼容播放入口不被新样式遮挡。
    await page.route('**/videos/**', route => route.abort());
    await page.locator('#video-start').click();
    await page.waitForFunction(() => document.querySelector('#video-status').textContent.includes('暂时无法加载'));
    assert.ok(await page.locator('#video-start').isEnabled());
    assert.ok(await page.locator('a[href$=".mp4"]').isVisible());
    assert.deepEqual(errors, []);
    console.log('主页检查通过：320 / 390 / 768 / 1440 px、下载与锚点、键盘访问、延迟视频加载和错误重试。');
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
