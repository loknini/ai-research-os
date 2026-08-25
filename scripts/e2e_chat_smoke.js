const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const FRONTEND_URL = process.env.FRONTEND_URL || 'http://localhost:5173';
const OUT_DIR = path.join('tmp', 'e2e-chat-smoke');
if (!fs.existsSync(OUT_DIR)) fs.mkdirSync(OUT_DIR, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const logs = [];
  const push = (msg) => { logs.push(msg); console.log(msg); };
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();

  // 拦截 LLM 流，避免依赖真实模型
  await page.route('**/api/chat/completions/stream', async (route) => {
    const body = 'data: {"type":"text","content":"测试回复"}\n\ndata: [DONE]\n\n';
    route.fulfill({
      status: 200,
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      },
      body,
    });
  });

  page.on('console', (msg) => {
    const text = msg.text();
    if (text.includes('fetch') || text.includes('error') || text.includes('Error') || text.includes('500')) {
      push(`[console] ${text}`);
    }
  });
  page.on('pageerror', (err) => push(`[pageerror] ${err.message}`));
  page.on('response', async (res) => {
    const url = res.url();
    if (url.includes('/api/')) {
      const status = res.status();
      const ok = status >= 200 && status < 300;
      if (!ok) {
        const body = await res.text().catch(() => '');
        push(`[api] ${res.request().method()} ${url} -> ${status} ${body.slice(0, 200)}`);
      }
    }
  });

  try {
    await page.goto(`${FRONTEND_URL}/chat`, { waitUntil: 'networkidle' });
    await page.screenshot({ path: path.join(OUT_DIR, '01-open.png') });

    // 处理 SpaceGate
    const spaceInput = await page.$('input[placeholder*="例如"], input[type="text"]');
    if (spaceInput) {
      push('SpaceGate detected, entering dream...');
      await spaceInput.fill('dream');
      await page.click('button:has-text("进入")');
      await sleep(1000);
    }
    await page.screenshot({ path: path.join(OUT_DIR, '02-space.png') });

    // 新建对话
    await page.click('button:has-text("新建对话")');
    await sleep(800);
    await page.screenshot({ path: path.join(OUT_DIR, '03-new-conv.png') });

    // 检查按钮可见性
    const buttonsVisible = await page.evaluate(() => {
      const items = document.querySelectorAll('.group');
      for (const item of items) {
        const edit = item.querySelector('button[title="修改标题"]');
        const del = item.querySelector('button[title="删除对话"]');
        if (edit && del) {
          const eRect = edit.getBoundingClientRect();
          const dRect = del.getBoundingClientRect();
          return {
            editVisible: eRect.width > 0 && eRect.height > 0,
            deleteVisible: dRect.width > 0 && dRect.height > 0,
          };
        }
      }
      return null;
    });
    push(`Buttons visibility: ${JSON.stringify(buttonsVisible)}`);

    // 发送消息
    const textarea = await page.$('textarea');
    if (textarea) {
      await textarea.fill('这是一个测试消息');
      await sleep(300);
      // 找发送按钮：submit 类型或包含 Send 图标或位于输入框旁边
      const sendBtn = await page.$('button[type="submit"], button:has(svg), .flex button');
      if (sendBtn) {
        await sendBtn.click();
      } else {
        push('ERROR: send button not found');
      }
      await sleep(2000);
      await page.screenshot({ path: path.join(OUT_DIR, '04-after-send.png') });
    } else {
      push('ERROR: textarea not found');
    }

    // 最终检查
    const has500 = logs.some((l) => l.includes('500') || l.includes('405') || l.includes('404'));
    const pass = buttonsVisible && buttonsVisible.editVisible && buttonsVisible.deleteVisible && !has500;
    push(`RESULT: ${pass ? 'PASS' : 'FAIL'} (buttons=${JSON.stringify(buttonsVisible)}, apiErrors=${has500})`);
    fs.writeFileSync(path.join(OUT_DIR, 'result.json'), JSON.stringify({ pass, buttonsVisible, logs }, null, 2));
  } catch (e) {
    push(`EXCEPTION: ${e.message}`);
    fs.writeFileSync(path.join(OUT_DIR, 'result.json'), JSON.stringify({ pass: false, error: e.message, logs }, null, 2));
  } finally {
    await browser.close();
  }
})();
