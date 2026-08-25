import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  message: string
}

/**
 * 顶层错误边界：捕获任意子组件渲染期抛出的异常，
 * 避免单个 Hub 崩溃导致整个应用白屏（React 默认行为）。
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: '' }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error.message || String(error) }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary] 捕获到渲染异常:', error, info)
  }

  handleReset = () => {
    this.setState({ hasError: false, message: '' })
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex items-center justify-center h-full p-8">
          <div className="max-w-md w-full p-6 rounded-xl border border-red-500/30 bg-red-500/5 space-y-4">
            <h2 className="text-lg font-semibold text-red-600">页面渲染出错</h2>
            <p className="text-sm text-muted-foreground break-words">
              {this.state.message}
            </p>
            <p className="text-sm text-muted-foreground">
              该模块出现异常，但不会影响其它功能。你可以尝试切换回其它页面，或点击下方按钮重试。
            </p>
            <button
              onClick={this.handleReset}
              className="px-4 py-2 text-sm rounded-md bg-primary text-primary-foreground hover:opacity-90"
            >
              重试
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

export default ErrorBoundary
