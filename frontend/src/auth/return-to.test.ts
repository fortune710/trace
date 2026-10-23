import { describe, expect, it } from 'vitest'

import { safeReturnTo } from '@/auth/return-to'

describe('safeReturnTo', () => {
  it('accepts only internal non-authentication paths', () => {
    expect(safeReturnTo('/account?tab=security')).toBe('/account?tab=security')
    expect(safeReturnTo('https://attacker.example')).toBe('/account')
    expect(safeReturnTo('//attacker.example')).toBe('/account')
    expect(safeReturnTo('/auth/callback')).toBe('/account')
  })
})
