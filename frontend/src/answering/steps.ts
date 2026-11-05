/** What each step needs before the expert can move on. The server checks the same rules again. */
import type { AnswerPayload, QuestionView } from '@/api/client'

import { countWords } from './highlights'

/** A question id, or the page at the end. */
export type StepId = string
export const REVIEW: StepId = 'review'
export const GATE_IDS = ['Q1', 'Q2', 'Q3']

/** The Q4 wording the API sends, which it types only as a dictionary. */
export interface Q4Wording {
  hypothesis: string
  hypothesis_min_words: number
  shift_lead: string
  shift_labels: Record<string, string>
  toward: string
  toward_labels: Record<string, string>
  why: string
}

export function q4Wording(question: QuestionView): Q4Wording {
  return question.wording as unknown as Q4Wording
}

/** The counter under an answer. Once there are enough words, the target stops mattering. */
export function wordCountLabel(words: number, minimum: number | null | undefined): string {
  return minimum && words < minimum
    ? `${words} of ${minimum} different words`
    : `${words} different words`
}

function tooFewWords(label: string, text: string, minimum: number): string | null {
  const words = countWords(text)
  return words < minimum ? `${label} has ${words} of ${minimum} different words.` : null
}

function q4Problem(question: QuestionView, payload: AnswerPayload): string | null {
  const q4 = payload.q4
  const hypothesisMinimum = (question.wording?.hypothesis_min_words as number | undefined) ?? 1
  if (countWords(q4?.hypothesis ?? '') < hypothesisMinimum) return 'Write your working hypothesis.'
  if (q4?.shift === null || q4?.shift === undefined) return 'Pick a point on the scale.'
  if (q4.shift === 0) return null
  if (q4.shift > 0) {
    if (!q4.toward) return 'Choose a direction.'
    if (q4.toward === 'other' && !q4.other_explanation?.trim()) {
      return 'Name the other explanation.'
    }
  }
  return tooFewWords('Why?', payload.answers.Q4 ?? '', question.min_words ?? 1)
}

/** The first thing stopping the expert from leaving this step, in words they can act on. */
export function stepProblem(question: QuestionView, payload: AnswerPayload): string | null {
  if (question.kind === 'shift') return q4Problem(question, payload)
  if (question.kind === 'rating_1_5') {
    return payload.rating || payload.insufficient_information ? null : 'Choose a rating.'
  }
  return tooFewWords(question.id, payload.answers[question.id] ?? '', question.min_words ?? 1)
}

/** Where to open a vignette. Before the gate that is at most Q3, which holds the lock-in button. */
export function firstOpenStep(
  questions: QuestionView[],
  payload: AnswerPayload,
  gateOpen: boolean,
): StepId {
  for (const question of questions) {
    if (stepProblem(question, payload)) return question.id
  }
  return gateOpen ? REVIEW : (questions[questions.length - 1]?.id ?? REVIEW)
}

/**
 * The draft as it goes to the server: the screen may remember hidden Q4 parts in case the scale
 * moves back, but the server submits what is saved, and refuses leftovers.
 */
export function forSaving(payload: AnswerPayload): AnswerPayload {
  const q4 = payload.q4
  if (!q4) return payload
  const shift = q4.shift ?? null
  const toward = shift !== null && shift > 0 ? (q4.toward ?? null) : null
  const answers = { ...payload.answers }
  if (shift === 0) delete answers.Q4
  return {
    ...payload,
    answers,
    q4: {
      ...q4,
      toward,
      other_explanation: toward === 'other' ? (q4.other_explanation ?? null) : null,
    },
  }
}
