import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const email = 'student.e2e@example.test'
const password = 'correct-horse-battery-staple'

async function openSignIn(page: Page) {
  await page.goto('/sign-in')
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible()
}

async function latestEmailLink(request: APIRequestContext, recipient: string, path: string) {
  let link: string | undefined
  await expect.poll(async () => {
    const mailpitUrl = process.env.E2E_MAILPIT_URL ?? 'http://127.0.0.1:18025'
    const messages = await request.get(`${mailpitUrl}/api/v1/messages`)
    const inbox = await messages.json() as { messages?: Array<{ ID?: string; To?: Array<{ Address?: string }> }> }
    const message = inbox.messages?.find((candidate) => candidate.To?.some((address) => address.Address === recipient))
    if (!message?.ID) return undefined
    const content = await request.get(`${mailpitUrl}/api/v1/message/${message.ID}`)
    const match = JSON.stringify(await content.json()).match(new RegExp(`http://127\\.0\\.0\\.1:5173${path}#[^"\\s]+`))
    link = match?.[0]
    return link
  }, { timeout: 30_000 }).toBeTruthy()
  return link!
}

test('unauthenticated visitors are sent to sign in', async ({ page }) => {
  await page.goto('/account')
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible()
})

test.describe('isolated authentication stack', () => {
  test.skip(!process.env.E2E_AUTH_STACK, 'Requires the isolated Compose E2E stack.')

  test('a user can register, verify their email, and sign in', async ({ page, request }) => {
    await page.goto('/sign-up')
    await page.getByLabel('Email').fill(email)
    await page.getByLabel('Password').fill(password)
    await page.getByRole('button', { name: 'Create account' }).click()
    await expect(page.getByRole('status')).toContainText('verification email')

    await page.goto(await latestEmailLink(request, email, '/auth/verify'))
    await page.getByRole('button', { name: 'Verify email' }).click()
    await expect(page.getByRole('status')).toContainText('Email verified')

    await openSignIn(page)
    await page.getByLabel('Email').fill(email)
    await page.getByLabel('Password').fill(password)
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByRole('heading', { name: 'Your account is ready.' })).toBeVisible()
  })

  test('invalid credentials do not authenticate a user', async ({ page }) => {
    await openSignIn(page)
    await page.getByLabel('Email').fill(email)
    await page.getByLabel('Password').fill('not-the-account-password')
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByRole('alert')).toContainText('Unable to complete authentication')
  })

  for (const provider of ['GitHub', 'Google'] as const) {
    test(`a user can sign in with ${provider}`, async ({ page }) => {
      await openSignIn(page)
      await page.getByRole('button', { name: `Continue with ${provider}` }).click()
      await expect(page.getByRole('heading', { name: 'Your account is ready.' })).toBeVisible()
    })
  }

  test('a provider denial returns to the client without credentials', async ({ page }) => {
    await page.goto('http://127.0.0.1:18000/auth/oauth/github/callback?error=access_denied')
    await expect(page.getByRole('heading', { name: 'Sign-in was not completed' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Return to sign in' })).toBeVisible()
  })
})
