/**
 * Lists in an answer are only a way of showing it: the stored text stays exactly what was typed. A
 * line is a list item when it starts with a number or a dash followed by a space, so "1.5 hours" and
 * "-5" are ordinary text.
 */
const MARKER = /^\s*(?:\d+[.)]|[-–•*])\s/

/** The marker with its surrounding spaces, or null if the line is not a list item. */
export function listMarker(line: string): string | null {
  return MARKER.exec(line)?.[0] ?? null
}

/** The marker for the line after this one. */
export function nextMarker(marker: string): string {
  return marker.replace(/\d+/, (n) => String(Number(n) + 1))
}
