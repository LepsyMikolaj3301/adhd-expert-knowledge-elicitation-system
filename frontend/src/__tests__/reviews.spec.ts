import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import type { ReviewItem, User } from '@/api/client'
import { activityText, describeError, speakerLabel } from '@/copy'
import { ApiError } from '@/api/client'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'
import ExpertsView from '@/views/ExpertsView.vue'
import HomeView from '@/views/HomeView.vue'
import ReviewsView from '@/views/ReviewsView.vue'
import ReviewView from '@/views/ReviewView.vue'

import { admin, expert, jsonResponse, stubFetch } from './helpers'

let wrapper: VueWrapper | undefined
afterEach(() => wrapper?.unmount())
beforeEach(() => setActivePinia(createPinia()))

function logIn(user: User) {
  const auth = useAuthStore()
  auth.user = user
  auth.loaded = true
}

const mountView = (component: Parameters<typeof mount>[0], props = {}) =>
  (wrapper = mount(component, { props, global: { plugins: [router] } }))

function review(overrides: Partial<ReviewItem> = {}): ReviewItem {
  return {
    assignment_id: 'a1',
    vignette_code: 'V001',
    vignette_version: 1,
    state: 'peer_review',
    relation: 'reviewer',
    opened: true,
    unit_count: 3,
    accepts: 1,
    declines: 0,
    comment_count: 2,
    my_vote: null,
    author_pseudonym: null,
    review_round: 1,
    updated_at: '2026-11-04T10:00:00Z',
    ...overrides,
  }
}

const unit = (comments: unknown[] = []) => ({
  audience: 'peer',
  id: 'u1',
  ordinal: 1,
  kind: 'fragment',
  direction: 'toward',
  patient_words: 'barely slept',
  text: 'She slept badly.',
  review_round: 1,
  comments,
})

describe('wording', () => {
  it('turns the new error codes into plain words', () => {
    const err = (code: string) => new ApiError(409, { code, message: 'engineering words' })
    expect(describeError(err('review_closed'))).toContain('still here')
    expect(describeError(err('stale_round'))).toContain('changed')
    expect(describeError(err('email_taken'))).toContain('already')
  })

  it('names speakers by role, and never calls a feed item by its kind', () => {
    expect(speakerLabel({ kind: 'author', pseudonym: null })).toBe('Author')
    expect(speakerLabel({ kind: 'reviewer', pseudonym: 'E07' })).toBe('E07')
    const text = activityText({
      kind: 'comment_on_mine',
      speaker: { kind: 'reviewer', pseudonym: 'E07' },
      unit_ordinal: 2,
      vignette_code: 'V001',
      assignment_id: 'a1',
      at: '',
      unread: true,
    })
    expect(text).toBe('E07 commented on statement 2 of case V001.')
  })
})

describe('ReviewsView', () => {
  it('groups an expert’s reviews by what they need to do', async () => {
    logIn(expert)
    stubFetch(() =>
      jsonResponse(200, [
        review({ assignment_id: 'a1' }),
        review({ assignment_id: 'a2', my_vote: 'accept' }),
        review({ assignment_id: 'a3', relation: 'author' }),
      ]),
    )
    mountView(ReviewsView)
    await flushPromises()
    const titles = wrapper!.findAll('[data-testid="group"] h2').map((h) => h.text())
    expect(titles).toEqual(['Waiting for your vote', "You've voted", 'Your submissions'])
    expect(wrapper!.get('a').attributes('href')).toBe('/reviews/a1')
  })

  it('lists an admin’s reviews in one list, oldest first', async () => {
    logIn(admin)
    stubFetch(() =>
      jsonResponse(200, [
        review({
          assignment_id: 'new',
          updated_at: '2026-11-05T10:00:00Z',
          author_pseudonym: 'E02',
        }),
        review({
          assignment_id: 'old',
          updated_at: '2026-11-01T10:00:00Z',
          author_pseudonym: 'E03',
        }),
      ]),
    )
    mountView(ReviewsView)
    await flushPromises()
    expect(wrapper!.findAll('[data-testid="group"] h2')).toHaveLength(0)
    expect(wrapper!.findAll('[data-testid="review"] a').map((a) => a.attributes('href'))).toEqual([
      '/reviews/old',
      '/reviews/new',
    ])
    expect(wrapper!.text()).toContain('E03')
  })
})

describe('ReviewView', () => {
  const peer = {
    audience: 'peer',
    id: 'a1',
    state: 'peer_review',
    review_round: 1,
    allowed_actions: ['comment', 'vote'],
    vignette: {
      code: 'V001',
      version: 1,
      framing: 'email',
      text: 'The patient text.',
      word_count: 3,
    },
  }

  function server(opened: boolean) {
    const calls: string[] = []
    let isOpen = opened
    stubFetch((url) => {
      calls.push(url.replace(/^.*\/api\/v1/, ''))
      if (url.endsWith('/review/open')) {
        isOpen = true
        return new Response(null, { status: 204 })
      }
      if (!isOpen) {
        return jsonResponse(409, { code: 'review_not_opened', message: 'Open the review first.' })
      }
      if (url.endsWith('/units')) return jsonResponse(200, [unit()])
      if (url.endsWith('/votes'))
        return jsonResponse(200, {
          accepts: 0,
          declines: 0,
          my_vote: null,
          review_round: 1,
          votes: [],
        })
      if (url.endsWith('/vote')) return jsonResponse(200, {})
      return jsonResponse(200, peer)
    })
    return calls
  }

  it('shows the gate first, and loads nothing else until Continue', async () => {
    logIn(expert)
    const calls = server(false)
    mountView(ReviewView, { id: 'a1' })
    await flushPromises()
    expect(wrapper!.get('[data-testid="gate"]').text()).toContain(
      "can't be assigned this case later",
    )
    expect(calls).toEqual(['/assignments/a1'])

    await wrapper!.get('[data-testid="gate"] button').trigger('click')
    await flushPromises()
    expect(wrapper!.find('[data-testid="gate"]').exists()).toBe(false)
    expect(wrapper!.get('[data-testid="unit"]').text()).toContain('She slept badly.')
    expect(wrapper!.text()).toContain('The patient text.')
  })

  it('offers the vote bar only when the server allows it, worded as advice', async () => {
    logIn(expert)
    server(true)
    mountView(ReviewView, { id: 'a1' })
    await flushPromises()
    const bar = wrapper!.get('[data-testid="votes"]')
    expect(bar.text()).toContain('study team makes the final decision')
    expect(bar.findAll('button').map((b) => b.text())).toEqual(['Accept', 'Decline'])
  })

  it('keeps a comment that could not be posted', async () => {
    logIn(expert)
    stubFetch((url) => {
      if (url.endsWith('/comments'))
        return jsonResponse(409, { code: 'review_closed', message: 'closed' })
      if (url.endsWith('/units')) return jsonResponse(200, [unit()])
      if (url.endsWith('/votes'))
        return jsonResponse(200, {
          accepts: 0,
          declines: 0,
          my_vote: null,
          review_round: 1,
          votes: [],
        })
      return jsonResponse(200, peer)
    })
    mountView(ReviewView, { id: 'a1' })
    await flushPromises()
    await wrapper!.get('textarea').setValue('My careful thought')
    await wrapper!.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper!.get('[role="alert"]').text()).toContain('already decided')
    expect((wrapper!.get('textarea').element as HTMLTextAreaElement).value).toBe(
      'My careful thought',
    )
  })

  it('lets the admin decide only once every statement has a decision', async () => {
    logIn(admin)
    stubFetch((url) => {
      if (url.endsWith('/units'))
        return jsonResponse(200, [
          { ...unit(), audience: 'admin', status: 'pending', decisions: [] },
        ])
      if (url.endsWith('/votes'))
        return jsonResponse(200, {
          accepts: 1,
          declines: 0,
          my_vote: null,
          review_round: 1,
          votes: [],
        })
      return jsonResponse(200, {
        audience: 'admin',
        id: 'a1',
        state: 'peer_review',
        review_round: 1,
        vignette_code: 'V001',
        allowed_actions: ['comment', 'decide_units'],
      })
    })
    mountView(ReviewView, { id: 'a1' })
    await flushPromises()
    const submit = wrapper!.findAll('button').find((b) => b.text() === 'Submit decisions')!
    expect(submit.attributes('disabled')).toBeDefined()
    await wrapper!.get('input[value="request_changes"]').setValue()
    expect(submit.attributes('disabled')).toBeDefined() // the comment is required
    await wrapper!.get('textarea[aria-label="What should change"]').setValue('Re-file sentence 2')
    expect(submit.attributes('disabled')).toBeUndefined()
  })
})

describe('HomeView', () => {
  it('shows each panel, with its own empty state', async () => {
    logIn(expert)
    stubFetch(() =>
      jsonResponse(200, {
        next_up: [
          {
            assignment_id: 'a9',
            action: 'check',
            vignette_code: 'V009',
            vignette_version: 1,
            state: 'expert_check',
            updated_at: '',
            expert_pseudonym: null,
          },
        ],
        next_up_total: 7,
        reviews_waiting: [],
        recent_reviews: [],
        activity: [],
        unread_activity: 0,
      }),
    )
    mountView(HomeView)
    await flushPromises()
    expect(wrapper!.get('[data-testid="next-up"] a.btn').text()).toBe('Check')
    expect(wrapper!.get('[data-testid="next-up"]').text()).toContain('See all 7')
    expect(wrapper!.get('[data-testid="waiting"]').text()).toContain('Nothing is waiting for you.')
    expect(wrapper!.get('[data-testid="news"]').text()).toContain('Nothing new yet.')
  })

  it('links a comment to its thread, and marks the feed as seen up to the newest item', async () => {
    logIn(expert)
    const seen: unknown[] = []
    stubFetch((url) => {
      if (url.endsWith('/activity/seen')) return new Response(null, { status: 204 })
      return jsonResponse(200, {
        next_up: [],
        next_up_total: 0,
        reviews_waiting: [],
        recent_reviews: [],
        unread_activity: 1,
        activity: [
          {
            kind: 'comment_on_mine',
            assignment_id: 'a1',
            unit_id: 'u1',
            unit_ordinal: 2,
            vignette_code: 'V001',
            unread: true,
            at: '2026-11-05T09:00:00Z',
            speaker: { kind: 'reviewer', pseudonym: 'E07' },
            excerpt: 'Why?',
          },
          {
            kind: 'case_assigned',
            assignment_id: 'a2',
            vignette_code: 'V002',
            unread: false,
            at: '2026-11-04T09:00:00Z',
          },
        ],
      })
    })
    const fetchMock = vi.mocked(globalThis.fetch)
    mountView(HomeView)
    await flushPromises()
    expect(wrapper!.get('[data-testid="news"] a').attributes('href')).toBe('/reviews/a1#unit-u1')
    const post = fetchMock.mock.calls
      .map(([r]) => r as Request)
      .find((r) => r.url.endsWith('/activity/seen'))
    seen.push(await post?.json())
    expect(seen).toEqual([{ until: '2026-11-05T09:00:00Z' }])
  })
})

describe('ExpertsView', () => {
  const person = (over = {}) => ({ ...expert, invite_pending: false, ...over })

  it('names each account’s status', async () => {
    logIn(admin)
    stubFetch(() =>
      jsonResponse(200, [
        person({ id: '1' }),
        person({ id: '2', invite_pending: true }),
        person({ id: '3', is_active: false }),
      ]),
    )
    mountView(ExpertsView)
    await flushPromises()
    expect(wrapper!.findAll('[data-testid="status"]').map((s) => s.text())).toEqual([
      'Active',
      'Invite not accepted',
      'Deactivated',
    ])
  })

  it('shows the invite link once, as a full address', async () => {
    logIn(admin)
    stubFetch((url) =>
      url.endsWith('/users') && !url.includes('?') ? jsonResponse(200, []) : jsonResponse(200, []),
    )
    mountView(ExpertsView)
    await flushPromises()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: Request) =>
        input.method === 'POST'
          ? jsonResponse(201, { invite_path: '/invite/tok', user: person() })
          : jsonResponse(200, []),
      ),
    )
    await wrapper!.get('input[type="email"]').setValue('new@example.com')
    await wrapper!.get('input:not([type])').setValue('New Person')
    await wrapper!.get('form').trigger('submit')
    await flushPromises()
    expect(
      (wrapper!.get('input[aria-label="Invite link"]').element as HTMLInputElement).value,
    ).toBe(`${location.origin}/invite/tok`)
    expect(wrapper!.get('[data-testid="invite"]').text()).toContain("can't be shown again")
  })
})

describe('ExpertCheck', () => {
  it('sends only the sentences that changed, then approves', async () => {
    logIn(expert)
    const sent: { method: string; url: string; body?: unknown }[] = []
    const findings = {
      version: 3,
      editable: true,
      check_outcome: null,
      review_round: 1,
      feedback: [],
      flags: [{ kind: 'coverage', highlight: 'h1', message: 'Nobody wrote about passage 1.' }],
      highlights: [
        { id: 'h1', chip: 1, direction: 'toward', origin: 'expert', text: 'barely slept' },
      ],
      sentences: [
        {
          id: 's1',
          question_id: 'Q1',
          text: 'She slept badly.',
          targets: ['case'],
          assigned_by: 'llm',
        },
        {
          id: 's2',
          question_id: 'Q1',
          text: 'Nothing else.',
          targets: ['case'],
          assigned_by: 'llm',
        },
      ],
    }
    stubFetch(() => jsonResponse(200, findings))
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: Request) => {
        sent.push({
          method: input.method,
          url: input.url.replace(/^.*\/api\/v1/, ''),
          body: input.method === 'PUT' ? await input.clone().json() : undefined,
        })
        return input.method === 'GET' ? jsonResponse(200, findings) : jsonResponse(200, findings)
      }),
    )
    const { default: ExpertCheck } = await import('@/components/answering/ExpertCheck.vue')
    mountView(ExpertCheck, { id: 'a1', canSkip: true })
    await flushPromises()
    expect(wrapper!.get('[data-testid="flags"]').text()).toContain('Nobody wrote')

    await wrapper!.findAll('[data-testid="sentence"]')[0]!.findAll('input')[0]!.setValue(true)
    await wrapper!
      .findAll('button')
      .find((b) => b.text() === 'Save and approve')!
      .trigger('click')
    await flushPromises()

    expect(sent.filter((c) => c.method !== 'GET')).toEqual([
      {
        method: 'PUT',
        url: '/assignments/a1/findings',
        body: { version: 3, sentences: { s1: ['case', 'h1'] }, directions: {} },
      },
      { method: 'POST', url: '/assignments/a1/expert-check/complete', body: undefined },
    ])
    expect(wrapper!.emitted('done')).toHaveLength(1)
  })
})
