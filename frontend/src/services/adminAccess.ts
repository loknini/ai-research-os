const ADMIN_TOKEN_SESSION_KEY = 'airos.adminToken'

export function getAdminSessionToken(): string {
  if (typeof window === 'undefined') return ''
  try {
    return window.sessionStorage.getItem(ADMIN_TOKEN_SESSION_KEY)?.trim() || ''
  } catch {
    return ''
  }
}

export function setAdminSessionToken(token: string): void {
  if (typeof window === 'undefined') return
  try {
    const normalized = token.trim()
    if (normalized) window.sessionStorage.setItem(ADMIN_TOKEN_SESSION_KEY, normalized)
    else window.sessionStorage.removeItem(ADMIN_TOKEN_SESSION_KEY)
  } catch {
    // sessionStorage may be unavailable in hardened/private browser contexts.
  }
}

export const ADMIN_TOKEN_HEADER = 'X-Admin-Token'
