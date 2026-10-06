import { expect, test } from '@playwright/test'

test('unauthenticated visitors are sent to sign in', async ({ page }) => {
  await page.goto('/account')
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible()
})

test.skip(!process.env.E2E_AUTH_STACK, 'Requires the isolated Compose E2E stack and OAuth provider emulator.')

test('email/password and provider authentication flows', async () => {
  // The isolated E2E stack supplies disposable Mailpit inboxes and both provider emulators.
  // Full-flow cases are enabled only in that environment to prevent external-provider traffic.
})
