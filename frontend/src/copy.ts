/**
 * Wording the expert reads, in one place. Clinical words, not engineering ones: "quote", not
 * "highlight" or "citation"; "reference", not "chip"; "case", not "vignette" (except where the
 * About page explains the method). The API's own
 * messages use the old terms, so what an expert sees for an error comes from here, by its stable
 * `code`. The questions themselves are not here: they come from the API, worded the same for all.
 */
import {
  ApiError,
  type ActivityItem,
  type AssignmentSummary,
  type Direction,
  type LinkedHighlight,
  type ReviewItem,
  type SystemStatus,
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
    lead: 'You can answer the questions in any order and change any of them until you submit.',
    steps: [
      {
        term: 'Answer Q1 to Q6',
        text: 'Move freely between the questions. Your quotes and their directions can change too.',
      },
      {
        term: 'Submit for proofreading',
        text: 'We check spelling, grammar and punctuation, leave out anything unreadable, and write short notes out as full sentences. This takes a minute or two.',
      },
      {
        term: 'Check the edited text',
        text: 'You see your answer next to the edited one, with every change marked. Change anything you want, and check which quotes each sentence is about.',
      },
      {
        term: 'Submit for review',
        text: 'Colleagues read your edited answers and comment; the study team decides. After this, nothing can be changed unless they send it back to you.',
      },
    ],
    flow: ['Answer', 'Proofread', 'Check', 'Review'],
    save: 'Your work is saved as you go, so you can leave and come back to a case.',
  },
  hints: {
    heading: 'Setting quotes and directions',
    items: [
      'To make a quote, select words in the text and press “Add quote”. The selection snaps to whole words.',
      'Click a quote in the list to put a reference to it in your answer, where your cursor is.',
      'Every quote needs a direction: what it does to your reading. If something is missing when you try to go on, it is marked in red.',
      "Not every text has something worth quoting. If that's your reading, that's fine.",
    ],
    directionsLead: 'The four directions',
  },
  hideAgain: "Don't show this again",
  continue: 'I understand, continue',
} as const

/** The case on the answer and review screens: who it is about, then the text itself. */
export const CASE_TEXT = {
  summaryHeading: 'About the patient',
  heading: 'Patient text',
  textType: 'Written as',
  answerLead: 'This is the text you analyse. Your answers and quotes come from it.',
  reviewLead: 'The text the answers are about.',
} as const

/** Quoting from the case: select words, then press the button that appears under them. */
export const CITE = {
  add: 'Add quote',
  toComment: 'Quote in comment',
  help: 'How to add a quote',
  helpSteps: 'Select words in the text above, then press “Add quote” right under them.',
  helpThen: 'Then choose its direction in the list of quotes.',
} as const

/** Setting a password from the link the study team sent. */
export const INVITE = {
  heading: 'Set your password',
  label: (min: number) => `Password (at least ${min} characters)`,
  submit: 'Set password',
  tooShort: (min: number, length: number) =>
    `The password needs at least ${min} characters. It has ${length} now.`,
  checking: 'Checking your link…',
  deadHeading: "This link can't be used",
  deadLead:
    'It has already been used to set a password, or it has expired. Each link works only once.',
  deadNext:
    'If you already set your password, sign in. Otherwise, ask the study team for a new link.',
  signIn: 'Go to sign in',
} as const

type ByRole<T> = { expert: T; admin: T }

/** "12 min", "2 h": how long a job has waited. */
function waited(minutes: number): string {
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h`
}

function jobs(count: number): string {
  return count === 1 ? '1 job' : `${count} jobs`
}

/** "ollama" → "Ollama can't be reached", as the API words it in `compute_unavailable`. */
function missingText(missing: string): string {
  if (missing === 'ollama') return "Ollama can't be reached"
  if (missing === 'languagetool') return "LanguageTool can't be reached"
  return `Ollama has no ${missing}`
}

/** For the admin only: is the background work (the PC with the models, the worker) moving? */
export const SYSTEM = {
  heading: 'System status',
  seeStatus: 'See status',
  /** What is wrong, most urgent first. Empty: nothing to tell. */
  problems(s: SystemStatus | null | undefined): string[] {
    if (!s) return []
    const out: string[] = []
    if (s.compute?.missing.length) {
      const why = s.compute.missing.map(missingText).join('; ')
      const queue = s.waiting_for_pc
        ? ` ${jobs(s.waiting_for_pc)} wait for it, the oldest for ${waited(s.oldest_waiting_minutes ?? 0)}.`
        : ''
      out.push(`The computer with the models is off or not ready (${why}).${queue}`)
    }
    if (s.stuck)
      out.push(
        `A job has waited ${waited(s.oldest_waiting_minutes ?? 0)} although it could run: the worker may be down.`,
      )
    if (s.failed_last_day)
      out.push(`${jobs(s.failed_last_day)} failed in the last day. Cases shows what to retry.`)
    return out
  },
  /** The three lines of the status panel. */
  rows(s: SystemStatus): { label: string; ok: boolean; text: string }[] {
    const missing = s.compute?.missing ?? []
    return [
      {
        label: 'Computer with the models',
        ok: !missing.length,
        text: !s.compute
          ? 'Not checked here (REQUIRE_COMPUTE is off).'
          : missing.length
            ? missing.map(missingText).join('; ')
            : `Ready, checked ${s.compute.checked_seconds_ago} s ago.`,
      },
      {
        label: 'Worker',
        ok: !s.stuck,
        text: s.stuck ? 'Jobs that could run are not being taken.' : 'Taking jobs.',
      },
      {
        label: 'Queue',
        ok: !s.failed_last_day && !s.waiting_for_pc,
        text: [
          s.waiting
            ? `${jobs(s.waiting)} waiting, the oldest for ${waited(s.oldest_waiting_minutes ?? 0)}` +
              (s.waiting_for_pc ? ` (${s.waiting_for_pc} for the computer)` : '')
            : 'Nothing waiting',
          s.failed_last_day ? `${s.failed_last_day} failed in the last day` : '',
        ]
          .filter(Boolean)
          .join('; ')
          .concat('.'),
      },
    ]
  },
}

/**
 * The home page: what PsyKnowHow is, in the order a newcomer needs it. `about` is always
 * visible; `more` sits behind "Learn more". Written for a busy clinician: short sentences.
 */
export const HOME = {
  tagline: 'Expert interviews for clinical knowledge',
  about: {
    heading: 'What is PsyKnowHow?',
    text: {
      expert: [
        'PsyKnowHow is a written expert elicitation study. You assess short clinical vignettes (first-person texts such as forum posts, diary entries or emails) and record your clinical reasoning, at your own pace.',
        'The focus is on ADHD-related traits: which features of a narrative you weigh, how you separate them from differential explanations such as low mood, anxiety or poor sleep, and what further history you would need. Each point is anchored to the exact wording it rests on.',
        "You work in two places: My cases, where you assess the vignettes assigned to you, and Reviews, where you peer-review colleagues' assessments.",
      ],
      admin: [
        'PsyKnowHow is a written expert elicitation study. Clinicians assess short clinical vignettes, peers review the assessments, and you decide which answers enter the knowledge base an AI assistant can cite.',
      ],
    } as ByRole<readonly string[]>,
  },
  more: {
    sections: [
      {
        id: 'aim',
        heading: 'What the study aims for',
        text: [
          'Experienced clinicians rely on cues that guidelines rarely put into words: a turn of phrase, what a person leaves out, how an account is ordered. This tacit knowledge rarely surfaces in answer to a general question, but it does when a clinician reasons through a concrete case.',
          'The study records that reasoning in a form that can be checked and reused. Each statement is tied to the passage it rests on, says which way that passage points, and is peer-reviewed before use.',
          'Approved answers form a knowledge base for an AI assistant. When a clinician asks a question or brings a new patient text, the assistant retrieves the relevant expert readings and cites them as clinician opinion, alongside the research literature. It supports clinical judgement; it does not make diagnoses.',
        ],
      },
      {
        id: 'vignettes',
        heading: 'Clinical vignettes',
        text: [
          'A clinical vignette is a short written description of a person, built to resemble a real clinical encounter. Because every clinician reads the same text under the same conditions, their reasoning can be compared. Vignettes are an established method for studying clinical decision-making, used for example in the ICD-11 field studies on mental disorders.',
          'The vignettes here are first-person texts of 120 to 250 words. Some contain features suggestive of ADHD-related traits, some contain features better explained by something else, and some are controls. You are not told which is which.',
        ],
      },
      {
        id: 'answer',
        heading: 'What an answer contains',
        text: [
          'An answer is your assessment of one vignette, given as six questions. Each statement is linked to the quotes it rests on, and each quote is marked as pointing toward ADHD-related traits, away from them, of no bearing, or unclear.',
        ],
      },
      {
        id: 'flow',
        heading: 'How a case goes',
        text: [
          'Each case moves through four steps. You can leave and come back at any point before you submit.',
        ],
      },
      {
        id: 'review',
        heading: 'How review works',
        text: [
          'Colleagues approve or disapprove each answer and say why. Votes are advice: the study team makes the final decision. An answer can be sent back to its author for another round.',
        ],
      },
      {
        id: 'answers',
        heading: 'What happens to answers',
        text: [
          'After your check, peers review each answer and the study team decides. Approved answers are split into single statements, each kept word for word with its quotes and the vignette passage it refers to, and added to the knowledge base.',
        ],
      },
    ],
    /** The six questions, paraphrased from the API's wording (backend/app/vignettes/questions.py). */
    questions: [
      {
        term: 'Q1 Relevant features',
        text: 'The passages that matter for your reading, in either direction, and why.',
      },
      {
        term: 'Q2 Differential explanations',
        text: 'Which features could equally reflect something else, and what would distinguish them.',
      },
      {
        term: 'Q3 Missing information',
        text: 'What you would need before treating these features as meaningful.',
      },
      {
        term: 'Q4 Hypothesis revision',
        text: 'How your working hypothesis changes given one added detail.',
      },
      {
        term: 'Q5 Common misreadings',
        text: 'What a less experienced clinician would likely over- or under-interpret.',
      },
      {
        term: 'Q6 Overall rating',
        text: 'How strongly the text shows ADHD-related traits, 1 to 5, or insufficient information.',
      },
    ],
    referencesHeading: 'Further reading',
    references: [
      {
        cite: "Evans, S. C., et al. (2015). Vignette methodologies for studying clinicians' decision-making: Validity, utility, and application in ICD-11 field studies. International Journal of Clinical and Health Psychology, 15(2), 160–170.",
        url: 'https://doi.org/10.1016/j.ijchp.2014.12.001',
      },
      {
        cite: 'Hoffman, R. R., Shadbolt, N. R., Burton, A. M., & Klein, G. (1995). Eliciting knowledge from experts: A methodological analysis. Organizational Behavior and Human Decision Processes, 62(2), 129–158.',
        url: 'https://doi.org/10.1006/obhd.1995.1039',
      },
    ],
    instructions: 'Read the full instructions',
  },
  learnMore: 'Learn more',
  privacy: {
    heading: 'Your data and the GDPR',
    points: [
      'Other experts see your answers under a pseudonym, never your name or email.',
      'Your answers are proofread on our own servers, not by an outside AI provider.',
      'You can see, correct or delete your data, and stop taking part at any time.',
    ],
    link: 'Read the full privacy notice',
  },
  sectionsHeading: 'Your sections',
  cards: {
    cases: {
      title: { expert: 'My cases', admin: 'Assignments' },
      text: {
        expert:
          'Short texts written like a clinical vignette: a forum post, a journal entry or an email. Quote the words that matter and say what they suggest to you.',
        admin: 'Cases given to experts, and where each one stands.',
      },
      action: { expert: 'Open My cases', admin: 'Open Assignments' },
    },
    reviews: {
      title: { expert: 'Reviews', admin: 'Reviews' },
      text: {
        expert:
          "Read colleagues' answers, approve or disapprove each one and say why. Your vote is advice; the study team decides.",
        admin: 'Follow the discussions and decide which answers enter the knowledge base.',
      },
      action: { expert: 'Open Reviews', admin: 'Open Reviews' },
    },
  },
} as const

/** The reminder under the heading of My cases (Assignments, for the study team). */
export const CASES_INTRO = {
  expert: {
    lead: 'Each case is a short text, like a clinical vignette. Read it, quote the words your reading rests on, and explain why they matter.',
    more: {
      statusHeading: 'What the status means',
      statuses: [
        { term: 'Not started', text: "You haven't opened the case yet." },
        { term: 'In progress', text: 'You have started. Your work is saved as you go.' },
        {
          term: 'Proofreading…',
          text: 'We are correcting spelling and grammar. This takes a minute or two.',
        },
        {
          term: 'Ready to check',
          text: 'Read the edited text, change what you want, and send it for review.',
        },
        { term: 'In review', text: 'Colleagues are reading it. Nothing more for you to do.' },
      ],
    },
  },
  admin: {
    lead: 'Give cases to experts and follow each one through answering, proofreading and review.',
  },
} as const

/** The reminder under the heading of Reviews. */
export const REVIEWS_INTRO = {
  expert: {
    lead: "Colleagues' answered cases, for you to read and advise on. Approve or disapprove each answer or say why in a comment.",
    more: [
      {
        term: 'Open and Closed',
        text: 'Open reviews are still taking votes. Closed ones have been decided by the study team.',
      },
      {
        term: 'Your three lists',
        text: "Waiting for your vote: answers you haven't judged yet. You've voted: reviews where every answer has your vote. Your submissions: your own answers, which you can read and comment on but not vote on.",
      },
      {
        term: 'Votes are advice',
        text: 'The study team makes the final decision. You can change a vote until the review closes.',
      },
      {
        term: 'What follows',
        text: 'An answer can be sent back to its author for another round. Approved answers go into the knowledge base.',
      },
    ],
  },
  admin: {
    lead: 'Follow the discussions, then decide: approve, reject or send back to the author.',
  },
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

/** Which thing a 404 was about. The server names it in `details.resource`. */
function notFoundMessage(resource: unknown): string {
  switch (resource) {
    case undefined:
    case 'Assignment':
    case 'Submission':
    case 'Findings':
    case 'Proofread':
      return "We can't find this case in your list. It may have been reassigned."
    case 'Vignette':
    case 'Vignette version':
      return 'This case text no longer exists. Please reload the page.'
    case 'User':
    case 'Person':
      return "This account can't be found. Please reload the page."
    case 'Review':
    case 'Review round':
    case 'Answer':
      return "This review can't be found. It may have been closed. Please reload the page."
    default:
      return `${String(resource)} can't be found.`
  }
}

/**
 * What went wrong, in words the reader can act on. Our own wording for the codes we know. For a
 * code we have no wording for, an expert gets the calm fallback, because the server's messages
 * use the old terms. The admin knows those terms, so `describeAdminError` shows the server's
 * message there instead. Unexpected failures (`internal_error`, `http_error`) never show it.
 */
export function describeError(error: unknown, { serverWording = false } = {}): string {
  if (!(error instanceof ApiError)) return SAFE_FALLBACK
  switch (error.code) {
    case 'not_editable':
      return error.details?.state === 'cancelled'
        ? "The study team has cancelled this case, so changes can't be saved."
        : 'This case can no longer be changed.'
    case 'submission_incomplete':
      return "Something's still missing. Please look through your answers and try again."
    case 'empty_answer': {
      const questions = questionNumbers(error.details?.question_ids ?? error.details?.answers)
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
      return 'The answers changed while you were reading. We have loaded the new ones, so please look again.'
    case 'comment_required':
      return 'Please say what should change.'
    case 'decisions_incomplete':
      return 'Please decide every answer once.'
    case 'proofread_conflict':
    case 'findings_conflict':
      return 'This was changed in another tab or device. Please reload to see the latest.'
    case 'links_missing':
      return 'Some sentences are not linked to a quote yet. They are marked “Choose quotes”.'
    case 'no_target':
      return 'A sentence has to be about something: keep at least one quote, or the whole case.'
    case 'unknown_target':
    case 'question_not_answered':
      return `This doesn't match your answers. Please reload the page. If it continues, contact ${STUDY_TEAM}.`
    case 'email_taken':
      return 'Someone already has an account with this email.'
    case 'cannot_deactivate_self':
      return "You can't deactivate your own account."
    case 'not_found':
      return notFoundMessage(error.details?.resource)
    case 'validation_error':
      return error.message
    case 'already_assigned':
      return 'This expert already has this case.'
    case 'illegal_transition': {
      const state = error.details?.state as AssignmentSummary['state'] | undefined
      const label = state ? ASSIGNMENT_STATE_LABELS[state] : undefined
      return label
        ? `This can't be done while the assignment is "${label}". The list shows its current state.`
        : "This can't be done in the assignment's current state. Please reload the page."
    }
    case 'draft_conflict':
      return 'This was changed in another tab or device. Please reload to see the latest.'
    case 'invalid_invite':
      return 'This invite link is not valid or was already used. Ask the study team for a new one.'
    case 'not_authenticated':
      return 'Please sign in again.'
    case 'unavailable':
      return "We can't reach the server right now. Please try again in a moment."
    case 'compute_unavailable':
      return 'The computer that checks answers is not ready right now. Your text is safe. Please try again later.'
    case 'embedding_unavailable':
      return "The embedding model can't be reached, so search is off right now. The list of units still works."
    case 'internal_error':
    case 'http_error':
      return SAFE_FALLBACK
    default:
      return serverWording && error.message ? error.message : SAFE_FALLBACK
  }
}

/** For the admin's screens: our wording where we have it, otherwise what the server said. */
export function describeAdminError(error: unknown): string {
  return describeError(error, { serverWording: true })
}

/** Why a save was refused. The same words as any other error. */
export function saveRefusal(error: ApiError): string {
  return describeError(error)
}

/** The tally is advice for the study team, never a verdict. */
export function tallyLabel(approvals: number, disapprovals: number): string {
  return `${approvals} approve, ${disapprovals} disapprove`
}

/** A tag on a line of an answer: one of the expert's quotes, quoted words, or the whole case. */
export function quoteTagLabel(target: string, highlight: LinkedHighlight | null): string {
  if (target === 'case') return 'Whole case'
  if (highlight?.chip) return `Quote ${highlight.chip}`
  const words = (highlight?.text ?? '').split(/\s+/)
  return `“${words.slice(0, 4).join(' ')}${words.length > 4 ? '…' : ''}”`
}

/** What the proofreading could not do, for the note above the edited answers. */
export function proofreadPassNote(passes: Record<string, unknown>): string | null {
  const answers = Object.entries(passes).filter(([key]) => /^Q\d$/.test(key))
  const missed = (pass: string) =>
    answers.some(([, value]) => (value as Record<string, unknown>)[pass] === 'unavailable')
  const grammar = missed('grammar')
  const enhanced = missed('enhanced')
  if (grammar && enhanced)
    return "The proofreading couldn't run this time, so your answers are as you wrote them, one sentence per line."
  if (grammar)
    return "The grammar check couldn't run this time. Please check the spelling yourself."
  if (enhanced) return "Short notes couldn't be written out this time. The grammar was checked."
  return null
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
  if (state === 'proofread_check')
    return `Sent back to the author for changes. A new round (${round}) follows.`
  if (state === 'rejected') return 'Closed: the study team rejected these answers.'
  return 'Closed: the study team decided. Approved answers go into the knowledge base.'
}

/** One sentence per kind of change in the home feed. */
export function activityText(a: ActivityItem): string {
  const who = speakerLabel(a.speaker)
  const where = a.question_id
    ? `the answer to ${questionLabel(a.question_id).toLowerCase()} of case ${a.vignette_code}`
    : `case ${a.vignette_code}`
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

export const FRAMING_LABELS: Record<string, string> = {
  forum_post: 'Forum post',
  personal_journal: 'Journal entry',
  email: 'Email',
}

/** How a sentence of an answer came to be in a knowledge unit, as the study team reads it. */
export const FILED_BY_LABELS: Record<string, string> = {
  chip: 'cited by the expert',
  quote: 'quotes the patient',
  llm: 'filed by the model',
  expert: 'moved by the expert',
}

/** What the study team reads in an assignment's status. */
export const ASSIGNMENT_STATE_LABELS: Record<AssignmentSummary['state'], string> = {
  assigned: 'Not started',
  in_progress: 'In progress',
  proofreading: 'Submitted, being proofread',
  proofread_check: 'Proofread, the expert is checking it',
  peer_review: 'In review, waiting for your decision',
  processing: 'Approved, being cut into units',
  processing_failed: 'Processing failed',
  ingesting: 'Entering the knowledge base',
  ingestion_failed: 'Entering the knowledge base failed',
  ingested: 'In the knowledge base',
  rejected: 'Rejected',
  cancelled: 'Cancelled',
}

/** When a comment was posted, short: "12 Nov, 14:05". */
export function postedAt(iso: string): string {
  return new Date(iso).toLocaleString('en-GB', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** A comment's opening words in the feed: a quote reads "[Quote 2]", not its stored token. */
export function commentExcerpt(text: string): string {
  return text.replace(/⟦h(\d+)⟧/g, '[Quote $1]').replace(/⟦h?\d*…$/, '…')
}

/**
 * The privacy notice (GDPR Art. 13), shown once before the first case and from the home page.
 * Values in [square brackets] are for the study team to fill in: the controller, contacts, legal
 * basis and how long data is kept are decisions, not facts the code can know. Raise `version`
 * whenever the substance changes: every expert is then asked to read it again.
 */
export const PRIVACY = {
  version: '2026-11-23',
  title: 'Your data and the GDPR',
  lead: 'Before your first case, please read how we use your personal data. It takes about three minutes. You can open this notice again at any time from the home page.',
  sections: [
    {
      id: 'who',
      heading: 'Who is responsible',
      items: [
        {
          term: 'Data controller',
          text: '[Name and address of the institution running the study].',
        },
        {
          term: 'Contact for this study',
          text: '[Name and email of the principal investigator].',
        },
        {
          term: 'Data protection officer',
          text: '[Name and email of the institution’s data protection officer].',
        },
      ],
    },
    {
      id: 'what',
      heading: 'What we collect',
      items: [
        {
          term: 'Your account',
          text: 'Your email address and name, the pseudonym we give you, and your password, which we keep only in scrambled (hashed) form that cannot be read back.',
        },
        {
          term: 'Your work',
          text: 'The quotes you mark, their directions, your answers and ratings, the proofread versions of your answers, and your comments and votes in reviews.',
        },
        {
          term: 'Security records',
          text: 'A record of what was done to each case and when (for example, submitted or sent back), and failed sign-in attempts, so that we can lock an account under attack.',
        },
        {
          term: 'In your browser',
          text: 'One cookie that keeps you signed in, and a note of whether you have read the instructions and this notice. No advertising or tracking cookies.',
        },
      ],
    },
    {
      id: 'why',
      heading: 'Why, and on what legal basis',
      paragraphs: [
        'We collect your clinical reading of short case texts to build a knowledge base of clinician opinion. After review, an AI assistant can find your answers and cite them, word for word, under your pseudonym, as one clinician’s view.',
        'Legal basis: [for example, a task in the public interest (GDPR Art. 6(1)(e)) for research at a public university, or your consent (Art. 6(1)(a)). To be confirmed by the data protection officer]. Research use is subject to the safeguards of GDPR Art. 89, above all pseudonymisation and collecting no more than the study needs.',
        'We do not ask for any health data about you. Please do not write anything in your answers that identifies you, a patient or anyone else.',
      ],
    },
    {
      id: 'who-sees',
      heading: 'Who sees your data',
      items: [
        {
          term: 'Other experts',
          text: 'See your answers in reviews under your pseudonym only, never your name or email.',
        },
        {
          term: 'The study team',
          text: 'Can link your pseudonym to your account, to manage invitations, assignments and reviews.',
        },
        {
          term: 'Automatic proofreading',
          text: 'Your answers are checked for spelling and grammar by a language model and a spell-checker that the study team runs itself. Your text is not sent to an outside AI provider.',
        },
        {
          term: 'Hosting',
          text: '[Name of the hosting provider and where the servers are, e.g. within the EU/EEA]. We do not transfer your data outside the EEA [unless stated here, with the safeguard used].',
        },
      ],
    },
    {
      id: 'how-long',
      heading: 'How long we keep it',
      paragraphs: [
        'Your account data is kept until the end of the study [date or period], then deleted. Answers accepted into the knowledge base are kept, under your pseudonym, for [period] after the study ends, so that the results can be checked and reused for research.',
      ],
    },
    {
      id: 'rights',
      heading: 'Your rights',
      paragraphs: [
        'You can ask to see the data we hold about you, have it corrected or deleted, restrict or object to its use, and receive a copy of it. Taking part is voluntary: you can stop at any time without giving a reason, and ask for your answers to be withdrawn. Answers already used in published results may not be removable once anonymised.',
        'Write to [the study contact] to use any of these rights. If you think we have mishandled your data, you can complain to the data protection authority: [for example, in Poland, the President of the Personal Data Protection Office (UODO), uodo.gov.pl].',
      ],
    },
  ],
  confirm:
    'By pressing “I understand”, you confirm that you have read how your personal data is used in this study.',
  understand: 'I understand',
  confirmed: 'You have confirmed this notice.',
  updated: 'Last updated',
} as const
