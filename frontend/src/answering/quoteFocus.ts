/**
 * The quote being pointed at on a screen. A chip in an answer, a quote tag on a line or a row of
 * the quote table sets it; the case text lights the passage up. One page provides it, and every
 * component under it that shows quotes takes part without passing events up by hand.
 */
import { computed, inject, provide, ref, type InjectionKey, type Ref } from 'vue'

import type { LinkedHighlight } from '@/api/client'

import { inkFor } from './highlights'

/** A highlight id: `h3` (the expert's quote 3) or `i1` (words quoted without being marked). */
export type QuoteId = string

const KEY: InjectionKey<Ref<QuoteId | null>> = Symbol('quote-focus')

export function provideQuoteFocus(): Ref<QuoteId | null> {
  const focus = ref<QuoteId | null>(null)
  provide(KEY, focus)
  return focus
}

/** The page's focus, or a private one when nothing provides it (a component on its own). */
export function useQuoteFocus(): Ref<QuoteId | null> {
  return inject(KEY, null) ?? ref(null)
}

const PIN: InjectionKey<Ref<QuoteId | null>> = Symbol('quote-pin')

/**
 * The quote clicked on, which stays lit after the pointer leaves. Pointing at another one shows
 * that one for as long as it is pointed at. Clicking the pinned one again lets it go.
 */
export function provideQuotePin(): Ref<QuoteId | null> {
  const pin = ref<QuoteId | null>(null)
  provide(PIN, pin)
  return pin
}

/** The page's pin, or null where nothing provides one: clicking then does nothing. */
export function useQuotePin(): Ref<QuoteId | null> | null {
  return inject(PIN, null)
}

export function togglePin(pin: Ref<QuoteId | null> | null, id: QuoteId) {
  if (pin) pin.value = pin.value === id ? null : id
}

/** The focus as a chip number, for screens that only know the expert's own quotes. */
export function chipFocus(focus: Ref<QuoteId | null>) {
  return computed<number | null>({
    get: () => {
      const match = /^h(\d+)$/.exec(focus.value ?? '')
      return match ? Number(match[1]) : null
    },
    set: (chip) => (focus.value = chip === null ? null : `h${chip}`),
  })
}

/** What the case text marks: a passage and its colour. Implicit quotes have no number or colour. */
export interface Mark {
  span: [number, number]
  chip: number | null
}

export function markFor(id: QuoteId | null, highlights: LinkedHighlight[]): Mark | null {
  const found = highlights.find((h) => h.id === id)
  return found ? { span: found.span as [number, number], chip: found.chip } : null
}

export function inkOf(chip: number | null): string {
  return chip ? inkFor(chip) : 'var(--ink-0)'
}
