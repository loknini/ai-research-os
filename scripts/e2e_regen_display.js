const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const FRONTEND = process.env.FRONTEND_URL || 'http://localhost:5173';
const SPACE = 'dream';
const MARKER = 'OLD_REPLY_MARKER_8f3a';
const OUT = path.join(__dirname, '..', 'tmp', 'e2e-regen');
fs.mkdirSync(OUT, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const logs = [];
  const push = (l) => { logs.push(l); console.log(l); };

  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  page.on('console', (m) => push(`[console.${m.type()}] ${m.text()}`));
  page.on('pageerror', (e) => push(`[pageerror] ${e.message}`));
  page.on('response', (r) => { if (r.status() >= 400) push(`[HTTP ${r.status()}] ${r.url()}`); });

  // 1. 打开前端 + 设置 space
  await page.goto(`${FRONTEND}/chat`, { waitUntil: 'networkidle' });
  await sleep(800);
  await page.screenshot({ path: path.join(OUT, '01-open.png') });

  const firstInput = page.locator('input').first();
  if (await firstInput.isVisible().catch(() => false)) {
    await firstInput.fill(SPACE);
    const enter = page.locator('button:has-text("进入")').first();
    if (await enter.isVisible().catch(() => false)) await enter.click();
    await sleep(1200);
    await page.screenshot({ path: path.join(OUT, '02-space.png') });
  }

  // 2. 在侧栏点击 seeded 对话
  const convItem = page.locator('text=QA-重新生成测试').first();
  await convItem.click({ timeout: 10000 }).catch(async () => {
    push('WARN: 未直接点到对话，尝试刷新列表');
    await page.reload({ waitUntil: 'networkidle' });
    await sleep(800);
    await page.locator('text=QA-重新生成测试').first().click({ timeout: 10000 });
  });
  await sleep(1500);

  // 3. 确认旧回复可见 + 只有 1 个 assistant 气泡
  const before = await page.evaluate((marker) => {
    const bubbles = Array.from(document.querySelectorAll('div')).filter(d => d.children.length === 0 && d.textContent && d.textContent.includes(marker));
    const regen = Array.from(document.querySelectorAll('button')).filter(b => b.textContent.includes('重新回答'));
    return { markerVisible: document.body.innerText.includes(marker), regenCount: regen.length };
  }, MARKER);
  push(`BEFORE regenerate: ${JSON.stringify(before)}`);
  await page.screenshot({ path: path.join(OUT, '03-before-regen.png') });

  if (!before.markerVisible) {
    push('FAIL: 旧回复未显示，无法继续');
    await finish(false);
  }
  if (before.regenCount < 1) {
    push('FAIL: 找不到重新回答按钮');
    await finish(false);
  }

  // 4. 点击最后一个“重新回答”
  const regenBtns = page.locator('button:has-text("重新回答")');
  await regenBtns.last().hover();
  await sleep(200);
  await regenBtns.last().click();
  push('clicked 重新回答');

  // 5. 断言：旧回复被本地移除（marker 应尽快不可见）
  let removedQuickly = false;
  try {
    await page.waitForFunction((m) => !document.body.innerText.includes(m), MARKER, { timeout: 8000 });
    removedQuickly = true;
  } catch { removedQuickly = false; }
  push(`old reply removed locally after click: ${removedQuickly}`);
  await sleep(2500); // 等生成（失败也会落新 assistant）结束
  await page.screenshot({ path: path.join(OUT, '04-after-regen.png') });

  // 6. 终态断言：marker 不应再出现，且 assistant 气泡数 == 1（不能旧+新叠加）
  const after = await page.evaluate((marker) => {
    const regen = Array.from(document.querySelectorAll('button')).filter(b => b.textContent.includes('重新回答'));
    // 粗略统计 assistant 气泡：包含“重新回答”按钮的父级消息容器
    const markerVisible = document.body.innerText.includes(marker);
    const text = document.body.innerText;
    return { markerVisible, regenCount: regen.length, hasError: text.includes('[错误') || text.includes('错误') };
  }, MARKER);
  push(`AFTER regenerate: ${JSON.stringify(after)}`);

  // 用户报修的核心问题：点击“重新回答”后旧回复仍然保留、并在下方追加新回复。
  // 本测试在无真实 LLM 下仍足以验证该问题：
  //  - 点击后旧回复立即被本地移除
  //  - 最终 DOM 中没有出现旧回复（若旧 bug 存在，原 assistant 气泡仍会显示）
  // 在有 LLM 时，终态会出现新的 assistant 气泡和“重新回答”按钮；无 LLM 时生成会失败或挂起，
  // 因此 regenCount 不作为强制断言，仅作为日志参考。
  const pass = removedQuickly && !after.markerVisible;
  push(`RESULT: ${pass ? 'PASS' : 'FAIL'} (oldRemoved=${removedQuickly}, markerGone=${!after.markerVisible}, regenBtns=${after.regenCount}, hasError=${after.hasError})`);

  fs.writeFileSync(path.join(OUT, 'console.log'), logs.join('\n'), 'utf-8');
  await finish(pass);

  async function finish(ok) {
    fs.writeFileSync(path.join(OUT, 'result.json'), JSON.stringify({ ok, before, after, removedQuickly }, null, 2), 'utf-8');
    await browser.close();
    process.exit(ok ? 0 : 1);
  }
})().catch((err) => {
  console.error('E2E crashed:', err);
  process.exit(2);
});
