import { act, cleanup, render } from '@testing-library/react'
import { type ReactNode, useSyncExternalStore } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setHideThreadTimeline } from '@/store/thread-timeline'

/**
 * #118782: the rail-index effect re-measured every mounted turn on every
 * scroll frame (querySelectorAll + closest + getBoundingClientRect per row).
 * This is the perf guard: a PURE SCROLL may not read any turn's layout — the
 * active index must come from cached content offsets — while a transcript
 * mutation (a new prompt mounting) refreshes the cache and keeps the index
 * correct.
 *
 * jsdom has no layout, so each turn's rect is modeled exactly as a browser
 * behaves: rect.top falls as the viewport scrolls, keeping each turn's
 * position in the viewport's content space constant. Spies are installed in
 * ref callbacks, i.e. before any effect runs, so the timeline's very first
 * measurement already sees browser-like geometry.
 */

interface FakeMessage {
  content: unknown
  id: string
  role: string
}

const messageListeners = new Set<() => void>()
let messages: FakeMessage[] = []

vi.mock('@assistant-ui/react', () => ({
  useAui: () => ({
    thread: () => ({
      getState: () => ({ messages })
    })
  }),
  useAuiState: (selector: (state: { thread: { messages: FakeMessage[] } }) => unknown) =>
    useSyncExternalStore(
      listener => {
        messageListeners.add(listener)

        return () => messageListeners.delete(listener)
      },
      () => selector({ thread: { messages } })
    )
}))

vi.mock('@/components/pane-shell/pane-visibility', () => ({ usePaneVisible: () => true }))
vi.mock('@/lib/haptics', () => ({ triggerHaptic: () => {} }))

const { ThreadTimeline } = await import('./timeline')

const rect = (top: number): DOMRect =>
  ({ top, bottom: top + 100, height: 100, width: 100, left: 0, right: 100, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect

/** Turn bases in the viewport's content space; rect.top tracks the scroll. */
const BASES = [0, 100, 200, 300, 400, 500]

/**
 * Mounts a transcript whose turns already carry browser-like geometry: each
 * turn's rect spy is installed from its ref callback (before effects), so
 * the timeline measures real positions, never jsdom's zero rects.
 */
const mountTranscript = (ui: ReactNode) => {
  const turnSpies: Map<number, ReturnType<typeof vi.spyOn>> = new Map()
  let viewport: HTMLElement

  act(() => {
    render(
      <div data-session-anchor="perf-guard">
        <div
          data-following="false"
          data-slot="aui_thread-viewport"
          ref={(node: HTMLDivElement | null) => {
            viewport = node!
          }}
        >
          <div data-slot="aui_thread-content">
            {BASES.map((base, i) => (
              <div
                data-slot="aui_turn-pair"
                key={i}
                ref={node => {
                  if (node && !turnSpies.has(i)) {
                    turnSpies.set(
                      i,
                      vi.spyOn(node, 'getBoundingClientRect').mockImplementation(() => rect(BASES[i]! - viewport.scrollTop))
                    )
                  }
                }}
              >
                <div data-message-id={`u${i}`} />
              </div>
            ))}
          </div>
        </div>
        {ui}
      </div>
    )
  })

  const readCount = () => [...turnSpies.values()].reduce((sum, spy) => sum + spy.mock.calls.length, 0)

  return {
    content: () => viewport.querySelector<HTMLElement>('[data-slot="aui_thread-content"]')!,
    readCount,
    turnSpies,
    viewport: () => viewport
  }
}

let frames: FrameRequestCallback[] = []
let frameHandle = 0

const flushFrames = () =>
  act(() => {
    const pending = frames
    frames = []
    for (const callback of pending) {
      callback(0)
    }
  })

const flushAll = () => {
  // Mutations and scroll schedules coalesce; keep flushing until settled.
  for (let i = 0; i < 6 && frames.length > 0; i += 1) {
    flushFrames()
  }
}

const activeTick = () =>
  [...document.querySelectorAll<HTMLElement>('[data-timeline-id]')].find(
    tick => tick.getAttribute('aria-current') === 'location'
  )?.getAttribute('data-timeline-id')

const scrollTo = (viewport: HTMLElement, scrollTop: number) => {
  viewport.scrollTop = scrollTop

  act(() => {
    viewport.dispatchEvent(new Event('scroll'))
  })
  flushAll()
}

beforeEach(() => {
  messages = Array.from({ length: BASES.length }, (_, i) => ({
    content: [{ text: `prompt ${i}`, type: 'text' }],
    id: `u${i}`,
    role: 'user'
  }))
  messageListeners.clear()

  frameHandle = 0
  frames = []
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    frames.push(callback)

    return ++frameHandle
  })
  vi.stubGlobal('cancelAnimationFrame', () => {})
  // The virtualized rail needs non-zero boxes before it mounts any ticks.
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(300)
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(48)
})

afterEach(() => {
  cleanup()
  setHideThreadTimeline(false)
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('timeline rail active index geometry', () => {
  it('tracks the prompt at the fold across scrolls without reading turn layout', () => {
    const { viewport, readCount } = mountTranscript(<ThreadTimeline />)
    flushAll()

    // Baseline: top of the transcript.
    expect(activeTick()).toBe('u0')

    // A pure scroll reads ZERO turn rects while the index moves.
    const readsBefore = readCount()

    scrollTo(viewport(), 250)
    expect(activeTick()).toBe('u2')
    expect(readCount()).toBe(readsBefore)

    // Scroll again from the new position: still no layout reads.
    scrollTo(viewport(), 450)
    expect(activeTick()).toBe('u4')
    expect(readCount()).toBe(readsBefore)
  })

  it('remeasures when the transcript mutates, not per scroll frame', async () => {
    const { viewport, content, turnSpies } = mountTranscript(<ThreadTimeline />)
    flushAll()

    expect(activeTick()).toBe('u0')

    // A new prompt is sent: the store grows and its turn mounts (base 600).
    // The rail grows a tick and the mutation refreshes the offset cache —
    // the appended turn's rect is read, not skipped.
    messages = [
      ...messages,
      {
        content: [{ text: 'prompt 6', type: 'text' }],
        id: 'u6',
        role: 'user'
      }
    ]
    await act(async () => {
      messageListeners.forEach(listener => listener())
    })

    const turn = document.createElement('div')
    turn.dataset.slot = 'aui_turn-pair'
    const message = document.createElement('div')
    message.dataset.messageId = 'u6'
    turn.append(message)

    const turnSpy = vi.spyOn(turn, 'getBoundingClientRect').mockImplementation(() => rect(600 - viewport().scrollTop))

    await act(async () => {
      content().append(turn)
    })
    flushAll()

    expect(document.querySelectorAll('[data-timeline-id]')).toHaveLength(7)
    expect(turnSpy.mock.calls.length).toBeGreaterThan(0)
    expect(activeTick()).toBe('u0')

    // Scrolling to the new tail lands on the new prompt with no per-frame
    // re-measurement of the older turns.
    const readsBefore = [...turnSpies.values()].reduce((sum, spy) => sum + spy.mock.calls.length, 0)

    scrollTo(viewport(), 650)
    expect(activeTick()).toBe('u6')
    expect([...turnSpies.values()].reduce((sum, spy) => sum + spy.mock.calls.length, 0)).toBe(readsBefore)
  })
})
