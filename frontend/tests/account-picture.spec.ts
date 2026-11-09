import { test, expect } from './fixtures'
const png = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=',
  'base64',
)
for (const width of [1280, 390]) {
  test(`account picture stays in sync with navigation at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/#/account')
    const section = page.getByRole('region', { name: 'Profile picture', exact: true })
    const navigation = page.locator('.account-menu > summary')
    const avatar = navigation.locator('.user-avatar')
    await expect(navigation).toHaveAccessibleName('Account: owner')
    await expect(avatar).toHaveText('O')
    await expect(section.locator('.user-avatar img')).toHaveCount(0)
    await section
      .getByLabel('Choose image', { exact: true })
      .setInputFiles({ name: 'picture.png', mimeType: 'image/png', buffer: png })
    await expect(section.getByRole('status')).toHaveText('Profile picture saved.')
    await expect(section.locator('.user-avatar img')).toBeVisible()
    await expect(avatar.locator('img')).toBeVisible()
    await expect
      .poll(() => avatar.locator('img').evaluate((img) => (img as HTMLImageElement).naturalWidth))
      .toBe(256)
    await expect(avatar).toHaveCSS('width', '28px')
    await expect(avatar).toHaveCSS('border-radius', '6px')
    await navigation.click()
    const menu = page.getByRole('group', { name: 'Account', exact: true })
    await expect(menu).toBeVisible()
    await expect(menu).toHaveCSS('opacity', '1')
    const menuBox = (await menu.boundingBox())!
    expect(menuBox.x).toBeGreaterThanOrEqual(0)
    expect(menuBox.x + menuBox.width).toBeLessThanOrEqual(width)
    expect(menuBox.y + menuBox.height).toBeLessThanOrEqual(900)
    await page.screenshot({
      path: `test-results/navigation-avatar-${width}.png`,
      animations: 'disabled',
    })
    await page.keyboard.press('Escape')
    await expect(menu).not.toBeVisible()
    await expect(navigation).toBeFocused()
    await page.reload()
    await expect(section.locator('.user-avatar img')).toBeVisible()
    await expect(avatar.locator('img')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
    await section.getByRole('button', { name: 'Remove picture', exact: true }).click()
    await expect(section.getByRole('status')).toHaveText('Profile picture removed.')
    await expect(section.locator('.user-avatar img')).toHaveCount(0)
    await expect(avatar.locator('img')).toHaveCount(0)
    await expect(avatar).toHaveText('O')
  })
}

test('navigation falls back to an initial when the picture cannot load', async ({
  page,
  request,
}) => {
  await request.put('/api/auth/avatar', { data: png, headers: { 'Content-Type': 'image/png' } })
  await page.route('**/api/auth/avatar?*', (route) => route.fulfill({ status: 404 }))
  await page.goto('/#/')
  const avatar = page.locator('.account-menu .user-avatar')
  await expect(avatar).toHaveText('O')
  await expect(avatar.locator('img')).toHaveCount(0)
  await page.locator('.account-menu > summary').click()
  await expect(page.getByRole('group', { name: 'Account', exact: true })).toBeVisible()
})
