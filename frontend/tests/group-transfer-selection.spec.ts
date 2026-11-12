import { test, expect } from './fixtures'

test('select labels in a transfer dialog and inspect their historical charge', async ({
  page,
  request,
}) => {
  const [cartridge] = await (await request.get('/api/cartridges')).json()
  expect(
    (
      await request.put(`/api/cartridges/${cartridge.id}/price`, {
        data: { price_minor: 2000, currency: 'EUR' },
      })
    ).ok(),
  ).toBeTruthy()
  const account = await (
    await request.post('/api/accounts/groups', { data: { name: 'Workshop fund' } })
  ).json()
  for (const [text, copies] of [
    ['Eligible workshop labels', 2],
    ['Personal label', 1],
  ] as const) {
    const result = await request.post('/api/jobs', {
      data: { tape_profile: cartridge.profile_id, copies, data: { text } },
    })
    expect(result.ok(), await result.text()).toBeTruthy()
  }
  expect((await request.post('/api/queue/print')).ok()).toBeTruthy()
  await expect
    .poll(async () => (await (await request.get('/api/batches')).json())[0]?.state)
    .toBe('printed')
  await page.goto(`/#/group-accounts?account=${account.id}&section=balances`)
  const opener = page.getByRole('button', { name: 'Transfer previous print costs', exact: true })
  await opener.click()
  const dialog = page.getByRole('dialog', { name: 'Previous print costs', exact: true })
  await expect(dialog.getByRole('checkbox')).toHaveCount(2)
  await expect(
    dialog.getByRole('button', { name: 'Charge group directly', exact: true }),
  ).toBeDisabled()
  await dialog.getByRole('checkbox', { name: 'Eligible workshop labels', exact: true }).check()
  await expect(
    dialog.getByRole('checkbox', { name: 'Personal label', exact: true }),
  ).not.toBeChecked()
  await expect(dialog.getByRole('img')).toHaveCount(2)
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await page.screenshot({
      path: `test-results/group-selection-${width}.png`,
      animations: 'disabled',
    })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
    const buttons = await dialog
      .getByRole('button', { name: /Request transfer|Charge group directly/ })
      .all()
    const a = (await buttons[0]!.boundingBox())!,
      b = (await buttons[1]!.boundingBox())!
    expect(b.x >= a.x + a.width + 8 || b.y >= a.y + a.height + 8).toBeTruthy()
  }
  await dialog.getByRole('button', { name: 'Charge group directly', exact: true }).click()
  await expect(dialog.getByRole('status').filter({ hasText: 'Costs transferred.' })).toBeVisible()
  await expect(
    dialog.getByRole('checkbox', { name: 'Eligible workshop labels', exact: true }),
  ).toBeDisabled()
  await expect(dialog.getByRole('checkbox', { name: 'Personal label', exact: true })).toBeEnabled()
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(dialog).toBeHidden()
  await expect(opener).toBeFocused()
  const charge = page
    .locator('tr')
    .filter({ has: page.getByRole('button', { name: 'View prints', exact: true }) })
  await expect(charge).toContainText('Historical transfer')
  await charge.getByRole('button', { name: 'View prints', exact: true }).click()
  const details = page.getByRole('dialog', { name: 'Charge details', exact: true })
  await expect(details).toContainText('Eligible workshop labels')
  await expect(details).not.toContainText('Personal label')
  await expect(details).toContainText('2 printed')
  await expect
    .poll(() =>
      details
        .locator('.history-thumbnail img')
        .evaluate((img: HTMLImageElement) => img.naturalWidth),
    )
    .toBeGreaterThan(0)
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await page.screenshot({
      path: `test-results/group-charge-${width}.png`,
      animations: 'disabled',
    })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
  }
  await details
    .getByRole('button', { name: 'Enlarge label preview: Eligible workshop labels' })
    .click()
  const enlarged = page.getByRole('dialog', { name: 'Label preview', exact: true })
  await expect(enlarged).toBeVisible()
  await enlarged.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(enlarged).toBeHidden()
  await details.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(details).toBeHidden()
  await expect(charge.getByRole('button', { name: 'View prints', exact: true })).toBeFocused()
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'reduce')
  let fail = true
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/accounts/groups/charges/*/prints', async (route) => {
    if (fail)
      return route.fulfill({ status: 422, json: { detail: 'Print details unavailable. Retry.' } })
    await gate
    await route.continue()
  })
  await charge.getByRole('button', { name: 'View prints', exact: true }).click()
  await expect(details.getByRole('alert')).toContainText('Print details unavailable.')
  fail = false
  await details.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(details.getByRole('status')).toHaveText('Loading prints…')
  await expect(details.getByRole('alert')).toHaveCount(0)
  release()
  await expect(details.getByRole('img')).toBeVisible()
  await expect(details.getByRole('status')).toHaveCount(0)
  await page.screenshot({
    path: 'test-results/group-charge-reduced-motion.png',
    animations: 'disabled',
  })
  await details.getByRole('link', { name: 'View batch', exact: true }).click()
  await expect(page).toHaveURL(/#\/batches\//)
  await expect(details).toBeHidden()
})
