// 隔离浏览器与本机假邮件服务，不读取或发送真实账号数据。
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || './website/node_modules/playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const path = require('node:path');
const directory = path.join(__dirname, 'work', 'accounts-web');
fs.mkdirSync(directory, {recursive:true});
const base = 'http://127.0.0.1:8767/melodica/account/';
const mail = () => JSON.parse(fs.readFileSync(path.join(directory, 'mail-test.json'), 'utf8')).code;
const suffix = Date.now();
const firstEmail = `web-${suffix}@example.com`;
const secondEmail = `other-${suffix}@example.com`;
const password = 'browser-test-password-123';
const score = {version:1,title:'游客的旋律',duration:1000,notes:[[0,500,60,0],[500,1000,62,0]]};
const waitText = (page, text) => page.waitForFunction(text => document.querySelector('#status').textContent.includes(text), text);
async function login(page, email, secret = password) {
  await page.locator('[data-mode=login]').click();
  await page.locator('#email').fill(email); await page.locator('#password').fill(secret);
  await page.locator('#submit-auth').click(); await waitText(page, '已登录');
}
async function register(page, email) {
  await page.locator('[data-mode=register]').click();
  await page.locator('#email').fill(email); await page.locator('#password').fill(password);
  await page.locator('#send-code').click(); await waitText(page, '验证码将发送');
  await page.locator('#code').fill(mail()); await page.locator('#submit-auth').click();
  await waitText(page, '同步完成');
}
(async () => {
  const browser = await chromium.launch({channel:'chrome',headless:true});
  const errors=[];
  try {
    const context = await browser.newContext({viewport:{width:1440,height:1000}});
    const page = await context.newPage(); page.on('pageerror', e => errors.push(e.message));
    await page.goto(base); await waitText(page,'游客模式');
    await page.locator('#sync').click(); await waitText(page,'需要登录');
    await page.locator('[data-mode=register]').click();
    await page.screenshot({path:path.join(directory,'web-register.png'),fullPage:true});
    await page.locator('#import-score').setInputFiles({name:'test.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(score))});
    await waitText(page,'已保存');
    await register(page,firstEmail);
    assert.equal(await page.locator('#song-list li').count(),1);
    await page.screenshot({path:path.join(directory,'web-signed-in.png'),fullPage:true});
    const cookies=await context.cookies(); assert.ok(cookies.find(c=>c.name==='melodica_session').httpOnly);
    assert.equal(await page.evaluate(()=>localStorage.length),0);
    await page.locator('#logout').click(); await waitText(page,'已退出');
    assert.equal(await page.locator('#song-list li').count(),0);
    // 同一浏览器的发送按钮有 60 秒倒计时，重新加载后由后端的测试限流规则管理。
    await page.reload(); await waitText(page,'游客模式');
    await register(page,secondEmail);
    assert.equal(await page.locator('#song-list li').count(),0);
    await page.locator('#logout').click(); await waitText(page,'已退出');
    await login(page,firstEmail);
    assert.equal(await page.locator('#song-list li').count(),1);
    const other = await browser.newContext({viewport:{width:390,height:844},isMobile:true});
    const mobile=await other.newPage(); mobile.on('pageerror',e=>errors.push(e.message));
    await mobile.goto(base); await waitText(mobile,'游客模式');
    await mobile.screenshot({path:path.join(directory,'web-mobile.png'),fullPage:true});
    assert.ok(await mobile.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await login(mobile,firstEmail); await mobile.locator('#sync').click(); await waitText(mobile,'同步完成');
    assert.equal(await mobile.locator('#song-list li').count(),1);
    await mobile.locator('#logout').click(); await waitText(mobile,'已退出');
    await mobile.locator('[data-mode=reset]').click(); await mobile.locator('#email').fill(firstEmail);
    await mobile.locator('#password').fill('new-browser-password-456'); await mobile.locator('#send-code').click(); await waitText(mobile,'验证码将发送');
    await mobile.locator('#code').fill(mail()); await mobile.locator('#submit-auth').click(); await waitText(mobile,'密码已重置');
    await page.locator('#sync').click(); await waitText(page,'重新登录');
    assert.equal(await page.locator('#guest-auth').isVisible(),true);
    await login(mobile,firstEmail,'new-browser-password-456');
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(directory,'result.json'),JSON.stringify({ok:true,checks:['游客登录提示','浏览器游客继承','账号隔离','跨设备同步','找回密码','旧会话失效','HttpOnly Cookie','无明文浏览器凭据','移动端无横向溢出'],screenshots:3}));
    console.log('官网端到端联调通过');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
