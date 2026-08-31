import { describe, expect, it } from 'vitest'
import { formatBytes, titleCase } from '../src/utils/format'

describe('format utilities', () => {
  it('formats byte values', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(1024)).toBe('1.0 KB')
  })

  it('turns API keys into labels', () => {
    expect(titleCase('governing_law')).toBe('Governing Law')
  })
})
