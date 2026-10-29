import { showEditorSettings } from './editor-settings'
import { test, expect } from './fixtures'

test('batch review applies outcomes to selected following uncertain copies before saving', async ({
  page,
  request,
}) => {
  const printer = (await (await request.get('/api/printers')).json())[0]
  const tape = (await (await request.get('/api/tape-profiles')).json())[0]
  const jobResponse = await request.post('/api/jobs', {
    data: {
      destination_id: printer.id,
      tape_profile: tape.id,
      copies: 5,
      data: { text: 'Review copies' },
    },
  })
  expect(jobResponse.status()).toBe(201)
  const job = await jobResponse.json()
  expect(
    (
      await request.put(`/api/printer/mock?printer_id=${printer.id}`, {
        data: { connected: true, tape_width_mm: 24, fail_after: 1 },
      })
    ).ok(),
  ).toBeTruthy()
  expect((await request.post(`/api/destinations/${printer.id}/print`)).status()).toBe(202)
  await expect
    .poll(async () => (await (await request.get(`/api/jobs/${job.id}`)).json()).status)
    .toBe('needs_review')
  const batch = (await (await request.get('/api/batches')).json())[0]
  const items = (await (await request.get(`/api/batches/${batch.id}`)).json()).items
  const previous = await (
    await request.post('/api/cartridges', {
      data: { profile_id: tape.id, name: 'Previous cassette', nominal_length_mm: 8000 },
    })
  ).json()
  // The printer's current assignment can differ from the attempt's saved one.
  await page.route('**/api/printers/status', async (route) => {
    const response = await route.fetch()
    const statuses = await response.json()
    await route.fulfill({
      json: statuses.map((status: object) => ({ ...status, active_cartridge_id: previous.id })),
    })
  })
  await page.goto(`/#/batches/${batch.id}`)
  const cartridge = page.getByRole('combobox', {
    name: 'Cartridge used for this attempt',
    exact: true,
  })
  await expect(cartridge).toHaveValue(batch.cartridge_id)
  await cartridge.selectOption(previous.id)
  await expect(page.getByLabel('Decision for label 1', { exact: true })).toHaveCount(0)
  await expect(page.getByLabel('Select label 1', { exact: true })).toHaveCount(0)
  const save = page.getByRole('button', { name: 'Save review', exact: true })
  await expect(save).toBeDisabled()
  await page
    .getByRole('button', { name: 'Select label 3 and following uncertain labels', exact: true })
    .click()
  await expect(page.getByRole('status', { name: '', exact: true })).toHaveText('3 selected')
  await expect(page.getByLabel('Select label 2', { exact: true })).not.toBeChecked()
  for (const label of [3, 4, 5])
    await expect(page.getByLabel(`Select label ${label}`, { exact: true })).toBeChecked()
  await page.getByLabel('Action for selected copies', { exact: true }).selectOption('printed')
  await page.getByRole('button', { name: 'Apply to selected', exact: true }).click()
  for (const label of [3, 4, 5])
    await expect(page.getByLabel(`Decision for label ${label}`, { exact: true })).toHaveValue(
      'printed',
    )
  await page.getByLabel('Decision for label 4', { exact: true }).selectOption('queued')
  const selectAllTarget = page
    .getByLabel('Select all uncertain copies', { exact: true })
    .locator('..')
  const targetBounds = await selectAllTarget.boundingBox()
  expect(targetBounds!.width).toBeGreaterThanOrEqual(44)
  expect(targetBounds!.height).toBeGreaterThanOrEqual(44)
  await selectAllTarget.click({ position: { x: 2, y: 2 } })
  await expect(page.getByRole('status', { name: '', exact: true })).toHaveText('4 selected')
  await page.getByLabel('Select all uncertain copies', { exact: true }).uncheck()
  await expect(page.getByRole('status', { name: '', exact: true })).toHaveText('0 selected')
  await expect(page.getByRole('button', { name: 'Apply to selected', exact: true })).toBeDisabled()
  await page.getByLabel('Select label 2', { exact: true }).check()
  await page.getByLabel('Action for selected copies', { exact: true }).selectOption('cancelled')
  await page.getByRole('button', { name: 'Apply to selected', exact: true }).click()
  await page.getByLabel('Total tape consumed by this attempt (mm)', { exact: true }).fill('200')
  await expect(save).toBeEnabled()
  // Applying a bulk action edits local decisions; the batch stays uncertain until Save.
  const unsaved = await (await request.get(`/api/batches/${batch.id}`)).json()
  expect(unsaved.items.map((item: { outcome: string }) => item.outcome)).toEqual([
    'printed',
    'needs_review',
    'needs_review',
    'needs_review',
    'needs_review',
  ])
  await page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/batches/${batch.id}`) && response.request().method() === 'GET',
  )
  await expect(page.getByLabel('Decision for label 4', { exact: true })).toHaveValue('queued')
  await expect(page.getByLabel('Select label 2', { exact: true })).toBeChecked()
  await expect(cartridge).toHaveValue(previous.id)
  await page.screenshot({ path: 'test-results/batch-review-selection.png', fullPage: true })
  await page
    .locator('.review-resolution')
    .screenshot({ path: 'test-results/review-cartridge-desktop.png', animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  await page
    .locator('.review-resolution')
    .screenshot({ path: 'test-results/review-cartridge-mobile.png', animations: 'disabled' })
  const review = page.waitForRequest(
    (response) =>
      response.url().endsWith(`/api/batches/${batch.id}/review`) && response.method() === 'POST',
  )
  await save.click()
  expect((await review).postDataJSON()).toEqual({
    decisions: {
      [items[1].copy_id]: 'cancelled',
      [items[2].copy_id]: 'printed',
      [items[3].copy_id]: 'queued',
      [items[4].copy_id]: 'printed',
    },
    consumed_mm: 200,
    cartridge_id: previous.id,
  })
  await expect(save).toHaveCount(0)
  const resolved = await (await request.get(`/api/batches/${batch.id}`)).json()
  expect(resolved.cartridge_id).toBe(previous.id)
  expect((await (await request.get('/api/status')).json()).active_cartridge_id).toBe(
    batch.cartridge_id,
  )
  const inventory = await (await request.get('/api/cartridges')).json()
  expect(inventory.find((c: { id: string }) => c.id === previous.id).remaining_mm).toBe(7800)
  expect(inventory.find((c: { id: string }) => c.id === batch.cartridge_id).remaining_mm).toBe(8000)
  expect(resolved.items.map((item: { outcome: string }) => item.outcome)).toEqual([
    'printed',
    'cancelled',
    'printed',
    'queued',
    'printed',
  ])
})

test('retry after a committed but lost response creates only one job', async ({ page }) => {
  await page.goto('/#/new?template=text')
  await page.getByLabel('Label text', { exact: true }).fill('Lost response')
  let firstKey = ''
  await page.route(
    '**/api/jobs',
    async (route) => {
      firstKey = route.request().headers()['idempotency-key'] ?? ''
      const committed = await route.fetch()
      expect(committed.status()).toBe(201)
      await route.abort('failed')
    },
    { times: 1 },
  )
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  expect(firstKey).not.toBe('')
  const retry = page.waitForRequest(
    (request) => request.url().endsWith('/api/jobs') && request.method() === 'POST',
  )
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  expect((await retry).headers()['idempotency-key']).toBe(firstKey)
  await expect(page).toHaveURL(/#\/queue$/)
  const jobs = await (await page.request.get('/api/jobs')).json()
  expect(jobs).toHaveLength(1)
  await page.goto('/#/new?template=text')
  await page.getByLabel('Label text', { exact: true }).fill('Intentional second job')
  const next = page.waitForRequest(
    (request) => request.url().endsWith('/api/jobs') && request.method() === 'POST',
  )
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  expect((await next).headers()['idempotency-key']).not.toBe(firstKey)
})

test('narrow tape elements fit the production printable band and print', async ({ page }) => {
  const tape = await (
    await page.request.post('/api/tape-profiles', {
      data: { name: 'Narrow tape', width_mm: 3.5, auto_print_threshold: 1 },
    })
  ).json()
  const cartridge = await (
    await page.request.post('/api/cartridges', {
      data: { name: 'Narrow', profile_id: tape.id, nominal_length_mm: 8000 },
    })
  ).json()
  await page.request.put('/api/printer/active-tape', { data: { cartridge_id: cartridge.id } })
  await page.request.put('/api/printer/mock', { data: { tape_width_mm: 3.5, connected: true } })
  await page.goto('/#/templates/new')
  await page.getByLabel('Template name', { exact: true }).fill('Narrow design')
  await page.getByRole('combobox', { name: 'Tape profile', exact: true }).selectOption(tape.id)
  await page.getByRole('button', { name: 'Add text', exact: true }).click()
  await page.getByRole('textbox', { name: 'Content', exact: true }).fill('Narrow')
  await showEditorSettings(page, 'Position & size')
  expect(
    Number(await page.getByLabel('Height (mm)', { exact: true }).inputValue()),
  ).toBeGreaterThan(0)
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page).toHaveURL(/templates\/[^/]+\/edit/)
  const template = page.url().split('/templates/')[1].split('/')[0]
  const response = await page.request.post('/api/jobs', {
    data: { template, tape_profile: tape.id, data: {} },
  })
  expect(response.status()).toBe(201)
  const job = await response.json()
  await expect
    .poll(async () => (await (await page.request.get(`/api/jobs/${job.id}`)).json()).status)
    .toBe('printed')
})
