/**
 * Whether an expert still has to confirm the privacy notice. The confirmation is kept on the
 * server (who, which version, when), so it follows the expert to any browser, and the admin sees
 * it on Experts. A newer `PRIVACY.version` asks everyone again.
 */
import type { User } from '@/api/client'
import { PRIVACY } from '@/copy'

export function privacyNeeded(user: Pick<User, 'privacy_version'>): boolean {
  return user.privacy_version !== PRIVACY.version
}
