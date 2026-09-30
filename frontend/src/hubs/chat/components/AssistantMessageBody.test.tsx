import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { AssistantMessageBody } from './AssistantMessageBody'

describe('AssistantMessageBody tool trace isolation', () => {
  it('does not render raw tool protocol or a production debug panel', () => {
    const html = renderToStaticMarkup(
      <AssistantMessageBody
        content={'可见回答<tool_call><function=web_search>secret</function></tool_call>完成'}
      />
    )

    expect(html).toContain('可见回答')
    expect(html).toContain('完成')
    expect(html).not.toContain('tool_call')
    expect(html).not.toContain('secret')
    expect(html).not.toContain('模型原始工具调用痕迹')
  })
})
