import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const email = 'apikeys.e2e@example.test'
const password = 'correct-horse-battery-staple'

async function latestEmailLink(request: APIRequestContext, recipient: string, path: string) {
  let link: string | undefined
  await expect.poll(async () => {
    const mailpitUrl = process.env.E2E_MAILPIT_URL ?? 'http://127.0.0.1:18025'
    const messages = await request.get(`${mailpitUrl}/api/v1/messages`)
    const inbox = await messages.json() as { messages?: Array<{ ID?: string; To?: Array<{ Address?: string }> }> }
    const message = inbox.messages?.find((candidate) => candidate.To?.some((address) => address.Address === recipient))
    if (!message?.ID) return undefined
    const content = await request.get(`${mailpitUrl}/api/v1/message/${message.ID}`)
    const messageBody = await content.json() as { Text?: string; HTML?: string }
    const searchableBody = `${messageBody.Text ?? ''}\n${messageBody.HTML ?? ''}`
    const match = searchableBody.match(new RegExp(`http://127\\.0\\.0\\.1:5173${path}[^\\s<]+`))
    link = match?.[0]
    return link
  }, { timeout: 30_000 }).toBeTruthy()
  return link!
}

async function registerAndSignIn(page: Page, request: APIRequestContext) {
  await page.goto('/sign-up')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page.getByRole('status')).toContainText('verification email')

  await page.goto(await latestEmailLink(request, email, '/auth/verify'))
  await page.getByRole('button', { name: 'Verify email' }).click()
  await expect(page.getByRole('status')).toContainText('Email verified')

  await page.goto('/sign-in')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('button', { name: `Open account menu for ${email}` })).toBeVisible()
}

test.describe('isolated authentication stack', () => {
  test.skip(!process.env.E2E_AUTH_STACK, 'Requires the isolated Compose E2E stack.')

  test('a user can create an API key and link it to an agent', async ({ page, request }) => {
    await registerAndSignIn(page, request)

    await page.getByRole('button', { name: `Open account menu for ${email}` }).click()
    await page
      .getByRole('navigation', { name: 'Account' })
      .getByRole('link', { name: 'Settings' })
      .click()
    await expect(page.getByText('Back to app')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'API keys' })).toBeVisible()
    const openAiApiKeySection = page
      .getByRole('heading', { name: 'OpenAI API Key' })
      .locator('xpath=..')
    await expect(openAiApiKeySection).toBeVisible()
    await expect(
      openAiApiKeySection.getByText(
        'Press Enter to save. Keys are encrypted and never shown again.',
      ),
    ).toBeVisible()
    await page.locator('#openai-api-key').fill('sk-e2e-test-key')
    await page.locator('#openai-api-key').press('Enter')
    await expect(page.getByText('API key saved')).toBeVisible()

    await page.goto('/agents')
    await page.getByRole('button', { name: 'Create agent' }).first().click()
    const agentDialog = page.getByRole('dialog')
    await agentDialog.getByLabel('Name').fill('E2E key agent')
    await agentDialog.getByLabel('Model access').click()
    await page.getByRole('option', { name: 'Your OpenAI API key' }).click()
    await agentDialog.getByRole('button', { name: 'Create agent' }).click()
    await expect(page.getByText('E2E key agent')).toBeVisible()
  })
})
