const key = 'trace.auth.return_to'
export function safeReturnTo(value: string | null) { return value && value.startsWith('/') && !value.startsWith('//') && !value.startsWith('/auth/') ? value : '/account' }
export function rememberReturnTo(value: string) { sessionStorage.setItem(key, safeReturnTo(value)) }
export function consumeReturnTo() { const value = safeReturnTo(sessionStorage.getItem(key)); sessionStorage.removeItem(key); return value }
