import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import MessageContent from './MessageContent'

describe('MessageContent nested lists', () => {
  it('keeps parent markers outside block paragraphs instead of showing empty dots', () => {
    const content = [
      '**核心定位**：偏重**研究、优化和创新**',
      '',
      '- **主要工作**：',
      '  - 研究和改进 Agent 核心算法',
      '  - 优化模型性能',
      '',
      '- **技能要求**：',
      '  - 扎实的机器学习基础',
    ].join('\n')

    const html = renderToStaticMarkup(<MessageContent content={content} />)

    expect(html).toContain('list-outside')
    expect(html).not.toContain('list-inside')
    expect(html).toContain('<strong>主要工作</strong>：')
    expect(html).toContain('<strong>技能要求</strong>：')
  })
})
