import { test, expect } from './fixtures'

test('administrators manage scoped notification endpoints without exposing stored tokens', async ({
  page,
  request,
}) => {
  const printers = await (await request.get('/api/printers')).json()
  const groupResponse = await request.post('/api/printer-groups', {
    data: { name: 'Notification station', printer_ids: [printers[0].id] },
  })
  expect(groupResponse.ok()).toBeTruthy()
  const group = await groupResponse.json()
  await page.goto('/#/admin')
  await page.getByRole('button', { name: 'Notification endpoints', exact: true }).click()
  const panel = page.locator('.notification-endpoints')
  await panel.getByRole('button', { name: 'Add notification endpoint', exact: true }).click()
  await expect(panel.getByLabel('Minimum destination access', { exact: true })).toHaveCount(0)
  await expect(panel.getByText('Role filters', { exact: true })).toHaveCount(0)
  await expect(
    panel.getByRole('combobox', { name: 'Priority for General alerts', exact: true }),
  ).toHaveValue('3')
  await expect(
    panel.getByRole('combobox', { name: 'Priority for Empty cartridges', exact: true }),
  ).toHaveValue('4')
  await panel.getByLabel('Endpoint name', { exact: true }).fill('Workshop alerts')
  await panel.getByLabel('ntfy server URL', { exact: true }).fill('https://ntfy.invalid')
  await panel.getByLabel('ntfy topic', { exact: true }).fill('workshop-alerts')
  await panel.getByLabel('Access token', { exact: false }).fill('private-original-token')
  await panel.getByRole('checkbox', { name: 'Enable this endpoint', exact: true }).uncheck()
  await panel
    .getByRole('checkbox', { name: 'Notify for Notification station', exact: true })
    .check()
  await panel.getByRole('checkbox', { name: 'Empty cartridges', exact: true }).check()
  await panel
    .getByRole('combobox', { name: 'Priority for Empty cartridges', exact: true })
    .selectOption('5')
  for (const kind of ['General alerts', 'Pending print requests']) {
    await panel.getByRole('checkbox', { name: kind, exact: true }).uncheck()
  }
  await panel.getByRole('button', { name: 'Save notification endpoint', exact: true }).click()
  await expect(panel.getByText('Notification endpoint saved.', { exact: true })).toBeVisible()
  const endpointsResponse = await request.get('/api/admin/notification-endpoints')
  const raw = await endpointsResponse.text()
  expect(raw).not.toContain('private-original-token')
  const endpoints = JSON.parse(raw)
  expect(endpoints).toHaveLength(1)
  expect(endpoints[0]).toMatchObject({
    name: 'Workshop alerts',
    enabled: false,
    has_token: true,
    destination_ids: [group.id],
    all_printers: false,
    kinds: ['empty_tape'],
    priorities: {
      general: 3,
      empty_tape: 5,
      printer_blocked: 4,
      batch_review: 4,
      tape_waiting: 3,
      approval_digest: 3,
    },
  })
  expect(endpoints[0]).not.toHaveProperty('token')
  expect(endpoints[0]).not.toHaveProperty('minimum_level')
  expect(endpoints[0]).not.toHaveProperty('role_ids')
  await expect(panel.getByText('Token stored', { exact: false })).toBeVisible()

  const submittedTokens: unknown[] = []
  page.on('request', (outgoing) => {
    if (
      outgoing.method() === 'PUT' &&
      outgoing.url().includes('/api/admin/notification-endpoints/')
    ) {
      submittedTokens.push(outgoing.postDataJSON().token)
    }
  })
  await panel.getByRole('button', { name: 'Edit endpoint Workshop alerts', exact: true }).click()
  await expect(panel.getByLabel('Access token', { exact: false })).toHaveValue('')
  await expect(
    panel.getByRole('combobox', { name: 'Priority for Empty cartridges', exact: true }),
  ).toHaveValue('5')
  await expect(
    panel.getByText('Leave blank to keep the stored token.', { exact: true }),
  ).toBeVisible()
  await page.screenshot({
    path: 'test-results/notification-endpoints-desktop.png',
    animations: 'disabled',
  })
  await panel.getByLabel('Endpoint name', { exact: true }).fill('Renamed workshop alerts')
  await panel.getByRole('button', { name: 'Save notification endpoint', exact: true }).click()
  await expect(
    panel.getByRole('button', { name: 'Edit endpoint Renamed workshop alerts', exact: true }),
  ).toBeVisible()
  expect(submittedTokens).toEqual([null])
  expect((await (await request.get('/api/admin/notification-endpoints')).json())[0].has_token).toBe(
    true,
  )

  await panel
    .getByRole('button', { name: 'Edit endpoint Renamed workshop alerts', exact: true })
    .click()
  await panel.getByLabel('Access token', { exact: false }).fill('private-replacement-token')
  await panel.getByRole('button', { name: 'Save notification endpoint', exact: true }).click()
  await expect(
    panel.getByRole('heading', { name: 'Edit notification endpoint', exact: true }),
  ).toHaveCount(0)
  const replaced = await request.get('/api/admin/notification-endpoints')
  expect(await replaced.text()).not.toContain('private-replacement-token')
  expect(submittedTokens).toEqual([null, 'private-replacement-token'])

  await panel
    .getByRole('button', { name: 'Edit endpoint Renamed workshop alerts', exact: true })
    .click()
  await panel.getByRole('checkbox', { name: 'Clear stored token', exact: true }).check()
  await expect(panel.getByLabel('Access token', { exact: false })).toBeDisabled()
  await panel.getByRole('button', { name: 'Save notification endpoint', exact: true }).click()
  await expect(panel.getByText('No token stored', { exact: false })).toBeVisible()
  expect(submittedTokens).toEqual([null, 'private-replacement-token', ''])
  expect((await (await request.get('/api/admin/notification-endpoints')).json())[0].has_token).toBe(
    false,
  )
  await page.setViewportSize({ width: 390, height: 844 })
  await panel
    .getByRole('button', { name: 'Edit endpoint Renamed workshop alerts', exact: true })
    .click()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await page.screenshot({
    path: 'test-results/notification-endpoints-mobile.png',
    animations: 'disabled',
  })
  await panel.getByRole('button', { name: 'Cancel', exact: true }).click()

  await panel
    .getByRole('button', { name: 'Edit endpoint Renamed workshop alerts', exact: true })
    .click()
  await panel
    .getByRole('button', { name: 'Delete endpoint Renamed workshop alerts', exact: true })
    .click()
  await page
    .getByRole('dialog', { name: 'Confirm action', exact: true })
    .getByRole('button', { name: 'Cancel', exact: true })
    .click()
  await expect(
    panel.getByRole('dialog', { name: 'Edit notification endpoint', exact: true }),
  ).toBeVisible()
  await panel
    .getByRole('button', { name: 'Delete endpoint Renamed workshop alerts', exact: true })
    .click()
  await page
    .getByRole('dialog', { name: 'Confirm action', exact: true })
    .getByRole('button', { name: 'Confirm', exact: true })
    .click()
  await expect(
    panel.getByText('No notification endpoints configured.', { exact: true }),
  ).toBeVisible()
  expect(await (await request.get('/api/admin/notification-endpoints')).json()).toEqual([])
})

test('unavailable endpoint filters can be removed before saving', async ({ page, request }) => {
  const printers = await (await request.get('/api/printers')).json()
  const created = await request.post('/api/admin/notification-endpoints', {
    data: {
      name: 'Old filters',
      url: 'https://ntfy.invalid',
      topic: 'old-filters',
      enabled: false,
      destination_ids: [printers[0].id],
      all_printers: false,
      kinds: ['empty_tape'],
    },
  })
  expect(created.ok()).toBeTruthy()
  const endpoint = await created.json()
  let saved: Record<string, unknown> | undefined
  page.on('request', (outgoing) => {
    if (
      outgoing.method() === 'PUT' &&
      outgoing.url().includes('/api/admin/notification-endpoints/')
    ) {
      saved = outgoing.postDataJSON()
    }
  })
  await page.route('**/api/admin/notification-endpoints', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify([
        saved
          ? endpoint
          : {
              ...endpoint,
              destination_ids: [...endpoint.destination_ids, 'removed-printer'],
            },
      ]),
    }),
  )
  await page.goto('/#/admin')
  await page.getByRole('button', { name: 'Notification endpoints', exact: true }).click()
  const panel = page.locator('.notification-endpoints')
  await panel.getByRole('button', { name: 'Edit endpoint Old filters', exact: true }).click()
  await expect(
    panel.getByText('Unavailable destination (removed-printer)', { exact: true }),
  ).toBeVisible()
  await expect(
    panel.getByRole('button', { name: 'Save notification endpoint', exact: true }),
  ).toBeDisabled()
  await panel
    .getByRole('checkbox', { name: 'Remove unavailable destination removed-printer', exact: true })
    .click()
  await expect(
    panel.getByRole('checkbox', {
      name: 'Remove unavailable destination removed-printer',
      exact: true,
    }),
  ).toHaveCount(0)
  await panel.getByRole('button', { name: 'Save notification endpoint', exact: true }).click()
  await expect(panel.getByText('Notification endpoint saved.', { exact: true })).toBeVisible()
  expect(saved?.destination_ids).toEqual([printers[0].id])
  expect(saved).not.toHaveProperty('role_ids')
  expect(saved).not.toHaveProperty('minimum_level')
})

test('printer alert selections clear and priorities disable when the endpoint scope is removed', async ({
  page,
}) => {
  await page.goto('/#/admin')
  await page.getByRole('button', { name: 'Notification endpoints', exact: true }).click()
  const panel = page.locator('.notification-endpoints')
  await panel.getByRole('button', { name: 'Add notification endpoint', exact: true }).click()
  const scoped = ['Empty cartridges', 'Blocked printers', 'Batch reviews', 'Waiting tape reminders']
  for (const kind of scoped) {
    await expect(panel.getByRole('checkbox', { name: kind, exact: true })).toBeDisabled()
    await expect(panel.getByRole('checkbox', { name: kind, exact: true })).not.toBeChecked()
    await expect(
      panel.getByRole('combobox', { name: `Priority for ${kind}`, exact: true }),
    ).toBeDisabled()
  }
  for (const kind of ['General alerts', 'Pending print requests']) {
    await expect(panel.getByRole('checkbox', { name: kind, exact: true })).toBeEnabled()
    await expect(panel.getByRole('checkbox', { name: kind, exact: true })).toBeChecked()
  }
  await panel.getByRole('checkbox', { name: 'Notify for Desk printer', exact: true }).check()
  for (const kind of scoped) {
    await expect(panel.getByRole('checkbox', { name: kind, exact: true })).toBeEnabled()
    await panel.getByRole('checkbox', { name: kind, exact: true }).check()
    await expect(
      panel.getByRole('combobox', { name: `Priority for ${kind}`, exact: true }),
    ).toBeEnabled()
  }
  await panel.getByRole('button', { name: 'Clear selection', exact: true }).click()
  for (const kind of scoped) {
    await expect(panel.getByRole('checkbox', { name: kind, exact: true })).toBeDisabled()
    await expect(panel.getByRole('checkbox', { name: kind, exact: true })).not.toBeChecked()
    await expect(
      panel.getByRole('combobox', { name: `Priority for ${kind}`, exact: true }),
    ).toBeDisabled()
  }
  await panel
    .getByRole('checkbox', { name: 'All current and future printers', exact: true })
    .check()
  await panel.getByRole('checkbox', { name: 'Empty cartridges', exact: true }).check()
  await panel.getByRole('button', { name: 'Select all', exact: true }).click()
  await expect(
    panel.getByRole('checkbox', { name: 'All current and future printers', exact: true }),
  ).not.toBeChecked()
  await expect(
    panel.getByRole('checkbox', { name: 'Notify for Desk printer', exact: true }),
  ).toBeChecked()
  await expect(panel.getByRole('checkbox', { name: 'Empty cartridges', exact: true })).toBeChecked()
})

test('select all snapshots only current physical printers while the explicit all-printers option includes future ones', async ({
  page,
  request,
}) => {
  const printers = await (await request.get('/api/printers')).json()
  const groupResponse = await request.post('/api/printer-groups', {
    data: { name: 'Snapshot station', printer_ids: [printers[0].id] },
  })
  expect(groupResponse.ok()).toBeTruthy()
  const group = await groupResponse.json()
  await page.goto('/#/admin')
  await page.getByRole('button', { name: 'Notification endpoints', exact: true }).click()
  const panel = page.locator('.notification-endpoints')
  await panel.getByRole('button', { name: 'Add notification endpoint', exact: true }).click()
  await panel.getByLabel('Endpoint name', { exact: true }).fill('Snapshot scope')
  await panel.getByLabel('ntfy server URL', { exact: true }).fill('https://ntfy.invalid')
  await panel.getByLabel('ntfy topic', { exact: true }).fill('snapshot-scope')
  await panel.getByRole('checkbox', { name: 'Enable this endpoint', exact: true }).uncheck()
  await panel.getByRole('checkbox', { name: 'Notify for Snapshot station', exact: true }).check()
  await panel.getByRole('button', { name: 'Select all', exact: true }).click()
  await expect(
    panel.getByRole('checkbox', { name: 'All current and future printers', exact: true }),
  ).not.toBeChecked()
  await expect(
    panel.getByRole('checkbox', { name: 'Notify for Desk printer', exact: true }),
  ).toBeChecked()
  await expect(
    panel.getByRole('checkbox', { name: 'Notify for Snapshot station', exact: true }),
  ).not.toBeChecked()
  await panel.getByRole('button', { name: 'Save notification endpoint', exact: true }).click()
  await expect(
    panel.getByRole('button', { name: 'Edit endpoint Snapshot scope', exact: true }),
  ).toBeVisible()
  let saved = (await (await request.get('/api/admin/notification-endpoints')).json())[0]
  expect(saved.all_printers).toBe(false)
  expect(saved.destination_ids).toEqual([printers[0].id])

  const futureResponse = await request.post('/api/printers', {
    data: { name: 'Future printer', usb_serial: 'UI-FUTURE' },
  })
  expect(futureResponse.ok()).toBeTruthy()
  const future = await futureResponse.json()
  expect(
    (
      await request.put(`/api/printer-groups/${group.id}`, {
        data: { name: 'Snapshot station', printer_ids: [printers[0].id, future.id] },
      })
    ).ok(),
  ).toBeTruthy()
  await page.reload()
  await page.getByRole('button', { name: 'Notification endpoints', exact: true }).click()
  await panel.getByRole('button', { name: 'Edit endpoint Snapshot scope', exact: true }).click()
  await expect(
    panel.getByRole('checkbox', { name: 'Notify for Future printer', exact: true }),
  ).not.toBeChecked()
  await expect(
    panel.getByRole('checkbox', { name: 'Notify for Snapshot station', exact: true }),
  ).not.toBeChecked()
  await expect(
    panel.getByRole('checkbox', { name: 'All current and future printers', exact: true }),
  ).not.toBeChecked()
  expect(saved.destination_ids).not.toContain(future.id)
  await panel
    .getByRole('checkbox', { name: 'All current and future printers', exact: true })
    .check()
  await expect(
    panel.getByRole('checkbox', { name: 'Notify for Future printer', exact: true }),
  ).toBeDisabled()
  await panel.getByRole('button', { name: 'Save notification endpoint', exact: true }).click()
  await expect(
    panel.getByRole('button', { name: 'Edit endpoint Snapshot scope', exact: true }),
  ).toBeVisible()
  saved = (await (await request.get('/api/admin/notification-endpoints')).json())[0]
  expect(saved.all_printers).toBe(true)
  expect(saved.destination_ids).toEqual([])
})

test('activity shows independent endpoint delivery states', async ({ page }) => {
  const now = Date.now() / 1000
  await page.route('**/api/notifications', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 'multiple-deliveries',
          title: 'Installed cartridge is empty',
          message: 'Desk printer: Yellow cassette 1 has an estimated 0 mm of tape remaining.',
          created_at: now,
          delivered_at: null,
          cancelled: false,
          attempts: 3,
          last_error: null,
          path: '/#/printers',
          deliveries: [
            {
              endpoint_name: 'Workshop phone',
              attempts: 1,
              delivered_at: now,
              cancelled: false,
              last_error: null,
              next_attempt_at: now,
            },
            {
              endpoint_name: 'Workshop tablet',
              attempts: 2,
              delivered_at: null,
              cancelled: false,
              last_error: 'Server unavailable',
              next_attempt_at: now + 60,
            },
          ],
        },
      ]),
    }),
  )
  await page.goto('/#/activity')
  const deliveries = page.getByRole('list', { name: 'Endpoint deliveries', exact: true })
  await expect(deliveries).toBeVisible()
  const phone = deliveries.getByRole('listitem').filter({ hasText: 'Workshop phone' })
  await expect(phone).toContainText('delivered')
  await expect(phone).toContainText('1 delivery attempts')
  const tablet = deliveries.getByRole('listitem').filter({ hasText: 'Workshop tablet' })
  await expect(tablet).toContainText('retrying')
  await expect(tablet).toContainText('2 delivery attempts')
  await expect(tablet).toContainText('Server unavailable')
})

test('members cannot configure notification endpoints', async ({ request, browser, baseURL }) => {
  const payload = {
    username: 'notification-member',
    password: 'notification-member-password',
    role_ids: ['member'],
  }
  const preview = await request.post('/api/admin/access-preview', {
    data: { resource: 'users', method: 'POST', payload },
  })
  expect(preview.ok()).toBeTruthy()
  const created = await request.post('/api/admin/users', {
    data: payload,
    headers: { 'X-Access-Confirmation': (await preview.json()).confirmation_token },
  })
  expect(created.ok()).toBeTruthy()
  const member = await browser.newContext({
    baseURL,
    storageState: { cookies: [], origins: [] },
    extraHTTPHeaders: {},
  })
  try {
    const login = await member.request.post('/api/auth/login', {
      data: { username: payload.username, password: payload.password },
    })
    expect(login.ok()).toBeTruthy()
    const page = await member.newPage()
    await page.goto('/#/')
    await expect(page.getByRole('link', { name: 'Administration', exact: true })).toHaveCount(0)
    await page.goto('/#/admin')
    await expect(
      page.getByRole('heading', { name: 'Access restricted', exact: true }),
    ).toBeVisible()
    await expect(
      page.getByRole('button', { name: 'Notification endpoints', exact: true }),
    ).toHaveCount(0)
    expect((await member.request.get('/api/admin/notification-endpoints')).status()).toBe(403)
  } finally {
    await member.close()
  }
})
