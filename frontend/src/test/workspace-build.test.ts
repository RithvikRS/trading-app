import { expect, it } from 'vitest'
import { assertProtectedModules } from '../../workspace-boundary'

it.each(['App.tsx', 'data/portfolio.ts', 'preferences.ts', 'data/banking.ts?raw', 'CreditCards.tsx', 'data/credit-cards.ts', 'test/workspace-ui.test.tsx'])('rejects a demo dependency in the protected module graph: %s', file => {
  expect(() => assertProtectedModules([`/project/frontend/src/${file}`], '/project/frontend/src')).toThrow('cannot import')
})
it('allows shared design tokens and protected modules on Windows and Unix', () => {
  expect(() => assertProtectedModules(['C:\\project\\frontend\\src\\design.css', 'C:\\project\\frontend\\workspace\\src\\auth.ts'], 'C:\\project\\frontend\\src')).not.toThrow()
  expect(() => assertProtectedModules(['/project/frontend/src/design.css', '/project/frontend/workspace/src/auth.ts'], '/project/frontend/src')).not.toThrow()
})
