import { test, expect } from './fixtures'

test('pointer opening and closing avoids focus rings while Tab restores keyboard indicators', async ({
  page,
}) => {
  await page.goto('/#/templates')
  const trigger = page.getByRole('button', { name: 'Changelog', exact: true })
  await trigger.click()
  const dialog = page.getByRole('dialog', { name: 'Changelog', exact: true })
  const heading = dialog.getByRole('heading', { name: 'Changelog', exact: true })
  const close = dialog.getByRole('button', { name: 'Close', exact: true })
  await expect(heading).toBeFocused()
  await expect(heading).toHaveCSS('outline-style', 'none')
  await page.screenshot({
    path: 'test-results/changelog-pointer-focus.png',
    animations: 'disabled',
  })
  await close.click()
  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()
  await expect(trigger).toHaveCSS('outline-style', 'none')
  await page.keyboard.press('Shift+Tab')
  await page.keyboard.press('Tab')
  await expect(trigger).toBeFocused()
  await expect(trigger).toHaveCSS('outline-style', 'solid')
  await page.keyboard.press('Enter')
  await expect(heading).toBeFocused()
  await expect(heading).toHaveCSS('outline-style', 'solid')
  await page.keyboard.press('Tab')
  await expect(close).toBeFocused()
  await expect(close).toHaveCSS('outline-style', 'solid')
  await page.keyboard.press('Escape')
  await expect(trigger).toBeFocused()
  await expect(trigger).toHaveCSS('outline-style', 'solid')
})

test('the version link opens the full changelog repeatedly without changing visit tracking', async ({
  page,
}) => {
  let visits = 0
  page.on('request', (request) => {
    if (request.url().endsWith('/api/auth/changelog')) visits++
  })
  const visit = page.waitForResponse('**/api/auth/changelog')
  await page.goto('/#/templates')
  await visit
  const link = page.getByRole('button', { name: 'Changelog', exact: true })
  await expect(link).toBeVisible()
  const version = (await page.locator('.version-number').boundingBox())!
  const trigger = (await link.boundingBox())!
  expect(trigger.x).toBeGreaterThan(version.x + version.width)
  expect(Math.abs(trigger.y - version.y)).toBeLessThan(4)
  await link.focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'Changelog', exact: true })
  await expect(dialog.getByRole('heading', { level: 3 })).toHaveText([
    'v0.4.0',
    'v0.3.2',
    'v0.3.1',
    'v0.3.0',
    'v0.2.1',
    'v0.2.0',
    'v0.1.0',
  ])
  await expect(dialog).toContainText('Initial release of Label Printer Server.')
  await page.screenshot({ path: 'test-results/full-changelog-desktop.png', animations: 'disabled' })
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(link).toBeFocused()
  await page.screenshot({ path: 'test-results/changelog-footer-link.png', animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.keyboard.press('Enter')
  await expect(dialog).toBeVisible()
  await dialog.getByRole('heading', { name: 'v0.1.0', exact: true }).scrollIntoViewIfNeeded()
  const close = dialog.getByRole('button', { name: 'Close', exact: true })
  await expect(close).toBeInViewport()
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
  await close.click()
  await expect(dialog).toBeHidden()
  await expect(link).toBeFocused()
  await expect(page.locator('dialog[open]')).toHaveCount(0)
  expect(visits).toBe(1)
})

test('first visits establish an account baseline shared with another browser', async ({
  page,
  browser,
  request,
}) => {
  const visit = page.waitForResponse('**/api/auth/changelog')
  await page.goto('/#/')
  expect((await (await visit).json()).previous_version).toBeNull()
  await expect(page.getByRole('dialog', { name: 'What’s new', exact: true })).toHaveCount(0)
  const other = await browser.newContext({ storageState: await request.storageState() })
  try {
    const second = await other.newPage()
    const repeat = second.waitForResponse('**/api/auth/changelog')
    await second.goto(new URL('/#/templates', page.url()).href)
    const result = await (await repeat).json()
    expect(result.previous_version).toBe(result.current_version)
    await expect(second.getByRole('dialog', { name: 'What’s new', exact: true })).toHaveCount(0)
  } finally {
    await other.close()
  }
})

for (const reducedMotion of ['no-preference', 'reduce'] as const) {
  test(`unseen releases appear newest first once with ${reducedMotion}`, async ({ page }) => {
    await page.emulateMedia({ reducedMotion })
    let visited = false
    await page.route('**/api/auth/changelog', async (route) => {
      expect(route.request().method()).toBe('POST')
      expect(route.request().headers()['x-csrf-token']).toBeTruthy()
      const previous = visited ? '0.2.1' : '0.1.0'
      visited = true
      await route.fulfill({ json: { current_version: '0.2.1', previous_version: previous } })
    })
    await page.goto('/#/templates')
    const dialog = page.getByRole('dialog', { name: 'What’s new', exact: true })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('heading', { level: 3 })).toHaveText(['v0.2.1', 'v0.2.0'])
    await expect(dialog).toContainText('while preserving explicitly chosen profiles')
    await expect(dialog).toContainText('Sidebar controls remain reachable in short windows')
    await expect(dialog).not.toContainText('Initial release of Label Printer Server.')
    await expect(dialog).toHaveCSS(
      'animation-name',
      reducedMotion === 'reduce' ? 'feedback-arrive' : 'dialog-arrive',
    )
    await expect(dialog.getByRole('heading', { name: 'What’s new', exact: true })).toBeFocused()
    await page.keyboard.press('Tab')
    const close = dialog.getByRole('button', { name: 'Close', exact: true })
    await expect(close).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(close).toBeFocused()
    await page.screenshot({
      path: `test-results/changelog-desktop-${reducedMotion}.png`,
      animations: 'disabled',
    })
    await page.setViewportSize({ width: 390, height: 844 })
    expect(await dialog.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true)
    expect((await dialog.boundingBox())!.height).toBeLessThanOrEqual(812)
    await dialog.getByRole('heading', { name: 'v0.2.0', exact: true }).scrollIntoViewIfNeeded()
    await expect(close).toBeInViewport()
    await page.screenshot({
      path: `test-results/changelog-mobile-${reducedMotion}.png`,
      animations: 'disabled',
    })
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
    await expect(page.locator('#main-content')).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(page.getByRole('link', { name: 'New label', exact: true })).toBeFocused()
    const again = page.waitForResponse('**/api/auth/changelog')
    await page.reload()
    expect((await (await again).json()).previous_version).toBe('0.2.1')
    await expect(dialog).toBeHidden()
  })
}

test('the modal excludes changelogs beyond the installed version', async ({ page }) => {
  await page.route('**/api/auth/changelog', (route) =>
    route.fulfill({
      json: { current_version: '0.2.0', previous_version: '0.0.0' },
    }),
  )
  await page.goto('/#/')
  const dialog = page.getByRole('dialog', { name: 'What’s new', exact: true })
  await expect(dialog.getByRole('heading', { level: 3 })).toHaveText(['v0.2.0', 'v0.1.0'])
  await expect(dialog).toContainText('Initial release of Label Printer Server.')
  await expect(dialog).toContainText(
    'Multiple physical printers and HomeBox integration remain deferred.',
  )
})

test('release notes wait for an active dialog and preserve keyboard focus', async ({ page }) => {
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/auth/changelog', async (route) => {
    await gate
    await route.fulfill({ json: { current_version: '0.2.1', previous_version: '0.2.0' } })
  })
  const visit = page.waitForRequest('**/api/auth/changelog')
  await page.goto('/#/admin?section=roles')
  await visit
  const create = page.getByRole('button', { name: 'New role', exact: true })
  await create.click()
  const role = page.getByRole('dialog', { name: 'New role', exact: true })
  await expect(role.getByLabel('Role name', { exact: true })).toBeFocused()
  const response = page.waitForResponse('**/api/auth/changelog')
  release()
  await response
  const notes = page.getByRole('dialog', { name: 'What’s new', exact: true })
  await expect(notes).toBeHidden()
  await expect(page.locator('dialog[open]')).toHaveCount(1)
  await expect(role.getByLabel('Role name', { exact: true })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(notes).toBeVisible()
  await expect(page.locator('dialog[open]')).toHaveCount(1)
  await expect(notes.getByRole('heading', { name: 'What’s new', exact: true })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(create).toBeFocused()
})
