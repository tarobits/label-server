import { test, expect } from './fixtures'

test('inventory supports renaming, archiving, restoring and confirmed permanent deletion', async ({
  page,
  request,
}) => {
  const [installed] = await (await request.get('/api/cartridges')).json()
  const response = await request.post('/api/cartridges', {
    data: { name: 'Spare roll', profile_id: installed.profile_id, nominal_length_mm: 8000 },
  })
  expect(response.ok()).toBeTruthy()
  const spare = await response.json()
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/#/cartridges')
  const cards = page.locator('.cartridge-card')
  const installedCard = cards.filter({ has: page.getByRole('heading', { name: installed.name }) })
  await expect(installedCard.getByRole('button', { name: 'Archive cartridge' })).toBeDisabled()
  await expect(installedCard.getByRole('button', { name: 'Delete permanently' })).toBeDisabled()
  await expect(
    installedCard.getByRole('button', { name: 'Delete permanently' }),
  ).toHaveAccessibleDescription(
    /Remove this cartridge from the printer before archiving or deleting it/,
  )
  // Renaming remains available even while the cartridge is installed.
  await installedCard.getByRole('button', { name: 'Rename', exact: true }).click()
  const renameInput = page.getByRole('textbox', { name: 'Cartridge name', exact: true })
  await expect(renameInput).toBeFocused()
  await renameInput.fill('Cancelled name')
  await renameInput.press('Escape')
  await expect(renameInput).toHaveCount(0)
  await expect(installedCard.getByRole('heading')).toHaveText(installed.name)

  await cards.filter({ hasText: 'Spare roll' }).getByRole('button', { name: 'Rename' }).click()
  await expect(renameInput).toBeFocused()
  await renameInput.fill('  Renamed spare  ')
  await page.screenshot({
    path: 'test-results/cartridge-rename-desktop.png',
    fullPage: true,
  })
  await page.getByRole('button', { name: 'Save name', exact: true }).click()
  const renamed = cards.filter({
    has: page.getByRole('heading', { name: 'Renamed spare', exact: true }),
  })
  await expect(renamed).toBeVisible()
  await expect(renameInput).toHaveCount(0)

  const dialog = page.getByRole('dialog')
  await renamed.getByRole('button', { name: 'Archive cartridge' }).click()
  await expect(dialog).toContainText('history, usage and costs remain available')
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(dialog).toBeHidden()
  await expect(renamed).toBeVisible()
  await renamed.getByRole('button', { name: 'Archive cartridge' }).click()
  await dialog.getByRole('button', { name: 'Archive cartridge' }).click()
  await expect(renamed).toHaveCount(0)
  const inventory = page.getByRole('combobox', { name: 'Inventory', exact: true })
  await inventory.selectOption('archived')
  await expect(renamed).toBeVisible()
  await expect(renamed.getByRole('button', { name: 'Install cartridge' })).toHaveCount(0)
  await renamed.getByRole('button', { name: 'Rename' }).click()
  await expect(renameInput).toBeFocused()
  await renameInput.fill('Archived spare')
  await page.getByRole('button', { name: 'Save name' }).click()
  const archived = cards.filter({ hasText: 'Archived spare' })
  await expect(archived.getByRole('heading')).toHaveText('Archived spare')
  await page.waitForTimeout(500)
  await page.screenshot({
    path: 'test-results/cartridge-archived-desktop.png',
    fullPage: true,
  })
  await archived.getByRole('button', { name: 'Restore cartridge' }).click()
  await expect(archived).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'No archived cartridges.' })).toBeVisible()
  await inventory.selectOption('active')
  await expect(archived).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.waitForTimeout(500)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.screenshot({
    path: 'test-results/cartridge-active-mobile.png',
    fullPage: true,
  })
  await archived.getByRole('button', { name: 'Delete permanently' }).click()
  await expect(dialog).toContainText('cannot be undone')
  await page.waitForTimeout(500)
  await page.screenshot({ path: 'test-results/cartridge-delete-mobile.png' })
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(dialog).toBeHidden()
  await expect(archived).toBeVisible()
  await archived.getByRole('button', { name: 'Delete permanently' }).click()
  await dialog.getByRole('button', { name: 'Delete permanently' }).click()
  await expect(archived).toHaveCount(0)
  const remaining = await (await request.get('/api/cartridges?include_archived=true')).json()
  expect(remaining.map((cartridge: { id: string }) => cartridge.id)).not.toContain(spare.id)
  await page.reload()
  await expect(cards).toHaveCount(1)

  // A used cartridge remains in history; its restriction is readable without hover.
  expect(
    (
      await request.post('/api/jobs', {
        data: { tape_profile: installed.profile_id, copies: 1, data: { text: 'Recorded usage' } },
      })
    ).ok(),
  ).toBeTruthy()
  expect((await request.post('/api/queue/print')).ok()).toBeTruthy()
  await expect
    .poll(async () => {
      const report = await (await request.get('/api/usage')).json()
      return report.entries.filter((entry: { state: string }) => entry.state === 'printed').length
    })
    .toBe(1)
  expect(
    (await request.put('/api/printer/active-tape', { data: { cartridge_id: null } })).ok(),
  ).toBeTruthy()
  await page.reload()
  await expect(
    installedCard.getByRole('button', { name: 'Delete permanently' }),
  ).toHaveAccessibleDescription('This cartridge has print or queue history. Archive it instead.')
  await expect(
    installedCard.getByText('This cartridge has print or queue history. Archive it instead.', {
      exact: true,
    }),
  ).toBeVisible()
  await page.waitForTimeout(500)
  await page.screenshot({ path: 'test-results/cartridge-used-mobile.png', fullPage: true })
  await page.setViewportSize({ width: 1440, height: 1000 })
  await installedCard.getByRole('button', { name: 'Archive cartridge' }).click()
  await dialog.getByRole('button', { name: 'Archive cartridge' }).click()
  await expect(installedCard).toHaveCount(0)
  await inventory.selectOption('archived')
  await expect(
    installedCard.getByText(
      'Cartridges with print or queue history cannot be permanently deleted.',
      { exact: true },
    ),
  ).toBeVisible()
  await expect(installedCard.getByRole('button', { name: 'Delete permanently' })).toBeDisabled()
  await page.waitForTimeout(500)
  await page.screenshot({
    path: 'test-results/cartridge-used-archived-desktop.png',
    fullPage: true,
  })
})
