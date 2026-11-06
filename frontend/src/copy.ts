/**
 * Wording the expert reads, in one place. Clinical words, not engineering ones: "marked passage",
 * not "highlight"; "reference", not "chip". The API's own messages use the old terms, so what an
 * expert sees for an error comes from here, by its stable `code`.
 */
import type { ApiError } from '@/api/client'

/** Why the server refused to save the draft, in words the expert can act on. */
export function saveRefusal(error: ApiError): string {
  switch (error.code) {
    case 'not_editable':
      return error.details?.state === 'cancelled'
        ? "The study team has cancelled this case, so changes can't be saved."
        : 'This case can no longer be changed.'
    case 'gate_locked':
      return "Part 1 is already locked, so this can't change."
    case 'unknown_chip':
    case 'chip_numbers':
    case 'highlight_not_in_vignette':
      return (
        "A reference in your answer doesn't match a marked passage. Please check your answers. " +
        'If it continues, contact the study team.'
      )
    case 'not_found':
      return "We can't find this case in your list. It may have been reassigned."
    default:
      return (
        "Something didn't save correctly. Your text is safe. " +
        'Please try again, or contact the study team.'
      )
  }
}
