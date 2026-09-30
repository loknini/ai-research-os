import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ContextRing } from './ContextRing'

describe('ContextRing token accounting', () => {
  it('separates estimates from actual and cumulative provider usage', () => {
    const html = renderToStaticMarkup(
      <ContextRing
        value={4093}
        limit={512000}
        compressed={false}
        lastUsage={{ prompt_tokens: 4200, completion_tokens: 600, total_tokens: 4800, api_calls: 5 }}
        cumulativeUsage={{ prompt_tokens: 15000, completion_tokens: 2000, total_tokens: 17000, api_calls: 9 }}
        expanded
        onToggle={() => undefined}
      />
    )

    expect(html).toContain('下轮请求上下文（估算）')
    expect(html).toContain('距配置上限')
    expect(html).toContain('本轮模型调用累计')
    expect(html).toContain('5 次请求')
    expect(html).toContain('会话累计（已计量）')
    expect(html).toContain('实际用量会累计本轮所有模型请求')
    expect(html).not.toContain('阈值：')
    expect(html).not.toContain('点击圆环可收起')
  })
})
