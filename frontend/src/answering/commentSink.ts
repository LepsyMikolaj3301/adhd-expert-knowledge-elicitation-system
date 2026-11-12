/**
 * The comment box that quotes go into on the review page. A discussion claims it when its box is
 * opened or clicked into; the quote table and the case text then add quotes to it.
 */
import { inject, provide, shallowRef, type InjectionKey, type ShallowRef } from 'vue'

export interface CommentSink {
  questionId: string
  insertChip: (chip: number) => void
  insertText: (text: string) => void
}

const KEY: InjectionKey<ShallowRef<CommentSink | null>> = Symbol('comment-sink')

export function provideCommentSink(): ShallowRef<CommentSink | null> {
  const sink = shallowRef<CommentSink | null>(null)
  provide(KEY, sink)
  return sink
}

/** The page's sink, or a private one when nothing provides it (a component on its own). */
export function useCommentSink(): ShallowRef<CommentSink | null> {
  return inject(KEY, null) ?? shallowRef(null)
}

/** A passage of the case as it goes into a comment. */
export function quoted(words: string): string {
  return `“${words.trim().replace(/\s+/g, ' ')}” `
}
