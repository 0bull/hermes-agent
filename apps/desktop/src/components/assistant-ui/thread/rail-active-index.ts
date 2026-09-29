/**
 * Cached-geometry helpers for the thread timeline's active-bar index.
 *
 * The rail-index effect used to walk every mounted message on every scroll
 * frame, calling `closest()` + `getBoundingClientRect()` per row — O(mounted
 * turns) of layout work per frame, which dominated the main thread on long
 * sessions. A turn's position in the viewport's scrolled content space is
 * invariant under a pure scroll, so it is measured once per geometry change
 * (transcript mutation, content resize) and scroll frames reduce to a binary
 * search over the cached offsets.
 */

export interface MountedRailOffset {
  /** Rail index of the mounted prompt this turn belongs to. */
  index: number
  /** Turn top in the viewport's scrolled content space — stable across pure scrolls. */
  contentTop: number
}

/** How far below the viewport's top edge a turn counts as the reading position. */
export const RAIL_FOLD_SLACK = 8

/**
 * One measurement pass over the mounted prompts. Called only when geometry may
 * have changed (mount, transcript mutation, content resize) — never per scroll
 * frame.
 */
export function measureRailOffsets(
  viewport: HTMLElement,
  indexes: Map<string, number>
): MountedRailOffset[] {
  const scrollTop = viewport.scrollTop
  const viewportTop = viewport.getBoundingClientRect().top
  const offsets: MountedRailOffset[] = []

  // Walk only mounted messages, never every archived prompt in the rail.
  const walk = viewport.querySelectorAll<HTMLElement>('[data-message-id]')
  const seen = new Set<string>()

  for (let i = 0; i < walk.length; i += 1) {
    const node = walk.item(i)
    // Skip duplicate occurrences of a prompt id (transcript reconciliation
    // can briefly keep two); the first in DOM order wins, matching the
    // previous per-frame walk.
    if (seen.has(node.dataset.messageId!)) {
      continue
    }

    seen.add(node.dataset.messageId!)
    const index = indexes.get(node.dataset.messageId!)

    if (index === undefined) {
      continue
    }

    const turn = node.closest<HTMLElement>('[data-slot="aui_turn-pair"]') ?? node
    // A turn's rect moves with every scroll frame, but rect.top − viewport top
    // + scrollTop recovers its scroll-invariant position in the content space.
    offsets.push({ index, contentTop: turn.getBoundingClientRect().top - viewportTop + scrollTop })
  }

  // Normal flow keeps turns in content order, but a virtualized mount or a
  // kept-alive duplicate can hand them over out of order; the binary search
  // requires the sequence sorted by content position, never by rail index.
  offsets.sort((a, b) => a.contentTop - b.contentTop)

  return offsets
}

/**
 * The active bar is the LAST mounted prompt at or above the fold line
 * (scrollTop + RAIL_FOLD_SLACK). When none has crossed it yet, the first
 * mounted prompt marks the reading position; with nothing mounted the rail
 * falls back to the top. Binary search over the content-ordered offsets —
 * O(log n) per scroll frame, zero layout reads.
 */
export function activeRailIndex(offsets: MountedRailOffset[], fold: number): number {
  if (offsets.length === 0) {
    return 0
  }

  let low = 0
  let high = offsets.length - 1
  let found = -1

  while (low <= high) {
    const mid = (low + high) >> 1

    if (offsets[mid]!.contentTop <= fold) {
      found = mid
      low = mid + 1
    } else {
      high = mid - 1
    }
  }

  // Nothing past the fold yet: the first mounted prompt is the reading position.
  return found === -1 ? Math.max(0, offsets[0]!.index) : offsets[found]!.index
}
