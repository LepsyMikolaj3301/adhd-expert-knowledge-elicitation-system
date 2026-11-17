import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import type { User } from '@/api/client'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'
import ReviewView from '@/views/ReviewView.vue'

import { admin, expert, jsonResponse, serve, writes, type Route } from './helpers'

let wrapper: VueWrapper | undefined
const A = '/api/v1/assignments/a1'

beforeAll(() => {
  const noRects = () => [] as unknown as DOMRectList
  Range.prototype.getClientRects = noRects
  Element.prototype.getClientRects = noRects
  Range.prototype.getBoundingClientRect = () => new DOMRect()
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '')
  }
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open')
  }
})
beforeEach(() => setActivePinia(createPinia()))
afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function logIn(user: User) {
  const auth = useAuthStore()
  auth.user = user
  auth.loaded = true
}

const answer = (id: string, text = 'She slept badly.') => ({
  question_id: id,
  question: `Question ${id}?`,
  text,
  lines: [{ text, targets: ['case'], assigned_by: 'llm' }],
  comments: [],
  approvals: 0,
  disapprovals: 0,
  my_vote: null,
  votes: [],
  decision: null,
})

const answers = (ids = ['Q1'], rounds = [1], round = 1) => ({
  review_round: round,
  rounds,
  state: 'peer_review',
  highlights: [],
  answers: ids.map((id) => answer(id)),
})

const assignment = (audience: string, allowed_actions: string[]) => ({
  audience,
  id: 'a1',
  state: 'peer_review',
  review_round: 1,
  vignette: {
    code: 'V001',
    version: 1,
    text: 'The patient text.',
    framing: 'personal_journal',
    patient_summary: 'A student.',
    word_count: 3,
  },
  expert_id: 'e1',
  expert_pseudonym: 'E01',
  vignette_version: 1,
  vignette_version_id: 'v1',
  allowed_actions,
})

async function open(routes: Record<string, Route>, props = { id: 'a1' }) {
  const mock = serve(routes)
  wrapper = mount(ReviewView, { props, global: { plugins: [router] } })
  await flushPromises()
  return mock
}

const read = (mock: ReturnType<typeof serve>, path: string) =>
  mock.mock.calls.filter(
    ([i]) => (i as Request).method === 'GET' && (i as Request).url.includes(path),
  )
const bodyOf = async (mock: ReturnType<typeof serve>, method: string) =>
  (mock.mock.calls.find(([i]) => (i as Request).method === method)![0] as Request).clone().json()
const button = (name: string, within = wrapper!) => {
  const found = within.findAll('button').find((b) => b.text() === name)
  if (!found) throw new Error(`no button "${name}"`)
  return found
}
const decide = (n: number, decision: string) =>
  wrapper!.findAll(`[data-decision="${decision}"]`)[n]!.trigger('click')

describe('the admin submitting decisions', () => {
  const routes = (post: Route): Record<string, Route> => ({
    [`GET ${A}`]: () => jsonResponse(200, assignment('admin', ['comment', 'decide_answers'])),
    [`GET ${A}/answers`]: () => jsonResponse(200, answers(['Q1', 'Q2'])),
    [`POST ${A}/answer-decisions`]: post,
  })

  async function decideBoth() {
    await decide(0, 'approve')
    await decide(1, 'request_changes')
    await wrapper!
      .get('textarea[aria-label="What should change"]')
      .setValue('  Say more about sleep  ')
  }

  it('sends one decision per answer, the comment trimmed or null, then starts afresh', async () => {
    const mock = await open(routes(new Response(null, { status: 204 })))
    await decideBoth()
    await button('Submit decisions').trigger('click')
    expect(writes(mock)).toEqual([]) // asked first
    await button('Submit decisions', wrapper!.get('dialog') as unknown as VueWrapper).trigger(
      'click',
    )
    await flushPromises()

    expect(await bodyOf(mock, 'POST')).toEqual({
      decisions: [
        { question_id: 'Q1', decision: 'approve', comment: null },
        { question_id: 'Q2', decision: 'request_changes', comment: 'Say more about sleep' },
      ],
    })
    expect(read(mock, '/answers')).toHaveLength(2) // reloaded
    expect(wrapper!.find('dialog').exists()).toBe(false)
    // nothing is chosen any more
    expect(
      wrapper!
        .findAll('[data-decision][aria-pressed="true"]')
        .map((b) => b.attributes('data-decision')),
    ).toEqual([])
  })

  it('does nothing when the admin keeps deciding', async () => {
    const mock = await open(routes(new Response(null, { status: 204 })))
    await decideBoth()
    await button('Submit decisions').trigger('click')
    await button('Keep deciding').trigger('click')
    expect(writes(mock)).toEqual([])
    expect(wrapper!.find('dialog').exists()).toBe(false)
    expect(wrapper!.get('[data-decision="approve"]').attributes('aria-pressed')).toBe('true')
  })

  it('keeps every choice and says so when the decisions are refused', async () => {
    const mock = await open(
      routes(jsonResponse(409, { code: 'stale_round', message: 'The round moved on.' })),
    )
    await decideBoth()
    await button('Submit decisions').trigger('click')
    await button('Submit decisions', wrapper!.get('dialog') as unknown as VueWrapper).trigger(
      'click',
    )
    await flushPromises()

    expect(wrapper!.get('[role="alert"]').text()).not.toBe('')
    expect(read(mock, '/answers')).toHaveLength(1) // no reload: nothing changed
    expect(wrapper!.get('[data-decision="approve"]').attributes('aria-pressed')).toBe('true')
    expect(
      (wrapper!.get('textarea[aria-label="What should change"]').element as HTMLTextAreaElement)
        .value,
    ).toBe('  Say more about sleep  ')
  })
})

describe('a reviewer who votes, and rounds', () => {
  const reviewer = (extra: Record<string, Route> = {}): Record<string, Route> => ({
    [`GET ${A}`]: () => jsonResponse(200, assignment('peer', ['comment', 'vote'])),
    [`GET ${A}/answers`]: () => jsonResponse(200, answers()),
    ...extra,
  })

  it('reloads the page and says so when the round has moved on under a vote', async () => {
    logIn(expert)
    const mock = await open(
      reviewer({
        [`PUT ${A}/answers/Q1/vote`]: jsonResponse(409, {
          code: 'stale_round',
          message: 'The round moved on.',
        }),
      }),
    )
    await button('Approve').trigger('click')
    await flushPromises()
    expect(wrapper!.get('[role="alert"]').text()).toContain('changed')
    expect(read(mock, '/answers')).toHaveLength(2)
  })

  it('sends the round it is showing with a vote', async () => {
    logIn(expert)
    const mock = await open(
      reviewer({ [`PUT ${A}/answers/Q1/vote`]: () => jsonResponse(200, answers()) }),
    )
    await button('Disapprove').trigger('click')
    await flushPromises()
    expect(await bodyOf(mock, 'PUT')).toEqual({ vote: 'disapprove', review_round: 1 })
  })

  it('reads an earlier round when asked, read-only, and goes back to the latest', async () => {
    logIn(admin)
    const mock = await open({
      [`GET ${A}`]: () => jsonResponse(200, assignment('admin', ['comment', 'decide_answers'])),
      [`GET ${A}/answers`]: (request) =>
        new URL(request.url).searchParams.get('review_round') === '1'
          ? jsonResponse(200, answers(['Q1'], [1, 2], 1))
          : jsonResponse(200, answers(['Q1'], [1, 2], 2)),
    })
    expect(wrapper!.find('[data-testid="decision-bar"]').exists()).toBe(true)
    const select = wrapper!.get('select')
    expect(select.findAll('option').map((o) => o.text())).toEqual(['1', '2 (latest)'])

    await select.setValue('1')
    await flushPromises()
    expect(
      read(mock, '/answers').some(([i]) => (i as Request).url.includes('review_round=1')),
    ).toBe(true)
    expect(wrapper!.text()).toContain('earlier round')
    expect(wrapper!.find('[data-testid="decision-bar"]').exists()).toBe(false)

    await wrapper!.get('select').setValue('2')
    await flushPromises()
    expect(wrapper!.text()).not.toContain('earlier round')
  })

  it('shows why the review could not be opened, and stays at the gate', async () => {
    logIn(expert)
    await open({
      [`GET ${A}`]: () => jsonResponse(200, assignment('peer', ['comment', 'vote'])),
      [`GET ${A}/answers`]: jsonResponse(409, { code: 'review_not_opened', message: 'Open it.' }),
      [`POST ${A}/review/open`]: jsonResponse(500, { code: 'internal_error', message: 'x' }),
    })
    expect(wrapper!.find('[data-testid="gate"]').exists()).toBe(true)
    await wrapper!.get('[data-testid="gate"] button').trigger('click')
    await flushPromises()
    expect(wrapper!.get('[data-testid="gate"] [role="alert"]').text()).not.toBe('')
  })
})

describe('the quiet refresh', () => {
  beforeEach(() => vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] }))

  const stubbed = () => ({
    [`GET ${A}`]: () => jsonResponse(200, assignment('peer', ['comment', 'vote'])),
    [`GET ${A}/answers`]: () => jsonResponse(200, answers()),
  })

  it('reads the answers again every thirty seconds while the page is in view', async () => {
    logIn(expert)
    const mock = await open(stubbed())
    expect(read(mock, '/answers')).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(read(mock, '/answers')).toHaveLength(2)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(read(mock, '/answers')).toHaveLength(3)
  })

  it('does not read while the tab is hidden, and stops when the page is left', async () => {
    logIn(expert)
    const mock = await open(stubbed())
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    await vi.advanceTimersByTimeAsync(60_000)
    expect(read(mock, '/answers')).toHaveLength(1)

    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
    wrapper!.unmount()
    wrapper = undefined
    await vi.advanceTimersByTimeAsync(60_000)
    expect(read(mock, '/answers')).toHaveLength(1)
  })
})
