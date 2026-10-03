import { test, expect } from '@playwright/test'

test('create tape and cartridge, queue copies, review an interrupted batch, and print the remainder', async ({
  page,
}) => {
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
  await expect(page.getByText('Installed', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Printer & settings' }).click()
  await page.getByLabel('Interrupt the next print batch').check()
  await page.getByLabel('Confirmed copies before interruption').fill('1')
  await page.getByRole('button', { name: 'Apply mock settings' }).click()
  await expect(page.getByRole('status')).toContainText('interrupted once')
  await page.getByRole('link', { name: 'New label', exact: true }).click()
  await page.getByLabel('Label text').fill('Network cables / Box 03')
  await page.getByLabel('Copies', { exact: true }).fill('3')
  await page.getByRole('button', { name: 'Add to queue' }).click()
  await page.getByRole('link', { name: 'Review batch →', exact: true }).click()
  await expect(page.getByText('Confirmed — no action needed')).toHaveCount(1)
  await expect(page.getByRole('button', { name: 'Save review and resume' })).toBeDisabled()
  await page.getByLabel('Decision for label 2', { exact: true }).selectOption('queued')
  await page.getByLabel('Decision for label 3', { exact: true }).selectOption('cancelled')
  await page.getByLabel('Total tape consumed by this attempt (mm)').fill('70')
  await page.getByRole('button', { name: 'Save review and resume' }).click()
  await expect(page.getByText('Tape consumed: 0.07 m.')).toBeVisible()
  await page.getByRole('link', { name: 'Overview', exact: true }).click()
  await page.getByRole('button', { name: 'Print compatible queue now' }).click()
  await expect(page.getByRole('link', { name: 'Review →', exact: true })).toHaveCount(0)
  await page.getByRole('link', { name: 'Print queue', exact: false }).click()
  await page.getByLabel('Filter jobs').selectOption('printed')
  await expect(page.getByText('Network cables / Box 03', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Cartridges', exact: true }).click()
  await expect(page.getByText('≈ 7.85 m')).toBeVisible()
})

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
  await expect(page.getByRole('heading', { name: 'At the printer' })).toBeVisible()
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
  await page.getByRole('button', { name: 'Add variable', exact: true }).click()
  await page.getByLabel('Variable name', { exact: true }).fill('asset')
  await page.getByLabel('Field label', { exact: true }).fill('Asset name')
  await page.getByLabel('Sample value', { exact: true }).fill('ASSET-42')
  await page.getByRole('button', { name: 'Add text', exact: true }).click()
  await page.getByLabel('X (mm)', { exact: true }).fill('24')
  await page.getByLabel('Width (mm)', { exact: true }).fill('34')
  await page.getByLabel('Height (mm)', { exact: true }).fill('20')
  await page.getByLabel('Content', { exact: true }).fill('{{asset}}')
  await page
    .getByRole('combobox', { name: 'Vertical text alignment', exact: true })
    .selectOption('center')
  await page.getByRole('button', { name: 'Add QR code', exact: true }).click()
  await expect(page.getByLabel('QR margin (mm)', { exact: true })).toHaveCount(0)
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
  await expect(page.getByRole('button', { name: '2. qr', exact: true })).toBeVisible()
  await expect(page.locator('svg image')).toBeVisible()
  const smoothPreview = await page.locator('svg image').getAttribute('href')
  await page.getByLabel('Show print pixels', { exact: true }).check()
  await expect(page.locator('svg image')).not.toHaveAttribute('href', smoothPreview!)
  await page.getByLabel('Show print pixels', { exact: true }).uncheck()
  await expect(page.locator('svg image')).toHaveAttribute('href', smoothPreview!)
  await page.screenshot({ path: 'test-results/template-editor.png', fullPage: true })
  await page.goto(`/#/new?template=${id}`)
  await page.getByRole('combobox', { name: 'Tape profile', exact: true }).selectOption(profile.id)
  await page.getByLabel('Asset name', { exact: true }).fill('ASSET-99')
  await expect(page.getByAltText('Rendered label preview')).toBeVisible()
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  await expect(page).toHaveURL(/#\/queue$/)
  const jobs = await (await page.request.get('/api/jobs')).json()
  const queued = jobs.find((job: { template_id: string }) => job.template_id === id)
  expect(queued.template_snapshot.revision).toBe(1)
  expect(queued.template_snapshot.document.elements[0].vertical_align).toBe('center')
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
  await expect(page.getByText('Automatic printing is held.', { exact: true })).toBeVisible()
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
  await page.getByLabel('Content', { exact: true }).fill('Short')
  await page.getByLabel('Fit text box width to content', { exact: true }).check()
  await page.getByLabel('Automatic label length', { exact: true }).check()
  await expect(page.getByLabel('Label length (mm)', { exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Add rectangle', exact: true }).click()
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
  await page.getByLabel('Y (mm)', { exact: true }).fill('2')
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
  await page.getByRole('button', { name: 'Next label', exact: true }).click()
  await expect(page.getByText('Label 2 of 2 · CSV record 2', { exact: true })).toBeVisible()
  await page.reload()
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
  await page.getByLabel('Filter by tape profile').selectOption(profile.id)
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
  await page.goto('/#/templates/new')
  await page.getByLabel('Template name', { exact: true }).fill('Artwork label')
  await page.getByRole('button', { name: 'Add image', exact: true }).click()
  await page.getByRole('combobox', { name: 'Image', exact: true }).selectOption(asset.id)
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
  await page.getByLabel('Preserve aspect ratio', { exact: true }).uncheck()
  await width.fill('30')
  await expect(height).toHaveValue('12')
  await page.getByLabel('Preserve aspect ratio', { exact: true }).check()
  await expect(width).toHaveValue('24')
  const portrait = await (
    await page.request.post('/api/image-assets?name=Portrait', {
      data: '<svg viewBox="0 0 50 100"><rect width="50" height="100"/></svg>',
      headers: { 'Content-Type': 'application/octet-stream' },
    })
  ).json()
  await page.getByRole('combobox', { name: 'Image', exact: true }).selectOption(portrait.id)
  await expect(width).toHaveValue('6')
  await expect(height).toHaveValue('12')
  await page.getByRole('combobox', { name: 'Image', exact: true }).selectOption(asset.id)
  await page.getByLabel('Height (mm)', { exact: true }).fill('18')
  await expect(page.locator('svg image')).toBeVisible()
  const threshold = await page.locator('svg image').getAttribute('href')
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
