// The Windows updaters run three helpers outside the Electron main process:
// two Python checkers under the payload interpreter and the PowerShell
// relaunch waiter. The sealed payload's repo snapshot omits apps/ and
// scripts/ (INERT_SNAPSHOT_DIRS), so the helpers ship as app resources
// (electron-builder.config.cjs win.extraResources) and resolve from there.

import * as path from 'node:path'

/** Directory under the app's resources holding the helpers. */
export const UPDATER_HELPER_DIR = 'updater-scripts'

/** Every helper the updaters run; the packaging config must ship each one. */
export const UPDATER_HELPER_SCRIPTS = [
  'check-appinstaller-update.py',
  'check-store-update.py',
  'update-relaunch-waiter.ps1'
] as const

export type UpdaterHelperScript = (typeof UPDATER_HELPER_SCRIPTS)[number]

export function updaterHelperScript(resourcesPath: string, name: UpdaterHelperScript): string {
  return path.join(resourcesPath, UPDATER_HELPER_DIR, name)
}
