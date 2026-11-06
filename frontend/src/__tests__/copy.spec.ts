import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/client'
import { saveRefusal } from '@/copy'

function refusal(code: string, details?: Record<string, unknown>) {
  return new ApiError(422, { code, message: 'Server wording, not for the expert.', details })
}

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
      expect(saveRefusal(refusal(code))).toContain("doesn't match a marked passage")
    }
  })

  it('has a calm fallback that tells the expert the text is safe', () => {
    const text = saveRefusal(refusal('something_new'))
    expect(text).toContain('Your text is safe')
    expect(text).not.toContain('Server wording')
  })
})
