/**
 * What the expert has written, as plain text to keep somewhere safe. The words are exactly as
 * written; only a reference is spelled [n] instead of its stored ⟦hN⟧ form.
 */
import type { AnswerPayload, QuestionView } from '@/api/client'

import { CHIP_RE } from './highlights'

function readable(text: string): string {
  return text.replace(CHIP_RE, (_match, n: string) => `[${n}]`)
}

export function plainText(payload: AnswerPayload, questions: QuestionView[]): string {
  const blocks: string[] = []
  for (const question of questions) {
    const lines: string[] = []
    const answer = payload.answers[question.id]
    if (question.kind === 'open') {
      if (answer?.trim()) lines.push(readable(answer))
    } else if (question.kind === 'shift') {
      const q4 = payload.q4
      if (q4?.hypothesis?.trim()) lines.push(`Hypothesis: ${q4.hypothesis}`)
      if (q4?.toward === 'other' && q4.other_explanation?.trim()) {
        lines.push(`Other explanation: ${q4.other_explanation}`)
      }
      if (answer?.trim()) lines.push(`Why: ${readable(answer)}`)
    } else if (payload.insufficient_information) {
      lines.push('Insufficient information')
    } else if (payload.rating) {
      lines.push(`Rating: ${payload.rating} of 5`)
    }
    if (lines.length) blocks.push([question.id, ...lines].join('\n'))
  }
  return blocks.join('\n\n')
}
