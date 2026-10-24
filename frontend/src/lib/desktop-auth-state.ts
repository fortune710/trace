let desktopCsrfToken: string | null = null

export function getDesktopCsrfToken() {
  return desktopCsrfToken
}

export function setDesktopCsrfToken(token: string) {
  desktopCsrfToken = token
}

export function clearDesktopCsrfToken() {
  desktopCsrfToken = null
}
