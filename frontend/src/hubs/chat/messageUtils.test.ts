import { describe, expect, it } from 'vitest'
import { appendAssistantDelta, stripAssistantLeadingBreaks } from './messageUtils'

describe('assistant reply whitespace normalization', () => {
  it('removes provider-added blank lines at the beginning', () => {
    expect(stripAssistantLeadingBreaks('\n\n你好')).toBe('你好')
    expect(stripAssistantLeadingBreaks('  \r\n\r\n你好')).toBe('你好')
  })

  it('preserves meaningful indentation when no leading line break exists', () => {
    expect(stripAssistantLeadingBreaks('    indented code')).toBe('    indented code')
  })

  it('normalizes multiple leading-only stream chunks', () => {
    let content = appendAssistantDelta('', '  \n')
    content = appendAssistantDelta(content, '\n')
    content = appendAssistantDelta(content, '回答')
    expect(content).toBe('回答')
  })
})
