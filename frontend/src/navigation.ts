import type { User } from '@/api/client'

export interface NavItem {
  label: string
  to: string
  /** One plain line about what the section is for, shown on the home page. */
  blurb: string
}

const HOME: NavItem = { label: 'Home', to: '/', blurb: '' }

// Only sections that exist are listed. Reviews, Experts and the Knowledge base are not built yet:
// their addresses answer with a placeholder, but nobody is led there.
const EXPERT: NavItem[] = [
  HOME,
  // Experts can't list vignettes (admin only in the API): theirs are the ones assigned to them.
  { label: 'My cases', to: '/assignments', blurb: 'Answer the cases assigned to you.' },
]

const ADMIN: NavItem[] = [
  HOME,
  {
    label: 'Vignettes',
    to: '/vignettes',
    blurb: 'Write vignettes, publish them and assign them to experts.',
  },
  {
    label: 'Assignments',
    to: '/assignments',
    blurb: "Follow each expert's progress and assign vignettes.",
  },
]

/** What the side panel and the home page list. The API still enforces every permission. */
export function navFor(role: User['role']): NavItem[] {
  return role === 'admin' ? ADMIN : EXPERT
}
