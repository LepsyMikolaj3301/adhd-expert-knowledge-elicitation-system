/**
 * What changed between two versions of an answer, word by word. A chip (`⟦h1⟧`) is one word, and
 * so is a line break, so that "one sentence per line" shows as moved breaks, not rewritten text.
 */

export type DiffKind = 'same' | 'added' | 'removed'
export interface DiffPart {
  kind: DiffKind
  text: string
}

/** Words with the spaces after them, line breaks on their own. */
export function tokens(text: string): string[] {
  return text.match(/\n|[^\s]+[^\S\n]*|[^\S\n]+/g) ?? []
}

/** Compared without trailing spaces: "word" and "word " are the same word. */
const bare = (token: string) => (token === '\n' ? token : token.trimEnd())

/**
 * The longest common subsequence of words, as runs of same, removed and added text. Quadratic,
 * which is fine for answers of a few hundred words.
 */
export function wordDiff(before: string, after: string): DiffPart[] {
  const a = tokens(before)
  const b = tokens(after)
  const rows = a.length + 1
  const cols = b.length + 1
  const lcs = new Uint32Array(rows * cols)
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i * cols + j] =
        bare(a[i] as string) === bare(b[j] as string)
          ? (lcs[(i + 1) * cols + j + 1] as number) + 1
          : Math.max(lcs[(i + 1) * cols + j] as number, lcs[i * cols + j + 1] as number)
    }
  }
  const parts: DiffPart[] = []
  const push = (kind: DiffKind, text: string) => {
    const last = parts[parts.length - 1]
    if (last?.kind === kind) last.text += text
    else parts.push({ kind, text })
  }
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (bare(a[i] as string) === bare(b[j] as string)) {
      push('same', b[j] as string)
      i++
      j++
    } else if ((lcs[(i + 1) * cols + j] as number) >= (lcs[i * cols + j + 1] as number)) {
      push('removed', a[i++] as string)
    } else {
      push('added', b[j++] as string)
    }
  }
  while (i < a.length) push('removed', a[i++] as string)
  while (j < b.length) push('added', b[j++] as string)
  return parts
}

/** Whether anything but spacing and line breaks changed. */
export function changed(before: string, after: string): boolean {
  const words = (text: string) => text.split(/\s+/).filter(Boolean).join(' ')
  return words(before) !== words(after)
}
