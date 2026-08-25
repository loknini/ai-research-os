/**
 * QA: 验证 Chat Hub 的 Markdown 表格能正确渲染。
 * 直接调用 frontend/node_modules 里的 react-markdown + remark-gfm，
 * 把截图里那段 raw table 转成 HTML，断言包含 <table>。
 */
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const raw = `|论文|主题|相关性|
|---|---|---|
|[2604.16241] BAGEL: Benchmarking Animal Knowledge|动物知识基准测试|低|
|[2604.16241] Language-conditioned World Model (LED-WM)|语言条件化世界模型|中（同领域）|
|[2402.11651] Learning From Failure|从失败中学习 Agent|中（相关方法）|`

function TableTest() {
  return React.createElement(
    ReactMarkdown,
    { remarkPlugins: [remarkGfm] },
    raw
  )
}

const html = renderToStaticMarkup(React.createElement(TableTest))
const hasTable = html.includes('<table')
const hasPipe = html.includes('|论文|')

console.log('--- rendered html ---')
console.log(html)
console.log('--- assertions ---')
console.log('contains <table:', hasTable)
console.log('still contains raw pipe:', hasPipe)

if (hasTable && !hasPipe) {
  console.log('\nRESULT: ALL_PASS')
  process.exit(0)
} else {
  console.log('\nRESULT: FAIL')
  process.exit(1)
}
