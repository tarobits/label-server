import { test, expect } from './fixtures'

test('audit facets, restricted details and disclosure work on desktop and mobile', async ({
  page,
  request,
}) => {
  const [printer] = await (await request.get('/api/printers')).json()
  const [cartridge] = await (await request.get('/api/cartridges')).json()
  const events = [
    {
      id: 'access',
      action: 'permission.changed',
      outcome: 'succeeded',
      occurred_at: Date.now() / 1000,
      recorded_at: Date.now() / 1000,
      printers: [printer.id],
      cartridges: [],
      fields: {
        actor_id: 'operator',
        actor_name: 'Operator',
        victim_ids: ['requester'],
        new_permissions: ['printer.view'],
      },
      restricted_details: true,
    },
    {
      id: 'swap',
      action: 'cartridge.swapped',
      outcome: 'succeeded',
      occurred_at: Date.now() / 1000,
      recorded_at: Date.now() / 1000,
      printers: [printer.id],
      cartridges: [cartridge.id],
      fields: { actor_id: 'operator', actor_name: 'Operator' },
      restricted_details: false,
    },
  ]
  const queries: URLSearchParams[] = []
  await page.route('**/api/audit?*', async (route) => {
    const query = new URL(route.request().url()).searchParams
    queries.push(query)
    const items = events.filter(
      (entry) => !query.get('action') || query.get('action') === entry.action,
    )
    await route.fulfill({
      json: {
        items,
        total: items.length,
        options: {
          printer: [{ id: printer.id, name: printer.id }],
          cartridge: [{ id: cartridge.id, name: cartridge.id }],
          action: events.map((entry) => ({ id: entry.action, name: entry.action })),
          actor: [{ id: 'operator', name: 'Operator' }],
          victim: [{ id: 'requester', name: 'Requester' }],
        },
      },
    })
  })
  await page.goto('/#/audit')
  const entries = page.locator('.audit-entry')
  await expect(entries).toHaveCount(2)
  const first = entries.first()
  await first.getByText('Details', { exact: true }).click()
  await expect(first.getByText('Some details are restricted.', { exact: true })).toBeVisible()
  await first.getByText('Details', { exact: true }).click()
  await expect(first.getByText('Some details are restricted.', { exact: true })).not.toBeVisible()
  for (const [label, value] of [
    ['Printer', printer.id],
    ['Cartridge', cartridge.id],
    ['Actor', 'operator'],
    ['Victim', 'requester'],
  ]) {
    await page.getByRole('combobox', { name: label, exact: true }).selectOption(value!)
    await expect.poll(() => queries.at(-1)?.get(label!.toLowerCase())).toBe(value)
  }
  await page
    .getByRole('combobox', { name: 'Action', exact: true })
    .selectOption('permission.changed')
  await expect(entries).toHaveCount(1)
  await first.getByText('Details', { exact: true }).click()
  await expect(first.getByText('Some details are restricted.', { exact: true })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBeLessThanOrEqual(390)
  await page.evaluate(async () => {
    await Promise.all(
      document
        .getAnimations()
        .filter((a) => a.effect?.getTiming().iterations !== Infinity)
        .map((a) => a.finished.catch(() => {})),
    )
  })
  await page.screenshot({ path: 'test-results/audit-mobile.png', fullPage: true })
})
