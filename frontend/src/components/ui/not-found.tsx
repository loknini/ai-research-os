import { Link } from 'react-router-dom'
import { Compass, Home } from 'lucide-react'
import { Button } from '@/components/ui/button'

/**
 * 全局 404 页（通配路由兜底）。
 * 采用 Apple HIG 风格的玻璃卡片 + 渐变大字 + fade-up 进场，
 * 与全局设计语言（Manrope / Space Grotesk / .glass / 冷蓝强调）保持一致。
 */
export default function NotFound() {
  return (
    <div className="h-full w-full flex items-center justify-center p-6">
      <div className="glass rounded-3xl px-10 py-14 max-w-lg w-full text-center animate-fade-up">
        <div className="mx-auto mb-6 w-20 h-20 rounded-2xl bg-primary/10 flex items-center justify-center">
          <Compass className="w-10 h-10 text-primary" strokeWidth={1.5} />
        </div>
        <h1 className="font-display text-7xl font-bold tracking-tight bg-gradient-to-br from-primary to-primary/60 bg-clip-text text-transparent">
          404
        </h1>
        <p className="mt-4 text-lg font-medium text-foreground">这个页面走丢了</p>
        <p className="mt-2 text-sm text-muted-foreground">
          你访问的地址不存在，或者它已经被移动到别处。
        </p>
        <Link to="/" className="mt-8 inline-flex">
          <Button className="gap-2">
            <Home className="w-4 h-4" />
            返回仪表盘
          </Button>
        </Link>
      </div>
    </div>
  )
}
