import { describe, expect, it } from 'vitest'

import { plainText } from '@/answering/plainText'
import type { AnswerPayload, QuestionView } from '@/api/client'

const QUESTIONS: QuestionView[] = [
  { id: 'Q1', kind: 'open', text: 'First?' },
  { id: 'Q2', kind: 'open', text: 'Second?' },
  { id: 'Q4', kind: 'shift', text: 'Fourth?' },
  { id: 'Q6', kind: 'rating_1_5', text: 'Sixth?' },
]

function payload(extra: Partial<AnswerPayload>): AnswerPayload {
  return { answers: {}, highlights: [], insufficient_information: false, ...extra }
}

describe('plainText', () => {
  it('lists what was written in question order, with references as [n]', () => {
    const text = plainText(
      payload({ answers: { Q2: 'second', Q1: '⟦h1⟧ could be burnout, see ⟦h2⟧.' } }),
      QUESTIONS,
    )
    expect(text).toBe('Q1\n[1] could be burnout, see [2].\n\nQ2\nsecond')
  })

  it('keeps the words exactly as written, line breaks included', () => {
    expect(plainText(payload({ answers: { Q1: 'one\n\n  two  ' } }), QUESTIONS)).toBe(
      'Q1\none\n\n  two  ',
    )
  })

  it('includes the Q4 hypothesis and reason, and the rating', () => {
    const text = plainText(
      payload({
        answers: { Q4: 'because of the exam' },
        q4: {
          hypothesis: 'tired, not a trait',
          shift: 1,
          toward: 'other',
          other_explanation: 'exam',
        },
        rating: 3,
      }),
      QUESTIONS,
    )
    expect(text).toBe(
      [
        'Q4',
        'Hypothesis: tired, not a trait',
        'Other explanation: exam',
        'Why: because of the exam',
        '',
        'Q6',
        'Rating: 3 of 5',
      ].join('\n'),
    )
  })

  it('says when there was not enough information, and skips questions with nothing written', () => {
    expect(plainText(payload({ insufficient_information: true }), QUESTIONS)).toBe(
      'Q6\nInsufficient information',
    )
    expect(plainText(payload({}), QUESTIONS)).toBe('')
  })
})
