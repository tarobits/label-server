import { test, expect } from './fixtures'
const png = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=',
  'base64',
)
test('account picture uploads, survives reload and can be removed', async ({ page }) => {
  await page.goto('/#/account')
  const section = page.getByRole('region', { name: 'Profile picture', exact: true })
  await expect(section.locator('.user-avatar img')).toHaveCount(0)
  await section
    .getByLabel('Choose image', { exact: true })
    .setInputFiles({ name: 'picture.png', mimeType: 'image/png', buffer: png })
  await expect(section.getByRole('status')).toHaveText('Profile picture saved.')
  await expect(section.locator('.user-avatar img')).toBeVisible()
  await page.reload()
  await expect(section.locator('.user-avatar img')).toBeVisible()
  await page.screenshot({ path: 'test-results/account-picture.png', animations: 'disabled' })
  await section.getByRole('button', { name: 'Remove picture', exact: true }).click()
  await expect(section.getByRole('status')).toHaveText('Profile picture removed.')
  await expect(section.locator('.user-avatar img')).toHaveCount(0)
})
