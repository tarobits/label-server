import { test, expect } from './fixtures'

test('cartridge actions target the chosen physical printer independently of a design group', async ({
  page,
  request,
}) => {
  const first = (await (await request.get('/api/printers')).json())[0]
  const profile = (await (await request.get('/api/tape-profiles')).json())[0]
  const secondResponse = await request.post('/api/printers', {
    data: { name: 'Workshop printer', usb_serial: 'WORKSHOP-CARTRIDGES' },
  })
  expect(secondResponse.ok()).toBeTruthy()
  const second = await secondResponse.json()
  const cartridgeResponse = await request.post('/api/cartridges', {
    data: { name: 'Workshop cassette', profile_id: profile.id, nominal_length_mm: 8000 },
  })
  expect(cartridgeResponse.ok()).toBeTruthy()
  const cartridge = await cartridgeResponse.json()
  expect(
    (
      await request.put(`/api/printer/active-tape?printer_id=${second.id}`, {
        data: { cartridge_id: cartridge.id },
      })
    ).ok(),
  ).toBeTruthy()
  const groupResponse = await request.post('/api/printer-groups', {
    data: { name: 'Cable station', printer_ids: [first.id, second.id] },
  })
  expect(groupResponse.ok()).toBeTruthy()
  const group = await groupResponse.json()
  await page.addInitScript((id) => localStorage.setItem('selectedPrinter', id), group.id)
  await page.goto('/#/cartridges')
  const picker = page.getByRole('combobox', { name: 'Printer', exact: true })
  await expect(picker).toHaveValue(first.id)
  await expect(picker.locator('option')).toHaveCount(2)
  await expect(page.getByRole('combobox', { name: 'Design destination' })).toHaveCount(0)
  const deskCard = page
    .locator('.cartridge-card')
    .filter({ has: page.getByRole('heading', { name: 'Yellow cassette 1', exact: true }) })
  const workshopCard = page
    .locator('.cartridge-card')
    .filter({ has: page.getByRole('heading', { name: 'Workshop cassette', exact: true }) })
  await expect(deskCard).toContainText('Installed in Desk printer')
  await expect(workshopCard).toContainText('Installed in Workshop printer')
  await expect(
    workshopCard.getByRole('button', { name: 'Install cartridge', exact: true }),
  ).toHaveCount(0)
  await expect(
    workshopCard.getByRole('button', { name: 'Remove from printer', exact: true }),
  ).toHaveCount(0)
  await picker.selectOption(second.id)
  await workshopCard.getByRole('button', { name: 'Remove from printer', exact: true }).click()
  await expect(
    workshopCard.getByRole('button', { name: 'Install cartridge', exact: true }),
  ).toBeVisible()
  let statuses = await (await request.get('/api/printers/status')).json()
  expect(
    statuses.find((s: { printer_id: string }) => s.printer_id === second.id).active_cartridge_id,
  ).toBeNull()
  expect(
    statuses.find((s: { printer_id: string }) => s.printer_id === first.id).active_cartridge_id,
  ).not.toBeNull()
  await expect(
    deskCard.getByRole('button', { name: 'Install cartridge', exact: true }),
  ).toHaveCount(0)
  await workshopCard.getByRole('button', { name: 'Install cartridge', exact: true }).click()
  await expect(workshopCard).toContainText('Installed in Workshop printer')
  statuses = await (await request.get('/api/printers/status')).json()
  expect(
    statuses.find((s: { printer_id: string }) => s.printer_id === second.id).active_cartridge_id,
  ).toBe(cartridge.id)
  expect(await page.evaluate(() => localStorage.getItem('selectedPrinter'))).toBe(group.id)
  await page.goto(`/#/cartridges?printer=${second.id}`)
  await expect(picker).toHaveValue(second.id)
  expect(await page.evaluate(() => localStorage.getItem('selectedPrinter'))).toBe(group.id)
  await expect(page.locator('.sidebar-footer')).toContainText('2 of 2 printers connected')
  await page.goto('/#/queue')
  await expect(page.locator('.sidebar-footer')).toContainText('2 of 2 printers connected')
  await expect(page.locator('.sidebar-footer')).not.toContainText('Workshop printer')
})

test('review locks follow the installed cartridge while a spare and another printer remain usable', async ({
  page,
  request,
}) => {
  const first = (await (await request.get('/api/printers')).json())[0]
  const profile = (await (await request.get('/api/tape-profiles')).json())[0]
  const second = await (
    await request.post('/api/printers', {
      data: { name: 'Workshop printer', usb_serial: 'WORKSHOP-REVIEW' },
    })
  ).json()
  const spare = await (
    await request.post('/api/cartridges', {
      data: { name: 'Spare cassette', profile_id: profile.id, nominal_length_mm: 8000 },
    })
  ).json()
  expect(
    (
      await request.put(`/api/printer/mock?printer_id=${first.id}`, {
        data: { connected: true, tape_width_mm: 24, fail_after: 0 },
      })
    ).ok(),
  ).toBeTruthy()
  const job = await (
    await request.post('/api/jobs', {
      data: { destination_id: first.id, tape_profile: profile.id, data: { text: 'Review this' } },
    })
  ).json()
  expect((await request.post(`/api/destinations/${first.id}/print`)).ok()).toBeTruthy()
  await expect
    .poll(async () => (await (await request.get(`/api/jobs/${job.id}`)).json()).status)
    .toBe('needs_review')
  await page.goto(`/#/cartridges?printer=${second.id}`)
  const deskCard = page
    .locator('.cartridge-card')
    .filter({ has: page.getByRole('heading', { name: 'Yellow cassette 1', exact: true }) })
  const spareCard = page
    .locator('.cartridge-card')
    .filter({ has: page.getByRole('heading', { name: 'Spare cassette', exact: true }) })
  await expect(
    deskCard.getByRole('button', { name: 'Correct estimate', exact: true }),
  ).toBeDisabled()
  await expect(
    spareCard.getByRole('button', { name: 'Correct estimate', exact: true }),
  ).toBeEnabled()
  await spareCard.getByRole('button', { name: 'Install cartridge', exact: true }).click()
  await expect(spareCard).toContainText('Installed in Workshop printer')
  expect(
    (await (await request.get('/api/printers/status')).json()).find(
      (s: { printer_id: string }) => s.printer_id === second.id,
    ).active_cartridge_id,
  ).toBe(spare.id)
  await page.getByRole('combobox', { name: 'Printer', exact: true }).selectOption(first.id)
  await expect(
    deskCard.getByRole('button', { name: 'Remove from printer', exact: true }),
  ).toBeDisabled()
  await expect(
    spareCard.getByRole('button', { name: 'Correct estimate', exact: true }),
  ).toBeEnabled()
})
