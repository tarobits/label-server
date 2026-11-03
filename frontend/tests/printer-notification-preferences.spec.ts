import { test, expect } from './fixtures'

for (const transport of ['ntfy', 'email']) {
  test(`administrators save per-printer ${transport} event choices and restore defaults`, async ({
    page,
    request,
  }) => {
    const second = await request.post('/api/printers', {
      data: { name: 'Side printer', usb_serial: 'UI-SIDE' },
    })
    expect(second.ok()).toBeTruthy()
    const printers = await (await request.get('/api/printers')).json()
    const desk = printers.find((printer: { name: string }) => printer.name === 'Desk printer')
    const side = await second.json()
    await page.goto('/#/admin')
    await page.getByRole('button', { name: 'Notification endpoints', exact: true }).click()
    await page.getByRole('button', { name: 'Add notification endpoint', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Endpoint name', { exact: true }).fill('Per-printer alerts')
    await dialog
      .getByRole('combobox', { name: 'Delivery method', exact: true })
      .selectOption(transport)
    if (transport === 'email')
      await dialog.getByLabel('Recipient email', { exact: true }).fill('operations@example.invalid')
    else {
      await dialog.getByLabel('ntfy server URL', { exact: true }).fill('https://ntfy.invalid')
      await dialog.getByLabel('ntfy topic', { exact: true }).fill('printers')
    }
    await dialog
      .getByRole('checkbox', { name: 'All current and future printers', exact: true })
      .check()
    const defaults = dialog.getByRole('group', { name: 'Default event types', exact: true })
    await defaults.getByRole('checkbox', { name: 'Empty cartridges', exact: true }).check()
    const custom = dialog.getByRole('checkbox', {
      name: 'Customize events for Desk printer',
      exact: true,
    })
    await custom.check()
    const events = dialog.getByRole('group', { name: 'Event types for Desk printer', exact: true })
    await events.getByRole('checkbox', { name: 'Empty cartridges', exact: true }).uncheck()
    await events.getByRole('checkbox', { name: 'Batch reviews', exact: true }).check()
    const priority = events.getByRole('combobox', {
      name: 'Priority for Batch reviews on Desk printer',
      exact: true,
    })
    if (transport === 'ntfy') {
      await expect(priority).toHaveValue('')
      await expect(
        events.getByRole('combobox', {
          name: 'Priority for Empty cartridges on Desk printer',
          exact: true,
        }),
      ).toBeDisabled()
      await priority.selectOption('5')
    } else await expect(events.getByRole('combobox')).toHaveCount(0)
    await dialog.getByRole('button', { name: 'Save notification endpoint', exact: true }).click()
    await expect(dialog).toBeHidden()
    let saved = (await (await request.get('/api/admin/notification-endpoints')).json())[0]
    expect(saved.printer_kinds).toEqual({ [desk.id]: ['batch_review'] })
    expect(saved.printer_priorities).toEqual(
      transport === 'ntfy' ? { [desk.id]: { batch_review: 5 } } : {},
    )
    await page
      .getByRole('button', { name: 'Edit endpoint Per-printer alerts', exact: true })
      .click()
    await expect(events.getByRole('checkbox', { name: 'Batch reviews', exact: true })).toBeChecked()
    if (transport === 'ntfy') await expect(priority).toHaveValue('5')
    await events.scrollIntoViewIfNeeded()
    await page.screenshot({
      path: `test-results/printer-events-${transport}-desktop.png`,
      animations: 'disabled',
    })
    await custom.uncheck()
    await expect(events).toBeHidden()
    await page.setViewportSize({ width: 390, height: 844 })
    await dialog
      .getByRole('checkbox', { name: 'Customize events for Side printer', exact: true })
      .check()
    const sideEvents = dialog.getByRole('group', {
      name: 'Event types for Side printer',
      exact: true,
    })
    await sideEvents.getByRole('checkbox', { name: 'Empty cartridges', exact: true }).uncheck()
    await sideEvents.scrollIntoViewIfNeeded()
    await page.screenshot({
      path: `test-results/printer-events-${transport}-mobile.png`,
      animations: 'disabled',
    })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
    await dialog.getByRole('button', { name: 'Save notification endpoint', exact: true }).click()
    await expect(dialog).toBeHidden()
    saved = (await (await request.get('/api/admin/notification-endpoints')).json())[0]
    expect(saved.printer_kinds).toEqual({ [side.id]: [] })
    expect(saved.printer_priorities).toEqual({})
  })
}

test('personal subscriptions retain different event choices for two printers', async ({
  page,
  request,
}) => {
  const second = await request.post('/api/printers', {
    data: { name: 'Side printer', usb_serial: 'UI-SIDE' },
  })
  expect(second.ok()).toBeTruthy()
  const side = await second.json()
  const printers = await (await request.get('/api/printers')).json()
  const desk = printers.find((printer: { name: string }) => printer.name === 'Desk printer')
  const added = await request.put('/api/auth/email', {
    data: { email: 'owner@example.invalid', current_password: 'browser-owner-password' },
  })
  expect(added.status()).toBe(202)
  const messages = await (await request.get('/api/test/emails')).json()
  const token = messages[0].body.match(/token=([^\s]+)/)[1]
  expect((await request.post('/api/auth/email/verify', { data: { token } })).status()).toBe(204)
  await page.goto('/#/account')
  const section = page.getByRole('region', { name: 'Email settings' })
  await section.getByRole('checkbox', { name: 'Receive email notifications', exact: true }).check()
  await section.getByRole('checkbox', { name: 'All printers I can moderate', exact: true }).check()
  for (const [name, event] of [
    ['Desk printer', 'Empty cartridges'],
    ['Side printer', 'Batch reviews'],
  ]) {
    await section
      .getByRole('checkbox', { name: `Customize events for ${name}`, exact: true })
      .check()
    await section
      .getByRole('group', { name: `Event types for ${name}`, exact: true })
      .getByRole('checkbox', { name: event, exact: true })
      .check()
  }
  await section.getByRole('button', { name: 'Save email notifications', exact: true }).click()
  await expect(section.getByRole('status')).toHaveText('Email notifications saved.')
  const saved = (await (await request.get('/api/auth/email')).json()).subscription
  expect(saved.printer_kinds).toEqual({ [desk.id]: ['empty_tape'], [side.id]: ['batch_review'] })
  await page.reload()
  await expect(
    section
      .getByRole('group', { name: 'Event types for Side printer', exact: true })
      .getByRole('checkbox', { name: 'Batch reviews', exact: true }),
  ).toBeChecked()
  await page.setViewportSize({ width: 390, height: 844 })
  const deskEvents = section.getByRole('group', {
    name: 'Event types for Desk printer',
    exact: true,
  })
  await deskEvents.scrollIntoViewIfNeeded()
  await page.screenshot({
    path: 'test-results/personal-printer-events-mobile.png',
    animations: 'disabled',
  })
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await section
    .getByRole('checkbox', { name: 'Customize events for Desk printer', exact: true })
    .uncheck()
  await expect(deskEvents).toBeHidden()
  await section.getByRole('button', { name: 'Save email notifications', exact: true }).click()
  await expect(section.getByRole('status')).toHaveText('Email notifications saved.')
  expect((await (await request.get('/api/auth/email')).json()).subscription.printer_kinds).toEqual({
    [side.id]: ['batch_review'],
  })
})
