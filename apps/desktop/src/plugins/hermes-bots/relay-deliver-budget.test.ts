import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  RELAY_DELIVER_BACKEND_CEILING_MS,
  RELAY_DELIVER_SETTLEMENT_MARGIN_MS,
  RELAY_DELIVER_TIMEOUT_MS,
  RELAY_TURN_ATTEMPT_MS,
  RELAY_TURN_LOCK_WAIT_MS,
  RELAY_TURN_MAX_ATTEMPTS
} from './relay-budget'

interface BackendBudget {
  turnWaitSeconds: number
  attemptSeconds: number
  maxAttempts: number
  settlementSeconds: number
  deliverSeconds: number
}

const repoRoot = join(process.cwd(), '..', '..')
const localPython = join(repoRoot, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
const python = process.env.HERMES_PYTHON ?? (existsSync(localPython) ? localPython : 'python3')

const backendBudget: BackendBudget = JSON.parse(execFileSync(python, ['-c', [
  'import json',
  'from hermes_cli.config_defaults import DEFAULT_CONFIG',
  'from tools import bot_relay',
  'print(json.dumps({',
  '  "turnWaitSeconds": DEFAULT_CONFIG["bot_mode"]["turn_wait_seconds"],',
  '  "attemptSeconds": bot_relay.TURN_ATTEMPT_TIMEOUT_SECONDS,',
  '  "maxAttempts": bot_relay.TURN_MAX_ATTEMPTS,',
  '  "settlementSeconds": bot_relay.DESKTOP_DELIVER_SETTLEMENT_MARGIN_SECONDS,',
  '  "deliverSeconds": bot_relay.DESKTOP_DELIVER_TIMEOUT_SECONDS,',
  '}))'
].join('\n')], { cwd: repoRoot, encoding: 'utf8' }))


describe('bot_relay.deliver budget', () => {
  it('outlives the backend turn bound with its settlement margin', () => {
    const backendCeiling = (backendBudget.turnWaitSeconds + backendBudget.attemptSeconds * backendBudget.maxAttempts) * 1000
    expect(RELAY_TURN_LOCK_WAIT_MS).toBe(backendBudget.turnWaitSeconds * 1000)
    expect(RELAY_TURN_ATTEMPT_MS).toBe(backendBudget.attemptSeconds * 1000)
    expect(RELAY_TURN_MAX_ATTEMPTS).toBe(backendBudget.maxAttempts)
    expect(RELAY_DELIVER_SETTLEMENT_MARGIN_MS).toBe(backendBudget.settlementSeconds * 1000)
    expect(RELAY_DELIVER_SETTLEMENT_MARGIN_MS).toBeGreaterThan(0)
    expect(RELAY_DELIVER_BACKEND_CEILING_MS).toBe(backendCeiling)
    expect(RELAY_DELIVER_TIMEOUT_MS).toBe(backendBudget.deliverSeconds * 1000)
    expect(RELAY_DELIVER_TIMEOUT_MS).toBeGreaterThan(backendCeiling)
  })
})
