import { useState, useCallback, useRef } from 'react'
import MDEditor from '@uiw/react-markdown-editor'
import { Button } from './button'
import { Image, X, Loader2 } from 'lucide-react'
import { cn } from '@/utils'

interface MarkdownEditorProps {
  value: string
  onChange: (value: string) => void
  height?: number
  className?: string
  /** 工具栏扩展插槽：在「插入图片」按钮之后渲染（如「插入公式」） */
  toolbarExtra?: React.ReactNode
}

export function MarkdownEditor({
  value,
  onChange,
  height = 400,
  className,
  toolbarExtra
}: MarkdownEditorProps) {
  const [isUploading, setIsUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // 处理图片上传
  const handleImageUpload = useCallback(async (file: File) => {
    if (!file.type.startsWith('image/')) {
      setUploadError('请上传图片文件')
      return
    }

    if (file.size > 5 * 1024 * 1024) {
      setUploadError('图片大小不能超过 5MB')
      return
    }

    setIsUploading(true)
    setUploadError(null)

    try {
      // 转换为 base64
      const base64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(reader.result as string)
        reader.onerror = reject
        reader.readAsDataURL(file)
      })

      // 插入图片到编辑器
      const imageMarkdown = `\n![${file.name}](${base64})\n`
      onChange(value + imageMarkdown)
    } catch (error) {
      setUploadError('图片上传失败')
      console.error('Image upload error:', error)
    } finally {
      setIsUploading(false)
    }
  }, [value, onChange])

  // 处理粘贴事件
  const handlePaste = useCallback(async (event: React.ClipboardEvent) => {
    const items = event.clipboardData?.items
    if (!items) return

    for (const item of items) {
      if (item.type.startsWith('image/')) {
        event.preventDefault()
        const file = item.getAsFile()
        if (file) {
          await handleImageUpload(file)
        }
        break
      }
    }
  }, [handleImageUpload])

  // 处理文件选择
  const handleFileSelect = useCallback(async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) {
      await handleImageUpload(file)
    }
    // 清空 input
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }, [handleImageUpload])

  return (
    <div className={cn('space-y-2', className)}>
      {/* 工具栏 */}
      <div className="flex items-center gap-2 p-2 bg-muted/50 rounded-lg">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => fileInputRef.current?.click()}
          disabled={isUploading}
        >
          {isUploading ? (
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
          ) : (
            <Image className="w-4 h-4 mr-2" />
          )}
          插入图片
        </Button>
        {toolbarExtra}
        <span className="text-xs text-muted-foreground ml-auto">
          支持拖拽或粘贴图片
        </span>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          onChange={handleFileSelect}
          className="hidden"
        />
      </div>

      {/* 错误提示 */}
      {uploadError && (
        <div className="flex items-center gap-2 p-2 bg-red-500/10 text-red-600 rounded-lg text-sm">
          <X className="w-4 h-4" />
          {uploadError}
          <button
            onClick={() => setUploadError(null)}
            className="ml-auto hover:underline"
          >
            清除
          </button>
        </div>
      )}

      {/* 编辑器 */}
      <div onPaste={handlePaste} className="border rounded-lg overflow-hidden">
        <MDEditor
          value={value}
          onChange={onChange}
          height={String(height)}
        />
      </div>

      {/* 字数统计 */}
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>支持 Markdown 语法</span>
        <span>{value.length} 字符</span>
      </div>
    </div>
  )
}

// Markdown 预览组件
interface MarkdownPreviewProps {
  content: string
  className?: string
}

export function MarkdownPreview({ content, className }: MarkdownPreviewProps) {
  return (
    <div className={cn('prose prose-sm max-w-none dark:prose-invert', className)}>
      <MDEditor.Markdown source={content} />
    </div>
  )
}
