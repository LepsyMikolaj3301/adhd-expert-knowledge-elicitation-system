/**
 * What a citation is and how it changes. No Vue and no DOM here, so all of it is easy to test.
 *
 * Offsets: the API's `span` counts characters the way Python does (code points), while the browser
 * counts UTF-16 units, in which an emoji takes two. Everything that touches the DOM uses UTF-16, and
 * converts when it reads or writes a span.
 */
import type { Citation } from '@/api/client'

export const CHIP_RE = /⟦h(\d+)⟧/g
export const INK_COUNT = 8
/** The API's limit on the length of a citation. */
const MAX_CITATION_LENGTH = 2000

const WORD_CHARACTER = /[\p{L}\p{N}\p{M}_'’-]/u
const WORD = /[\p{L}\p{N}_]+/gu
const SPACE = /\s/

export type Answers = Record<string, string | undefined>

export function utf16ToCodePoint(text: string, index: number): number {
  return Array.from(text.slice(0, index)).length
}

export function codePointToUtf16(text: string, index: number): number {
  return Array.from(text).slice(0, index).join('').length
}

/** Drops spaces at the edges and completes words cut in half. Null if nothing is left. */
export function snapToWords(text: string, start: number, end: number): [number, number] | null {
  let from = start
  let to = end
  while (from < to && SPACE.test(text.charAt(from))) from++
  while (to > from && SPACE.test(text.charAt(to - 1))) to--
  if (from >= to) return null
  while (
    from > 0 &&
    WORD_CHARACTER.test(text.charAt(from)) &&
    WORD_CHARACTER.test(text.charAt(from - 1))
  ) {
    from--
  }
  while (
    to < text.length &&
    WORD_CHARACTER.test(text.charAt(to - 1)) &&
    WORD_CHARACTER.test(text.charAt(to))
  ) {
    to++
  }
  return [from, to]
}

export type AddResult =
  | { kind: 'added'; citations: Citation[] }
  | { kind: 'duplicate'; chip: number }
  | { kind: 'too_long' }
  | { kind: 'empty' }

/** `start` and `end` are browser offsets into `text`, as a selection gives them. */
export function addCitation(
  citations: Citation[],
  text: string,
  start: number,
  end: number,
): AddResult {
  const snapped = snapToWords(text, start, end)
  if (!snapped) return { kind: 'empty' }
  const [from, to] = snapped
  const span: [number, number] = [utf16ToCodePoint(text, from), utf16ToCodePoint(text, to)]
  const existing = citations.find((c) => c.span[0] === span[0] && c.span[1] === span[1])
  if (existing) return { kind: 'duplicate', chip: existing.chip }
  if (span[1] - span[0] > MAX_CITATION_LENGTH) return { kind: 'too_long' }
  const citation: Citation = {
    chip: citations.length + 1,
    text: text.slice(from, to),
    span,
    direction: null,
  }
  return { kind: 'added', citations: [...citations, citation] }
}

function withoutChip(answer: string, chip: number): string {
  const token = new RegExp(`( ?)⟦h${chip}⟧( ?)`, 'g')
  return answer.replace(token, (_match, before: string, after: string, at: number) => {
    const next = answer.charAt(at + _match.length)
    const startsLine = at === 0 || answer.charAt(at - 1) === '\n'
    if (startsLine || /[.,;:!?)]/.test(next)) return ''
    return before && after ? ' ' : before + after
  })
}

/**
 * Takes a citation out, moves the later ones up, and updates the chips in the answers, so that the
 * numbers stay 1..n. Locked answers never change: they can only cite locked citations, which are
 * never removed and come before any that can be.
 */
export function removeCitation(
  citations: Citation[],
  answers: Answers,
  chip: number,
): { citations: Citation[]; answers: Record<string, string> } {
  const updated: Record<string, string> = {}
  for (const [question, answer] of Object.entries(answers)) {
    if (answer === undefined) continue
    updated[question] = withoutChip(answer, chip).replace(CHIP_RE, (match, n: string) =>
      Number(n) > chip ? `⟦h${Number(n) - 1}⟧` : match,
    )
  }
  return {
    citations: citations
      .filter((c) => c.chip !== chip)
      .map((c) => (c.chip > chip ? { ...c, chip: c.chip - 1 } : c)),
    answers: updated,
  }
}

/** Different words, like the server's count: chips are not words. */
export function countWords(text: string): number {
  const words = text.replace(CHIP_RE, ' ').toLowerCase().match(WORD) ?? []
  return new Set(words).size
}

export function citedChips(answers: Answers): Set<number> {
  const cited = new Set<number>()
  for (const answer of Object.values(answers)) {
    for (const match of (answer ?? '').matchAll(CHIP_RE)) cited.add(Number(match[1]))
  }
  return cited
}

export function uncitedChips(citations: Citation[], answers: Answers): number[] {
  const cited = citedChips(answers)
  return citations.map((c) => c.chip).filter((chip) => !cited.has(chip))
}

/** The colour follows the number. The number is always shown too, so colour is never the only cue. */
export function inkFor(chip: number): string {
  return `var(--ink-${((chip - 1) % INK_COUNT) + 1})`
}

export function segmentsFor(
  text: string,
  active: Citation | null,
): { before: string; marked: string; after: string } {
  if (!active) return { before: text, marked: '', after: '' }
  const start = codePointToUtf16(text, active.span[0])
  const end = codePointToUtf16(text, active.span[1])
  return { before: text.slice(0, start), marked: text.slice(start, end), after: text.slice(end) }
}
