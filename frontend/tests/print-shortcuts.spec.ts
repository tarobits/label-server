import { test, expect } from './fixtures'

for (const language of ['en', 'de']) {
  test(`global print shortcuts are separate from page creation in ${language}`, async ({
    page,
    request,
  }) => {
    await request.put('/api/auth/language', { data: { language, browser_language: language } })
    await page.goto('/#/templates')
    const group = page.getByRole('group', {
      name: language === 'en' ? 'Create prints' : 'Drucke erstellen',
      exact: true,
    })
    const createTemplate = page.getByRole('link', {
      name: language === 'en' ? 'Create template' : 'Vorlage erstellen',
      exact: true,
    })
    await expect(createTemplate).toBeVisible()
    await expect(page.locator('.route-surface')).not.toHaveClass(/page-enter-active/)
    await expect(group).toBeVisible()
    await expect(group.getByRole('link')).toHaveCount(2)
    await expect(group.locator('a[href="#/templates/new"]')).toHaveCount(0)
    for (const width of [320, 390, 600, 850, 851, 1280]) {
      await page.setViewportSize({ width, height: 900 })
      const menu = page
        .locator('.main-navigation')
        .getByRole('button', { name: language === 'en' ? 'Menu' : 'Menü', exact: true })
      if (width <= 850) await expect(menu).toBeVisible()
      else await expect(menu).not.toBeVisible()
      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth - innerWidth))
        .toBeLessThanOrEqual(1)
      const panel = (await group.boundingBox())!
      for (const link of await group.getByRole('link').all()) {
        const bounds = (await link.boundingBox())!
        expect(bounds.height).toBeGreaterThanOrEqual(44)
        expect(bounds.x).toBeGreaterThan(panel.x)
        expect(bounds.x + bounds.width).toBeLessThan(panel.x + panel.width)
      }
      await expect
        .poll(() =>
          page.evaluate(() => {
            const panel = document.querySelector('.print-shortcuts')!.getBoundingClientRect()
            const local = document
              .querySelector('a[href="#/templates/new"]')!
              .getBoundingClientRect()
            return local.top - panel.bottom
          }),
        )
        .toBeGreaterThanOrEqual(20)
      if (width === 390 || width === 1280)
        await page.screenshot({ path: `test-results/print-shortcuts-${language}-${width}.png` })
    }
    await group.locator('a[href="#/runs"]').click()
    await expect(page).toHaveURL(/#\/runs(?:\?|$)/)
    await expect(page.locator('.csv-form')).toBeVisible()
    await expect(group.locator('a[href="#/runs"]')).toHaveCount(0)
    await group.locator('a[href="#/new"]').click()
    await expect(page).toHaveURL(/#\/new(?:\?|$)/)
    await expect(group.locator('a[href="#/new"]')).toHaveCount(0)
    await expect(group.locator('a[href="#/runs"]')).toBeVisible()
  })
}

test('print shortcuts are absent without submission permission', async ({ page }) => {
  await page.route('**/api/auth/session', async (route) => {
    const response = await route.fetch()
    const session = await response.json()
    session.user = {
      ...session.user,
      is_admin: false,
      destination_permissions: {},
      destination_levels: {},
    }
    await route.fulfill({ response, json: session })
  })
  await page.goto('/#/templates')
  await expect(page.getByRole('navigation', { name: 'Main navigation' })).toBeVisible()
  await expect(page.getByRole('group', { name: 'Create prints', exact: true })).toHaveCount(0)
  await expect(
    page.locator('.page-header a[href="#/new"], .page-header a[href="#/runs"]'),
  ).toHaveCount(0)
})
