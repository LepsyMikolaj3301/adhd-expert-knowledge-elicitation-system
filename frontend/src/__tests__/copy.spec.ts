import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/client'
import { citedTimes, directionLabel, directionNeeded, renumberNote, saveRefusal } from '@/copy'

function refusal(code: string, details?: Record<string, unknown>) {
  return new ApiError(422, { code, message: 'Server wording, not for the expert.', details })
}

describe('renumberNote', () => {
  it('says nothing when no quote comes after it', () => {
    expect(renumberNote(3, 3)).toBeNull()
  })

  it('names the one quote that moves', () => {
    expect(renumberNote(2, 3)).toBe('Quote 3 will become quote 2.')
  })

  it('names the range when several move', () => {
    expect(renumberNote(2, 5)).toBe('Quotes 3–5 will be renumbered 2–4.')
  })
})

describe('the words for a quote', () => {
  it('calls the neutral direction No bearing', () => {
    expect(directionLabel('neutral')).toBe('No bearing')
  })

  it('asks for a direction per quote', () => {
    expect(directionNeeded([2])).toBe('Choose a direction for quote 2.')
    expect(directionNeeded([2, 4])).toBe('Choose a direction for quotes 2, 4.')
  })

  it('counts citations in plain words', () => {
    expect(citedTimes(0)).toBe('Cited 0 times')
    expect(citedTimes(1)).toBe('Cited 1 time')
    expect(citedTimes(2)).toBe('Cited 2 times')
  })
})

describe('saveRefusal', () => {
  it('says a cancelled case cannot take changes', () => {
    expect(saveRefusal(refusal('not_editable', { state: 'cancelled' }))).toBe(
      "The study team has cancelled this case, so changes can't be saved.",
    )
  })

  it('says a submitted case is closed', () => {
    expect(saveRefusal(refusal('not_editable', { state: 'processing' }))).toBe(
      'This case can no longer be changed.',
    )
  })

  it('does not use the server wording for a reference that no longer matches', () => {
    for (const code of ['unknown_chip', 'chip_numbers', 'highlight_not_in_vignette']) {
      expect(saveRefusal(refusal(code))).toContain("doesn't match a quote")
    }
  })

  it('has a calm fallback that tells the expert the text is safe', () => {
    const text = saveRefusal(refusal('something_new'))
    expect(text).toContain('Your text is safe')
    expect(text).not.toContain('Server wording')
  })
})
