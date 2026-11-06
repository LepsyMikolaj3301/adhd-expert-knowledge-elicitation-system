/**
 * Wording the expert reads, in one place. Clinical words, not engineering ones: "marked passage",
 * not "highlight" or "citation"; "reference", not "chip"; "case", not "vignette". The API's own
 * messages use the old terms, so what an expert sees for an error comes from here, by its stable
 * `code`. The questions themselves are not here: they come from the API, worded the same for all.
 */
import { ApiError, type Direction } from '@/api/client'

/** Says what happens to the answers. Keep it true: check it against the consent text. */
export const TRUST_SENTENCE =
  'Your answers are kept word for word under a pseudonym and, after review, an AI assistant can cite them as clinician opinion.'

/** The stored values are `toward`/`away`/`neutral`/`unclear`; this is what the expert reads. */
export const DIRECTIONS: { value: Direction; label: string }[] = [
  { value: 'toward', label: 'Points toward ADHD traits' },
  { value: 'away', label: 'Points away from ADHD traits' },
  { value: 'neutral', label: 'Ordinary, no bearing' },
  { value: 'unclear', label: 'Unclear' },
]

export function directionLabel(direction: Direction | null | undefined): string {
  return DIRECTIONS.find((d) => d.value === direction)?.label ?? ''
}

function list(items: (string | number)[]): string {
  return items.join(', ')
}

/** "Choose a direction for passage 2." / "…for passages 2, 4." */
export function directionNeeded(chips: number[]): string {
  return `Choose a direction for ${chips.length === 1 ? 'passage' : 'passages'} ${list(chips)}.`
}

/** "Passage 2 is not mentioned in any answer." Only a note: it never stops anyone. */
export function notMentioned(chips: number[], where: 'in any answer' | 'in an answer yet'): string {
  const one = chips.length === 1
  return `${one ? 'Passage' : 'Passages'} ${list(chips)} ${one ? 'is' : 'are'} not mentioned ${where}.`
}

export function markedPassages(count: number): string {
  return count === 1 ? 'marked passage' : `${count} marked passages`
}

/** "Q3" on the screen's heading reads "Question 3". The step rail keeps the short form. */
export function questionLabel(id: string): string {
  return id.replace(/^Q(\d+)$/i, 'Question $1')
}

const STUDY_TEAM = 'the study team'
const SAFE_FALLBACK = `Something went wrong. Your text is safe. Please try again, or contact ${STUDY_TEAM}.`

function numbers(value: unknown): number[] {
  return Array.isArray(value) ? value.map(Number).filter((n) => Number.isInteger(n)) : []
}

/** The server names questions "Q3"; the expert reads "question 3". */
function questionNumbers(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map((id) => String(id).replace(/^Q/i, '')).filter((n) => /^\d+$/.test(n))
    : []
}

/** What went wrong, in words an expert can act on. Never the server's own wording. */
export function describeError(error: unknown): string {
  if (!(error instanceof ApiError)) return SAFE_FALLBACK
  switch (error.code) {
    case 'not_editable':
      return error.details?.state === 'cancelled'
        ? "The study team has cancelled this case, so changes can't be saved."
        : 'This case can no longer be changed.'
    case 'gate_not_passed':
      return 'Please answer questions 1–3 first.'
    case 'gate_locked':
      return "Part 1 is already locked, so this can't change."
    case 'submission_incomplete':
      return "Something's still missing. Please look through your answers and try again."
    case 'empty_answer': {
      const questions = questionNumbers(error.details?.answers)
      if (!questions.length) return 'An answer needs a little more.'
      return questions.length === 1
        ? `Question ${questions[0]} needs a little more.`
        : `Questions ${list(questions)} need a little more.`
    }
    case 'highlight_no_direction': {
      const chips = numbers(error.details?.chips)
      return chips.length ? directionNeeded(chips) : 'Choose a direction for each marked passage.'
    }
    case 'unknown_chip':
    case 'chip_numbers':
    case 'highlight_not_in_vignette':
      return (
        "A reference in your answer doesn't match a marked passage. Please check your answers. " +
        `If it continues, contact ${STUDY_TEAM}.`
      )
    case 'not_found':
      return "We can't find this case in your list. It may have been reassigned."
    case 'unavailable':
      return "We can't reach the server right now. Please try again in a moment."
    default:
      return SAFE_FALLBACK
  }
}

/** Why a save was refused. The same words as any other error. */
export function saveRefusal(error: ApiError): string {
  return describeError(error)
}
