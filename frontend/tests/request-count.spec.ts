import { test, expect } from './fixtures'

for (const width of [1280, 390]) {
  test(`pending requests update the navigation badge at ${width}px`, async ({ page, request }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/#/templates')
    const link = page
      .getByRole('navigation', { name: 'Main navigation' })
      .locator('a[href="#/requests"]')
    const count = link.locator('.nav-count')
    if (width === 390) {
      await page.getByRole('button', { name: 'Menu', exact: true }).click()
    }
    await expect(link).toBeVisible()
    await expect(count).toHaveCount(0)
    const [printer] = await (await request.get('/api/printers')).json()
    const [profile] = await (await request.get('/api/tape-profiles')).json()
    const ids: string[] = []
    for (const text of ['Approve this request', 'Reject this request']) {
      const response = await request.post('/api/requests', {
        data: {
          kind: 'job',
          input: {
            destination_id: printer.id,
            tape_profile: profile.id,
            data: { text },
            copies: 3,
          },
        },
      })
      expect(response.ok()).toBeTruthy()
      ids.push((await response.json()).id)
    }
    // A different client submitted these: the global refresh must find them
    // without opening the requests page or reloading the current page.
    await expect(count).toHaveText('2', { timeout: 18000 })
    await link.scrollIntoViewIfNeeded()
    await page
      .locator('.sidebar nav')
      .screenshot({ path: `test-results/request-badge-${width}.png`, animations: 'disabled' })
    await page.goto(`/#/requests/${ids[0]}`)
    await page.getByRole('button', { name: 'Approve and queue', exact: true }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
    await expect(count).toHaveText('1')
    await page.goto(`/#/requests/${ids[1]}`)
    await page.getByLabel('Reason for rejection').fill('Not needed')
    await page.getByRole('button', { name: 'Reject request', exact: true }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
    await expect(count).toHaveCount(0)
  })
}
