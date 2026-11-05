/** The parts of the vignette form that are plain logic. */
import { ApiError, type VignetteDesign } from '@/api/client'

export type FormField = 'code' | 'text' | 'q4_whatif' | 'knowledge_target' | 'quotes'

export const MIN_WORDS = 120
export const MAX_WORDS = 250

const FIELD_OF_CODE: Record<string, FormField> = {
  vignette_code_taken: 'code',
  word_count_out_of_range: 'text',
  q4_without_whatif: 'q4_whatif',
  track_without_target: 'knowledge_target',
  span_not_in_text: 'quotes',
  control_with_cues: 'quotes',
}
const FIELDS: readonly string[] = ['code', 'text', 'q4_whatif', 'knowledge_target']

/** Where on the form a refusal from the server belongs. Null: at the top of the form. */
export function fieldForError(error: ApiError): FormField | null {
  if (error.code === 'construct_word_in_text') {
    const field = error.details?.field
    return field === 'text' || field === 'q4_whatif' ? field : null
  }
  if (error.code === 'validation_error') {
    const errors = (error.details?.errors ?? []) as { loc?: unknown[] }[]
    const field = errors[0]?.loc?.[1]
    return typeof field === 'string' && FIELDS.includes(field) ? (field as FormField) : null
  }
  return FIELD_OF_CODE[error.code] ?? null
}

export function nextCode(codes: string[]): string {
  const numbers = codes.map((code) => Number(code.replace(/^V/, ''))).filter(Number.isFinite)
  const next = Math.max(0, ...numbers) + 1
  return `V${String(next).padStart(3, '0')}`
}

export function emptyDesign(): VignetteDesign {
  return {
    purpose: '',
    planted_cues: [],
    confounders: [],
    is_control: false,
    track: 'general',
    knowledge_target: null,
    origin: 'hand_written',
    population: 'adult',
    source_ref: null,
  }
}

/** Fields that only apply in some cases go out empty when they don't apply. */
export function designForSaving(design: VignetteDesign): VignetteDesign {
  return {
    ...design,
    planted_cues: design.is_control ? [] : design.planted_cues,
    knowledge_target: design.track === 'text_analysis' ? design.knowledge_target : null,
    source_ref: design.origin === 'real_text' ? design.source_ref : null,
  }
}

export function countTextWords(text: string): number {
  return text.split(/\s+/).filter(Boolean).length
}
