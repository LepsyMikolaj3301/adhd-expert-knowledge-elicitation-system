import { describe, expect, it } from 'vitest'

import { changed, tokens, wordDiff } from '@/answering/wordDiff'

describe('wordDiff', () => {
  it('marks words added and removed, and keeps the rest', () => {
    expect(wordDiff('he dont know teh move', "he doesn't know the move")).toEqual([
      { kind: 'same', text: 'he ' },
      { kind: 'removed', text: 'dont ' },
      { kind: 'added', text: "doesn't " },
      { kind: 'same', text: 'know ' },
      { kind: 'removed', text: 'teh ' },
      { kind: 'added', text: 'the ' },
      { kind: 'same', text: 'move' },
    ])
  })

  it('keeps a chip whole, and a line break is a change of its own', () => {
    const parts = wordDiff('⟦h1⟧ shows it. Not a trait.', '⟦h1⟧ shows it.\nNot a trait.')
    expect(parts[0]).toEqual({ kind: 'same', text: '⟦h1⟧ shows it.' })
    expect(parts.filter((p) => p.kind !== 'same')).toEqual([{ kind: 'added', text: '\n' }])
    expect(tokens('a ⟦h12⟧, b\nc')).toEqual(['a ', '⟦h12⟧, ', 'b', '\n', 'c'])
  })

  it('reads the same text back from either side', () => {
    const before = 'one two three four'
    const after = 'one 2 three five four'
    const parts = wordDiff(before, after)
    const side = (kind: 'added' | 'removed') =>
      parts
        .filter((p) => p.kind !== kind)
        .map((p) => p.text)
        .join('')
    expect(side('added')).toBe(before)
    expect(side('removed')).toBe(after)
  })

  it('tells real changes from new line breaks', () => {
    expect(changed('one. two.', 'one.\ntwo.')).toBe(false)
    expect(changed('one. two.', 'one. three.')).toBe(true)
  })
})
