import { render, screen } from '@testing-library/react'
import { createElement } from 'react'
import { describe, expect, it } from 'vitest'

import { CopyButton } from '../copy-button'
import { RowButton } from '../row-button'

describe('button tooltips', () => {
  it('RowButton uses an accessible name without leaking a native title through forwarded props', () => {
    render(createElement(RowButton, { title: 'Select item', 'aria-label': 'Select item' }))
    const button = screen.getByRole('button', { name: 'Select item' })
    expect(button.getAttribute('title')).toBeNull()
  })

  it('CopyButton renders its title as a themed tip, not a native button title', () => {
    render(createElement(CopyButton, { appearance: 'icon', text: 'hello', title: 'Copy value', label: 'Copy value' }))
    const button = screen.getByRole('button', { name: 'Copy value' })
    expect(button.getAttribute('title')).toBeNull()
    expect(button.getAttribute('data-slot')).toBe('tooltip-trigger')
  })
})
