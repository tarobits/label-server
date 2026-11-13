import { languagePicker, selectLanguage, expectLanguage } from './language'
import { test, expect } from './fixtures'

test('failed language saves preserve the account preference and allow a later save', async ({
  page,
  request,
}) => {
  await page.goto('/#/account')
  const picker = languagePicker(page)
  await expectLanguage(page, 'en')
  await page.route('**/api/auth/language', (route) => route.abort('failed'), { times: 1 })
  await selectLanguage(page, 'de')
  await expect(page.getByRole('alert')).toContainText('Could not save language')
  await expect(picker).toBeEnabled()
  await expectLanguage(page, 'en')
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  expect((await (await request.get('/api/auth/session')).json()).user.language).toBe('browser')
  await selectLanguage(page, 'de')
  await expect(page.locator('html')).toHaveAttribute('lang', 'de')
  await expect(languagePicker(page)).toBeEnabled()
  await expect(page.getByRole('alert')).toHaveCount(0)
  expect((await (await request.get('/api/auth/session')).json()).user.language).toBe('de')
  await page.goto('/#/activity')
  await expect(page.locator('.pagination [aria-live]').first()).toHaveText('Seite 1 von 1')
})

test('a language save completing after sign-out cannot restore the old account or its locale', async ({
  page,
}) => {
  await page.goto('/#/account')
  const picker = languagePicker(page)
  await expectLanguage(page, 'en')
  let release!: () => void
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  let committed!: () => void
  const saved = new Promise<void>((resolve) => {
    committed = resolve
  })
  let finished!: () => void
  const delivered = new Promise<void>((resolve) => {
    finished = resolve
  })
  await page.route('**/api/auth/language', async (route) => {
    const response = await route.fetch()
    committed()
    await held
    try {
      await route.fulfill({ response })
    } finally {
      finished()
    }
  })
  try {
    await selectLanguage(page, 'de')
    await saved
    await expect(picker).toHaveAttribute('aria-busy', 'true')
    await page.locator('.account-menu > summary').click()
    await page
      .getByRole('group', { name: 'Account', exact: true })
      .getByRole('button', { name: 'Sign out', exact: true })
      .click()
    await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
    release()
    await delivered
    await expect(page.locator('html')).toHaveAttribute('lang', 'en')
    await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
    // A subsequent device preference change must still work after the stale response.
    await selectLanguage(page, 'de')
    await expect(page.getByRole('heading', { name: 'Anmelden', exact: true })).toBeVisible()
  } finally {
    release()
    await page.unrouteAll({ behavior: 'wait' })
  }
})

test('account language changes live, preserves input and follows another session', async ({
  page,
  request,
  browser,
  baseURL,
}) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/#/account')
  await page.locator('input[name="current_password"]').fill('unsaved text')
  await selectLanguage(page, 'de')
  await expect(page.locator('html')).toHaveAttribute('lang', 'de')
  await expectLanguage(page, 'de')
  await expect(page.locator('input[name="current_password"]')).toHaveValue('unsaved text')
  await expect(page).toHaveTitle(/Kontoeinstellungen/)
  await expect(page.getByRole('heading', { name: 'Kontoeinstellungen', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Menü', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Vorlagen', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Menü', exact: true }).click()
  await expect(page.getByRole('button', { name: 'PIN festlegen', exact: true })).toBeVisible()
  await expect(page.getByText('Keine bestätigte E-Mail-Adresse', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await languagePicker(page).scrollIntoViewIfNeeded()
  await page.screenshot({ path: 'test-results/i18n-de-account.png', animations: 'disabled' })
  const another = await browser.newContext({
    baseURL,
    storageState: await request.storageState(),
    locale: 'en-US',
  })
  try {
    const second = await another.newPage()
    await second.goto('/#/account')
    await expectLanguage(second, 'de')
    await expect(second.locator('html')).toHaveAttribute('lang', 'de')
  } finally {
    await another.close()
  }
  await selectLanguage(page, 'en')
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await expect(page.getByRole('button', { name: 'Set PIN', exact: true })).toBeVisible()
  await expect(page.locator('input[name="current_password"]')).toHaveValue('unsaved text')
  expect(errors).toEqual([])
})

test('signed-out language uses the browser and keeps form values when switched', async ({
  browser,
  baseURL,
}) => {
  const context = await browser.newContext({
    baseURL,
    locale: 'de-DE',
    storageState: { cookies: [], origins: [] },
  })
  try {
    const page = await context.newPage()
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'Anmelden', exact: true })).toBeVisible()
    await page.locator('input[autocomplete="username"]').fill('unchanged-name')
    await selectLanguage(page, 'en')
    await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
    await expect(page.locator('input[autocomplete="username"]')).toHaveValue('unchanged-name')
    await page.reload()
    await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  } finally {
    await context.close()
  }
})
