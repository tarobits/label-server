import { test, expect } from './fixtures'

test('switching authentication forms clears old validation and focuses the username', async ({
  page,
}) => {
  await page.goto('/#/')
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await page.route('**/api/auth/login', (route) =>
    route.fulfill({ status: 401, json: { detail: 'Invalid username or password.' } }),
  )
  await page.getByLabel('Username', { exact: true }).fill('tester')
  await page.getByLabel('Password', { exact: true }).fill('test-password-123')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveText('Invalid username or password.')
  await page.getByRole('button', { name: 'Create an account', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Create account', exact: true })).toBeVisible()
  await expect(page.getByLabel('Username', { exact: true })).toBeFocused()
  await expect(page.locator('[aria-invalid="true"], .field-error')).toHaveCount(0)
  await page.getByRole('button', { name: 'Back to sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  await expect(page.getByLabel('Username', { exact: true })).toBeFocused()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('navigation stays reachable in short windows and identifies nested pages on mobile', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1024, height: 600 })
  await page.goto('/#/templates/text/edit')
  const navigation = page.getByRole('navigation', { name: 'Main navigation' })
  const templates = navigation.getByRole('link', { name: 'Templates', exact: true })
  await expect(templates).toHaveAttribute('aria-current', 'location')
  const admin = navigation.getByRole('link', { name: 'Administration', exact: true })
  await admin.focus()
  const bounds = await admin.boundingBox()
  expect(bounds!.y).toBeGreaterThanOrEqual(0)
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(600)
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: 'Administration', exact: true })).toBeVisible()
  await expect(admin).toHaveAttribute('aria-current', 'page')

  await page.setViewportSize({ width: 390, height: 812 })
  await page.goto('/#/templates/text/edit')
  await expect(templates).toHaveAttribute('aria-current', 'location')
  await expect
    .poll(async () => {
      const item = await templates.boundingBox()
      const container = await navigation.boundingBox()
      return item!.x >= container!.x && item!.x + item!.width <= container!.x + container!.width
    })
    .toBe(true)
  await templates.click()
  await expect(page.getByRole('heading', { name: 'Templates', exact: true })).toBeVisible()
  await expect(templates).toHaveAttribute('aria-current', 'page')
})

test('primary buttons keep readable contrast in default and hover states', async ({ page }) => {
  await page.goto('/#/profiles')
  await page.getByRole('button', { name: 'Add tape profile', exact: true }).click()
  const save = page.getByRole('button', { name: 'Save tape profile', exact: true })
  const contrast = () =>
    save.evaluate((button) => {
      const style = getComputedStyle(button)
      const luminance = (color: string) => {
        const values = color
          .match(/[\d.]+/g)!
          .slice(0, 3)
          .map(Number)
          .map((channel) => {
            const value = channel / 255
            return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
          })
        return values[0] * 0.2126 + values[1] * 0.7152 + values[2] * 0.0722
      }
      const values = [luminance(style.color), luminance(style.backgroundColor)].sort(
        (a, b) => a - b,
      )
      return (values[1] + 0.05) / (values[0] + 0.05)
    })
  expect(await contrast()).toBeGreaterThanOrEqual(4.5)
  await save.hover()
  await expect.poll(contrast).toBeGreaterThanOrEqual(4.5)
})

test('mobile queue scrolls locally and compact checkbox targets work at their edges', async ({
  page,
  request,
}) => {
  const profile = (await (await request.get('/api/tape-profiles')).json())[0]
  await request.post('/api/jobs', {
    data: { tape_profile: profile.id, data: { text: 'Mobile selection' } },
  })
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/#/queue')
  const checkbox = page.getByRole('checkbox', { name: 'Select Mobile selection', exact: true })
  await expect(checkbox).toBeVisible()
  const target = checkbox.locator('..')
  const box = await target.boundingBox()
  expect(box!.width).toBeGreaterThanOrEqual(44)
  expect(box!.height).toBeGreaterThanOrEqual(44)
  expect(await checkbox.evaluate((el) => el.getBoundingClientRect().width)).toBe(17)
  await target.click({ position: { x: 2, y: 2 } })
  await expect(checkbox).toBeChecked()
  const scroll = page.locator('.table-scroll')
  expect(await scroll.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375)
  await scroll.evaluate((el) => (el.scrollLeft = el.scrollWidth))
  await expect.poll(() => scroll.evaluate((el) => el.scrollLeft)).toBeGreaterThan(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375)
  await scroll.evaluate((el) => (el.scrollLeft = 0))
  await checkbox.focus()
  await page.keyboard.press('Space')
  await expect(checkbox).not.toBeChecked()
})

test('failed forms retain inline errors, focus linked summaries, and recover without submitting invalid data', async ({
  page,
}) => {
  let saves = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/api/tape-profiles')) saves++
  })
  await page.goto('/#/profiles')
  await page.getByRole('button', { name: 'Add tape profile', exact: true }).click()
  const name = page.getByLabel('Profile name', { exact: true })
  const threshold = page.getByLabel('Automatic batch threshold', { exact: true })
  await threshold.fill('')
  const save = page.getByRole('button', { name: 'Save tape profile', exact: true })
  await save.click()
  const summary = page.locator('.validation-summary')
  await expect(summary).toBeFocused()
  await expect(summary.getByRole('link')).toHaveCount(2)
  for (const field of [name, threshold]) {
    await expect(field).toHaveAttribute('aria-invalid', 'true')
    const id = await field.getAttribute('aria-describedby')
    await expect(page.locator(`[id="${id}"]`)).not.toBeEmpty()
  }
  expect(saves).toBe(0)
  // An unrelated Vue update must not replace the focused summary.
  await page.getByLabel('Tape color', { exact: true }).evaluate((input: HTMLInputElement) => {
    input.value = '#aaaaaa'
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await expect(summary).toBeFocused()
  await summary.getByRole('link', { name: /^Profile name:/ }).click()
  await expect(name).toBeFocused()
  await name.fill('Accessible profile')
  await expect(name).not.toHaveAttribute('aria-invalid')
  await expect(summary).toHaveCount(0)
  await expect(threshold).toHaveAttribute('aria-invalid', 'true')
  await save.click()
  await expect(threshold).toBeFocused()
  await threshold.fill('50')
  await expect(threshold).not.toHaveAttribute('aria-invalid')
  await save.click()
  await expect(page.getByRole('heading', { name: 'Accessible profile', exact: true })).toBeVisible()
  expect(saves).toBe(1)
})

test('label submission associates server field errors and clears only the edited error', async ({
  page,
}) => {
  await page.route('**/api/jobs', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    await route.fulfill({
      status: 422,
      json: {
        detail: [
          { loc: ['body', 'data', 'text'], msg: 'Choose different label text.' },
          { loc: ['body', 'copies'], msg: 'Choose a different copy count.' },
        ],
      },
    })
  })
  await page.goto('/#/new')
  const text = page.getByLabel('Label text', { exact: true })
  const copies = page.getByLabel('Copies', { exact: true })
  await text.fill('Invalid server value')
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  await expect(page.locator('.validation-summary')).toBeFocused()
  await expect(page.getByRole('alert')).toHaveCount(1)
  await expect(text).toHaveAttribute('aria-invalid', 'true')
  await expect(copies).toHaveAttribute('aria-invalid', 'true')
  await expect(text).toHaveAccessibleDescription('Choose different label text.')
  await expect(copies).toHaveAccessibleDescription('Choose a different copy count.')
  await text.fill('Corrected text')
  await expect(text).not.toHaveAttribute('aria-invalid')
  await expect(copies).toHaveAttribute('aria-invalid', 'true')
  await expect(text).toBeFocused()
  await copies.fill('2')
  await expect(copies).not.toHaveAttribute('aria-invalid')
})
