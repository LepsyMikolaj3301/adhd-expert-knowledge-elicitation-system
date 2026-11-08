/**
 * Whether an expert has read the instructions. "Don't show again" lasts for good in this browser;
 * plain "continue" lasts for the tab, so that reloading in the middle of a case does not bring the
 * page back. Browsers can refuse storage (private windows, blocked site data): then the page just
 * shows every time, which is harmless.
 */
const key = (userId: string) => `intro-seen:${userId}`

function read(storage: () => Storage, userId: string): boolean {
  try {
    return storage().getItem(key(userId)) === '1'
  } catch {
    return false
  }
}

function write(storage: () => Storage, userId: string) {
  try {
    storage().setItem(key(userId), '1')
  } catch {
    // Nothing to do: see above.
  }
}

export function introNeeded(userId: string): boolean {
  return !read(() => localStorage, userId) && !read(() => sessionStorage, userId)
}

export function acknowledgeIntro(userId: string, forever: boolean) {
  write(() => sessionStorage, userId)
  if (forever) write(() => localStorage, userId)
}
