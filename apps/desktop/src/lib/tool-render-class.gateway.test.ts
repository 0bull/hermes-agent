import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

import { expect, it } from 'vitest'

import { CONNECTION_CARD_KEY, isCardTool, isFileEditTool } from './tool-render-class'

interface GatewayFrame {
  method: string
  params: {
    type: string
    payload: { tool_id?: string }
  }
}

interface GatewayProbe {
  names: string[]
  frames: GatewayFrame[]
}

it('delivers both gateway lifecycle frames for every registered Desktop card', () => {
  const repoRoot = resolve(process.cwd(), '../..')
  const home = mkdtempSync(join(tmpdir(), 'hermes-card-lifecycle-'))

  const script = [
    'import json, os',
    'from types import SimpleNamespace',
    'from tools.registry import discover_builtin_tools, registry',
    'from tui_gateway import server',
    'discover_builtin_tools()',
    'names = sorted(registry.get_all_tool_names())',
    'frames = []',
    'server.write_json = lambda frame: frames.append(frame) or True',
    'sid = "desktop-card-contract"',
    'server._sessions[sid] = {',
    '  "show_reasoning": False, "tool_progress_mode": "off",',
    '  "tool_started_at": {}, "edit_snapshots": {},',
    '  "agent": SimpleNamespace(reasoning_config={"enabled": True, "effort": "high"}),',
    '  "transport": SimpleNamespace(write=lambda frame: frames.append(frame) or True),',
    '}',
    'for name in names:',
    '  tool_id = "registry-" + name',
    '  server._on_tool_start(sid, tool_id, name, {})',
    '  server._on_tool_complete(sid, tool_id, name, {}, json.dumps({"success": True}))',
    'os.write(1, (json.dumps({"names": names, "frames": frames}) + "\\n").encode())'
  ].join('\n')

  let probe: GatewayProbe

  try {
    const output = execFileSync(process.env.HERMES_PYTHON ?? 'python3', ['-c', script], {
      cwd: repoRoot,
      encoding: 'utf8',
      env: { ...process.env, HERMES_HOME: home },
      timeout: 60_000
    })

    probe = JSON.parse(output)
  } finally {
    rmSync(home, { recursive: true, force: true })
  }

  expect(probe.names).toEqual(expect.arrayContaining(['clarify', 'write_file', 'read_file']))
  expect(probe.names).not.toContain(CONNECTION_CARD_KEY)
  const cards = probe.names.filter(isCardTool)
  expect(cards).toContain('write_file')
  expect(cards.filter(isFileEditTool)).not.toHaveLength(0)

  for (const name of cards) {
    const lifecycle = probe.frames
      .filter(frame => frame.method === 'event' && frame.params.payload?.tool_id === `registry-${name}`)
      .map(frame => frame.params.type)

    expect(lifecycle, name).toEqual(['tool.start', 'tool.complete'])
  }

  const readLifecycle = probe.frames
    .filter(frame => frame.method === 'event' && frame.params.payload?.tool_id === 'registry-read_file')

  expect(readLifecycle).toEqual([])
})
