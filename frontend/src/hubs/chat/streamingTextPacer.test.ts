import { afterEach, describe, expect, it, vi } from 'vitest'
import { StreamingTextPacer } from './streamingTextPacer'

describe('StreamingTextPacer', () => {
  afterEach(() => vi.useRealTimers())

  it('spreads a coalesced response over separate timer frames', async () => {
    vi.useFakeTimers()
    const flushed: string[] = []
    const pacer = new StreamingTextPacer((text) => flushed.push(text), {
      intervalMs: 20,
      minCharsPerFlush: 4,
      maxDrainFrames: 4,
    })

    pacer.push('abcdefghijklmnopqrstuvwxyz')
    expect(flushed).toEqual([])

    await vi.advanceTimersByTimeAsync(20)
    expect(flushed).toHaveLength(1)
    expect(flushed.join('').length).toBeLessThan(26)

    const drained = pacer.drain()
    await vi.runAllTimersAsync()
    await drained
    expect(flushed.join('')).toBe('abcdefghijklmnopqrstuvwxyz')
    expect(flushed.length).toBeGreaterThan(1)
  })

  it('flushes immediately at semantic boundaries', () => {
    vi.useFakeTimers()
    const flushed: string[] = []
    const pacer = new StreamingTextPacer((text) => flushed.push(text))

    pacer.push('before tool')
    pacer.flushNow()

    expect(flushed).toEqual(['before tool'])
    expect(vi.getTimerCount()).toBe(0)
  })

  it('cancels queued text without emitting it', async () => {
    vi.useFakeTimers()
    const flushed: string[] = []
    const pacer = new StreamingTextPacer((text) => flushed.push(text))

    pacer.push('partial answer')
    pacer.cancel()
    await vi.runAllTimersAsync()

    expect(flushed).toEqual([])
  })
})
