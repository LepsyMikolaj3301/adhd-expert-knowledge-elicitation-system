import type { User } from '@/api/client'

export interface NavItem {
  label: string
  to: string
  /** One plain line about what the section is for, shown on the home page. */
  blurb: string
}

const HOME: NavItem = { label: 'Home', to: '/', blurb: '' }

// Sections that are not built yet are listed too: they open a placeholder, so the shape of the
// application stays visible.
const EXPERT: NavItem[] = [
  HOME,
  // Experts can't list vignettes (admin only in the API): theirs are the ones assigned to them.
  { label: 'My cases', to: '/assignments', blurb: 'Answer the cases assigned to you.' },
  {
    label: 'Reviews',
    to: '/reviews',
    blurb: "Read colleagues' submissions, discuss them and give your advice.",
  },
]

const ADMIN: NavItem[] = [
  HOME,
  {
    label: 'All cases',
    to: '/vignettes',
    blurb: 'Write cases, publish them and assign them to experts.',
  },
  {
    label: 'Reviews',
    to: '/reviews',
    blurb: 'Follow the discussions and decide what enters the knowledge base.',
  },
  {
    label: 'Assignments',
    to: '/assignments',
    blurb: "Follow each expert's progress and assign vignettes.",
  },
  { label: 'Experts', to: '/experts', blurb: 'Invite experts and manage their accounts.' },
  {
    label: 'Knowledge base',
    to: '/knowledge',
    blurb: 'Browse the ingested knowledge units and test the search.',
  },
]

/** What the side panel and the home page list. The API still enforces every permission. */
export function navFor(role: User['role']): NavItem[] {
  return role === 'admin' ? ADMIN : EXPERT
}
