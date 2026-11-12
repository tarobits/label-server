import { test, expect } from './fixtures'
import { tapeProfileControl } from './tape-profile-picker-helpers'

for (const width of [390, 1280]) {
  test(`tape availability and shared picker work across all forms at ${width}px`, async ({
    page,
    request,
  }) => {
    await page.setViewportSize({ width, height: 900 })
    const profiles = []
    for (let index = 0; index < 13; index++) {
      const response = await request.post('/api/tape-profiles', {
        data: {
          name: index === 0 ? 'Retired tape' : index === 1 ? 'Blue label tape' : `Stock ${index}`,
          width_mm: index === 2 ? 12 : 24,
          background: index === 1 ? '#94c5ed' : '#ffffff',
        },
      })
      expect(response.ok()).toBeTruthy()
      profiles.push(await response.json())
    }
    await page.goto('/#/profiles')
    const card = page
      .locator('.profile-card')
      .filter({ has: page.getByRole('heading', { name: 'Retired tape', exact: true }) })
    await card.getByRole('button', { name: 'Mark unavailable', exact: true }).click()
    await expect(card.getByText('Unavailable', { exact: true })).toBeVisible()
    await page.screenshot({ path: `test-results/profile-unavailable-${width}.png`, fullPage: true })
    for (const path of ['/new', '/runs', '/templates/new']) {
      await page.goto(`/#${path}`)
      const control = tapeProfileControl(page)
      await control.click()
      const dialog = page.getByRole('dialog', { name: 'Choose tape profile', exact: true })
      const search = dialog.getByRole('searchbox', { name: 'Search tape profiles', exact: true })
      await expect(search).toBeFocused()
      await expect(dialog.locator('article')).toHaveCount(12)
      await dialog.getByRole('button', { name: 'Next', exact: true }).click()
      await expect(dialog.getByText('Page 2 of 2', { exact: true })).toBeVisible()
      await search.fill('Retired')
      await expect(
        dialog.getByRole('button', { name: 'Use Retired tape', exact: true }),
      ).toBeDisabled()
      await expect(dialog.getByText('Unavailable', { exact: true })).toBeVisible()
      await page.screenshot({
        path: `test-results/profile-picker-${path.replaceAll('/', '-')}-${width}.png`,
        animations: 'disabled',
      })
      const box = (await dialog.boundingBox())!
      expect(box.x).toBeGreaterThanOrEqual(0)
      expect(box.y).toBeGreaterThanOrEqual(0)
      expect(box.x + box.width).toBeLessThanOrEqual(width)
      expect(box.y + box.height).toBeLessThanOrEqual(900)
      await search.press('Escape')
      await expect(dialog).toBeHidden()
      await expect(control).toBeFocused()
      await control.click()
      await dialog.getByRole('button', { name: 'Clear filters', exact: true }).click()
      await dialog.getByRole('combobox', { name: 'Tape width', exact: true }).selectOption('12')
      await expect(dialog.locator('article')).toHaveCount(1)
      await dialog.getByRole('button', { name: 'Clear filters', exact: true }).click()
      await search.fill('Blue label')
      await dialog.getByRole('button', { name: 'Use Blue label tape', exact: true }).focus()
      await page.keyboard.press('Enter')
      await expect(dialog).toBeHidden()
      await expect(control).toHaveJSProperty('value', profiles[1].id)
      await control.scrollIntoViewIfNeeded()
      await page.screenshot({
        path: `test-results/profile-picker-closed-${path.replaceAll('/', '-')}-${width}.png`,
        animations: 'disabled',
      })
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
        width,
      )
    }
    await page.goto('/#/profiles')
    await page
      .getByRole('dialog')
      .filter({ hasText: 'Discard unsaved template changes?' })
      .getByRole('button', { name: 'Confirm', exact: true })
      .click()
    await card.getByRole('button', { name: 'Make available', exact: true }).click()
    await expect(card.getByText('Unavailable', { exact: true })).toBeHidden()
    await page.goto('/#/templates/new')
    await tapeProfileControl(page).click()
    const dialog = page.getByRole('dialog', { name: 'Choose tape profile', exact: true })
    await dialog.getByRole('searchbox').fill('Retired')
    await expect(
      dialog.getByRole('button', { name: 'Use Retired tape', exact: true }),
    ).toBeEnabled()
  })
}
