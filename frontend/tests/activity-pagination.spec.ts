import { test, expect } from './fixtures'
import type { Page, APIRequestContext } from '@playwright/test'

async function history(page: Page, request: APIRequestContext) {
  const [cartridge] = await (await request.get('/api/cartridges')).json()
  const [printer] = await (await request.get('/api/printers')).json()
  let stamp = Date.now() / 1000
  const batches = Array.from({ length: 137 }, (_, i) => ({
    id: `batch-${i + 1}`,
    printer_id: printer.id,
    cartridge_id: cartridge.id,
    state: 'failed',
    created_at: stamp - i - 1,
    finished_at: stamp - i,
    estimated_mm: 140,
    consumed_mm: null,
    consumption_source: null,
    process_names: [`History label ${i + 1}`],
    error: 'Rejected before printing',
    trigger: { kind: 'manual', actor: { id: 'owner', username: 'owner' }, at: stamp - i - 30 },
    attribution_summary: [],
    shortage_warning: false,
  }))
  const notices = Array.from({ length: 57 }, (_, i) => ({
    id: `notice-${i + 1}`,
    title: `Saved alert ${i + 1}`,
    message: 'Printing did not start.',
    path: '/#/activity',
    created_at: stamp - i - 1,
    attempts: 0,
    delivered_at: null,
    last_error: null,
    cancelled: false,
    deliveries: [],
  }))
  const requests: string[] = []
  const state = { failSecond: false, delaySecond: null as Promise<void> | null }
  for (const kind of ['batches', 'notifications'] as const) {
    await page.route(`**/api/${kind}/page?*`, async (route) => {
      const url = new URL(route.request().url())
      requests.push(url.search)
      const offset = Number(url.searchParams.get('offset'))
      if (kind === 'batches' && offset === 25) {
        if (state.delaySecond) await state.delaySecond
        if (state.failSecond)
          return route.fulfill({
            status: 503,
            contentType: 'application/json',
            body: JSON.stringify({ detail: 'History unavailable. Try again.' }),
          })
      }
      const before = Number(url.searchParams.get('before') ?? stamp)
      const records = (kind === 'batches' ? batches : notices).filter(
        (item) => item.created_at <= before,
      )
      await route.fulfill({
        json: { items: records.slice(offset, offset + 25), total: records.length, before },
      })
    })
  }
  return {
    state,
    requests,
    addLatest() {
      stamp += 2
      batches.unshift({
        ...batches[0]!,
        id: 'new-batch',
        created_at: stamp - 1,
        process_names: ['New arrival'],
      })
    },
  }
}

test('activity reaches old records, preserves independent pages and snapshots, and returns to latest', async ({
  page,
  request,
}) => {
  const data = await history(page, request)
  await page.goto('/#/activity')
  const batchNav = page.getByRole('navigation', { name: 'Print batch pages', exact: true })
  const noticeNav = page.getByRole('navigation', { name: 'Notification pages', exact: true })
  const batches = page.getByRole('region', { name: 'Print batches', exact: true })
  await expect(batchNav).toContainText('Page 1 of 6')
  await expect(batchNav.getByRole('button', { name: 'Previous', exact: true })).toBeDisabled()
  await expect(batches.getByText('History label 1', { exact: true })).toBeVisible()
  await batchNav.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(batchNav).toContainText('Page 2 of 6')
  await expect(batches.getByText('History label 26', { exact: true })).toBeVisible()
  await expect(page).toHaveURL(/batches_before=/)
  data.addLatest()
  for (let target = 3; target <= 6; target++) {
    await batchNav.getByRole('button', { name: 'Next', exact: true }).click()
    await expect(batchNav).toContainText(`Page ${target} of 6`)
    await expect(batches.locator('article').first()).toContainText(
      `History label ${(target - 1) * 25 + 1}`,
    )
  }
  await expect(batches.locator('article')).toHaveCount(12)
  await expect(batchNav.getByRole('button', { name: 'Next', exact: true })).toBeDisabled()
  expect(data.requests.some((query) => query.includes('offset=125'))).toBe(true)
  await noticeNav.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(noticeNav).toContainText('Page 2 of 3')
  await expect(batchNav).toContainText('Page 6 of 6')
  await page.reload()
  await expect(batchNav).toContainText('Page 6 of 6')
  await expect(noticeNav).toContainText('Page 2 of 3')
  await page.goBack()
  await expect(noticeNav).toContainText('Page 1 of 3')
  await expect(batchNav).toContainText('Page 6 of 6')
  await page.goForward()
  await expect(noticeNav).toContainText('Page 2 of 3')
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({
    path: 'test-results/activity-history-desktop.png',
    animations: 'disabled',
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.evaluate(() => window.scrollTo(0, 0))
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.screenshot({
    path: 'test-results/activity-history-mobile.png',
    animations: 'disabled',
  })
  await batchNav.getByRole('button', { name: 'Latest', exact: true }).click()
  await expect(batchNav).toContainText('Page 1 of 6')
  await expect(batches.getByText('New arrival', { exact: true })).toBeVisible()
  await expect(noticeNav).toContainText('Page 2 of 3')
})

test('failed page loads can be retried without displaying the previous page as the requested page', async ({
  page,
  request,
}) => {
  const data = await history(page, request)
  await page.goto('/#/activity')
  const nav = page.getByRole('navigation', { name: 'Print batch pages', exact: true })
  const batches = page.getByRole('region', { name: 'Print batches', exact: true })
  await expect(nav).toContainText('Page 1 of 6')
  data.state.failSecond = true
  await nav.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(batches.getByRole('alert')).toContainText('History unavailable. Try again.')
  await expect(batches.locator('article')).toHaveCount(0)
  await expect(batches.getByText('No batches yet.', { exact: true })).toHaveCount(0)
  await page.screenshot({ path: 'test-results/activity-history-error.png', animations: 'disabled' })
  data.state.failSecond = false
  await batches.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(batches.getByText('History label 26', { exact: true })).toBeVisible()
  await expect(batches.getByRole('alert')).toHaveCount(0)
  await page.goto('/#/activity?batches_page=999')
  await expect(nav).toContainText('Page 6 of 6')
  await expect(batches.locator('article')).toHaveCount(12)
})

test('a late response cannot overwrite a newer page selection', async ({ page, request }) => {
  const data = await history(page, request)
  await page.goto('/#/activity')
  const nav = page.getByRole('navigation', { name: 'Print batch pages', exact: true })
  const batches = page.getByRole('region', { name: 'Print batches', exact: true })
  await expect(nav).toContainText('Page 1 of 6')
  let release = () => {}
  data.state.delaySecond = new Promise<void>((resolve) => {
    release = resolve
  })
  try {
    await nav.getByRole('button', { name: 'Next', exact: true }).click()
    await expect(batches.getByRole('status')).toHaveText('Loading page 2…')
    await page.goBack()
    await expect(nav).toContainText('Page 1 of 6')
    const late = page.waitForResponse(
      (response) =>
        response.url().includes('/api/batches/page?') &&
        new URL(response.url()).searchParams.get('offset') === '25',
    )
    release()
    await late
    await expect(batches.getByText('History label 1', { exact: true })).toBeVisible()
    await expect(batches.getByText('History label 26', { exact: true })).toHaveCount(0)
    await expect(nav).toContainText('Page 1 of 6')
  } finally {
    release()
  }
})
