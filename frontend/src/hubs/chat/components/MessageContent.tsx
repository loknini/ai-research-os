import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { cn } from '@/utils'
import type { RagSource } from '../types'

interface MessageContentProps {
  content: string
  citationSources?: RagSource[]
  onCitationClick?: (rank: number) => void
}

// 把正文中形如 [1] [2] 的引用标记转为可点击的引用角标链接。
// 仅当该 rank 真实存在于 citationSources 中时才渲染为按钮，否则保持原样。
function useCitationContent(content: string, sources?: RagSource[]) {
  if (!sources?.length) return content
  const validRanks = new Set(sources.map((s) => s.rank))
  return content.replace(/\[(\d+)\]/g, (match, rankStr) => {
    const rank = parseInt(rankStr, 10)
    return validRanks.has(rank) ? `[${rank}](#cite-${rank})` : match
  })
}

// 渲染消息内容（支持 Markdown + RAG 引用角标）
const MessageContent = ({
  content,
  citationSources,
  onCitationClick,
}: MessageContentProps) => {
  const processed = useCitationContent(content, citationSources)

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        code({ node, inline, className, children, ...props }: any) {
          const match = /language-(\w+)/.exec(className || '')
          return !inline && match ? (
            <SyntaxHighlighter
              style={oneDark}
              language={match[1]}
              PreTag="div"
              {...props}
            >
              {String(children).replace(/\n$/, '')}
            </SyntaxHighlighter>
          ) : (
            <code className={cn('bg-muted px-1.5 py-0.5 rounded text-sm', className)} {...props}>
              {children}
            </code>
          )
        },
        // 舒适阅读：行高 1.7 对齐 ChatGPT/Claude 聊天正文，段落间距 12px 更清晰
        p({ children }) {
          return <p className="mb-3 last:mb-0 leading-[1.7]">{children}</p>
        },
        ul({ children }) {
          return <ul className="list-disc list-inside mb-3 leading-[1.7]">{children}</ul>
        },
        ol({ children }) {
          return <ol className="list-decimal list-inside mb-3 leading-[1.7]">{children}</ol>
        },
        li({ children }) {
          return <li className="mb-1.5">{children}</li>
        },
        h1({ children }) {
          return <h1 className="text-xl font-bold mb-3 mt-1 leading-snug">{children}</h1>
        },
        h2({ children }) {
          return <h2 className="text-lg font-bold mb-3 mt-1 leading-snug">{children}</h2>
        },
        h3({ children }) {
          return <h3 className="text-base font-bold mb-2 mt-1 leading-snug">{children}</h3>
        },
        blockquote({ children }) {
          return (
            <blockquote className="border-l-4 border-primary pl-4 italic my-3 leading-[1.7] text-muted-foreground">
              {children}
            </blockquote>
          )
        },
        table({ children }) {
          return (
            <div className="overflow-x-auto my-3">
              <table className="w-full text-sm border-collapse border border-border rounded-lg">
                {children}
              </table>
            </div>
          )
        },
        thead({ children }) {
          return <thead className="bg-muted/80">{children}</thead>
        },
        tbody({ children }) {
          return <tbody>{children}</tbody>
        },
        tr({ children }) {
          return <tr className="border-b border-border last:border-b-0">{children}</tr>
        },
        th({ children }) {
          return (
            <th className="text-left px-3 py-2 font-semibold text-foreground/90">
              {children}
            </th>
          )
        },
        td({ children }) {
          return <td className="px-3 py-2 text-foreground/80">{children}</td>
        },
        // 把形如 [1](#cite-1) 的链接渲染为上标引用角标（可点击或纯视觉）
        a({ href, children }) {
          const citeMatch = typeof href === 'string' ? href.match(/^#cite-(\d+)$/) : null
          if (citeMatch) {
            const rank = parseInt(citeMatch[1], 10)
            return (
              <sup
                className={cn(
                  'inline-block mx-0.5 text-[10px] font-semibold text-primary align-super',
                  onCitationClick && 'cursor-pointer'
                )}
              >
                {onCitationClick ? (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.preventDefault()
                      onCitationClick(rank)
                    }}
                    className="inline-flex h-4 min-w-4 items-center justify-center rounded bg-primary/15 px-1 text-[10px] font-semibold text-primary hover:bg-primary/25 transition-colors align-super"
                    title={`查看引用来源 [${rank}]`}
                  >
                    {children}
                  </button>
                ) : (
                  <span className="inline-flex h-4 min-w-4 items-center justify-center rounded bg-primary/15 px-1">
                    {children}
                  </span>
                )}
              </sup>
            )
          }
          return (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary underline underline-offset-2 hover:opacity-80"
            >
              {children}
            </a>
          )
        },
      }}
    >
      {processed}
    </ReactMarkdown>
  )
}

export default MessageContent
