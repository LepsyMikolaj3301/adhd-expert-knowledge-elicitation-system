import { describe, expect, it } from 'vitest'

import { listMarker, nextMarker } from '@/answering/listLines'

describe('listMarker', () => {
  it('finds a number or a dash at the start of a line', () => {
    expect(listMarker('1. first')).toBe('1. ')
    expect(listMarker('12) twelfth')).toBe('12) ')
    expect(listMarker('- item')).toBe('- ')
    expect(listMarker('• item')).toBe('• ')
    expect(listMarker('  - indented')).toBe('  - ')
  })

  it('leaves ordinary text alone', () => {
    for (const line of [
      '1.5 hours of sleep',
      '-5 points',
      '2024 was hard',
      'a - b',
      '1.',
      '-',
      '',
    ]) {
      expect(listMarker(line)).toBeNull()
    }
  })
})

describe('nextMarker', () => {
  it('counts numbers up and repeats dashes', () => {
    expect(nextMarker('1. ')).toBe('2. ')
    expect(nextMarker('9) ')).toBe('10) ')
    expect(nextMarker('- ')).toBe('- ')
    expect(nextMarker('  • ')).toBe('  • ')
    expect(nextMarker('  3. ')).toBe('  4. ')
  })
})
