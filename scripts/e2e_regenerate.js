const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const outDir = path.join(__dirname, '..', 'tmp', 'e2e');
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch({
    channel: 'chrome',
    headless: false,
    slowMo: 50,
  });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();

  // 监听 console 日志与网络错误
  const logs = [];
  const pushLog = (line) => {
    logs.push(line);
    console.log(line);
  };
  page.on('console', (msg) => pushLog(`[${msg.type()}] ${msg.text()}`));
  page.on('pageerror', (err) => pushLog(`[PAGEERROR] ${err.message}`));
  page.on('response', (response) => {
    if (response.status() >= 400) {
      pushLog(`[HTTP ${response.status()}] ${response.url()}`);
    }
  });

  // 1. 打开页面
  await page.goto('http://localhost:5174/chat', { waitUntil: 'networkidle' });
  await page.screenshot({ path: path.join(outDir, '01-open.png') });

  // 2. 处理 SpaceGate（如果存在）
  const firstInput = page.locator('input').first();
  if (await firstInput.isVisible().catch(() => false)) {
    await firstInput.fill('dream');
    const submit = page.locator('button:has-text("进入")').first();
    if (await submit.isVisible().catch(() => false)) await submit.click();
    await page.waitForTimeout(1200);
    await page.screenshot({ path: path.join(outDir, '02-space.png') });
  }

  // 3. 创建新对话
  await page.locator('button:has-text("新建对话")').first().click().catch(() => {});
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(outDir, '02b-new-chat.png') });

  // 4. 发送测试消息
  const textarea = page.locator('textarea').first();
  await textarea.waitFor({ state: 'visible', timeout: 10000 });
  await textarea.fill('给我 LangChain 学习路径');
  await textarea.press('Enter');
  pushLog('sent first message');

  // 5. 等待第一次回复完成："重新回答"按钮出现即代表已有 assistant 消息
  await page.waitForFunction(() => {
    return Array.from(document.querySelectorAll('button')).some(b => b.textContent.includes('重新回答'));
  }, { timeout: 120000 });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: path.join(outDir, '03-first-reply.png') });

  // 6. 统计第一次回复后的消息气泡与重新回答按钮数
  let firstRegenCount = 0;
  let firstBubbleCount = 0;
  const firstStats = await page.evaluate(() => {
    const bubbles = document.querySelectorAll('.rounded-2xl.px-4.py-3.max-w-full');
    const regenBtns = Array.from(document.querySelectorAll('button')).filter(b => b.textContent.includes('重新回答'));
    return { bubbleCount: bubbles.length, regenCount: regenBtns.length };
  });
  firstRegenCount = firstStats.regenCount;
  firstBubbleCount = firstStats.bubbleCount;
  pushLog(`first reply: bubbleCount=${firstBubbleCount}, regenButtonCount=${firstRegenCount}`);

  // 7. hover 到最后一个"重新回答"按钮所在消息，点击
  const regenButtons = page.locator('button:has-text("重新回答")');
  const lastRegenBtn = regenButtons.last();
  await lastRegenBtn.hover();
  await page.waitForTimeout(300);
  await lastRegenBtn.click();
  pushLog('clicked regenerate');

  // 8. 等待第二次回复完成：重新回答按钮数量应保持稳定（>= firstRegenCount）
  await page.waitForFunction((expected) => {
    const count = Array.from(document.querySelectorAll('button')).filter(b => b.textContent.includes('重新回答')).length;
    return count >= expected;
  }, firstRegenCount, { timeout: 120000 });
  await page.waitForTimeout(2500);
  await page.screenshot({ path: path.join(outDir, '04-after-regen.png') });

  // 9. 统计最终消息数量与文本
  const result = await page.evaluate(() => {
    const bubbles = Array.from(document.querySelectorAll('.rounded-2xl.px-4.py-3.max-w-full'));
    const regenBtns = Array.from(document.querySelectorAll('button')).filter(b => b.textContent.includes('重新回答'));
    return {
      bubbleCount: bubbles.length,
      regenButtonCount: regenBtns.length,
      texts: bubbles.map((el, i) => ({
        index: i,
        text: el.textContent?.slice(0, 300) || '',
        hasContent: (el.textContent?.trim().length || 0) > 30,
      })),
      assistantCount: regenBtns.length,
    };
  });
  pushLog('after regenerate: ' + JSON.stringify(result, null, 2));

  // 10. 写日志
  fs.writeFileSync(path.join(outDir, 'console.log'), logs.join('\n'), 'utf-8');
  fs.writeFileSync(path.join(outDir, 'result.json'), JSON.stringify(result, null, 2), 'utf-8');

  await browser.close();
})().catch((err) => {
  console.error('E2E failed:', err);
  process.exit(1);
});
