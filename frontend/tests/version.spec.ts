import { test, expect } from './fixtures'

test('version display and dismissible update notice stay consistent across navigation', async ({
  page,
}) => {
  let latest = '0.2.1'
  await page.route('**/api/version', (route) =>
    route.fulfill({
      json: {
        current_version: '0.2.0',
        latest_version: latest,
        update_available: true,
        release_url: `https://github.com/tarobits/label-server/releases/tag/v${latest}`,
      },
    }),
  )
  await page.goto('/#/')
  await expect(page.locator('.version-number')).toHaveText('v0.2.0')
  const notice = page.getByRole('status', { name: 'Software update' })
  await expect(notice).toContainText('0.2.1')
  await expect(notice.getByRole('link', { name: 'View release' })).toHaveAttribute(
    'href',
    /v0\.2\.1$/,
  )
  const position = await notice.boundingBox()
  const viewport = page.viewportSize()!
  expect(position!.x + position!.width).toBeGreaterThan(viewport.width - 40)
  expect(position!.y + position!.height).toBeGreaterThan(viewport.height - 40)
  await page.getByRole('button', { name: 'Dismiss update notification' }).click()
  await expect(notice).toHaveCount(0)
  await page.goto('/#/templates')
  await page.reload()
  await expect(page.locator('.version-number')).toHaveText('v0.2.0')
  await expect(notice).toHaveCount(0)
  latest = '0.3.0'
  await expect(notice).toContainText('0.3.0', { timeout: 10000 })
  await page.screenshot({ path: 'test-results/version-notice.png' })
})

test('current or unavailable releases do not show a notice', async ({ page }) => {
  await page.goto('/#/')
  await expect(page.locator('.version-number')).toHaveText('v0.2.0')
  await expect(page.getByRole('status', { name: 'Software update' })).toHaveCount(0)
})
