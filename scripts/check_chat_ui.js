const { chromium } = require('C:/Users/Administrator/.workbuddy/binaries/node/workspace/node_modules/playwright');
(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  const baseUrl = process.env.FRONTEND_URL || 'http://localhost:5173';
  await page.goto(`${baseUrl}/chat`, { waitUntil: 'networkidle' });
  await page.screenshot({ path: 'tmp/check_chat_ui_01.png' });
  // handle SpaceGate if present
  const enterBtn = page.getByRole('button').filter({ hasText: /进入/ }).first();
  const hasSpaceGate = await enterBtn.isVisible().catch(() => false);
  console.log('space gate visible:', hasSpaceGate);
  if (hasSpaceGate) {
    await page.locator('input').first().fill('dream');
    await enterBtn.click();
    await page.waitForTimeout(1000);
  }
  await page.screenshot({ path: 'tmp/check_chat_ui_02.png' });
  // create a new conversation
  const newBtn = page.getByRole('button').filter({ hasText: /新建对话/ }).first();
  if (await newBtn.isVisible().catch(() => false)) {
    await newBtn.click();
    await page.waitForTimeout(800);
  } else {
    console.log('new conversation button not found');
  }
  await page.screenshot({ path: 'tmp/check_chat_ui_03.png' });
  const items = await page.locator('.group.flex.items-center').count();
  const firstItem = page.locator('.group.flex.items-center').first();
  const buttons = await firstItem.locator('button').count();
  await firstItem.screenshot({ path: 'tmp/check_chat_ui_item.png' });
  console.log(JSON.stringify({ items, buttons }));
  await browser.close();
})();
