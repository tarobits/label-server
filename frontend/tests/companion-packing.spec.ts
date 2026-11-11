import { test, expect } from '@playwright/test'
import { resolve } from 'node:path'

test('companion groups CSV rows, prints the installed tape queue and packs completed batches', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1024, height: 600 })
  let locked = false
  const printBodies: string[] = []
  const permissions = ['view', 'view_queue', 'view_activity', 'start_any'].map(
    (name) => `printer.${name}`,
  )
  const stock = { id: 'cart', profile_id: 'wide', name: 'White tape', installed: true }
  const job = (id: string, profile: string, copies: number, row: number | null = null) => ({
    id,
    profile_id: profile,
    profile_name: profile === 'wide' ? 'Black on white 24 mm' : 'Black on yellow 12 mm',
    process_name: `Label ${id}`,
    owner_id: 'alice',
    can_print: profile === 'wide',
    run_id: row === null ? null : 'csv-run',
    source_row: row,
    width_mm: 24,
    length_mm: 60,
    attribution: { requested_by: { id: 'alice', name: 'Alice' } },
    labels: Array.from({ length: copies }, (_, index) => ({
      id: `${id}-${index}`,
      state: 'queued',
    })),
  })
  const rows = [job('row-one', 'wide', 2, 1), job('row-two', 'wide', 1, 2)]
  const item = (position: number, requester: string) => ({
    copy_id: `printed-${position}`,
    job_id: position < 2 ? 'first' : 'second',
    position,
    outcome: 'printed',
    process_name: `Packed ${requester}`,
    width_mm: 24,
    length_mm: 60,
    attribution: { requested_by: { id: requester, name: requester } },
  })
  const batch = {
    id: 'finished',
    state: 'printed',
    created_at: 1794390000,
    process_names: ['Workshop CSV'],
    items: [item(0, 'Zoe'), item(1, 'Zoe'), item(2, 'Alice')],
  }
  await page.route('http://localhost:12345/**', async (route) => {
    const url = new URL(route.request().url()),
      path = url.pathname
    if (path === '/api/station')
      return route.fulfill({
        json: {
          name: 'Workshop station',
          version: '0.14.0',
          locked,
          online: true,
          lock_remaining_seconds: 295,
          user: locked
            ? null
            : {
                id: 'alice',
                username: 'Alice',
                permissions: [],
                groups: {},
                printer_permissions: { printer: permissions },
              },
          users: [],
          removed_printers: [],
          csrf_token: 'fixture',
          stop_policy: {},
          printers: [
            {
              local_id: 'usb',
              id: 'printer',
              name: 'Label printer',
              status: { connected: true, tape_width_mm: 24 },
              blocked: false,
              printing: false,
              dashboard: {
                queued_labels: 3,
                shared_queued_labels: 0,
                printed_last_24h: 5,
                held: false,
                cartridge_check_pending: false,
                active_batch: null,
                last_batch: null,
                cartridge: {
                  name: stock.name,
                  profile_name: 'Black on white 24 mm',
                  remaining_mm: 5000,
                  nominal_length_mm: 8000,
                  uncertain: false,
                },
              },
            },
          ],
        },
      })
    if (path === '/api/station/lock') {
      locked = true
      return route.fulfill({ json: {} })
    }
    if (path === '/api/station/activity')
      return route.fulfill({ json: { lock_remaining_seconds: 295 } })
    if (path === '/api/proxy/cartridges') return route.fulfill({ json: [stock] })
    if (path === '/api/proxy/tape-profiles')
      return route.fulfill({
        json: [
          { id: 'wide', name: 'Black on white 24 mm' },
          { id: 'narrow', name: 'Black on yellow 12 mm' },
        ],
      })
    if (path === '/api/proxy/printers') return route.fulfill({ json: [] })
    if (path === '/api/proxy/status')
      return route.fulfill({
        json: {
          printer_id: 'printer',
          active_cartridge_id: 'cart',
          needs_review: [],
          printing: false,
          queues: [],
        },
      })
    if (path === '/api/proxy/queue/groups')
      return route.fulfill({
        json: [
          { id: 'run', run_id: 'csv-run', name: 'Workshop CSV', jobs: rows },
          { id: 'single', run_id: null, name: null, jobs: [job('single', 'narrow', 1)] },
        ],
      })
    if (path === '/api/proxy/queue/print') {
      expect(url.searchParams.get('printer_id')).toBe('printer')
      expect(url.searchParams.get('destination_id')).toBe('printer')
      printBodies.push(route.request().postData() ?? '')
      return route.fulfill({ json: {} })
    }
    if (path === '/api/proxy/batches/page') {
      expect(url.searchParams.get('printer_id')).toBe('printer')
      return route.fulfill({ json: { items: [batch], total: 1, before: 1794391000 } })
    }
    if (path === '/api/proxy/batches/finished') return route.fulfill({ json: batch })
    if (path.endsWith('/preview'))
      return route.fulfill({
        contentType: 'image/png',
        body: Buffer.from(
          'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=',
          'base64',
        ),
      })
    if (path.startsWith('/assets/'))
      return route.fulfill({ path: resolve(`dist-companion${path}`) })
    if (path === '/')
      return route.fulfill({
        path: resolve('dist-companion/companion.html'),
        contentType: 'text/html',
      })
    return route.abort()
  })
  await page.goto('http://localhost:12345/')
  await expect(page.getByRole('button', { name: 'Pack labels', exact: true })).toBeVisible()
  await page.locator('.station-printer').evaluateAll(async (cards) => {
    await Promise.all(
      cards.flatMap((card) => card.getAnimations().map((animation) => animation.finished)),
    )
  })
  expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBeLessThanOrEqual(600)
  await page.screenshot({
    path: 'test-results/station-unlocked-1024x600.png',
    animations: 'disabled',
  })
  await page.getByRole('button', { name: 'Controls', exact: true }).click()
  const groups = page.locator('.station-queue-group')
  await expect(groups).toHaveCount(2)
  await expect(groups.first()).toContainText('Workshop CSV')
  await expect(groups.first()).toContainText('2 rows · 3 copies')
  await expect(groups.first()).toContainText('Black on white 24 mm')
  await groups.first().getByRole('checkbox').first().check()
  await expect(page.getByRole('button', { name: 'Print selected (3)', exact: true })).toBeEnabled()
  await groups.first().locator('summary').click()
  await expect(
    groups
      .first()
      .getByRole('checkbox', { name: 'Row 1 2 copies · Black on white 24 mm', exact: true }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Print selected (3)', exact: true }).click()
  await expect.poll(() => printBodies.length).toBe(1)
  expect(JSON.parse(printBodies[0]!).copy_ids).toEqual(['row-one-0', 'row-one-1', 'row-two-0'])
  await page.getByRole('button', { name: 'Print current tape queue', exact: true }).click()
  await expect.poll(() => printBodies.length).toBe(2)
  expect(printBodies[1]).toBe('')
  await page.getByRole('button', { name: 'Pack labels', exact: true }).click()
  const packing = page.getByRole('region', { name: 'Batch packing' })
  await expect(packing.locator('.packing-label')).toHaveCount(2)
  await expect(packing.locator('.packing-label h2')).toHaveText(['Zoe', 'Alice'])
  await expect(packing.locator('.packing-label').first()).toContainText('2 copies')
  await packing.getByLabel('Sort by').selectOption('requester')
  await expect(packing.locator('.packing-label h2')).toHaveText(['Alice', 'Zoe'])
  await packing.getByRole('button', { name: 'Enlarge label preview: Packed Alice' }).click()
  await page
    .getByRole('dialog', { name: 'Label preview', exact: true })
    .getByRole('button', { name: 'Close' })
    .click()
  await page.screenshot({
    path: 'test-results/station-packing-1024x600.png',
    animations: 'disabled',
  })
  await packing.getByRole('button', { name: 'Back to printers' }).click()
  await expect(packing).not.toBeVisible()
  await page.getByRole('button', { name: 'Pack labels', exact: true }).click()
  await expect(packing.locator('.packing-label')).toHaveCount(2)
  await page.getByRole('button', { name: 'Lock', exact: true }).click()
  await expect(packing).not.toBeVisible()
  await expect(page.getByRole('button', { name: 'Pack labels', exact: true })).toHaveCount(0)
})
