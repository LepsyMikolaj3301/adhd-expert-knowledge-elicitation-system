/** What each step needs before the expert can move on. The server checks the same rules again. */
import type { AnswerPayload, QuestionView } from '@/api/client'

/** A question id, or the page at the end. */
export type StepId = string
export const REVIEW: StepId = 'review'
export const GATE_IDS = ['Q1', 'Q2', 'Q3']

/** The Q4 wording the API sends, which it types only as a dictionary. */
export interface Q4Wording {
  hypothesis: string
  shift_lead: string
  shift_labels: Record<string, string>
  toward: string
  toward_labels: Record<string, string>
  why: string
}

export function q4Wording(question: QuestionView): Q4Wording {
  return question.wording as unknown as Q4Wording
}

/** The counter under an answer. There is no target to reach: it only shows how much is written. */
export function wordCountLabel(words: number): string {
  return `${words} different ${words === 1 ? 'word' : 'words'}`
}

function q4Problem(payload: AnswerPayload): string | null {
  const q4 = payload.q4
  if (!q4?.hypothesis?.trim()) return 'Write your working hypothesis.'
  if (q4.shift === null || q4.shift === undefined) return 'Pick a point on the scale.'
  if (q4.shift === 0) return null
  if (q4.shift > 0) {
    if (!q4.toward) return 'Choose a direction.'
    if (q4.toward === 'other' && !q4.other_explanation?.trim()) {
      return 'Name the other explanation.'
    }
  }
  return payload.answers.Q4?.trim() ? null : 'Explain why.'
}

/** The first thing missing from this step, in words they can act on. Length never counts. */
export function stepProblem(question: QuestionView, payload: AnswerPayload): string | null {
  if (question.kind === 'shift') return q4Problem(payload)
  if (question.kind === 'rating_1_5') {
    return payload.rating || payload.insufficient_information ? null : 'Choose a rating.'
  }
  return payload.answers[question.id]?.trim() ? null : `${question.id} needs an answer.`
}

/** What stops the expert from locking in Q1 to Q3. Moving between them is never stopped. */
export function gateProblem(questions: QuestionView[], payload: AnswerPayload): string | null {
  for (const question of questions) {
    if (GATE_IDS.includes(question.id)) {
      const problem = stepProblem(question, payload)
      if (problem) return problem
    }
  }
  return null
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
