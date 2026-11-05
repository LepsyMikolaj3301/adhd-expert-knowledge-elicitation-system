/**
 * The stored answer is plain text with `⟦hN⟧` tokens; the editor works on a document with chip
 * nodes. These two functions convert exactly, so that opening an answer never changes it.
 */
import type { JSONContent } from '@tiptap/core'

const TOKEN = /⟦h(\d+)⟧/g

function lineToContent(line: string): JSONContent[] {
  const content: JSONContent[] = []
  let at = 0
  for (const match of line.matchAll(TOKEN)) {
    if (match.index > at) content.push({ type: 'text', text: line.slice(at, match.index) })
    content.push({ type: 'chip', attrs: { n: Number(match[1]) } })
    at = match.index + match[0].length
  }
  if (at < line.length) content.push({ type: 'text', text: line.slice(at) })
  return content
}

export function textToDoc(text: string): JSONContent {
  return {
    type: 'doc',
    content: text.split('\n').map((line) => {
      const content = lineToContent(line)
      return content.length ? { type: 'paragraph', content } : { type: 'paragraph' }
    }),
  }
}

export function docToText(doc: JSONContent): string {
  return (doc.content ?? [])
    .map((paragraph) =>
      (paragraph.content ?? [])
        .map((node) => (node.type === 'chip' ? `⟦h${node.attrs?.n}⟧` : (node.text ?? '')))
        .join(''),
    )
    .join('\n')
}
