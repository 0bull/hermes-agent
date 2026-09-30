// The sealed payload's repo snapshot has no apps/ or scripts/, so the Windows
// updaters' helpers must be shipped by the packaging config at the path the
// strategies resolve. A helper missing from the package surfaces at runtime as
// the checker's "Microsoft Store returned invalid JSON": python fails to open
// the script and prints nothing.

import assert from 'node:assert/strict'
import fs from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'

import { expect, test } from 'vitest'

import { UPDATER_HELPER_DIR, UPDATER_HELPER_SCRIPTS, updaterHelperScript } from './helper-scripts'

const require: NodeJS.Require = createRequire(import.meta.url)
const desktop: string = path.resolve(import.meta.dirname, '..', '..')

interface FileSet {
  from: string
  to: string
  filter: string[]
}

test('the windows packaging config ships exactly the helpers the updaters resolve', () => {
  const config = require('../../electron-builder.config.cjs')

  const shipped: FileSet[] = ((config.win.extraResources ?? []) as FileSet[]).filter(
    item => item.to === UPDATER_HELPER_DIR
  )

  assert.equal(shipped.length, 1, `win.extraResources must have one ${UPDATER_HELPER_DIR} entry`)
  expect([...shipped[0].filter].sort()).toEqual([...UPDATER_HELPER_SCRIPTS].sort())

  for (const name of UPDATER_HELPER_SCRIPTS) {
    assert.ok(fs.existsSync(path.join(desktop, shipped[0].from, name)), `${shipped[0].from}/${name} must exist`)
  }
})

test('a helper resolves under the resources directory', () => {
  const resources = path.join('app', 'resources')

  expect(updaterHelperScript(resources, 'check-store-update.py')).toBe(
    path.join(resources, UPDATER_HELPER_DIR, 'check-store-update.py')
  )
})
