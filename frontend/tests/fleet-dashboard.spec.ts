import { test, expect } from './fixtures'
import type { APIRequestContext } from '@playwright/test'

async function create(request: APIRequestContext, path: string, data: unknown) {
  const response = await request.post(`/api/${path}`, { data })
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}

async function fleet(request: APIRequestContext) {
  const first = (await (await request.get('/api/printers')).json())[0]
  const second = await create(request, 'printers', {
    name: 'Workshop printer',
    usb_serial: 'UI-WORKSHOP',
  })
  const firstProfile = (await (await request.get('/api/tape-profiles')).json())[0]
  const secondProfile = await create(request, 'tape-profiles', {
    name: 'Black on blue 24 mm',
    width_mm: 24,
    background: '#8acfff',
    auto_print_threshold: 1000,
  })
  const cartridge = await create(request, 'cartridges', {
    name: 'Workshop blue cassette',
    profile_id: secondProfile.id,
    nominal_length_mm: 5000,
  })
  expect(
    (
      await request.put(`/api/printer/active-tape?printer_id=${second.id}`, {
        data: { cartridge_id: cartridge.id },
      })
    ).ok(),
  ).toBeTruthy()
  const group = await create(request, 'printer-groups', {
    name: 'Cable station',
    printer_ids: [first.id, second.id],
  })
  const jobs = []
  for (const [destination, profile, copies, text] of [
    [first.id, firstProfile.id, 2, 'Desk labels'],
    [second.id, secondProfile.id, 3, 'Workshop labels'],
    [group.id, firstProfile.id, 4, 'Group labels'],
  ])
    jobs.push(
      await create(request, 'jobs', {
        destination_id: destination,
        tape_profile: profile,
        copies,
        data: { text },
      }),
    )
  return { first, second, group, jobs }
}

test('fleet overview separates direct and group queues and targets card actions independently', async ({
  page,
  request,
}) => {
  const { first, second, group, jobs } = await fleet(request)
  expect(
    (
      await request.put(`/api/printer/mock?printer_id=${second.id}`, {
        data: { connected: false, tape_width_mm: 24 },
      })
    ).ok(),
  ).toBeTruthy()
  await page.addInitScript((id) => localStorage.setItem('selectedPrinter', id), first.id)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/#/')
  const desk = page.getByRole('article', { name: 'Printer Desk printer', exact: true })
  const workshop = page.getByRole('article', { name: 'Printer Workshop printer', exact: true })
  const station = page.getByRole('article', {
    name: 'Distribution group Cable station',
    exact: true,
  })
  await expect(desk).toBeVisible()
  await expect(workshop).toBeVisible()
  await expect(station).toBeVisible()
  await expect(
    page.getByRole('article', { name: 'Queued labels', exact: true }).locator('strong'),
  ).toHaveText(/9\s*copies/)
  await expect(
    page.getByRole('article', { name: 'Connected printers', exact: true }).locator('strong'),
  ).toHaveText(/1\s*\/\s*2/)
  await expect(desk.locator('dd').first()).toHaveText('2 copies')
  await expect(workshop.locator('dd').first()).toHaveText('3 copies')
  await expect(station.locator('dd').first()).toHaveText('4 copies')
  await expect(desk).toContainText('Yellow cassette 1')
  await expect(desk).toContainText('8.00 m')
  await expect(workshop).toContainText('Workshop blue cassette')
  await expect(workshop).toContainText('5.00 m')
  await expect(
    workshop.getByRole('button', { name: 'Print direct queue', exact: true }),
  ).toBeDisabled()
  await expect(page.getByRole('combobox', { name: 'Design destination', exact: true })).toHaveCount(
    0,
  )
  await page.screenshot({ path: 'test-results/fleet-dashboard-desktop.png', fullPage: true })
  await workshop.getByRole('button', { name: 'Hold automatic printing', exact: true }).click()
  await expect(
    workshop.getByRole('button', { name: 'Resume automatic printing', exact: true }),
  ).toBeVisible()
  await expect(
    desk.getByRole('button', { name: 'Hold automatic printing', exact: true }),
  ).toBeVisible()
  const statuses = await (await request.get('/api/printers/status')).json()
  expect(
    statuses.find((item: { printer_id: string }) => item.printer_id === second.id)
      .automatic_printing_held,
  ).toBe(true)
  expect(
    statuses.find((item: { printer_id: string }) => item.printer_id === first.id)
      .automatic_printing_held,
  ).toBe(false)
  await station.getByRole('button', { name: 'Hold group', exact: true }).click()
  await expect(station.getByRole('button', { name: 'Resume group', exact: true })).toBeVisible()
  await desk.getByRole('button', { name: 'Print direct queue', exact: true }).click()
  await expect
    .poll(async () => (await (await request.get(`/api/jobs/${jobs[0].id}`)).json()).status)
    .toBe('printed')
  expect((await (await request.get(`/api/jobs/${jobs[1].id}`)).json()).status).toBe('queued')
  expect((await (await request.get(`/api/jobs/${jobs[2].id}`)).json()).status).toBe('queued')
  await station.getByRole('link', { name: 'View group queue', exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'Destination', exact: true })).toHaveValue(
    group.id,
  )
  await expect(page.getByText('Group labels', { exact: true })).toBeVisible()
  await expect(page.getByText('Workshop labels', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Print compatible queue now' })).toHaveCount(0)
  await page.reload()
  await expect(page.getByRole('combobox', { name: 'Destination', exact: true })).toHaveValue(
    group.id,
  )
  await page.goto('/#/')
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(workshop).toBeVisible()
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBeLessThanOrEqual(390)
  await page.screenshot({ path: 'test-results/fleet-dashboard-mobile.png', fullPage: true })
  await workshop.getByRole('link', { name: 'Print a label', exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'Print destination', exact: true })).toHaveValue(
    second.id,
  )
})

test('group-only dashboard shows authorized routing without physical printer details', async ({
  page,
  request,
  browser,
  baseURL,
}) => {
  const { group } = await fleet(request)
  async function change(resource: string, payload: unknown) {
    const preview = await create(request, 'admin/access-preview', {
      resource,
      method: 'POST',
      payload,
    })
    const response = await request.post(`/api/admin/${resource}`, {
      data: payload,
      headers: { 'X-Access-Confirmation': preview.confirmation_token },
    })
    expect(response.ok(), await response.text()).toBeTruthy()
    return response.json()
  }
  const role = await change('roles', {
    name: 'Group dashboard requests',
    permissions: [{ kind: 'destination', destination_id: group.id, level: 'request' }],
  })
  await change('users', {
    username: 'groupmember',
    password: 'group-member-password',
    role_ids: [role.id],
  })
  const context = await browser.newContext({
    baseURL,
    storageState: { cookies: [], origins: [] },
    extraHTTPHeaders: {},
  })
  try {
    const member = await context.newPage()
    await member.goto('/#/')
    await member.getByLabel('Username', { exact: true }).fill('groupmember')
    await member.getByLabel('Password', { exact: true }).fill('group-member-password')
    await member.getByRole('button', { name: 'Sign in', exact: true }).click()
    const station = member.getByRole('article', {
      name: 'Distribution group Cable station',
      exact: true,
    })
    await expect(station).toBeVisible()
    await expect(member.getByRole('heading', { name: 'Your printers', exact: true })).toHaveCount(0)
    await expect(member.getByText('Workshop blue cassette', { exact: true })).toHaveCount(0)
    await expect(member.getByText('Yellow cassette 1', { exact: true })).toHaveCount(0)
    await expect(
      member.getByRole('article', { name: 'Connected printers', exact: true }),
    ).toHaveCount(0)
    await expect(member.getByRole('button', { name: 'Hold group', exact: true })).toHaveCount(0)
    await expect(
      member.getByRole('button', { name: 'Print group queue', exact: true }),
    ).toHaveCount(0)
    await expect(member.getByRole('link', { name: 'Configure group', exact: true })).toHaveCount(0)
    await expect(
      member.getByRole('article', { name: 'Queued labels', exact: true }).locator('strong'),
    ).toHaveText(/0\s*copies/)
    await station.getByRole('link', { name: 'Request printing', exact: true }).click()
    await expect(
      member.getByRole('combobox', { name: 'Print destination', exact: true }),
    ).toHaveValue(group.id)
    await member.route('**/api/destinations', async (route) => {
      const response = await route.fetch()
      const destinations = await response.json()
      await route.fulfill({
        response,
        json: destinations.map((target: { id: string }) =>
          target.id === group.id ? { ...target, available: false, capabilities: null } : target,
        ),
      })
    })
    await member.goto('/#/')
    // Install the mocked catalog into a fresh session cache rather than reuse its earlier read.
    await member.reload()
    await expect(station).toContainText('Unavailable')
    await expect(
      station.getByRole('button', { name: 'Request printing', exact: true }),
    ).toBeDisabled()
    await expect(station.getByRole('link', { name: 'Request printing', exact: true })).toHaveCount(
      0,
    )
    await expect(station.getByRole('link', { name: 'View group queue', exact: true })).toBeVisible()
    await page.goto('/#/')
  } finally {
    await context.close()
  }
})

test('review alerts and card controls identify the physical printer with an interrupted batch', async ({
  page,
  request,
}) => {
  const { first, second, jobs } = await fleet(request)
  await expect
    .poll(async () => {
      const response = await request.put(`/api/printer/mock?printer_id=${second.id}`, {
        data: { connected: true, tape_width_mm: 24, fail_after: 0 },
      })
      if (response.status() !== 409) expect(response.ok(), await response.text()).toBeTruthy()
      return response.ok()
    })
    .toBe(true)
  await create(request, `destinations/${second.id}/print`, undefined)
  await expect
    .poll(async () => (await (await request.get(`/api/jobs/${jobs[1].id}`)).json()).status)
    .toBe('needs_review')
  await page.addInitScript((id) => localStorage.setItem('selectedPrinter', id), first.id)
  await page.goto('/#/')
  const workshop = page.getByRole('article', { name: 'Printer Workshop printer', exact: true })
  const desk = page.getByRole('article', { name: 'Printer Desk printer', exact: true })
  await expect(
    workshop.getByRole('link', { name: 'Review interrupted batch', exact: true }),
  ).toBeVisible()
  await expect(
    desk.getByRole('link', { name: 'Review interrupted batch', exact: true }),
  ).toHaveCount(0)
  await expect(
    page.getByRole('article', { name: 'Printers needing review', exact: true }).locator('strong'),
  ).toHaveText(/1\s*printers/)
  await expect(
    workshop.getByRole('button', { name: 'Print direct queue', exact: true }),
  ).toBeDisabled()
  await workshop.getByRole('link', { name: 'Review interrupted batch', exact: true }).click()
  const batch = (await (await request.get('/api/batches')).json()).find(
    (item: { printer_id: string }) => item.printer_id === second.id,
  )
  await expect(page).toHaveURL(new RegExp(`/batches/${batch.id}$`))
})

test('unavailable printer and group cards retain queues without enabling submissions', async ({
  page,
  request,
}) => {
  const { second, group } = await fleet(request)
  await page.route('**/api/destinations', async (route) => {
    const response = await route.fetch()
    const destinations = await response.json()
    await route.fulfill({
      response,
      json: destinations
        .filter((target: { id: string }) => target.id !== second.id)
        .map((target: { id: string }) =>
          target.id === group.id ? { ...target, available: false, capabilities: null } : target,
        ),
    })
  })
  await page.route('**/api/printers', async (route) => {
    const response = await route.fetch()
    const printers = await response.json()
    await route.fulfill({
      response,
      json: printers.map((device: { id: string }) =>
        device.id === second.id
          ? { ...device, configuration_error: 'Configuration needs repair' }
          : device,
      ),
    })
  })
  await page.goto('/#/')
  const workshop = page.getByRole('article', { name: 'Printer Workshop printer', exact: true })
  await expect(workshop).toContainText('Configuration needs repair')
  await expect(workshop.locator('dd').first()).toHaveText('3 copies')
  await expect(workshop).toContainText('Black on blue 24 mm')
  await expect(
    workshop.getByRole('button', { name: 'Print direct queue', exact: true }),
  ).toBeDisabled()
  await expect(workshop.getByRole('link', { name: 'Configure', exact: true })).toBeVisible()
  const station = page.getByRole('article', {
    name: 'Distribution group Cable station',
    exact: true,
  })
  await expect(station).toBeVisible()
  await expect(station).toContainText('Unavailable')
  await expect(station.locator('dd').first()).toHaveText('4 copies')
  await expect(station.getByRole('button', { name: 'Print a label', exact: true })).toBeDisabled()
  await expect(station.getByRole('link', { name: 'Print a label', exact: true })).toHaveCount(0)
  await expect(
    station.getByRole('button', { name: 'Print group queue', exact: true }),
  ).toBeDisabled()
  await expect(station.getByRole('link', { name: 'View group queue', exact: true })).toBeVisible()
  await expect(station.getByRole('link', { name: 'Configure group', exact: true })).toBeVisible()
  await expect(station.getByRole('button', { name: 'Hold group', exact: true })).toBeEnabled()
})
