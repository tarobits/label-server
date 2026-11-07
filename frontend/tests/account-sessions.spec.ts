import { test, expect } from './fixtures'

for (const width of [390, 1280]) {
  test(`sessions disclose details and remotely sign out at ${width}px`, async ({
    page,
    playwright,
    baseURL,
  }) => {
    await page.setViewportSize({ width, height: 900 })
    const other = await playwright.request.newContext({
      baseURL,
      storageState: { cookies: [], origins: [] },
      userAgent:
        'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Version/18.0 Mobile/15E148 Safari/604.1',
    })
    try {
      expect(
        (
          await other.post('/api/auth/login', {
            data: { username: 'owner', password: 'browser-owner-password' },
          })
        ).ok(),
      ).toBeTruthy()
      await page.goto('/#/account')
      const section = page.getByRole('region', { name: 'Logged-in sessions', exact: true })
      const rows = section.getByRole('listitem')
      await expect(rows).toHaveCount(2)
      const remote = rows.filter({ hasText: 'Safari 18.0' })
      const details = remote.getByRole('button', { name: 'Session details' })
      await details.click()
      await expect(details).toHaveAttribute('aria-expanded', 'true')
      await expect(remote.getByText('iOS 18.0', { exact: true })).toBeVisible()
      await expect(remote.getByText('IP address', { exact: true })).toBeVisible()
      await expect(remote.getByText('First signed in', { exact: true })).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
        width,
      )
      await section.scrollIntoViewIfNeeded()
      await page.screenshot({
        path: `test-results/account-sessions-${width}.png`,
        animations: 'disabled',
      })
      await details.click()
      await expect(details).toHaveAttribute('aria-expanded', 'false')
      await expect(remote.getByText('iOS 18.0', { exact: true })).toBeHidden()
      await remote.getByRole('button', { name: 'Sign out', exact: true }).click()
      const dialog = page.getByRole('dialog')
      await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
      await expect(dialog).toBeHidden()
      await expect(rows).toHaveCount(2)
      await remote.getByRole('button', { name: 'Sign out', exact: true }).click()
      await dialog.getByRole('button', { name: 'Sign out', exact: true }).click()
      await expect(rows).toHaveCount(1)
      await expect(section.getByRole('button', { name: 'Refresh sessions' })).toBeFocused()
      expect((await other.get('/api/auth/sessions')).status()).toBe(401)
      await expect(section.getByText('This session', { exact: true })).toBeVisible()
      await section.getByRole('button', { name: 'Sign out', exact: true }).click()
      await dialog.getByRole('button', { name: 'Sign out', exact: true }).click()
      await expect(page.getByLabel('Username or email', { exact: true })).toBeVisible()
    } finally {
      await other.dispose()
    }
  })
}

test('session load failures can be retried', async ({ page }) => {
  await page.route('**/api/auth/sessions', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Temporarily unavailable' }),
    }),
  )
  await page.goto('/#/account')
  const section = page.getByRole('region', { name: 'Logged-in sessions', exact: true })
  await expect(section.getByRole('alert')).toContainText('Temporarily unavailable')
  await page.unroute('**/api/auth/sessions')
  await section.getByRole('button', { name: 'Refresh sessions' }).click()
  await expect(section.getByText('This session', { exact: true })).toBeVisible()
  await expect(section.getByRole('alert')).toHaveCount(0)
})
