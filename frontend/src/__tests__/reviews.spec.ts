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
    answer_count: 3,
    approvals: 1,
    disapprovals: 0,
    comment_count: 2,
    my_votes: 0,
    author_pseudonym: null,
    review_round: 1,
    updated_at: '2026-11-04T10:00:00Z',
    ...overrides,
  }
}

const answers = (comments: unknown[] = []) => ({
  review_round: 1,
  rounds: [1],
  state: 'peer_review',
  highlights: [
    { id: 'h1', chip: 1, text: 'patient', span: [4, 11], origin: 'expert', direction: 'away' },
  ],
  answers: [
    {
      question_id: 'Q1',
      question: 'Which fragments matter?',
      text: 'She slept badly.\nNothing else.',
      lines: [
        { text: 'She slept badly.', targets: ['h1'], assigned_by: 'chip' },
        { text: 'Nothing else.', targets: ['case'], assigned_by: 'llm' },
      ],
      comments,
      approvals: 0,
      disapprovals: 0,
      my_vote: null,
      votes: [],
      decision: null,
    },
  ],
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
      question_id: 'Q2',
      vignette_code: 'V001',
      assignment_id: 'a1',
      at: '',
      unread: true,
    })
    expect(text).toBe('E07 commented on the answer to question 2 of case V001.')
  })
})

describe('ReviewsView', () => {
  it('groups an expert’s reviews by what they need to do', async () => {
    logIn(expert)
    stubFetch(() =>
      jsonResponse(200, [
        review({ assignment_id: 'a1' }),
        review({ assignment_id: 'a2', my_votes: 3 }),
        review({ assignment_id: 'a4', my_votes: 1 }),
        review({ assignment_id: 'a3', relation: 'author' }),
      ]),
    )
    mountView(ReviewsView)
    await flushPromises()
    const titles = wrapper!.findAll('[data-testid="group"] h2').map((h) => h.text())
    expect(titles).toEqual(['Waiting for your vote', "You've voted", 'Your submissions'])
    expect(wrapper!.get('a').attributes('href')).toBe('/reviews/a1')
    const waiting = wrapper!.findAll('[data-testid="group"]')[0]!
    expect(waiting.text()).toContain('3 answers')
    expect(waiting.findAll('a').map((a) => a.attributes('href'))).toEqual([
      '/reviews/a1',
      '/reviews/a4',
    ])
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
      if (url.endsWith('/answers')) return jsonResponse(200, answers())
      if (url.endsWith('/vote')) {
        const voted = answers()
        voted.answers[0] = { ...voted.answers[0]!, my_vote: 'approve' as never, approvals: 1 }
        return jsonResponse(200, voted)
      }
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
    const answer = wrapper!.get('[data-testid="answer"]')
    expect(answer.text()).toContain('Which fragments matter?')
    expect(answer.findAll('[data-testid="lines"] li').map((l) => l.text())).toEqual([
      expect.stringContaining('She slept badly.'),
      expect.stringContaining('Nothing else.'),
    ])
    expect(wrapper!.text()).toContain('The patient text.')
  })

  it('shows what each sentence is about, and lights the quote in the text', async () => {
    logIn(expert)
    server(true)
    mountView(ReviewView, { id: 'a1' })
    await flushPromises()
    const tags = wrapper!.findAll('[data-testid="quote-tag"]')
    expect(tags.map((t) => t.text())).toEqual(['Quote 1', 'Whole case'])
    expect(wrapper!.find('[data-testid="vignette-text"] mark').exists()).toBe(false)
    await tags[0]!.trigger('mouseover')
    expect(wrapper!.get('[data-testid="vignette-text"] mark').text()).toBe('patient')
  })

  it('lets a reviewer vote on each answer, worded as advice', async () => {
    logIn(expert)
    server(true)
    mountView(ReviewView, { id: 'a1' })
    await flushPromises()
    expect(wrapper!.text()).toContain('study team makes the final decision')
    const bar = wrapper!.get('[data-testid="votes"]')
    expect(bar.findAll('button').map((b) => b.text())).toEqual(['Approve', 'Disapprove'])
    await bar.findAll('button')[0]!.trigger('click')
    await flushPromises()
    const after = wrapper!.get('[data-testid="votes"]')
    expect(after.text()).toContain('1 approve, 0 disapprove')
    expect(after.findAll('button')[0]!.attributes('aria-pressed')).toBe('true')
  })

  it('keeps a comment that could not be posted', async () => {
    logIn(expert)
    stubFetch((url) => {
      if (url.endsWith('/comments'))
        return jsonResponse(409, { code: 'review_closed', message: 'closed' })
      if (url.endsWith('/answers')) return jsonResponse(200, answers())
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

  it('lets the admin decide only once every answer has a decision', async () => {
    logIn(admin)
    // jsdom doesn't implement dialogs.
    HTMLDialogElement.prototype.showModal = function () {
      this.setAttribute('open', '')
    }
    HTMLDialogElement.prototype.close = function () {
      this.removeAttribute('open')
    }
    stubFetch((url) => {
      if (url.endsWith('/answers')) return jsonResponse(200, answers())
      return jsonResponse(200, {
        audience: 'admin',
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
        allowed_actions: ['comment', 'decide_answers'],
      })
    })
    mountView(ReviewView, { id: 'a1' })
    await flushPromises()
    const submit = wrapper!.findAll('button').find((b) => b.text() === 'Submit decisions')!
    expect(submit.attributes('disabled')).toBeDefined()
    await wrapper!.get('input[value="request_changes"]').setValue()
    expect(submit.attributes('disabled')).toBeDefined() // the comment is required
    await wrapper!.get('textarea[aria-label="What should change"]').setValue('Say more about sleep')
    expect(submit.attributes('disabled')).toBeUndefined()
    await submit.trigger('click')
    expect(wrapper!.text()).toContain('sends every answer back to the author')
  })
})

describe('an admin reading a review', () => {
  it('sees the patient summary and the full case text beside the answers', async () => {
    logIn(admin)
    stubFetch((url) => {
      if (url.endsWith('/answers')) return jsonResponse(200, answers())
      return jsonResponse(200, {
        audience: 'admin',
        id: 'a1',
        state: 'peer_review',
        review_round: 1,
        vignette: {
          code: 'V001',
          version: 1,
          text: 'The whole patient text.',
          framing: 'personal_journal',
          patient_summary: 'A student.',
          word_count: 4,
        },
        expert_id: 'e1',
        expert_pseudonym: 'E01',
        vignette_version: 1,
        vignette_version_id: 'v1',
        allowed_actions: ['comment', 'decide_answers'],
      })
    })
    mountView(ReviewView, { id: 'a1' })
    await flushPromises()
    expect(wrapper!.get('[data-testid="vignette-text"]').text()).toContain(
      'The whole patient text.',
    )
    expect(wrapper!.get('[data-testid="patient-summary"]').text()).toContain('A student.')
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
            state: 'proofread_check',
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
            question_id: 'Q2',
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
    expect(wrapper!.get('[data-testid="news"] a').attributes('href')).toBe('/reviews/a1#answer-Q2')
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
