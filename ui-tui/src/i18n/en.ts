// Bundled English catalog for the TUI — the only bundled TUI locale. Every
// other language arrives as a pack over `i18n.catalog {surface: 'tui'}` and is
// merged over this object at runtime (see runtime.ts).
//
// Facade: the catalog is composed from topical siblings under ./en/. Each
// sibling owns a disjoint set of top-level namespaces (a vitest test enforces
// the disjointness). Leaves are strings or `(...args) => string`; packs express
// function leaves as strings with positional `{0}`, `{1}` placeholders.
//
// `locales/_keys.tui.json` is generated from this object by `npm run i18n:keys`.

import { appEn } from './en/app.js'
import { chromeEn } from './en/chrome.js'
import { libEn } from './en/lib.js'
import { overlaysEn } from './en/overlays.js'
import { slashEn } from './en/slash.js'

export const en = {
  ...chromeEn,
  ...overlaysEn,
  ...appEn,
  ...slashEn,
  ...libEn
}

/** The sibling catalogs `en` is composed from, for the disjointness test. */
export const EN_SIBLINGS: readonly Record<string, unknown>[] = [chromeEn, overlaysEn, appEn, slashEn, libEn]
