import { showEditorSettings, showEditorTab } from './editor-settings'
import { test, expect } from './fixtures'

test(
  'create tape and cartridge, queue copies, review an interrupted batch, and print the remainder',
  { tag: '@empty-fleet' },
  async ({ page }) => {
    await page.goto('/#/')
    await expect(page.getByRole('heading', { name: 'Add your first printer' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Printer & settings' })).toHaveCount(0)
    await page.getByRole('link', { name: 'Activity', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Activity', exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Add your first printer' })).toHaveCount(0)
    await page.goto('/#/')
    await page.getByRole('link', { name: 'Set up printers' }).click()
    await page.getByRole('button', { name: 'Add printer', exact: true }).click()
    await expect(page.getByRole('option', { name: 'Mock printer', exact: true })).toHaveCount(0)
    await page.getByLabel('Printer name', { exact: true }).fill('Desk printer')
    await page
      .getByRole('combobox', { name: 'Default print resolution', exact: true })
      .selectOption('normal')
    await page.getByLabel('USB serial number', { exact: true }).fill('UI-DESK')
    await page.getByRole('button', { name: 'Register printer', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Desk printer', exact: true })).toBeVisible()
    await page.reload()
    await expect(page.getByRole('heading', { name: 'Desk printer', exact: true })).toBeVisible()
    await page.goto('/#/profiles')
    await page.getByRole('button', { name: 'Add tape profile', exact: true }).click()
    await page.getByLabel('Profile name').fill('Black on Yellow 24 mm')
    await page.getByLabel('Automatic batch threshold').fill('3')
    await page.getByLabel('Tape color', { exact: true }).fill('#ffe17b')
    await page.getByLabel('Remind me when this tape').check()
    await page.getByRole('button', { name: 'Save tape profile' }).click()
    await expect(page.getByRole('heading', { name: 'Black on Yellow 24 mm' })).toBeVisible()
    await page.getByRole('link', { name: 'Cartridges', exact: true }).click()
    await page.getByRole('button', { name: 'Register cartridge', exact: true }).click()
    await page.getByLabel('Cartridge name').fill('Yellow cassette 1')
    await page.locator('form').getByRole('button', { name: 'Register cartridge' }).click()
    await page.getByRole('button', { name: 'Install cartridge' }).click()
    await expect(page.getByText('Installed in Desk printer', { exact: true })).toBeVisible()
    await page.request.put('/api/printer/mock', {
      data: { connected: true, tape_width_mm: 24, fail_after: 1 },
    })
    await page.getByRole('link', { name: 'New label', exact: true }).click()
    await page.getByLabel('Label text').fill('Network cables / Box 03')
    await page.getByLabel('Copies', { exact: true }).fill('3')
    await page.getByRole('button', { name: 'Add to queue' }).click()
    await page.getByRole('link', { name: 'Review batch →', exact: true }).click()
    await expect(page.getByText('Confirmed — no action needed')).toHaveCount(1)
    await expect(page.getByRole('button', { name: 'Save review', exact: true })).toBeDisabled()
    await page.getByLabel('Decision for label 2', { exact: true }).selectOption('queued')
    await page.getByLabel('Decision for label 3', { exact: true }).selectOption('cancelled')
    await page.getByLabel('Total tape consumed by this attempt (mm)').fill('70')
    await page.getByRole('button', { name: 'Save review', exact: true }).click()
    await expect(page.getByText('Tape consumed: 0.07 m.')).toBeVisible()
    await page.getByRole('link', { name: 'Overview', exact: true }).click()
    await page.getByRole('button', { name: 'Print direct queue' }).click()
    await expect(page.getByRole('link', { name: 'Review →', exact: true })).toHaveCount(0)
    await page.getByRole('link', { name: 'Print queue', exact: false }).click()
    await page.getByRole('combobox', { name: 'Job status', exact: true }).selectOption('printed')
    await page.locator('.queue-label-details > summary').click()
    await expect(page.getByText('Network cables / Box 03', { exact: true })).toBeVisible()
    await page.getByRole('link', { name: 'Cartridges', exact: true }).click()
    // Tape usage changes asynchronously in the worker after the print command is accepted.
    await expect(page.getByText('≈ 7.84 m')).toBeVisible({ timeout: 15000 })
  },
)

test('profile editing, custom snooze, silence and resume survive polling', async ({ page }) => {
  await page.request.post('/api/tape-profiles', {
    data: { name: 'Editable tape', width_mm: 24, waiting_notification_enabled: true },
  })
  await page.goto('/#/profiles')
  const card = page.locator('article').filter({ hasText: 'Editable tape' })
  await card.getByRole('button', { name: 'Edit profile' }).click()
  await page.getByLabel('Automatic batch threshold').fill('8')
  await page.getByLabel('Repeat reminder every (hours)').fill('12')
  // Allow a background refresh while editing. It must not overwrite the form.
  await page.waitForTimeout(2700)
  await expect(page.getByLabel('Automatic batch threshold')).toHaveValue('8')
  await page.getByRole('button', { name: 'Save tape profile' }).click()
  await expect(card).toContainText('Prints at 8 copies')
  await expect(card).toContainText('Every 12 h')
  // Queue a waiting episode on another profile through the API for reminder controls.
  const profile = await (
    await page.request.post('/api/tape-profiles', {
      data: {
        name: 'White waiting tape',
        width_mm: 24,
        auto_print_threshold: 1,
        waiting_notification_enabled: true,
      },
    })
  ).json()
  await page.request.post('/api/jobs', {
    data: { tape_profile: profile.id, data: { text: 'Waiting' } },
  })
  // API fixture writes are outside the browser store; reload the newly created catalog.
  await page.reload()
  const waiting = page.locator('article').filter({ hasText: 'White waiting tape' })
  await waiting.getByRole('button', { name: 'Silence episode' }).click()
  await expect(waiting).toContainText('Silenced for this waiting episode.')
  await waiting.getByRole('button', { name: 'Resume', exact: true }).click()
  await expect(waiting).not.toContainText('Silenced for this waiting episode.')
  await waiting.getByRole('button', { name: 'Snooze', exact: true }).click()
  const tomorrow = new Date(Date.now() + 86400000)
  const localDate = new Date(tomorrow.getTime() - tomorrow.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16)
  await page.getByLabel('Snooze until (local time)').fill(localDate)
  await page.getByRole('button', { name: 'Set snooze' }).click()
  await expect(waiting).toContainText('Snoozed until')
})

test('mobile dashboard is usable and server errors do not look like success', async ({ page }) => {
  await page.request.post('/api/tape-profiles', {
    data: { name: 'Mobile tape', width_mm: 24 },
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBeTruthy()
  await page.screenshot({ path: 'test-results/mobile-dashboard.png', fullPage: true })
  await page.getByRole('link', { name: 'New label', exact: true }).click()
  await page.getByLabel('Label text').fill('Test validation error')
  await page.route('**/api/jobs', (route) =>
    route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Simulated save failure' }),
    }),
  )
  await page.getByRole('button', { name: 'Add to queue' }).click()
  await expect(page.getByRole('alert')).toContainText('Simulated save failure')
  await expect(page.getByLabel('Label text')).toHaveValue('Test validation error')
  await expect(page).toHaveURL(/#\/new$/)
})

test('desktop overview renders without console errors', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Your printers' })).toBeVisible()
  await page.screenshot({ path: 'test-results/desktop-dashboard.png', fullPage: true })
  expect(errors).toEqual([])
})

test('visual editor saves text and QR, reopens revisions, and queues without changing old jobs', async ({
  page,
}) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  const profile = await (
    await page.request.post('/api/tape-profiles', { data: { name: 'Editor tape', width_mm: 24 } })
  ).json()
  await page.goto('/#/templates/new')
  await page.getByLabel('Template name', { exact: true }).fill('Asset labels')
  await page.getByRole('combobox', { name: 'Tape profile', exact: true }).selectOption(profile.id)
  await page.getByRole('button', { name: 'Add variable', exact: true }).click()
  await page.getByLabel('Variable name', { exact: true }).fill('asset')
  await page.getByLabel('Field label', { exact: true }).fill('Asset name')
  await page.getByLabel('Sample value', { exact: true }).fill('ASSET-42')
  await page.getByRole('button', { name: 'Add text', exact: true }).click()
  await showEditorSettings(page, 'Position & size')
  await page.getByLabel('X (mm)', { exact: true }).fill('24')
  await showEditorSettings(page, 'Position & size')
  await page.getByLabel('Width (mm)', { exact: true }).fill('34')
  await showEditorSettings(page, 'Position & size')
  await page.getByLabel('Height (mm)', { exact: true }).fill('20')
  await showEditorTab(page, 'Content')
  await page.getByRole('textbox', { name: 'Content', exact: true }).fill('{{asset}}')
  await showEditorSettings(page, 'Spacing & padding')
  await page.getByLabel('Horizontal character spacing (mm)', { exact: true }).fill('0.3')
  await page.getByLabel('Vertical line spacing (mm)', { exact: true }).fill('1.1')
  await page
    .getByRole('combobox', { name: 'Vertical text alignment', exact: true })
    .selectOption('center')
  await page.getByRole('button', { name: 'Add QR code', exact: true }).click()
  await expect(page.getByLabel('QR margin (mm)', { exact: true })).toHaveCount(0)
  await showEditorSettings(page, 'Position & size')
  await page.getByLabel('Scale up to bounding box', { exact: true }).check()
  await page.getByLabel('QR margin (mm)', { exact: true }).fill('0.5')
  await page.getByRole('button', { name: 'Add rectangle', exact: true }).click()
  await page.getByRole('button', { name: 'Undo', exact: true }).click()
  await page.getByRole('button', { name: 'Redo', exact: true }).click()
  await page.getByRole('button', { name: 'Undo', exact: true }).click()
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page).toHaveURL(/templates\/[^/]+\/edit/)
  const id = page.url().split('/templates/')[1].split('/')[0]
  await expect(page.getByText('Revision 1', { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByLabel('Template name', { exact: true })).toHaveValue('Asset labels')
  await page.getByRole('button', { name: '1. text', exact: true }).click()
  await showEditorSettings(page, 'Spacing & padding')
  await expect(page.getByLabel('Horizontal character spacing (mm)', { exact: true })).toHaveValue(
    '0.3',
  )
  await expect(page.getByLabel('Vertical line spacing (mm)', { exact: true })).toHaveValue('1.1')
  await expect(page.getByRole('button', { name: '2. qr', exact: true })).toBeVisible()
  await expect(page.locator('svg image')).toBeVisible()
  await expect(page.getByLabel('Show print pixels', { exact: true })).toBeChecked()
  await page.getByLabel('Show print pixels', { exact: true }).uncheck()
  const smoothPreview = await page.locator('svg image').getAttribute('href')
  await page.getByLabel('Show print pixels', { exact: true }).check()
  await expect(page.locator('svg image')).not.toHaveAttribute('href', smoothPreview!)
  await page.getByLabel('Show print pixels', { exact: true }).uncheck()
  await expect(page.locator('svg image')).toHaveAttribute('href', smoothPreview!)
  await page.screenshot({ path: 'test-results/template-editor.png', fullPage: true })
  await page.goto(`/#/new?template=${id}`)
  await expect(page.getByRole('combobox', { name: 'Tape profile', exact: true })).toHaveValue(
    profile.id,
  )

  await page.getByLabel('Asset name', { exact: true }).fill('ASSET-99')
  await expect(page.getByAltText('Rendered label preview')).toBeVisible()
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  await expect(page).toHaveURL(/#\/queue$/)
  const jobs = await (await page.request.get('/api/jobs')).json()
  const queued = jobs.find((job: { template_id: string }) => job.template_id === id)
  expect(queued.template_snapshot.revision).toBe(1)
  expect(queued.template_snapshot.document.elements[0].vertical_align).toBe('center')
  expect(queued.template_snapshot.document.elements[0].character_spacing).toBe(0.3)
  expect(queued.template_snapshot.document.elements[0].line_spacing).toBe(1.1)
  expect(queued.template_snapshot.document.elements[1].qr_margin_mm).toBe(0.5)
  await page.goto(`/#/templates/${id}/edit`)
  await page.getByLabel('Template name', { exact: true }).fill('Asset labels v2')
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page.getByText('Revision 2', { exact: true })).toBeVisible()
  const old = await (await page.request.get(`/api/jobs/${queued.id}`)).json()
  expect(old.template_snapshot.revision).toBe(1)
  expect(errors).toEqual([])
})

test('automatic hold is visible, persists after reload, and resumes explicitly', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Hold automatic printing', exact: true }).click()
  await page.reload()
  await expect(
    page.getByRole('button', { name: 'Resume automatic printing', exact: true }),
  ).toBeVisible()
  await page.getByRole('link', { name: 'New label', exact: true }).click()
  await expect(
    page.getByText('Automatic printing is held. Print manually or resume to print these copies.', {
      exact: true,
    }),
  ).toBeVisible()
  await page.goto('/')
  await page.getByRole('button', { name: 'Resume automatic printing', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Hold automatic printing', exact: true }),
  ).toBeVisible()
})

test('automatic length and clipping persist while outside objects remain editable', async ({
  page,
}) => {
  await page.goto('/#/templates/new')
  await expect(page.getByLabel('Automatic label length', { exact: true })).toBeChecked()
  await expect(page.getByLabel('Ignore out-of-bounds objects', { exact: true })).toBeChecked()
  await page.getByLabel('Ignore out-of-bounds objects', { exact: true }).uncheck()
  await page.getByLabel('Template name', { exact: true }).fill('Automatic layout')
  await page.getByRole('button', { name: 'Add text', exact: true }).click()
  await page.getByRole('textbox', { name: 'Content', exact: true }).fill('Short')
  await showEditorSettings(page, 'Position & size')
  await page.getByLabel('Fit text box width to content', { exact: true }).check()
  await page.getByLabel('Automatic label length', { exact: true }).check()
  await expect(page.getByLabel('Label length (mm)', { exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Add rectangle', exact: true }).click()
  await showEditorSettings(page, 'Position & size')
  await page.getByLabel('Y (mm)', { exact: true }).fill('23')
  await expect(page.getByRole('alert')).toContainText('outside the printable area')
  await page.getByLabel('Ignore out-of-bounds objects', { exact: true }).check()
  await expect(page.locator('.alert.warning')).toContainText('omitted')
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page).toHaveURL(/templates\/[^/]+\/edit/)
  await page.reload()
  await expect(page.getByLabel('Automatic label length', { exact: true })).toBeChecked()
  await expect(page.getByLabel('Ignore out-of-bounds objects', { exact: true })).toBeChecked()
  await page.getByRole('button', { name: '2. rectangle', exact: true }).click()
  await showEditorSettings(page, 'Position & size')
  await page.getByLabel('Y (mm)', { exact: true }).fill('2')
  await showEditorSettings(page, 'Arrange')
  await page.getByRole('button', { name: 'Delete element', exact: true }).click()
  await expect(page.locator('.alert.warning')).toHaveCount(0)
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page.getByText('Revision 2', { exact: true })).toBeVisible()
  await page.screenshot({ path: 'test-results/automatic-layout.png', fullPage: true })
})

test('CSV runs map columns, preview reordered rows, survive reload and submit once', async ({
  page,
}) => {
  const response = await page.request.post('/api/tape-profiles', {
    data: { name: 'CSV tape', width_mm: 24, auto_print_threshold: 100 },
  })
  const profile = await response.json()
  await page.goto('/#/runs')
  await page.getByLabel('Run name', { exact: true }).fill('Inventory CSV')
  await page.getByRole('combobox', { name: 'Template', exact: true }).selectOption('text')
  await page.getByRole('combobox', { name: 'Tape profile', exact: true }).selectOption(profile.id)

  await page
    .getByLabel('CSV content', { exact: true })
    .fill('Title,Note\n"First, item",Office\nSecond,Garage')
  await page.getByRole('button', { name: 'Read CSV', exact: true }).click()
  await page.getByRole('combobox', { name: 'Label text', exact: true }).selectOption('Title')
  await page.getByLabel('Copies for record 3', { exact: true }).fill('2')
  await page.getByRole('button', { name: 'Move record 3 up', exact: true }).click()
  await page.getByRole('button', { name: 'Validate and preview run', exact: true }).click()
  await expect(page).toHaveURL(/#\/runs\/[^/]+$/)
  const id = page.url().split('/runs/')[1]
  await expect(page.getByAltText('CSV label preview')).toBeVisible()
  await expect(page.getByText('Label 1 of 2 · CSV record 3', { exact: true })).toBeVisible()
  const pixels = page.getByRole('checkbox', { name: 'Show print pixels', exact: true })
  await expect(pixels).toBeChecked()
  await page.getByText('Show print pixels', { exact: true }).click()
  await expect(pixels).not.toBeChecked()
  await pixels.check()
  await page.getByRole('button', { name: 'Next label', exact: true }).click()
  await expect(page.getByText('Label 2 of 2 · CSV record 2', { exact: true })).toBeVisible()
  await expect(page).toHaveURL(/row=2/)
  await page.reload()
  await expect(page.getByText('Label 2 of 2 · CSV record 2', { exact: true })).toBeVisible()
  await expect(page.getByAltText('CSV label preview')).toBeVisible()
  await page.screenshot({ path: 'test-results/csv-run.png', fullPage: true })
  await page.getByRole('button', { name: 'Submit entire run', exact: true }).click()
  await expect(page.getByText('Run submitted.', { exact: false })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('button', { name: 'Submit entire run', exact: true })).toHaveCount(0)
  const submitted = await (await page.request.post(`/api/runs/${id}/submit`)).json()
  expect(submitted.jobs.map((job: { source_row: number }) => job.source_row)).toEqual([3, 2])
  expect(submitted.jobs.map((job: { copies: number }) => job.copies)).toEqual([2, 1])
})

test('queue runs expand, select individual rows, and drafts can be deleted', async ({ page }) => {
  const profile = await (
    await page.request.post('/api/tape-profiles', {
      data: { name: 'Selection tape', width_mm: 24, auto_print_threshold: 1000 },
    })
  ).json()
  const cartridge = await (
    await page.request.post('/api/cartridges', {
      data: { profile_id: profile.id, name: 'Selection cassette', nominal_length_mm: 8000 },
    })
  ).json()
  await page.request.put('/api/printer/active-tape', { data: { cartridge_id: cartridge.id } })
  const body = {
    request_key: 'select-run',
    name: 'Selectable run',
    template: 'text',
    expected_revision: 2,
    tape_profile: profile.id,
    csv_text: 'text\nSelect first\nSelect second',
    mapping: { text: 'text' },
    rows: [
      { source_row: 2, copies: 1 },
      { source_row: 3, copies: 2 },
    ],
  }
  const run = (await (await page.request.post('/api/runs/prepare', { data: body })).json()).run
  const submitted = await (await page.request.post(`/api/runs/${run.id}/submit`)).json()
  await page.goto('/#/queue')
  await page.getByRole('combobox', { name: 'Tape profile', exact: true }).selectOption(profile.id)
  for (const viewport of [
    { width: 1280, height: 720 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport)
    await expect(page.locator('label[for="queue-filter"]')).toContainText('Job status')
    await expect(page.locator('label[for="queue-profile-filter"]')).toContainText('Tape profile')
    const status = (await page.locator('#queue-filter').boundingBox())!
    const tape = (await page.locator('#queue-profile-filter').boundingBox())!
    expect(status.y).toBe(tape.y)
    expect(tape.x).toBeGreaterThan(status.x + status.width)
    await page.screenshot({
      path: `test-results/queue-filters-${viewport.width}.png`,
      fullPage: true,
    })
  }
  await page.setViewportSize({ width: 1280, height: 720 })

  const toggle = page.getByRole('button', { name: 'Toggle Selectable run', exact: true })
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByLabel('Select Select first', { exact: true })).not.toBeVisible()
  await page.getByLabel('Select run Selectable run', { exact: true }).check()
  await expect(page.getByRole('button', { name: 'Print selected (3)', exact: true })).toBeEnabled()
  const columnsBefore = await page
    .locator('.queue-table th')
    .evaluateAll((cells) => cells.map((cell) => cell.getBoundingClientRect().width))
  await toggle.click()
  await page.getByLabel('Select Select first', { exact: true }).uncheck()
  await expect(page.locator('.queue-expand-enter-active')).toHaveCount(0)
  expect(
    await page
      .locator('.queue-table th')
      .evaluateAll((cells) => cells.map((cell) => cell.getBoundingClientRect().width)),
  ).toEqual(columnsBefore)
  const parentBox = await page
    .getByLabel('Select run Selectable run', { exact: true })
    .boundingBox()
  const childBox = await page.getByLabel('Select Select first', { exact: true }).boundingBox()
  expect(childBox!.x).toBeGreaterThan(parentBox!.x)
  const mutationCount = await page.locator('.queue-table').evaluate(async (table) => {
    let count = 0
    const observer = new MutationObserver((records) => {
      count += records.length
    })
    observer.observe(table, {
      subtree: true,
      childList: true,
      attributes: true,
      characterData: true,
    })
    await new Promise((resolve) => setTimeout(resolve, 2800))
    observer.disconnect()
    return count
  })
  expect(mutationCount).toBe(0)
  await expect(page.getByRole('button', { name: 'Print selected (2)', exact: true })).toBeEnabled()
  await page.screenshot({ path: 'test-results/selected-queue.png', fullPage: true })
  await page.getByRole('button', { name: 'Print selected (2)', exact: true }).click()
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/jobs/${submitted.jobs[1].id}`)).json()).status,
    )
    .toBe('printed')
  expect((await (await page.request.get(`/api/jobs/${submitted.jobs[0].id}`)).json()).status).toBe(
    'queued',
  )
  expect((await (await page.request.get('/api/status')).json()).automatic_printing_held).toBe(true)
  await page.getByLabel('Select Select first', { exact: true }).check()
  await page.getByRole('button', { name: 'Remove selected (1)', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/jobs/${submitted.jobs[0].id}`)).json()).status,
    )
    .toBe('cancelled')
  const draft = (
    await (
      await page.request.post('/api/runs/prepare', {
        data: { ...body, request_key: 'delete-draft', name: 'Deletable draft' },
      })
    ).json()
  ).run
  await page.goto(`/#/runs/${draft.id}`)
  await page.getByRole('button', { name: 'Delete draft', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(page).toHaveURL(/#\/runs$/)
  expect((await page.request.get(`/api/runs/${draft.id}`)).status()).toBe(404)
  await page.goto(`/#/runs/${run.id}`)
  await expect(page.getByRole('heading', { name: 'Selectable run', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Delete draft', exact: true })).toHaveCount(0)
})

test('upload a font, select its face and preserve saved labels when hidden', async ({ page }) => {
  await page.goto('/#/fonts')
  await page.getByLabel('Font file').setInputFiles('../app/fonts/NotoSans-Bold.ttf')
  await page.getByRole('button', { name: 'Upload font', exact: true }).click()
  const row = page
    .locator('tr')
    .filter({ has: page.getByRole('button', { name: 'Hide', exact: true }) })
  await expect(row).toContainText('Bold')
  await page.screenshot({ path: 'test-results/fonts-library.png', fullPage: true })
  const fonts = await (await page.request.get('/api/font-assets')).json()
  await page.goto('/#/templates/new')
  await page.getByLabel('Template name', { exact: true }).fill('Uploaded font template')
  await page.getByRole('button', { name: 'Add text', exact: true }).click()
  await showEditorSettings(page, 'Typography')
  await page.getByRole('combobox', { name: 'Font', exact: true }).selectOption(fonts[0].id)
  await expect(page.locator('svg image')).toBeVisible()
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page).toHaveURL(/templates\/[^/]+\/edit/)
  const editorUrl = page.url()
  await page.goto('/#/fonts')
  await row.getByRole('button', { name: 'Hide', exact: true }).click()
  await expect(row).toHaveCount(0)
  await page.goto(editorUrl)
  await page.getByRole('button', { name: '1. text', exact: true }).click()
  await showEditorSettings(page, 'Typography')
  await expect(page.getByRole('combobox', { name: 'Font', exact: true })).toHaveValue(fonts[0].id)
  await expect(page.locator('svg image')).toBeVisible()
  await page.screenshot({ path: 'test-results/uploaded-font-editor.png', fullPage: true })
})

test('image uploads, tonal controls and saved image elements survive hiding', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/#/images')
  await page.getByLabel('Image file').setInputFiles({
    name: 'label-art.svg',
    mimeType: 'image/svg+xml',
    buffer: Buffer.from(
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"><circle cx="25" cy="25" r="22" fill="black"/><rect x="50" width="50" height="50" fill="#999999"/></svg>',
    ),
  })
  await page.getByRole('button', { name: 'Upload image', exact: true }).click()
  await expect(page.getByRole('cell', { name: 'SVG', exact: true })).toBeVisible()
  await page.screenshot({ path: 'test-results/image-library.png', fullPage: true })
  const [asset] = await (await page.request.get('/api/image-assets')).json()
  // Create externally supplied assets before opening the editor's cached catalog.
  const portrait = await (
    await page.request.post('/api/image-assets?name=Portrait', {
      data: '<svg viewBox="0 0 50 100"><rect width="50" height="100"/></svg>',
      headers: { 'Content-Type': 'application/octet-stream' },
    })
  ).json()
  await page.reload()
  await page.goto('/#/templates/new')
  await page.getByLabel('Template name', { exact: true }).fill('Artwork label')
  await page.getByRole('button', { name: 'Add image', exact: true }).click()
  await showEditorTab(page, 'Content')
  await page.getByRole('combobox', { name: 'Image', exact: true }).selectOption(asset.id)
  await showEditorSettings(page, 'Position & size')
  const width = page.getByLabel('Width (mm)', { exact: true })
  const height = page.getByLabel('Height (mm)', { exact: true })
  await expect(width).toHaveValue('16')
  await expect(height).toHaveValue('8')
  await width.fill('24')
  await expect(height).toHaveValue('12')
  await height.fill('10')
  await expect(width).toHaveValue('20')
  const handle = page.locator('svg circle')
  await handle.scrollIntoViewIfNeeded()
  const box = (await handle.boundingBox())!
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2 + 16)
  await page.mouse.up()
  await expect(height).toHaveValue('12')
  await expect(width).toHaveValue('24')
  await showEditorSettings(page, 'Position & size')
  await page.getByLabel('Preserve aspect ratio', { exact: true }).uncheck()
  await width.fill('30')
  await expect(height).toHaveValue('12')
  await showEditorSettings(page, 'Position & size')
  await page.getByLabel('Preserve aspect ratio', { exact: true }).check()
  await expect(width).toHaveValue('24')
  await showEditorTab(page, 'Content')
  await page.getByRole('combobox', { name: 'Image', exact: true }).selectOption(portrait.id)
  await showEditorSettings(page, 'Position & size')
  await expect(width).toHaveValue('6')
  await expect(height).toHaveValue('12')
  await showEditorTab(page, 'Content')
  await page.getByRole('combobox', { name: 'Image', exact: true }).selectOption(asset.id)
  await showEditorSettings(page, 'Position & size')
  await page.getByLabel('Height (mm)', { exact: true }).fill('18')
  await expect(page.locator('svg image')).toBeVisible()
  const threshold = await page.locator('svg image').getAttribute('href')
  await showEditorSettings(page, 'Image adjustments')
  await page.getByRole('combobox', { name: 'Image conversion', exact: true }).selectOption('dither')
  await expect(page.locator('svg image')).not.toHaveAttribute('href', threshold!)
  await page.getByLabel('Brightness', { exact: true }).fill('1.2')
  await page.getByLabel('Contrast', { exact: true }).fill('1.1')
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page).toHaveURL(/templates\/[^/]+\/edit/)
  const url = page.url()
  await page.goto('/#/images')
  await page
    .locator('tr')
    .filter({ hasText: 'label-art.svg' })
    .getByRole('button', { name: 'Hide', exact: true })
    .click()
  await expect(page.getByRole('cell', { name: 'Hidden', exact: true })).toBeVisible()
  await page.goto(url)
  await page.getByRole('button', { name: '1. image', exact: true }).click()
  await showEditorSettings(page, 'Image adjustments')
  await expect(page.getByLabel('Brightness', { exact: true })).toHaveValue('1.2')
  await expect(page.getByLabel('Contrast', { exact: true })).toHaveValue('1.1')
  await expect(page.getByRole('combobox', { name: 'Image conversion', exact: true })).toHaveValue(
    'dither',
  )
  await expect(page.locator('svg image')).toBeVisible()
  await page.screenshot({ path: 'test-results/image-editor.png', fullPage: true })
  expect(errors).toEqual([])
})

test('upload artwork inside the editor and confirm navigation with the themed dialog', async ({
  page,
}) => {
  await page.goto('/#/templates/new')
  await page.getByLabel('Template name', { exact: true }).fill('Inline upload')
  await page.getByRole('button', { name: 'Add image', exact: true }).click()
  await page.getByLabel('Upload image file', { exact: true }).setInputFiles({
    name: 'inline-art.svg',
    mimeType: 'image/svg+xml',
    buffer: Buffer.from('<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="8"/></svg>'),
  })
  await page.getByRole('button', { name: 'Upload and use image', exact: true }).click()
  await expect(
    page.getByRole('combobox', { name: 'Image', exact: true }).locator('option:checked'),
  ).toHaveText('inline-art.svg')
  await expect(page.getByLabel('Width (mm)', { exact: true })).toHaveValue('8')
  await expect(page.getByLabel('Height (mm)', { exact: true })).toHaveValue('8')
  await expect(page.getByLabel('Template name', { exact: true })).toHaveValue('Inline upload')
  await expect(page.locator('svg image')).toBeVisible()
  await page.getByRole('link', { name: 'Images', exact: true }).click()
  const modal = page.getByRole('dialog')
  await expect(modal).toContainText('Discard unsaved template changes?')
  await expect(modal.getByRole('button', { name: 'Cancel', exact: true })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(modal).not.toBeVisible()
  await expect(page).toHaveURL(/templates\/new/)
  await page.getByRole('link', { name: 'Images', exact: true }).click()
  await modal.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page).toHaveURL(/templates\/new/)
  await page.getByRole('link', { name: 'Images', exact: true }).click()
  await page.screenshot({ path: 'test-results/confirmation-dialog.png', animations: 'disabled' })
  await modal.getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(page).toHaveURL(/#\/images$/)
})

test('printer configuration replaces settings and shows device errors', async ({ page }) => {
  await page.route('**/api/printers/status', async (route) => {
    const response = await route.fetch()
    const states = await response.json()
    await route.fulfill({
      json: states.map((state: object) => ({
        ...state,
        printer_error: 'Install supported TZe tape',
      })),
    })
  })
  await page.goto('/#/settings')
  await expect(page).toHaveURL(/#\/printers$/)
  await expect(page.getByRole('heading', { name: 'Mock printer controls' })).toHaveCount(0)
  await expect(page.getByText('Install supported TZe tape')).toBeVisible()
  await page.getByRole('button', { name: 'Configure', exact: true }).click()
  await expect(page.getByLabel('Printer name', { exact: true })).toHaveValue('Desk printer')
  await expect(page.getByLabel('USB serial number', { exact: true })).toHaveValue('UI-DESK')
  await page.getByLabel('Printer name', { exact: true }).fill('Label station')
  await page.screenshot({ path: 'test-results/printer-configuration.png', fullPage: true })
  await page.getByRole('button', { name: 'Save printer', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Label station', exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Label station', exact: true })).toBeVisible()
})

test('built-in text preview fits the configured printable tape width', async ({ page }) => {
  const profile = await (
    await page.request.post('/api/tape-profiles', {
      data: { name: 'Physical preview tape', width_mm: 24 },
    })
  ).json()
  const band = (128 * 25.4) / 180
  await page.route('**/api/printers', async (route) => {
    const response = await route.fetch()
    const printers = await response.json()
    printers[0].capabilities.printable_widths_mm = { '24': band }
    await route.fulfill({ json: printers })
  })
  await page.goto('/#/new?template=text')
  await page.getByRole('combobox', { name: 'Tape profile', exact: true }).selectOption(profile.id)

  const rendered = page.waitForRequest(
    (request) =>
      request.url().endsWith('/api/preview') &&
      request.postDataJSON()?.data?.text === 'Printable band',
  )
  await page.getByLabel('Label text').fill('Printable band')
  const document = (await rendered).postDataJSON().document
  expect(document.elements[0].y).toBeCloseTo((24 - band) / 2)
  expect(document.elements[0].height).toBeCloseTo(band)
  await expect(page.getByRole('button', { name: 'Add to queue' })).toBeEnabled()
})

test('rectangular print pixels keep the physical label aspect ratio on screen', async ({
  page,
}) => {
  await page.request.post('/api/tape-profiles', {
    data: { name: 'Resolution preview', width_mm: 24 },
  })
  await page.route('**/api/preview', async (route) => {
    const response = await route.fetch()
    if (!response.ok()) {
      await route.fulfill({ response })
      return
    }
    const preview = await response.json()
    const png =
      'data:image/svg+xml,' +
      encodeURIComponent(
        `<svg xmlns="http://www.w3.org/2000/svg" width="${preview.pixel_width * 2}" height="${preview.pixel_height}"><rect width="100%" height="100%" fill="white"/></svg>`,
      )
    await route.fulfill({ json: { ...preview, png, design_png: png } })
  })
  await page.goto('/#/new?template=text')
  const preview = page.getByAltText('Rendered label preview')
  await page.getByLabel('Label text').fill('High resolution')
  await expect(page.getByLabel('Show print pixels', { exact: true })).toBeChecked()
  await expect(preview).toBeVisible()
  for (const pixels of [false, true]) {
    await page.getByLabel('Show print pixels', { exact: true }).setChecked(pixels)
    const bounds = await preview.boundingBox()
    expect(bounds!.width / bounds!.height).toBeCloseTo(60 / 24, 1)
  }
})

test('template resolution, text padding, rulers and object bounds work together', async ({
  page,
}) => {
  await page.goto('/#/templates/new')
  await expect(page.getByLabel('Show print pixels', { exact: true })).toBeChecked()
  await page.getByLabel('Template name', { exact: true }).fill('Measured high-resolution template')
  await page.getByLabel('Automatic label length', { exact: true }).uncheck()
  await page.getByRole('combobox', { name: 'Print resolution', exact: true }).selectOption('high')
  await page.getByRole('button', { name: 'Add text', exact: true }).click()
  await showEditorSettings(page, 'Spacing & padding')
  for (const [side, value] of [
    ['Top', '1'],
    ['Right', '2'],
    ['Bottom', '0.7'],
    ['Left', '3'],
  ]) {
    await page.getByLabel(`${side} padding (mm)`, { exact: true }).fill(value)
  }
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page).toHaveURL(/templates\/[^/]+\/edit/)
  const id = page.url().split('/templates/')[1].split('/')[0]
  const saved = await (await page.request.get(`/api/templates/${id}`)).json()
  expect(saved.document.print_resolution).toBe('high')
  expect(saved.document.elements[0].padding_left).toBe(3)
  const rendered = await (
    await page.request.post('/api/preview', { data: { template_id: id } })
  ).json()
  expect(rendered.pixel_width).toBe(850)
  expect(rendered.svg).not.toContain('object-boundary')
  await page.reload()
  await expect(page.getByRole('combobox', { name: 'Print resolution', exact: true })).toHaveValue(
    'high',
  )
  await page.getByRole('button', { name: '1. text', exact: true }).click()
  await showEditorSettings(page, 'Spacing & padding')
  await expect(page.getByLabel('Left padding (mm)', { exact: true })).toHaveValue('3')
  await expect(page.getByLabel('Bottom padding (mm)', { exact: true })).toHaveValue('0.7')
  const paddingBoxes = await page.locator('.text-padding input').evaluateAll((nodes) =>
    nodes.map((node) => ({
      y: node.getBoundingClientRect().y,
      width: node.getBoundingClientRect().width,
    })),
  )
  expect(paddingBoxes[0].y).toBe(paddingBoxes[1].y)
  expect(paddingBoxes[2].y).toBe(paddingBoxes[3].y)
  expect(paddingBoxes.every((box) => Math.abs(box.width - paddingBoxes[0].width) < 1)).toBeTruthy()
  const settings = await page
    .locator('.editor-settings-fields input, .editor-settings-fields select')
    .evaluateAll((nodes) => nodes.map((node) => node.getBoundingClientRect().y))
  expect(new Set(settings).size).toBe(1)

  const canvas = page.getByRole('img', { name: 'Label design canvas', exact: true })
  await expect(page.getByRole('img', { name: 'Top ruler (mm)', exact: true })).toBeVisible()
  await expect(page.getByRole('img', { name: 'Left ruler (mm)', exact: true })).toBeVisible()
  await expect(page.locator('.editor-ruler-top .ruler-selection')).toHaveAttribute('width', '240')
  await showEditorSettings(page, 'Position & size')
  await page.getByRole('combobox', { name: 'Rotation', exact: true }).selectOption('90')
  await expect(page.locator('.editor-ruler-top .ruler-selection')).toHaveAttribute('width', '64')
  await page.getByRole('combobox', { name: 'Rotation', exact: true }).selectOption('0')
  await canvas.click({ position: { x: 58 * 8, y: 22 * 8 } })
  await expect(page.locator('.object-boundary')).toHaveAttribute('stroke-dasharray', '4 3')
  await expect(page.locator('.object-boundary')).toHaveAttribute('stroke', '#64748b')
  await page.getByLabel('Object boundaries', { exact: true }).uncheck()
  await expect(page.locator('.object-boundary')).toHaveAttribute('stroke', 'transparent')
  await page.getByLabel('Object boundaries', { exact: true }).check()
  for (const zoom of [100, 200]) {
    await page.getByLabel('Zoom', { exact: true }).evaluate((node, value) => {
      ;(node as HTMLInputElement).value = String(value)
      node.dispatchEvent(new Event('input', { bubbles: true }))
    }, zoom)
    await expect(canvas).toHaveAttribute('width', String((60 * 8 * zoom) / 100))
    await canvas.scrollIntoViewIfNeeded()
    await page.locator('.editor-canvas-scroll').evaluate((node) => {
      node.scrollLeft = 50
    })
    const box = (await canvas.boundingBox())!
    const scale = box.width / 60
    await page.mouse.move(box.x + 10 * scale, box.y + 6 * scale)
    await expect(page.locator('.canvas-cursor-guides')).toBeVisible()
    await expect(page.locator('.editor-ruler-top .ruler-cursor')).toHaveAttribute(
      'x1',
      String(10 * scale),
    )
    await expect(page.locator('.editor-ruler-left .ruler-cursor')).toHaveAttribute(
      'y1',
      String(6 * scale),
    )
  }
  for (const label of ['Grid', 'Rulers', 'Cursor guides']) {
    await expect(page.getByRole('checkbox', { name: label, exact: true })).toHaveCount(0)
  }
  await expect(page.locator('.editor-ruler')).toHaveCount(2)
  await expect(page.locator('rect[fill="url(#editor-grid)"]')).toBeVisible()
  await page.getByLabel('Zoom', { exact: true }).evaluate((node) => {
    ;(node as HTMLInputElement).value = '100'
    node.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await page.locator('.editor-canvas-scroll').evaluate((node) => {
    node.scrollLeft = 0
  })
  await page.getByRole('button', { name: '1. text', exact: true }).click()
  await expect(page.locator('svg image')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save template', exact: true })).toBeEnabled()
  const workspace = (await page.locator('.editor-workspace').boundingBox())!
  const properties = (await page.locator('.editor-properties').boundingBox())!
  expect(properties.x).toBeGreaterThanOrEqual(workspace.x + workspace.width)
  expect(properties.y).toBe(workspace.y)
  await expect(page.getByRole('group', { name: 'Add elements' }).locator('svg')).toHaveCount(5)
  const heights = await page
    .locator('.editor-layout input[type=number]:visible, .editor-layout select:visible')
    .evaluateAll((nodes) => nodes.map((node) => node.getBoundingClientRect().height))
  expect(heights.every((height) => height === 42)).toBeTruthy()
  await page.screenshot({ path: 'test-results/editor-rulers-padding.png', fullPage: true })
  await showEditorTab(page, 'Style')
  const spacing = page.getByRole('button', { name: 'Spacing & padding', exact: true })
  await expect(spacing).toHaveAttribute('aria-expanded', 'false')
  await spacing.focus()
  await page.keyboard.press('Enter')
  await expect(spacing).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByLabel('Left padding (mm)', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Left padding (mm)', { exact: true })).toHaveValue('3')
  await spacing.click()
  await expect(page.getByLabel('Left padding (mm)', { exact: true })).toBeHidden()
  await page.setViewportSize({ width: 390, height: 844 })
  await spacing.click()
  await expect(page.getByLabel('Left padding (mm)', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  const sectionId = await spacing.getAttribute('aria-controls')
  await expect(page.locator(`[id="${sectionId}"]`)).toHaveCSS('opacity', '1')
  await page.screenshot({ path: 'test-results/editor-mobile-properties.png', fullPage: true })
})

test('image library previews, renames and confirms permanent deletion', async ({ page }) => {
  await page.goto('/#/images')
  await page.getByLabel('Image file').setInputFiles({
    name: 'library-preview.svg',
    mimeType: 'image/svg+xml',
    buffer: Buffer.from(
      '<svg viewBox="0 0 120 60"><circle cx="30" cy="30" r="25" fill="#6366f1"/><path d="M65 5H115V55H65Z" fill="#22c55e"/></svg>',
    ),
  })
  await page.getByRole('button', { name: 'Upload image', exact: true }).click()
  let row = page.locator('tr').filter({
    has: page.getByRole('button', { name: 'Preview library-preview.svg', exact: true }),
  })
  await expect(row).toBeVisible()
  await expect
    .poll(() => row.locator('img').evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0)
  await row.getByRole('button', { name: 'Preview library-preview.svg', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'library-preview.svg', exact: true })
  await expect(dialog).toBeVisible()
  await expect
    .poll(() => dialog.locator('img').evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0)
  await page.screenshot({ path: 'test-results/image-library-preview.png', fullPage: true })
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await row.getByRole('button', { name: 'Rename', exact: true }).click()
  await expect(row.getByRole('textbox', { name: 'Image name', exact: true })).toBeFocused()
  await row.getByRole('textbox', { name: 'Image name', exact: true }).fill('Changed but cancelled')
  await row.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(row).toContainText('library-preview.svg')
  await row.getByRole('button', { name: 'Rename', exact: true }).click()
  await row
    .getByRole('textbox', { name: 'Image name', exact: true })
    .fill('Renamed library artwork')
  await row.getByRole('button', { name: 'Save name', exact: true }).click()
  row = page.locator('tr').filter({ hasText: 'Renamed library artwork' })
  await expect(row.getByRole('button', { name: 'Rename', exact: true })).toBeEnabled()
  await page.reload()
  await expect(row).toBeVisible()
  await page.screenshot({ path: 'test-results/image-library-management.png', fullPage: true })
  const assets = await (await page.request.get('/api/image-assets')).json()
  const asset = assets.find((item: { name: string }) => item.name === 'Renamed library artwork')
  await row.getByRole('button', { name: 'Delete', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(row).toBeVisible()
  await row.getByRole('button', { name: 'Delete', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(row).toHaveCount(0)
  expect((await page.request.get(`/api/image-assets/${asset.id}/preview`)).status()).toBe(404)
})

test('distance holders follow text and selection URLs survive refresh', async ({ page }) => {
  const profile = await (
    await page.request.post('/api/tape-profiles', { data: { name: 'URL tape', width_mm: 24 } })
  ).json()
  const template = await (
    await page.request.post('/api/templates', {
      data: {
        name: 'ZZ Cable distances',
        document: {
          auto_length: true,
          elements: [
            {
              id: 'source',
              kind: 'text',
              x: 2,
              y: 4,
              width: 20,
              height: 8,
              content: 'Source',
              auto_width: true,
            },
            { id: 'divider', kind: 'rectangle', x: 28, y: 3, width: 1, height: 14 },
            {
              id: 'destination',
              kind: 'text',
              x: 32,
              y: 4,
              width: 20,
              height: 8,
              content: 'Destination',
              auto_width: true,
            },
          ],
        },
      },
    })
  ).json()
  await page.goto(`/#/templates/${template.id}/edit?element=divider`)
  await expect(page.getByRole('button', { name: '2. rectangle', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  await showEditorSettings(page, 'Distance holder')
  await page.getByRole('combobox', { name: 'Follow element', exact: true }).selectOption('source')
  await page.getByLabel('Gap (mm)', { exact: true }).fill('3')
  await showEditorSettings(page, 'Position & size')
  await expect(page.getByLabel('X (mm)', { exact: true })).toBeDisabled()
  await page.getByRole('button', { name: '3. text', exact: true }).click()
  await page.getByRole('combobox', { name: 'Follow element', exact: true }).selectOption('divider')
  await page.getByLabel('Gap (mm)', { exact: true }).fill('3')
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await page.reload()
  await expect(page.getByRole('button', { name: '3. text', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  await showEditorSettings(page, 'Position & size')
  await expect(page.getByLabel('X (mm)', { exact: true })).toBeDisabled()
  await page.getByRole('button', { name: '1. text', exact: true }).click()
  await showEditorTab(page, 'Content')
  await page.getByRole('textbox', { name: 'Content', exact: true }).fill('Longer cable source')
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  const saved = await (await page.request.get(`/api/templates/${template.id}`)).json()
  const preview = await (
    await page.request.post('/api/preview', { data: { template_id: template.id } })
  ).json()
  const [left, divider, right] = preview.resolved_elements
  expect(divider.x - left.x - left.width).toBeCloseTo(3)
  expect(right.x - divider.x - divider.width).toBeCloseTo(3)
  expect(saved.document.elements[2].distance_holder.element_id).toBe('divider')
  await page.screenshot({ path: 'test-results/cable-distance-holders.png', fullPage: true })
  await page.goto('/#/new')
  await page.getByRole('combobox', { name: 'Template', exact: true }).selectOption(template.id)
  await page.getByRole('combobox', { name: 'Tape profile', exact: true }).selectOption(profile.id)
  await expect(page).toHaveURL(new RegExp(`profile=${profile.id}`))
  await page.reload()
  await expect(page.getByRole('combobox', { name: 'Template', exact: true })).toHaveValue(
    template.id,
  )
  await expect(page.getByRole('combobox', { name: 'Tape profile', exact: true })).toHaveValue(
    profile.id,
  )
  await page.goto('/#/runs')
  await page.getByRole('combobox', { name: 'Template', exact: true }).selectOption(template.id)
  await page.getByRole('combobox', { name: 'Tape profile', exact: true }).selectOption(profile.id)
  await expect(page).toHaveURL(new RegExp(`profile=${profile.id}`))
  await page.reload()
  await expect(page.getByRole('combobox', { name: 'Template', exact: true })).toHaveValue(
    template.id,
  )
  await expect(page.getByRole('combobox', { name: 'Tape profile', exact: true })).toHaveValue(
    profile.id,
  )
})

test('rotated objects drag and resize with the opposite corner fixed', async ({ page }) => {
  const template = await (
    await page.request.post('/api/templates', {
      data: {
        name: 'Rotated geometry',
        document: {
          length_mm: 90,
          elements: [{ id: 'box', kind: 'rectangle', x: 30, y: 8, width: 8, height: 4 }],
        },
      },
    })
  ).json()
  await page.goto(`/#/templates/${template.id}/edit?element=box`)
  for (const rotation of [90, 180, 270, 0]) {
    await showEditorSettings(page, 'Position & size')
    await page.getByLabel('X (mm)', { exact: true }).fill('30')
    await showEditorSettings(page, 'Position & size')
    await page.getByLabel('Y (mm)', { exact: true }).fill('8')
    await showEditorSettings(page, 'Position & size')
    await page.getByLabel('Width (mm)', { exact: true }).fill('8')
    await showEditorSettings(page, 'Position & size')
    await page.getByLabel('Height (mm)', { exact: true }).fill('4')
    await page
      .getByRole('combobox', { name: 'Rotation', exact: true })
      .selectOption(String(rotation))
    const handle = page.locator('.editor-canvas circle')
    await handle.scrollIntoViewIfNeeded()
    const corner = () =>
      page.locator('.object-boundary').evaluate((node) => {
        const rect = node as SVGRectElement
        // Measure within the label so page layout shifts do not look like
        // movement of the opposite corner during a resize.
        const point = new DOMPoint(rect.x.baseVal.value, rect.y.baseVal.value).matrixTransform(
          rect.getCTM()!,
        )
        return { x: point.x, y: point.y }
      })
    const fixed = await corner()
    const box = (await handle.boundingBox())!
    const angle = (rotation * Math.PI) / 180
    const dx = 16 * Math.cos(angle) - 8 * Math.sin(angle)
    const dy = 16 * Math.sin(angle) + 8 * Math.cos(angle)
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.down()
    await page.mouse.move(box.x + box.width / 2 + dx, box.y + box.height / 2 + dy)
    await page.mouse.up()
    await expect(page.getByLabel('Width (mm)', { exact: true })).toHaveValue('10')
    await expect(page.getByLabel('Height (mm)', { exact: true })).toHaveValue('5')
    const after = await corner()
    expect(after.x).toBeCloseTo(fixed.x, 1)
    expect(after.y).toBeCloseTo(fixed.y, 1)
    const x = Number(await page.getByLabel('X (mm)', { exact: true }).inputValue())
    const y = Number(await page.getByLabel('Y (mm)', { exact: true }).inputValue())
    const bounds = (await page.locator('.object-boundary').boundingBox())!
    await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2)
    await page.mouse.down()
    await page.mouse.move(bounds.x + bounds.width / 2 + 16, bounds.y + bounds.height / 2 + 8)
    await page.mouse.up()
    await expect(page.getByLabel('X (mm)', { exact: true })).toHaveValue(String(x + 2))
    await expect(page.getByLabel('Y (mm)', { exact: true })).toHaveValue(String(y + 1))
  }
})

test('printed batch history shows saved pixels and an enlarged preview', async ({ page }) => {
  const profile = await (
    await page.request.post('/api/tape-profiles', {
      data: { name: 'History preview tape', width_mm: 24, auto_print_threshold: 1 },
    })
  ).json()
  const cartridge = await (
    await page.request.post('/api/cartridges', {
      data: { profile_id: profile.id, name: 'History preview cassette', nominal_length_mm: 8000 },
    })
  ).json()
  await page.request.put('/api/printer/active-tape', { data: { cartridge_id: cartridge.id } })
  await page.request.put('/api/printer/automatic-printing', { data: { held: false } })
  const document = {
    print_resolution: 'high',
    width_mm: 24,
    length_mm: 60,
    elements: [
      {
        id: 'title',
        kind: 'text',
        x: 2,
        y: 4,
        width: 56,
        height: 16,
        font_size: 6,
        content: 'History preview',
      },
    ],
  }
  const template = await (
    await page.request.post('/api/templates', {
      data: { name: 'History template', document },
    })
  ).json()
  const job = await (
    await page.request.post('/api/jobs', {
      data: { template: template.id, tape_profile: profile.id, data: {}, copies: 2 },
    })
  ).json()
  await expect
    .poll(async () => (await (await page.request.get(`/api/jobs/${job.id}`)).json()).status)
    .toBe('printed')
  document.elements[0]!.content = 'Changed after printing'
  await page.request.put(`/api/templates/${template.id}`, {
    data: { name: 'Changed template', document, expected_revision: 1 },
  })
  await page.goto('/#/activity')
  await page
    .locator('.list-row')
    .filter({ hasText: 'History preview cassette' })
    .getByRole('link', { name: 'Details →' })
    .click()
  const thumbnails = page.locator('.history-thumbnail img')
  await expect(thumbnails).toHaveCount(2)
  await expect
    .poll(() => thumbnails.first().evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBe(850)
  const box = (await thumbnails.first().boundingBox())!
  expect(box.width / box.height).toBeCloseTo(60 / 24, 1)
  await page
    .getByRole('button', { name: 'Enlarge label preview: Label', exact: true })
    .first()
    .click()
  const dialog = page.getByRole('dialog', { name: 'Label preview', exact: true })
  await expect(dialog).toBeVisible()
  await expect
    .poll(() => dialog.locator('img').evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBe(850)
  await page.screenshot({ path: 'test-results/history-label-preview.png', fullPage: true })
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Enlarge label preview: Label', exact: true }).first(),
  ).toBeFocused()
  await page.route('**/api/batches/*/items/*/preview', (route) => route.fulfill({ status: 404 }))
  await page.reload()
  await expect(page.getByText('Preview unavailable.', { exact: false })).toHaveCount(2)
  await page.unroute('**/api/batches/*/items/*/preview')
  await page.getByRole('button', { name: 'Retry preview' }).first().click()
  await expect
    .poll(() =>
      page
        .locator('.history-thumbnail img')
        .first()
        .evaluate((img: HTMLImageElement) => img.naturalWidth),
    )
    .toBe(850)
})

test('printer groups route different tapes and preserve destination choices', async ({ page }) => {
  const first = await (
    await page.request.post('/api/printers', {
      data: { name: 'White printer', usb_serial: 'UI-WHITE' },
    })
  ).json()
  const second = await (
    await page.request.post('/api/printers', {
      data: { name: 'Yellow printer', usb_serial: 'UI-YELLOW' },
    })
  ).json()
  const tapes = []
  for (const [name, printer] of [
    ['White group tape', first],
    ['Yellow group tape', second],
  ] as const) {
    const tape = await (
      await page.request.post('/api/tape-profiles', {
        data: { name, width_mm: 24, auto_print_threshold: 1 },
      })
    ).json()
    const cartridge = await (
      await page.request.post('/api/cartridges', {
        data: { name: `${name} cassette`, profile_id: tape.id, nominal_length_mm: 8000 },
      })
    ).json()
    await page.request.put(`/api/printer/active-tape?printer_id=${printer.id}`, {
      data: { cartridge_id: cartridge.id },
    })
    tapes.push(tape)
  }
  await page.goto('/#/printers')
  await page.getByRole('button', { name: 'Create group', exact: true }).click()
  await page.getByLabel('Group name', { exact: true }).fill('Cable station')
  await page.getByLabel('White printer', { exact: true }).check()
  await page.getByLabel('Yellow printer', { exact: true }).check()
  await page.getByRole('button', { name: 'Save group', exact: true }).click()
  const group = page.locator('.printer-group').filter({ hasText: 'Cable station' })
  await expect(group).toBeVisible()
  await group.getByRole('button', { name: 'Hold group', exact: true }).click()
  await group.getByRole('link', { name: 'Print a label', exact: true }).click()
  const destination = await page
    .getByRole('combobox', { name: 'Print destination', exact: true })
    .inputValue()
  await page.getByRole('combobox', { name: 'Template', exact: true }).selectOption('text')
  await page.getByRole('combobox', { name: 'Tape profile', exact: true }).selectOption(tapes[0].id)
  await page.reload()
  await expect(page.getByRole('combobox', { name: 'Print destination', exact: true })).toHaveValue(
    destination,
  )
  await page.getByLabel('Label text', { exact: true }).fill('White cable')
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  await expect(page).toHaveURL(/#\/queue/)
  await page.request.post('/api/jobs', {
    data: {
      destination_id: destination,
      tape_profile: tapes[1].id,
      data: { text: 'Yellow cable' },
    },
  })
  await page.goto('/#/printers')
  await group.getByRole('button', { name: 'Resume group', exact: true }).click()
  await expect
    .poll(async () => {
      const jobs = await (await page.request.get(`/api/jobs?destination_id=${destination}`)).json()
      return jobs.map((job: { status: string }) => job.status)
    })
    .toEqual(['printed', 'printed'])
  const batches = await (await page.request.get('/api/batches')).json()
  expect(batches.some((batch: { printer_id: string }) => batch.printer_id === first.id)).toBe(true)
  expect(batches.some((batch: { printer_id: string }) => batch.printer_id === second.id)).toBe(true)
  await page.screenshot({ path: 'test-results/printer-groups.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(group.getByRole('link', { name: 'Print a label', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391)
})
