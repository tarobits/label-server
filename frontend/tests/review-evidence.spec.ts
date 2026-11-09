import { test, expect } from './fixtures'
const picture = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aCdwAAAAASUVORK5CYII=',
  'base64',
)

test('required evidence covers misprints, history and retry selection', async ({
  page,
  request,
}) => {
  await page.goto('/#/admin')
  await page.getByRole('button', { name: 'Account settings', exact: true }).click()
  await page
    .getByRole('combobox', { name: 'Batch review evidence', exact: true })
    .selectOption('required')
  await page.getByRole('button', { name: 'Save account settings', exact: true }).click()
  await expect(page.getByText('Account settings saved.', { exact: true })).toBeVisible()
  const printer = (await (await request.get('/api/printers')).json())[0]
  const tape = (await (await request.get('/api/tape-profiles')).json())[0]
  const response = await request.post('/api/jobs', {
    data: {
      destination_id: printer.id,
      tape_profile: tape.id,
      copies: 2,
      data: { text: 'Misprinted tape' },
    },
  })
  expect(response.status()).toBe(201)
  const job = await response.json()
  expect((await request.post(`/api/destinations/${printer.id}/print`)).status()).toBe(202)
  await expect
    .poll(async () => (await (await request.get(`/api/jobs/${job.id}`)).json()).status)
    .toBe('printed')
  const batch = (await (await request.get('/api/batches')).json())[0]
  await page.goto(`/#/batches/${batch.id}`)
  await page.setViewportSize({ width: 1024, height: 600 })
  const trigger = page.getByRole('button', { name: 'Report misprint', exact: true })
  await trigger.click()
  const dialog = page.getByRole('dialog', { name: 'Report misprint', exact: true })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await expect(trigger).toBeFocused()
  await trigger.click()
  await dialog.getByRole('checkbox').first().check()
  await dialog.getByLabel('Reason', { exact: true }).fill('Tape ran out')
  const save = dialog.getByRole('button', { name: 'Save misprint report', exact: true })
  await expect(save).toBeDisabled()
  await dialog
    .getByLabel('Evidence photo (required)', { exact: true })
    .setInputFiles({ name: 'evidence.png', mimeType: 'image/png', buffer: picture })
  await expect(dialog.getByAltText('Selected evidence photo')).toBeVisible()
  await expect(save).toBeEnabled()
  await dialog.getByRole('button', { name: 'Remove photo', exact: true }).click()
  await expect(save).toBeDisabled()
  await expect(dialog.getByLabel('Evidence photo (required)', { exact: true })).toBeFocused()
  await dialog
    .getByLabel('Evidence photo (required)', { exact: true })
    .setInputFiles({ name: 'evidence.png', mimeType: 'image/png', buffer: picture })
  await expect(save).toBeEnabled()
  await dialog.screenshot({ path: 'test-results/misprint-evidence-desktop.png' })
  await page.setViewportSize({ width: 390, height: 844 })
  await dialog.screenshot({ path: 'test-results/misprint-evidence-mobile.png' })
  await save.scrollIntoViewIfNeeded()
  await dialog.screenshot({ path: 'test-results/misprint-evidence-actions-mobile.png' })
  await save.click()
  await expect(dialog).not.toBeVisible()
  await page.getByText('Review history', { exact: true }).click()
  await expect(page.getByText('Tape ran out', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'View evidence photo', exact: true }).click()
  const evidence = page.getByRole('dialog', { name: 'Evidence photo', exact: true })
  await expect(evidence.getByAltText('Batch review evidence')).toBeVisible()
  await expect
    .poll(() => evidence.locator('img').evaluate((image: HTMLImageElement) => image.naturalWidth))
    .toBeGreaterThan(0)
  await page.keyboard.press('Escape')
  await expect(evidence).not.toBeVisible()
  await page.getByRole('button', { name: 'Retry labels', exact: true }).click()
  const retry = page.getByRole('dialog', { name: 'Retry labels', exact: true })
  await expect(retry.getByRole('checkbox', { checked: true })).toHaveCount(1)
  const after = await (await request.get(`/api/batches/${batch.id}`)).json()
  expect(after.items.map((item: { outcome: string }) => item.outcome)).toEqual([
    'failed',
    'printed',
  ])
  expect(after.reviews).toHaveLength(1)
})

test('uncertain batch review requires evidence and disabled policy hides the control', async ({
  page,
  request,
}) => {
  const printer = (await (await request.get('/api/printers')).json())[0]
  const tape = (await (await request.get('/api/tape-profiles')).json())[0]
  await request.put('/api/admin/settings', {
    data: { registration_code_required: true, batch_review_evidence: 'required' },
  })
  await request.put(`/api/printer/mock?printer_id=${printer.id}`, {
    data: { connected: true, tape_width_mm: 24, fail_after: 0 },
  })
  const job = await (
    await request.post('/api/jobs', {
      data: {
        destination_id: printer.id,
        tape_profile: tape.id,
        copies: 1,
        data: { text: 'Uncertain output' },
      },
    })
  ).json()
  await request.post(`/api/destinations/${printer.id}/print`)
  await expect
    .poll(async () => (await (await request.get(`/api/jobs/${job.id}`)).json()).status)
    .toBe('needs_review')
  const batch = (await (await request.get('/api/batches')).json())[0]
  await page.goto(`/#/batches/${batch.id}`)
  await page.getByLabel('Decision for label 1', { exact: true }).selectOption('failed')
  await page.getByLabel('Total tape consumed by this attempt (mm)', { exact: true }).fill('50')
  const save = page.getByRole('button', { name: 'Save review', exact: true })
  await expect(save).toBeDisabled()
  await page
    .getByLabel('Evidence photo (required)', { exact: true })
    .setInputFiles({ name: 'evidence.png', mimeType: 'image/png', buffer: picture })
  await expect(save).toBeEnabled()
  await save.click()
  await expect(save).toHaveCount(0)
  expect(
    (await (await request.get(`/api/batches/${batch.id}`)).json()).reviews[0].photo_url,
  ).toBeTruthy()
  await request.put('/api/admin/settings', {
    data: { registration_code_required: true, batch_review_evidence: 'disabled' },
  })
  await page.reload()
  await page.getByText('Review history', { exact: true }).click()
  await expect(page.getByRole('button', { name: 'View evidence photo', exact: true })).toBeVisible()
  await expect(page.locator('input[type=file]')).toHaveCount(0)
})
