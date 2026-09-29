import { afterEach, describe, expect, it, vi } from 'vitest'

import { activeRailIndex, measureRailOffsets, RAIL_FOLD_SLACK, type MountedRailOffset } from './rail-active-index'

/** jsdom has no layout; hand-built rects keep the test about the contract. */
function rect(top: number): DOMRect {
  return { top, bottom: top + 100, height: 100, width: 100, left: 0, right: 100, x: 0, y: 0, toJSON: () => ({}) } as DOMRect
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('activeRailIndex', () => {
  it('picks the last prompt at or above the fold, falling back to the first mounted prompt', () => {
    // Three prompts at content tops 0, 500, 1000 (indexes match rail order).
    const offsets: MountedRailOffset[] = [
      { index: 0, contentTop: 0 },
      { index: 1, contentTop: 500 },
      { index: 2, contentTop: 1000 }
    ]

    // Fold at the very top: the first prompt is the reading position.
    expect(activeRailIndex(offsets, 0)).toBe(0)
    // Fold just past the second prompt.
    expect(activeRailIndex(offsets, 500 + RAIL_FOLD_SLACK)).toBe(1)
    // Fold far below the last prompt.
    expect(activeRailIndex(offsets, 5000)).toBe(2)
    // Fold above the second prompt: still the first.
    expect(activeRailIndex(offsets, 499)).toBe(0)
    // Nothing mounted: the rail keeps its top.
    expect(activeRailIndex([], 100)).toBe(0)
  })

  it('keeps the index rail-ordered even when turns mount out of rail order', () => {
    // A virtualized window may mount a later prompt first; the offsets are
    // content-ordered (measureRailOffsets sorts), so the rail's own order —
    // not DOM order — decides, matching the previous walk's `first` fallback.
    const offsets: MountedRailOffset[] = [
      { index: 1, contentTop: 1000 },
      { index: 2, contentTop: 2000 },
      { index: 3, contentTop: 3000 }
    ]

    // Nothing above a fold at 500: fall back to the FIRST mounted in content
    // order, not the smallest index in the rail.
    expect(activeRailIndex(offsets, 500)).toBe(1)
    expect(activeRailIndex(offsets, 2500)).toBe(2)
    expect(activeRailIndex(offsets, 4000)).toBe(3)
  })
})

describe('measureRailOffsets', () => {
  it('derives scroll-invariant content tops from one measurement pass', () => {
    const viewport = window.document.createElement('div')
    const content = window.document.createElement('div')
    viewport.append(content)

    for (const [id, top] of [
      ['m0', 0],
      ['m1', 500],
      ['m2', 1000]
    ] as const) {
      const turn = window.document.createElement('div')
      turn.dataset.slot = 'aui_turn-pair'
      const message = window.document.createElement('div')
      message.dataset.messageId = id
      turn.append(message)
      content.append(turn)
      vi.spyOn(turn, 'getBoundingClientRect').mockReturnValue(rect(top))
    }

    vi.spyOn(viewport, 'getBoundingClientRect').mockReturnValue(rect(50))

    const rail = new Map([
      ['m0', 0],
      ['m1', 1],
      ['m2', 2]
    ])

    // Scroll position and rect tops move together in a real browser, so the
    // derived content tops are scroll-invariant.
    const turnRects = [...content.querySelectorAll<HTMLElement>('[data-slot="aui_turn-pair"]')].map(node =>
      vi.spyOn(node, 'getBoundingClientRect')
    )

    const atScroll = (scrollTop: number) => {
      viewport.scrollTop = scrollTop
      turnRects.forEach((spy, i) => spy.mockReturnValue(rect([0, 500, 1000][i]! - scrollTop)))

      return measureRailOffsets(viewport, rail)
    }

    expect(atScroll(0)).toEqual([
      { index: 0, contentTop: -50 },
      { index: 1, contentTop: 450 },
      { index: 2, contentTop: 950 }
    ])
    expect(atScroll(250)).toEqual(atScroll(0))

    // A message the rail does not know (assistant streaming row, foreign pane)
    // is skipped without resolving its turn or reading its rect.
    const unknown = window.document.createElement('div')
    unknown.dataset.messageId = 'foreign'
    content.append(unknown)
    const unknownRect = vi.spyOn(unknown, 'getBoundingClientRect')
    expect(atScroll(250)).toEqual([
      { index: 0, contentTop: -50 },
      { index: 1, contentTop: 450 },
      { index: 2, contentTop: 950 }
    ])
    expect(unknownRect).not.toHaveBeenCalled()
  })
})
