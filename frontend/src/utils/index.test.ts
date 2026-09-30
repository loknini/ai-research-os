import { describe, expect, it } from 'vitest'
import { stripToolCallTrace } from './index'

describe('stripToolCallTrace', () => {
  it('removes complete and unclosed internal tool protocol blocks', () => {
    expect(stripToolCallTrace([
      '正文',
      '<tool_call><function=web_search><parameter=query>secret</parameter></function></tool_call>',
      '结尾',
    ].join('\n'))).toBe('正文\n\n结尾')

    expect(stripToolCallTrace('正文<tool_call><function=web_search>未闭合')).toBe('正文')
  })

  it('removes orphan protocol blocks without retaining a debug copy', () => {
    expect(stripToolCallTrace('答案<function=web_search>内部参数</function>完成')).toBe('答案完成')
    expect(stripToolCallTrace('普通自然语言')).toBe('普通自然语言')
    expect(stripToolCallTrace('保留 <functionality> 这样的普通标签')).toBe('保留 <functionality> 这样的普通标签')
  })
})
