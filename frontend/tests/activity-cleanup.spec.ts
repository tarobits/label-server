import { test, expect } from './fixtures'

test('duplicate purge previews, cancels, confirms, and refreshes older activity pages', async ({
  page,
  request,
}) => {
  const [cartridge] = await (await request.get('/api/cartridges')).json()
  const [printer] = await (await request.get('/api/printers')).json()
  const stamp = Date.now() / 1000
  let purged = false
  let deletions = 0
  const batches = Array.from({ length: 81 }, (_, i) => ({
    id: `failure-${i}`,
    cartridge_id: cartridge.id,
    printer_id: printer.id,
    created_at: stamp - i - 1,
    finished_at: stamp - i,
    state: 'failed',
    estimated_mm: 140,
    consumed_mm: null,
    consumption_source: null,
    process_names: ['Bitte nicht anfassen'],
    error: 'Rejected before transmission',
    attribution_summary: [],
    trigger: null,
  }))
  await page.route('**/api/batches/page?*', async (route) => {
    const url = new URL(route.request().url())
    const offset = Number(url.searchParams.get('offset'))
    const records = purged ? batches.slice(80) : batches
    await route.fulfill({
      json: { items: records.slice(offset, offset + 25), total: records.length, before: stamp },
    })
  })
  await page.route('**/api/admin/history/duplicates', async (route) => {
    await route.fulfill({
      json: {
        confirmation: 'a'.repeat(64),
        batches: purged ? 0 : 80,
        notifications: 0,
        deliveries: 0,
        groups: purged
          ? []
          : [
              {
                retained_batch_id: 'failure-80',
                process_names: ['Bitte nicht anfassen'],
                printer_id: printer.id,
                copies: 2,
                duplicates: 80,
                first_at: stamp - 81,
                last_at: stamp - 1,
                error: 'Could not prepare labels: font unavailable',
              },
            ],
      },
    })
  })
  await page.route('**/api/admin/history/duplicates/purge', async (route) => {
    expect(route.request().postDataJSON()).toEqual({ confirmation: 'a'.repeat(64) })
    deletions++
    purged = true
    await route.fulfill({ json: { batches: 80, notifications: 0, deliveries: 0 } })
  })
  await page.goto('/#/activity?batches_page=4')
  const nav = page.getByRole('navigation', { name: 'Print batch pages', exact: true })
  await expect(nav).toContainText('Page 4 of 4')
  const open = page.getByRole('button', { name: 'Purge duplicates…', exact: true })
  const dialog = page.getByRole('dialog', { name: 'Purge duplicate failures' })
  await open.click()
  await expect(
    dialog.getByRole('button', { name: 'Permanently delete 80', exact: true }),
  ).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Cancel', exact: true })).toBeFocused()
  await expect(dialog).toContainText('zero-usage records')
  await expect(dialog.getByText('Scanning history…', { exact: true })).toHaveCount(0)
  await page.screenshot({
    path: 'test-results/activity-cleanup-desktop.png',
    animations: 'disabled',
  })
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(dialog).toBeHidden()
  await expect(open).toBeFocused()
  expect(deletions).toBe(0)
  await open.click()
  await expect(
    dialog.getByRole('button', { name: 'Permanently delete 80', exact: true }),
  ).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  expect(deletions).toBe(0)
  await page.setViewportSize({ width: 390, height: 844 })
  await open.click()
  const confirm = dialog.getByRole('button', { name: 'Permanently delete 80', exact: true })
  await expect(confirm).toBeInViewport()
  await expect(dialog.getByText('Scanning history…', { exact: true })).toHaveCount(0)
  await page.screenshot({
    path: 'test-results/activity-cleanup-mobile.png',
    animations: 'disabled',
  })
  await confirm.click()
  await expect(dialog).toBeHidden()
  await expect(
    page.getByRole('status').filter({ hasText: 'Permanently deleted 80 duplicate attempts.' }),
  ).toBeVisible()
  await expect(nav).toContainText('Page 1 of 1')
  expect(deletions).toBe(1)
  await open.click()
  await expect(
    dialog.getByRole('status').filter({ hasText: 'No duplicate failures eligible for removal.' }),
  ).toBeVisible()
  await expect(dialog.getByRole('button', { name: /Permanently delete/ })).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(dialog).toBeHidden()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('cleanup rejects stale previews and requires reviewing a new one', async ({ page }) => {
  let scans = 0
  await page.route('**/api/admin/history/duplicates', async (route) => {
    scans++
    if (scans === 1)
      return route.fulfill({ status: 503, json: { detail: 'Preview unavailable. Try again.' } })
    await route.fulfill({
      json: {
        confirmation: (scans === 2 ? 'a' : 'b').repeat(64),
        batches: 2,
        notifications: 1,
        deliveries: 1,
        groups: [
          {
            retained_batch_id: 'old',
            process_names: ['A label'],
            printer_id: 'main',
            copies: 1,
            duplicates: 2,
            first_at: 1000,
            last_at: 1002,
            error: 'Rejected',
          },
        ],
      },
    })
  })
  await page.route('**/api/admin/history/duplicates/purge', async (route) => {
    await route.fulfill({
      status: 409,
      json: { detail: 'Duplicate history changed. Review a fresh preview before purging.' },
    })
  })
  await page.goto('/#/activity')
  await page.getByRole('button', { name: 'Purge duplicates…', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Purge duplicate failures' })
  await expect(dialog.getByRole('alert')).toContainText('Preview unavailable')
  await dialog.getByRole('button', { name: 'Refresh preview', exact: true }).click()
  await dialog.getByRole('button', { name: 'Permanently delete 2', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('Duplicate history changed')
  await expect(dialog.getByRole('button', { name: /Permanently delete/ })).toHaveCount(0)
  await expect(dialog.getByRole('list', { name: 'Duplicate groups' })).toHaveCount(0)
  await page.screenshot({ path: 'test-results/activity-cleanup-error.png', animations: 'disabled' })
  await dialog.getByRole('button', { name: 'Refresh preview', exact: true }).click()
  await expect(
    dialog.getByRole('button', { name: 'Permanently delete 2', exact: true }),
  ).toBeEnabled()
  await expect(dialog.getByRole('alert')).toHaveCount(0)
  expect(scans).toBe(3)
})
