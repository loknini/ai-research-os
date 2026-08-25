const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const url = (process.env.FRONTEND_URL || 'http://localhost:5173') + '/chat?space=dream';
  await page.goto(url);
  await page.waitForTimeout(2000);
  await page.click('text=新建对话');
  await page.waitForTimeout(1000);
  await page.screenshot({ path: 'tmp/e2e-chat-list-02.png', scale: 'css' });
  // inspect edit button
  const edit = await page.$('[title="修改标题"]');
  const del = await page.$('[title="删除对话"]');
  if (edit && del) {
    const eBox = await edit.boundingBox();
    const dBox = await del.boundingBox();
    const eColor = await edit.evaluate(el => window.getComputedStyle(el).color);
    const dColor = await del.evaluate(el => window.getComputedStyle(el).color);
    const eBg = await edit.evaluate(el => window.getComputedStyle(el).backgroundColor);
    console.log('edit box:', eBox, 'color:', eColor, 'bg:', eBg);
    console.log('delete box:', dBox, 'color:', dColor);
    // highlight buttons for screenshot
    await page.evaluate(() => {
      document.querySelectorAll('[title="修改标题"], [title="删除对话"]').forEach(el => {
        el.style.outline = '2px solid magenta';
      });
    });
    await page.screenshot({ path: 'tmp/e2e-chat-list-03-highlighted.png', scale: 'css' });
  } else {
    console.log('buttons not found');
  }
  await browser.close();
})();
