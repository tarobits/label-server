import { selectLanguage } from './language'
import { test, expect } from './fixtures'

test('every navigation destination has distinct artwork, including migration', async ({ page }) => {
  await page.route('**/api/auth/session', async (route) => {
    const response = await route.fetch()
    const session = await response.json()
    await route.fulfill({ response, json: { ...session, migration_required: true } })
  })
  await page.goto('/#/templates')
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  await expect(nav.getByRole('link')).toHaveCount(19)
  const artwork = await nav.getByRole('link').evaluateAll((links) =>
    links.map((link) => {
      const svg = link.querySelector('svg')!
      return {
        name: link.textContent?.trim(),
        paths: [...svg.querySelectorAll('path')].map((path) => path.getAttribute('d')).join('|'),
        hidden: svg.getAttribute('aria-hidden'),
      }
    }),
  )
  for (const icon of artwork) {
    expect(icon.paths, icon.name).toBeTruthy()
    expect(icon.hidden, icon.name).toBe('true')
    expect(
      artwork.filter((other) => other.paths === icon.paths),
      icon.name,
    ).toHaveLength(1)
  }
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 1100 })
    const menu = nav.getByRole('button', { name: 'Menu', exact: true })
    if (await menu.isVisible()) await menu.click()
    await nav.getByRole('link').last().focus()
    await page.screenshot({ path: `test-results/navigation-icons-${width}.png` })
  }
})

for (const language of ['en', 'de']) {
  test(`navigation never overflows horizontally in ${language}`, async ({ page, request }) => {
    await request.put('/api/auth/language', {
      data: { language, browser_language: language },
    })
    await page.goto('/#/templates')
    const nav = page.getByRole('navigation', {
      name: language === 'en' ? 'Main navigation' : 'Hauptnavigation',
    })
    await expect(nav).toBeVisible()
    for (const width of [320, 360, 390, 600, 768, 849, 850, 851, 1024, 1280, 1920, 3840]) {
      await page.setViewportSize({ width, height: 800 })
      await expect
        .poll(() => nav.evaluate((el) => el.scrollWidth - el.clientWidth))
        .toBeLessThanOrEqual(1)
      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth - innerWidth))
        .toBeLessThanOrEqual(1)
      const menu = nav.getByRole('button', {
        name: language === 'en' ? 'Menu' : 'Menü',
        exact: true,
      })
      // Wait for ResizeObserver to settle before interacting across the shell breakpoint.
      if (width <= 850) await expect(menu).toBeVisible()
      else await expect(menu).not.toBeVisible()
      if (await menu.isVisible()) {
        await menu.click()
        await expect(menu).toHaveAttribute('aria-expanded', 'true')
        await expect
          .poll(() => nav.evaluate((el) => el.scrollWidth - el.clientWidth))
          .toBeLessThanOrEqual(1)
        const links = nav.getByRole('link')
        for (const link of await links.all()) {
          await link.focus()
          await expect(link).toBeInViewport()
          const item = (await link.boundingBox())!
          const bounds = (await nav.boundingBox())!
          expect(item.x).toBeGreaterThanOrEqual(bounds.x)
          expect(item.x + item.width).toBeLessThanOrEqual(bounds.x + bounds.width)
        }
        await page.keyboard.press('Escape')
        await expect(menu).toBeFocused()
        await expect(menu).toHaveAttribute('aria-expanded', 'false')
        await expect(links.first()).not.toBeVisible()
      }
      if (width === 390 || width === 1280) {
        await page.screenshot({ path: `test-results/navigation-${language}-${width}.png` })
      }
    }
  })
}

test('open navigation updates its language without losing destinations', async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 600 })
  await page.goto('/#/account')
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  await nav.getByRole('button', { name: 'Menu', exact: true }).click()
  const before = await nav
    .getByRole('link')
    .evaluateAll((links) => links.map((link) => link.getAttribute('href')))
  await selectLanguage(page, 'de')
  const translated = page.getByRole('navigation', { name: 'Hauptnavigation' })
  await expect(translated.getByRole('button', { name: 'Menü', exact: true })).toHaveAttribute(
    'aria-expanded',
    'true',
  )
  await expect(translated.getByRole('link', { name: 'Vorlagen', exact: true })).toBeVisible()
  expect(
    await translated
      .getByRole('link')
      .evaluateAll((links) => links.map((link) => link.getAttribute('href'))),
  ).toEqual(before)
  await expect
    .poll(() => translated.evaluate((el) => el.scrollWidth - el.clientWidth))
    .toBeLessThanOrEqual(1)
})

for (const reducedMotion of ['reduce', 'no-preference'] as const) {
  test(`compact menu supports keyboard, short windows and resizing with ${reducedMotion}`, async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion })
    await page.setViewportSize({ width: 390, height: 500 })
    await page.goto('/#/templates/text/edit')
    await expect(page.getByLabel('Template name', { exact: true })).toBeVisible()
    await expect(page).toHaveURL(/profile=/)
    const nav = page.getByRole('navigation', { name: 'Main navigation' })
    const menu = nav.getByRole('button', { name: 'Menu', exact: true })
    await expect(menu).toBeVisible()
    await expect(nav.locator('.navigation-current')).toHaveText('Templates')
    await menu.focus()
    await page.keyboard.press('Enter')
    const links = nav.getByRole('link')
    await page.keyboard.press('Tab')
    await expect(links.first()).toBeFocused()
    await expect(nav.getByRole('link', { name: 'Templates', exact: true })).toHaveAttribute(
      'aria-current',
      'location',
    )
    await links.last().focus()
    await expect(links.last()).toBeInViewport()
    await page.screenshot({ path: `test-results/navigation-mobile-${reducedMotion}.png` })
    await page.keyboard.press('Escape')
    await expect(menu).toBeFocused()
    await page.keyboard.press('Enter')
    await nav.getByRole('link', { name: 'Templates', exact: true }).click()
    await expect(page).toHaveURL(/#\/templates$/)
    await expect(menu).toHaveAttribute('aria-expanded', 'false')
    await expect(links.first()).not.toBeVisible()
    await menu.click()
    await links.first().focus()
    await page.setViewportSize({ width: 1024, height: 600 })
    await expect(menu).not.toBeVisible()
    await expect(nav.getByRole('link', { name: 'Templates', exact: true })).toBeFocused()
    await page.setViewportSize({ width: 390, height: 500 })
    await expect(menu).toBeFocused()
    await expect(menu).toHaveAttribute('aria-expanded', 'false')
  })
}
