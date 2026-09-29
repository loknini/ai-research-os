export interface StreamingTextPacerOptions {
  intervalMs?: number
  minCharsPerFlush?: number
  maxDrainFrames?: number
}

/**
 * Decouple transport chunks from paint frames.
 *
 * A single ReadableStream read may contain many SSE events. React batches all
 * updates performed in that same task, which otherwise makes a long answer
 * appear at once. This queue emits bounded pieces on separate timer tasks and
 * can be drained before the final message is persisted.
 */
export class StreamingTextPacer {
  private pending = ''
  private timer: ReturnType<typeof setTimeout> | null = null
  private drainWaiters: Array<() => void> = []
  private readonly intervalMs: number
  private readonly minCharsPerFlush: number
  private readonly maxDrainFrames: number

  constructor(
    private readonly onFlush: (text: string) => void,
    options: StreamingTextPacerOptions = {},
  ) {
    this.intervalMs = options.intervalMs ?? 24
    this.minCharsPerFlush = options.minCharsPerFlush ?? 8
    this.maxDrainFrames = options.maxDrainFrames ?? 60
  }

  push(text: string): void {
    if (!text) return
    this.pending += text
    this.schedule()
  }

  /** Flush synchronously at semantic boundaries such as a tool call. */
  flushNow(): void {
    this.clearTimer()
    if (this.pending) {
      const text = this.pending
      this.pending = ''
      this.onFlush(text)
    }
    this.resolveWaiters()
  }

  /** Wait until every queued delta has reached the visible generation state. */
  drain(): Promise<void> {
    if (!this.pending && !this.timer) return Promise.resolve()
    this.schedule()
    return new Promise((resolve) => this.drainWaiters.push(resolve))
  }

  cancel(): void {
    this.clearTimer()
    this.pending = ''
    this.resolveWaiters()
  }

  private schedule(): void {
    if (this.timer || !this.pending) return
    this.timer = setTimeout(() => this.tick(), this.intervalMs)
  }

  private tick(): void {
    this.timer = null
    if (!this.pending) {
      this.resolveWaiters()
      return
    }

    const codePoints = Array.from(this.pending)
    const count = Math.min(
      codePoints.length,
      Math.max(this.minCharsPerFlush, Math.ceil(codePoints.length / this.maxDrainFrames)),
    )
    const piece = codePoints.slice(0, count).join('')
    this.pending = codePoints.slice(count).join('')
    this.onFlush(piece)

    if (this.pending) this.schedule()
    else this.resolveWaiters()
  }

  private clearTimer(): void {
    if (!this.timer) return
    clearTimeout(this.timer)
    this.timer = null
  }

  private resolveWaiters(): void {
    if (this.pending || this.timer) return
    const waiters = this.drainWaiters.splice(0)
    waiters.forEach((resolve) => resolve())
  }
}
