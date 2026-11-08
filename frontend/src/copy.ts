/**
 * Wording the expert reads, in one place. Clinical words, not engineering ones: "quote", not
 * "highlight" or "citation"; "reference", not "chip"; "case", not "vignette". The API's own
 * messages use the old terms, so what an expert sees for an error comes from here, by its stable
 * `code`. The questions themselves are not here: they come from the API, worded the same for all.
 */
import {
  ApiError,
  type ActivityItem,
  type Direction,
  type ReviewItem,
  type Speaker,
} from '@/api/client'

/** Says what happens to the answers. Keep it true: check it against the consent text. */
export const TRUST_SENTENCE =
  'Your answers are kept word for word under a pseudonym and, after review, an AI assistant can cite them as clinician opinion.'

/** The stored values are `toward`/`away`/`neutral`/`unclear`; this is what the expert reads. */
export const DIRECTIONS: { value: Direction; label: string; help: string }[] = [
  {
    value: 'toward',
    label: 'Points toward ADHD traits',
    help: 'This quote makes ADHD-related traits more likely in your reading.',
  },
  {
    value: 'away',
    label: 'Points away from ADHD traits',
    help: 'This quote makes them less likely, or better explained by something else.',
  },
  {
    value: 'neutral',
    label: 'No bearing',
    help: 'An ordinary detail that says nothing either way.',
  },
  {
    value: 'unclear',
    label: 'Unclear',
    help: "It could go either way, or you can't tell from the text.",
  },
]

/**
 * The instruction page experts see before their first case. Plain words, short sentences. The
 * study team should read this once: it promises things about how the questionnaire works.
 */
export const INTRO = {
  title: 'Before you begin',
  lead: 'A few minutes here saves you trouble later. You can open these instructions again from My cases.',
  what: {
    heading: 'What this is',
    text: [
      'Each case is a short text written by a real person: a forum post, a journal entry or an email. You read it and answer a few questions about what in it matters, and what it suggests to you as a clinician.',
      'There are no right answers. We want your own reading.',
    ],
  },
  aim: {
    heading: 'What we are asking of you',
    items: [
      {
        term: 'Clear quotes',
        text: 'Point to the exact words your reading rests on. A short, specific quote is more useful than a long one.',
      },
      {
        term: 'Your reasoning',
        text: 'Say why those words matter, in your own words. A verdict alone is not enough.',
      },
      {
        term: 'Clinical language',
        text: 'Write as you would in a case note. Use the terms you would normally use.',
      },
    ],
  },
  structure: {
    heading: 'How it is structured',
    lead: 'Each case has two stages, and the first one is locked once you finish it.',
    steps: [
      {
        term: 'Stage 1: Q1 to Q3',
        text: 'You answer these three together, from your first reading of the text.',
      },
      {
        term: 'Lock in',
        text: "When you lock in, you can't change your answers to Q1 to Q3 or the quotes you have made so far, including their directions. This keeps your first reading as you wrote it.",
      },
      {
        term: 'Stage 2: Q4 to Q6',
        text: 'The remaining questions open. You can still add new quotes here.',
      },
      {
        term: 'Review and submit',
        text: 'You check all your answers, then submit. After you submit, nothing can be changed.',
      },
    ],
    flow: ['Stage 1', 'Lock in', 'Stage 2', 'Review', 'Submit'],
    save: 'Your work is saved as you go, so you can leave and come back to a case.',
  },
  hints: {
    heading: 'Setting quotes and directions',
    items: [
      'To make a quote, select words in the text. The selection snaps to whole words.',
      'Click a quote in the list to put a reference to it in your answer, where your cursor is.',
      'Every quote needs a direction: what it does to your reading. If something is missing when you try to go on, it is marked in red.',
      "Not every text has something worth quoting. If that's your reading, that's fine.",
    ],
    directionsLead: 'The four directions',
  },
  hideAgain: "Don't show this again",
  continue: 'I understand, continue',
} as const

export function directionLabel(direction: Direction | null | undefined): string {
  return DIRECTIONS.find((d) => d.value === direction)?.label ?? ''
}

function list(items: (string | number)[]): string {
  return items.join(', ')
}

/** "Choose a direction for quote 2." / "…for quotes 2, 4." */
export function directionNeeded(chips: number[]): string {
  return `Choose a direction for ${chips.length === 1 ? 'quote' : 'quotes'} ${list(chips)}.`
}

/** "Quote 2 is not mentioned in any answer." Only a note: it never stops anyone. */
export function notMentioned(chips: number[], where: 'in any answer' | 'in an answer yet'): string {
  const one = chips.length === 1
  return `${one ? 'Quote' : 'Quotes'} ${list(chips)} ${one ? 'is' : 'are'} not mentioned ${where}.`
}

export function quoteCount(count: number): string {
  return count === 1 ? '1 quote' : `${count} quotes`
}

/** "Cited 2 times", on a quote's row. */
export function citedTimes(count: number): string {
  return `Cited ${count} ${count === 1 ? 'time' : 'times'}`
}

/** What removing a quote does to the answers. */
export function removalNote(count: number): string {
  if (!count) return "It isn't cited in any answer yet."
  const times = count === 1 ? 'once' : `${count} times`
  return `It is cited ${times}. Removing it also takes it out of your answers.`
}

/** What removing a quote does to the numbers of the ones after it. Null if there are none. */
export function renumberNote(chip: number, total: number): string | null {
  if (chip >= total) return null
  if (chip + 1 === total) return `Quote ${total} will become quote ${chip}.`
  return `Quotes ${chip + 1}–${total} will be renumbered ${chip}–${total - 1}.`
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
      return chips.length ? directionNeeded(chips) : 'Choose a direction for each quote.'
    }
    case 'unknown_chip':
    case 'chip_numbers':
    case 'highlight_not_in_vignette':
      return (
        "A reference in your answer doesn't match a quote. Please check your answers. " +
        `If it continues, contact ${STUDY_TEAM}.`
      )
    case 'review_closed':
      return 'The study team has already decided on this case, so this can no longer be added. What you typed is still here.'
    case 'stale_round':
      return 'The statements changed while you were reading. We have loaded the new ones, so please look again.'
    case 'comment_required':
      return 'Please say what should change.'
    case 'findings_conflict':
      return 'This was changed in another tab or device. Please reload to see the latest.'
    case 'email_taken':
      return 'Someone already has an account with this email.'
    case 'cannot_deactivate_self':
      return "You can't deactivate your own account."
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

/** The word experts read for what the API calls a unit. */
export const STATEMENT = 'statement'

/** The tally is advice for the study team, never a verdict. */
export function tallyLabel(accepts: number, declines: number): string {
  return `${accepts} accept, ${declines} decline`
}

export function speakerLabel(speaker: Speaker | null | undefined): string {
  if (!speaker) return ''
  if (speaker.pseudonym) return speaker.pseudonym
  return { author: 'Author', admin: 'Admin', reviewer: 'A reviewer' }[speaker.kind]
}

export const STANCES = { support: 'Supports', challenge: 'Challenges', question: 'Asks' } as const

/** What the study team did with a submission, as the page of a closed review says it. */
export function reviewOutcome(state: ReviewItem['state'], round: number): string | null {
  if (state === 'peer_review') return null
  if (state === 'expert_check')
    return `Sent back to the author for changes. A new round (${round}) follows.`
  if (state === 'rejected') return 'Closed: the study team rejected these statements.'
  return 'Closed: the study team decided. Approved statements go into the knowledge base.'
}

/** One sentence per kind of change in the home feed. */
export function activityText(a: ActivityItem): string {
  const who = speakerLabel(a.speaker)
  const where = `${STATEMENT} ${a.unit_ordinal ?? ''} of case ${a.vignette_code}`.replace('  ', ' ')
  switch (a.kind) {
    case 'case_assigned':
      return `Case ${a.vignette_code} was assigned to you.`
    case 'check_ready':
      return `Case ${a.vignette_code} is ready for you to check.`
    case 'review_opened':
      return `Case ${a.vignette_code} is open for review.`
    case 'review_closed':
      return a.outcome === 'sent_back'
        ? `Case ${a.vignette_code} was sent back for changes.`
        : `The review of case ${a.vignette_code} is closed${a.outcome ? `: ${a.outcome}` : ''}.`
    case 'comment_on_mine':
      return `${who} commented on ${where}.`
    case 'reply':
      return `${who} replied in the discussion of ${where}.`
    case 'job_failed':
      return `Processing case ${a.vignette_code} failed.`
  }
}
