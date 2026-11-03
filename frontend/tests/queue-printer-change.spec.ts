import { test, expect } from './fixtures'

for (const width of [1280, 390]) {
  test(`queued printer substitution and activity at ${width}px`, async ({
    page,
    request,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    const printers = await (await request.get('/api/printers')).json()
    const original = printers[0]
    const replacement = await (
      await request.post('/api/printers', {
        data: { name: 'Packing printer', usb_serial: 'UI-PACKING' },
      })
    ).json()
    const profiles = await (await request.get('/api/tape-profiles')).json()
    const response = await request.post('/api/jobs', {
      data: {
        destination_id: original.id,
        tape_profile: profiles[0].id,
        data: { text: 'Change destination' },
        copies: 2,
      },
    })
    expect(response.status()).toBe(201)
    const job = await response.json()
    await page.goto('/#/queue')
    const button = page.getByRole('button', { name: 'Change printer', exact: true })
    await expect(button).toBeDisabled()
    await page.getByRole('checkbox', { name: 'Select Change destination', exact: true }).check()
    await button.click()
    const dialog = page.getByRole('dialog', { name: 'Change printer', exact: true })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Change printer', exact: true })).toBeDisabled()
    await dialog.getByLabel('Replacement printer').selectOption(replacement.id)
    await dialog.getByLabel('Reason (optional)').fill('Original printer is offline')
    await expect(dialog).toHaveCSS('opacity', '1')
    await page.screenshot({
      path: testInfo.outputPath(`change-printer-${width}.png`),
      fullPage: true,
    })
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(dialog).toBeHidden()
    await expect(button).toBeFocused()
    await button.click()
    await dialog.getByLabel('Replacement printer').selectOption(replacement.id)
    await dialog.getByLabel('Reason (optional)').fill('Original printer is offline')
    await dialog.getByRole('button', { name: 'Change printer', exact: true }).click()
    await expect(dialog).toBeHidden()
    await expect
      .poll(async () => (await (await request.get(`/api/jobs/${job.id}`)).json()).destination_id)
      .toBe(replacement.id)
    await page.goto('/#/activity')
    const history = page.getByRole('region', { name: 'Printer changes', exact: true })
    await expect(history.getByText('Desk printer → Packing printer')).toBeVisible()
    await expect(history.getByText('Original printer is offline')).toBeVisible()
    await expect(history.getByText(/owner.*2 copies/)).toBeVisible()
    await history.scrollIntoViewIfNeeded()
    await page.screenshot({
      path: testInfo.outputPath(`printer-history-${width}.png`),
      fullPage: true,
    })
    const entries = await (await request.get('/api/printer-changes/page')).json()
    expect(entries.total).toBe(1)
    expect(entries.items[0].actor.name).toBe('owner')
  })
}
