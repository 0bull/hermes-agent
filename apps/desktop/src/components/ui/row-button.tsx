import * as React from 'react'

import { Tip } from './tooltip'

/**
 * A full-row / region click target rendered as a real `<button>`: bakes in
 * `type="button"` + a stable `data-slot`, imposes no styling (callers keep their
 * own layout classes, so nothing changes visually). Use for row/region targets;
 * use `Button` for ordinary compact actions.
 */
function RowButton({ className, type = 'button', title, ...props }: React.ComponentProps<'button'>) {
  const button = <button className={className} data-slot="row-button" type={type} {...props} />

  return title ? <Tip label={title}>{button}</Tip> : button
}

export { RowButton }
