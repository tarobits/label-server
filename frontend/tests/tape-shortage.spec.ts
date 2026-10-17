import { test, expect } from './fixtures'

function warning(confirmation: string, remaining = '0.20') {
  return {
    detail: {
      code: 'tape_shortage',
      message: `The selected labels exceed the estimated remaining tape.\nDesk printer · Yellow cassette 1: 3 copies need approximately 1.00 m; approximately ${remaining} m remains. Print anyway?`,
      confirmation,
      shortages: [
        {
          printer_id: 'desk',
          printer_name: 'Desk printer',
          cartridge_id: 'yellow',
          cartridge_name: 'Yellow cassette 1',
          copies: 3,
          estimated_mm: 1000,
          remaining_mm: Number(remaining) * 1000,
        },
      ],
    },
  }
}

test('real remaining-tape warning leaves labels queued until explicitly confirmed', async ({
  page,
  request,
}) => {
  const cartridges = await (await request.get('/api/cartridges')).json()
  const cartridge = cartridges[0]
  expect(
    (
      await request.put(`/api/cartridges/${cartridge.id}/remaining`, {
        data: { remaining_mm: 10 },
      })
    ).ok(),
  ).toBeTruthy()
  const response = await request.post('/api/jobs', {
    data: {
      tape_profile: cartridge.profile_id,
      data: { text: 'Real tape warning' },
      copies: 30,
    },
  })
  expect(response.ok()).toBeTruthy()
  const job = await response.json()
  await page.goto('/#/queue')
  const selected = page.getByRole('checkbox', { name: 'Select Real tape warning', exact: true })
  await selected.check()
  await page.getByRole('button', { name: 'Print selected (30)', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('Desk printer')
  await expect(dialog).toContainText('Yellow cassette 1')
  await expect(dialog).toContainText('0.01 m')
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Print selected (30)', exact: true })).toBeEnabled()
  await expect(selected).toBeChecked()
  const unchanged = await (await request.get(`/api/jobs/${job.id}`)).json()
  expect(unchanged.labels.every((copy: { state: string }) => copy.state === 'queued')).toBe(true)
  expect((await (await request.get('/api/batches')).json()).length).toBe(0)

  await page.getByRole('button', { name: 'Print selected (30)', exact: true }).click()
  await dialog.getByRole('button', { name: 'Print anyway', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Print selected (0)', exact: true })).toBeDisabled()
  await expect
    .poll(async () => {
      const completed = await (await request.get(`/api/jobs/${job.id}`)).json()
      return completed.labels.filter((copy: { state: string }) => copy.state === 'printed').length
    })
    .toBe(30)
})

test('queue shortage can be cancelled without losing selection, then explicitly overridden', async ({
  page,
  request,
}) => {
  const profiles = await (await request.get('/api/tape-profiles')).json()
  const job = await (
    await request.post('/api/jobs', {
      data: { tape_profile: profiles[0].id, data: { text: 'Tape warning' }, copies: 3 },
    })
  ).json()
  const calls: { body: unknown; token?: string }[] = []
  await page.route('**/api/destinations/*/print', async (route) => {
    const token = route.request().headers()['x-tape-shortage-confirmation']
    calls.push({ body: route.request().postDataJSON(), token })
    await route.fulfill({
      status: token === 'first-estimate' ? 200 : 409,
      contentType: 'application/json',
      body: JSON.stringify(token ? { request_id: 'reserved' } : warning('first-estimate')),
    })
  })
  await page.goto('/#/queue')
  const selected = page.getByRole('checkbox', { name: 'Select Tape warning', exact: true })
  await selected.check()
  await page.getByRole('button', { name: 'Print selected (3)', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('need approximately 1.00 m')
  await expect(dialog).toContainText('approximately 0.20 m remains')
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await expect(selected).toBeChecked()
  await expect(page.getByRole('button', { name: 'Print selected (3)', exact: true })).toBeEnabled()
  await expect(page.getByRole('alert')).toHaveCount(0)
  expect(calls).toHaveLength(1)

  await page.getByRole('button', { name: 'Print selected (3)', exact: true }).click()
  await dialog.getByRole('button', { name: 'Print anyway', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Print selected (0)', exact: true })).toBeDisabled()
  expect(calls).toHaveLength(3)
  expect(calls[0]?.body).toEqual({ copy_ids: job.labels.map((copy: { id: string }) => copy.id) })
  expect(calls[1]?.body).toEqual(calls[0]?.body)
  expect(calls[2]?.body).toEqual(calls[0]?.body)
  expect(calls.map((call) => call.token)).toEqual([undefined, undefined, 'first-estimate'])
})

test('a changed estimate requires a fresh confirmation before printing', async ({
  page,
  request,
}) => {
  const profiles = await (await request.get('/api/tape-profiles')).json()
  await request.post('/api/jobs', {
    data: { tape_profile: profiles[0].id, data: { text: 'Changed estimate' }, copies: 3 },
  })
  const tokens: (string | undefined)[] = []
  await page.route('**/api/destinations/*/print', async (route) => {
    const token = route.request().headers()['x-tape-shortage-confirmation']
    tokens.push(token)
    await route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify(token ? warning('new-estimate', '0.10') : warning('old-estimate')),
    })
  })
  await page.goto('/#/queue')
  const selected = page.getByRole('checkbox', { name: 'Select Changed estimate', exact: true })
  await selected.check()
  await page.getByRole('button', { name: 'Print selected (3)', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Print anyway', exact: true }).click()
  await expect(dialog).toContainText('approximately 0.10 m remains')
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Print selected (3)', exact: true })).toBeEnabled()
  await expect(selected).toBeChecked()
  await expect(page.getByRole('alert')).toHaveCount(0)
  expect(tokens).toEqual([undefined, 'old-estimate'])
})

for (const screen of ['overview', 'printers'] as const) {
  test(`${screen} group printing also warns before starting`, async ({ page, request }) => {
    const printers = await (await request.get('/api/printers')).json()
    const group = await (
      await request.post('/api/printer-groups', {
        data: { name: 'Tape warning group', printer_ids: [printers[0].id] },
      })
    ).json()
    const profiles = await (await request.get('/api/tape-profiles')).json()
    await request.post('/api/jobs', {
      data: {
        destination_id: group.id,
        tape_profile: profiles[0].id,
        data: { text: 'Group tape warning' },
        copies: 3,
      },
    })
    const calls: (string | undefined)[] = []
    await page.route(`**/api/destinations/${group.id}/print`, async (route) => {
      expect(route.request().postData()).toBeNull()
      const token = route.request().headers()['x-tape-shortage-confirmation']
      calls.push(token)
      await route.fulfill({
        status: token ? 200 : 409,
        contentType: 'application/json',
        body: JSON.stringify(token ? { request_ids: ['reserved'] } : warning('group-estimate')),
      })
    })
    await page.goto(screen === 'overview' ? '/#/' : '/#/printers')
    await page
      .getByRole('button', {
        name: screen === 'overview' ? 'Print group queue' : 'Print matching queue',
        exact: true,
      })
      .click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('estimated remaining tape')
    await dialog.getByRole('button', { name: 'Print anyway', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    await expect.poll(() => calls).toEqual([undefined, 'group-estimate'])
    await expect(page.getByRole('alert')).toHaveCount(0)
  })
}
