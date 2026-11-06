import type { User } from '@/api/client'

export interface NavItem {
  label: string
  to: string
  /** One plain line about what the section is for, shown on the home page. */
  blurb: string
}

// This build only collects answers: the review, knowledge base and home sections are not offered.
const EXPERT: NavItem[] = [
  // Experts can't list vignettes (admin only in the API): theirs are the ones assigned to them.
  { label: 'My cases', to: '/assignments', blurb: 'Answer the cases assigned to you.' },
]

const ADMIN: NavItem[] = [
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
  { label: 'Experts', to: '/experts', blurb: 'Invite experts and manage their accounts.' },
]

/** What the side panel and the home page list. The API still enforces every permission. */
export function navFor(role: User['role']): NavItem[] {
  return role === 'admin' ? ADMIN : EXPERT
}
