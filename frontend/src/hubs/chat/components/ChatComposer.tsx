import type { ChangeEventHandler, Dispatch, KeyboardEventHandler, RefObject, SetStateAction } from 'react'
import { Image, Send, Square, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/utils'
import type { ChatContentPart } from '../types'

interface ChatComposerProps {
  inputRef: RefObject<HTMLTextAreaElement>
  input: string
  onInputChange: Dispatch<SetStateAction<string>>
  pendingImages: ChatContentPart[]
  onRemoveImage: (index: number) => void
  onImageSelect: ChangeEventHandler<HTMLInputElement>
  onKeyDown: KeyboardEventHandler<HTMLTextAreaElement>
  hasConversation: boolean
  isGenerating: boolean
  onSend: () => void
  onCancel: () => void
}

export function ChatComposer({
  inputRef,
  input,
  onInputChange,
  pendingImages,
  onRemoveImage,
  onImageSelect,
  onKeyDown,
  hasConversation,
  isGenerating,
  onSend,
  onCancel,
}: ChatComposerProps) {
  return (
    <>
        {/* 输入区域 */}
        <div className="border-t p-4">
          <div className="max-w-3xl mx-auto">
            {/* 旧胶囊已移至顶部圆环 */}
            {pendingImages.length > 0 && (
              <div className="flex flex-wrap gap-2 px-1 pb-1">
                {pendingImages.map((img, i) => (
                  <div key={i} className="relative group">
                    <img
                      src={img.image_url?.url}
                      alt="待发送图片"
                      className="h-16 w-16 object-cover rounded-lg border border-border"
                    />
                    <button
                      type="button"
                      onClick={() => onRemoveImage(i)}
                      className="absolute -top-1.5 -right-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-background border border-border text-foreground shadow-sm hover:bg-accent"
                      title="移除"
                    >
                      <X className="h-2.5 w-2.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div className="flex items-center gap-2 rounded-xl border bg-card px-4 py-3 focus-within:ring-2 focus-within:ring-primary/20 focus-within:border-primary">
              <label
                className="flex h-8 w-8 flex-shrink-0 cursor-pointer items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground"
                title="上传图片（多模态对话，支持视觉模型）"
              >
                <Image className="h-4 w-4" />
                <input
                  type="file"
                  accept="image/*"
                  multiple
                  className="hidden"
                  onChange={onImageSelect}
                />
              </label>
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => onInputChange(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder={
                  hasConversation
                    ? '输入消息... (Shift+Enter 换行)'
                    : '输入消息直接创建对话… (Shift+Enter 换行)'
                }
                disabled={isGenerating}
                rows={1}
                className={cn(
                  'flex-1 resize-none bg-transparent px-0 py-0',
                  'focus:outline-none focus:ring-0',
                  'disabled:opacity-50 disabled:cursor-not-allowed',
                  'min-h-[52px] max-h-[200px]'
                )}
                style={{ height: 'auto' }}
                onInput={(e) => {
                  const target = e.target as HTMLTextAreaElement
                  target.style.height = 'auto'
                  target.style.height = Math.min(target.scrollHeight, 200) + 'px'
                }}
              />
              <Button
                onClick={isGenerating ? onCancel : onSend}
                disabled={!isGenerating && (!input.trim() && pendingImages.length === 0)}
                size="icon"
                className="h-8 w-8 flex-shrink-0"
                title={isGenerating ? '停止生成' : '发送'}
              >
                {isGenerating ? (
                  <Square className="w-4 h-4" />
                ) : (
                  <Send className="w-4 h-4" />
                )}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground text-center mt-2">
              AI 助手可能会产生不准确的信息，请验证重要信息。
            </p>
          </div>
        </div>
    </>
  )
}
