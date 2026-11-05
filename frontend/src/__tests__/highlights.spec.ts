import { describe, expect, it } from 'vitest'

import type { Citation } from '@/api/client'
import {
  addCitation,
  codePointToUtf16,
  countWords,
  citedChips,
  inkFor,
  removeCitation,
  segmentsFor,
  snapToWords,
  uncitedChips,
  utf16ToCodePoint,
} from '@/answering/highlights'
import { docToText, textToDoc } from '@/answering/chipDoc'

const TEXT = 'I have barely slept since the move. My hand starts shaking slightly.'

function citation(chip: number, text: string, source = TEXT): Citation {
  const start = source.indexOf(text)
  return { chip, text, span: [start, start + text.length], direction: null }
}

describe('offsets', () => {
  it('counts an emoji as one character for the API and two for the browser', () => {
    const text = '😀 I slept'
    expect(utf16ToCodePoint(text, 3)).toBe(2)
    expect(codePointToUtf16(text, 2)).toBe(3)
    expect(utf16ToCodePoint('plain', 3)).toBe(3)
    expect(codePointToUtf16('plain', 3)).toBe(3)
  })
})

describe('snapToWords', () => {
  it('extends a selection that stops inside a word', () => {
    const start = TEXT.indexOf('arely')
    const end = TEXT.indexOf('since') + 2
    expect(TEXT.slice(...(snapToWords(TEXT, start, end) as [number, number]))).toBe(
      'barely slept since',
    )
  })

  it('trims spaces around the selection', () => {
    const start = TEXT.indexOf(' barely')
    const end = TEXT.indexOf(' since') + 1
    expect(TEXT.slice(...(snapToWords(TEXT, start, end) as [number, number]))).toBe('barely slept')
  })

  it('keeps a contraction and accented letters whole', () => {
    const text = "I haven't śpię dobrze"
    const start = text.indexOf('ven')
    const end = text.indexOf('ię') + 1
    expect(text.slice(...(snapToWords(text, start, end) as [number, number]))).toBe("haven't śpię")
  })

  it('does not grow past punctuation at the edges', () => {
    const start = TEXT.indexOf('move.')
    const end = start + 'move.'.length
    expect(TEXT.slice(...(snapToWords(TEXT, start, end) as [number, number]))).toBe('move.')
  })

  it('gives nothing for a selection of only spaces', () => {
    const start = TEXT.indexOf(' barely')
    expect(snapToWords(TEXT, start, start + 1)).toBeNull()
  })
})

describe('addCitation', () => {
  it('adds the next number, with API offsets and no direction yet', () => {
    const start = TEXT.indexOf('hand starts')
    const result = addCitation([], TEXT, start, start + 'hand starts'.length)
    expect(result).toEqual({
      kind: 'added',
      citations: [{ chip: 1, text: 'hand starts', span: [start, start + 11], direction: null }],
    })
  })

  it('stores code point offsets when an emoji comes first', () => {
    const text = '😀 I slept'
    const start = text.indexOf('slept')
    const result = addCitation([], text, start, start + 5)
    expect(result.kind === 'added' && result.citations[0]?.span).toEqual([4, 9])
  })

  it('points at the existing citation instead of adding the same text again', () => {
    const existing = [citation(1, 'barely slept')]
    const start = TEXT.indexOf('barely slept')
    expect(addCitation(existing, TEXT, start, start + 12)).toEqual({ kind: 'duplicate', chip: 1 })
  })

  it('allows a citation that overlaps another', () => {
    const existing = [citation(1, 'barely slept')]
    const start = TEXT.indexOf('slept since')
    const result = addCitation(existing, TEXT, start, start + 11)
    expect(result.kind === 'added' && result.citations.map((c) => c.chip)).toEqual([1, 2])
  })

  it('refuses a selection too long for the API', () => {
    const long = 'word '.repeat(500)
    expect(addCitation([], long, 0, long.length).kind).toBe('too_long')
  })

  it('ignores an empty selection', () => {
    expect(addCitation([], TEXT, 3, 3).kind).toBe('empty')
  })
})

describe('removeCitation', () => {
  const all = [citation(1, 'barely slept'), citation(2, 'the move'), citation(3, 'hand starts')]

  it('renumbers later citations and their chips in every answer', () => {
    const result = removeCitation(all, { Q1: '⟦h1⟧ then ⟦h3⟧', Q2: '⟦h3⟧ only' }, 2)
    expect(result.citations.map((c) => [c.chip, c.text])).toEqual([
      [1, 'barely slept'],
      [2, 'hand starts'],
    ])
    expect(result.answers).toEqual({ Q1: '⟦h1⟧ then ⟦h2⟧', Q2: '⟦h2⟧ only' })
  })

  it('takes out the removed chip without leaving a double space', () => {
    const result = removeCitation(all, { Q1: 'see ⟦h2⟧ and more', Q2: '⟦h2⟧ first' }, 2)
    expect(result.answers).toEqual({ Q1: 'see and more', Q2: 'first' })
  })

  it('leaves line breaks alone', () => {
    const result = removeCitation(all, { Q1: 'one\n\n⟦h1⟧ two' }, 3)
    expect(result.answers.Q1).toBe('one\n\n⟦h1⟧ two')
  })
})

describe('countWords', () => {
  it('counts different words like the server', () => {
    expect(countWords('test Test TEST, test!')).toBe(1)
    expect(countWords('... --- !!!')).toBe(0)
    expect(countWords('Pacjent nie śpi dobrze')).toBe(4)
  })

  it('ignores chips', () => {
    expect(countWords('⟦h1⟧ ⟦h2⟧ ⟦h3⟧ word')).toBe(1)
  })
})

describe('cited and uncited', () => {
  it('finds which citations are never used', () => {
    const all = [citation(1, 'barely slept'), citation(2, 'the move')]
    const answers = { Q1: 'See ⟦h2⟧.' }
    expect([...citedChips(answers)]).toEqual([2])
    expect(uncitedChips(all, answers)).toEqual([1])
  })
})

describe('inkFor', () => {
  it('gives each number its own ink and starts again after eight', () => {
    expect(inkFor(1)).toBe('var(--ink-1)')
    expect(inkFor(8)).toBe('var(--ink-8)')
    expect(inkFor(9)).toBe('var(--ink-1)')
  })
})

describe('segmentsFor', () => {
  it('is one plain run when nothing is active', () => {
    expect(segmentsFor(TEXT, null)).toEqual({ before: TEXT, marked: '', after: '' })
  })

  it('splits around the active citation, using browser offsets', () => {
    const text = '😀 I slept badly'
    const active: Citation = { chip: 1, text: 'slept', span: [4, 9], direction: null }
    expect(segmentsFor(text, active)).toEqual({
      before: '😀 I ',
      marked: 'slept',
      after: ' badly',
    })
  })
})

describe('chipDoc', () => {
  const cases = [
    '',
    'plain words',
    '⟦h2⟧ could just as easily be burnout',
    'two ⟦h1⟧⟦h2⟧ together, then ⟦h12⟧.',
    'first line\nsecond line',
    'one\n\nblank line above\n',
    '  spaces kept  ',
  ]

  it.each(cases)('returns exactly the same text for %j', (text) => {
    expect(docToText(textToDoc(text))).toBe(text)
  })

  it('makes each chip one node', () => {
    expect(textToDoc('a ⟦h3⟧ b')).toEqual({
      type: 'doc',
      content: [
        {
          type: 'paragraph',
          content: [
            { type: 'text', text: 'a ' },
            { type: 'chip', attrs: { n: 3 } },
            { type: 'text', text: ' b' },
          ],
        },
      ],
    })
  })
})
