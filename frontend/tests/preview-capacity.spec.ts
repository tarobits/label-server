import type { APIRequestContext } from '@playwright/test'
import { test, expect } from './fixtures'

async function seed(request: APIRequestContext, count = 1) {
  const items: { id: string; name: string }[] = []
  for (let index = 0; index < count; index++) {
    const response = await request.post('/api/templates', {
      data: {
        name: `Capacity preview ${index}`,
        document: {
          width_mm: 24,
          length_mm: 60,
          out_of_bounds: 'clip',
          fields: [],
          elements: [
            {
              id: 'text',
              kind: 'text',
              x: 2,
              y: 2,
              width: 50,
              height: 12,
              content: 'Preview',
            },
          ],
        },
      },
    })
    expect(response.ok(), await response.text()).toBeTruthy()
    items.push(await response.json())
  }
  const preview = await request.get(`/api/templates/${items[0].id}/preview.webp`)
  expect(preview.ok()).toBeTruthy()
  return { items, body: await preview.body() }
}

test('busy gallery previews queue and retry without leaving error cards', async ({
  page,
  request,
}) => {
  const { items, body } = await seed(request, 6)
  const calls = new Map<string, number[]>()
  let active = 0,
    peak = 0
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.route(/\/api\/templates\/[^/]+\/preview\.webp/, async (route) => {
    const id = new URL(route.request().url()).pathname
    const times = calls.get(id) ?? []
    times.push(Date.now())
    calls.set(id, times)
    active++
    peak = Math.max(peak, active)
    try {
      await new Promise((resolve) => setTimeout(resolve, 150))
      if (times.length === 1)
        await route.fulfill({ status: 503, headers: { 'Retry-After': '1' }, body: 'Busy' })
      else await route.fulfill({ contentType: 'image/webp', body })
    } finally {
      active--
    }
  })
  await page.goto('/#/templates')
  for (const item of items) {
    const card = page.locator('article').filter({ hasText: item.name })
    await card.scrollIntoViewIfNeeded()
    const image = card.getByRole('img', { name: `Preview of ${item.name}`, exact: true })
    await expect
      .poll(() => image.evaluate((img: HTMLImageElement) => img.naturalWidth), { timeout: 15000 })
      .toBeGreaterThan(0)
  }
  expect(peak).toBeLessThanOrEqual(2)
  for (const item of items) {
    const times = calls.get(`/api/templates/${item.id}/preview.webp`)!
    expect(times).toHaveLength(2)
    expect(times[1] - times[0]).toBeGreaterThanOrEqual(1000)
  }
  await expect(page.getByText('Preview unavailable', { exact: true })).toHaveCount(0)
  await page.screenshot({ path: 'test-results/preview-capacity-desktop.png', fullPage: true })
})

for (const status of [403, 404]) {
  test(`permanent preview error ${status} stops automatically and manual retry works`, async ({
    page,
    request,
  }) => {
    const { items, body } = await seed(request)
    let calls = 0
    await page.setViewportSize({ width: 390, height: 844 })
    await page.route(`**/api/templates/${items[0].id}/preview.webp?**`, async (route) => {
      calls++
      await route.fulfill(
        calls === 1 ? { status, body: 'Unavailable' } : { contentType: 'image/webp', body },
      )
    })
    await page.goto('/#/templates')
    const card = page.locator('article').filter({ hasText: items[0].name })
    await card.scrollIntoViewIfNeeded()
    await expect(card.getByRole('button', { name: 'Retry preview' })).toBeVisible()
    await page.waitForTimeout(1200)
    expect(calls).toBe(1)
    if (status === 403)
      await page.screenshot({
        path: 'test-results/preview-capacity-mobile-error.png',
        fullPage: true,
      })
    await card.getByRole('button', { name: 'Retry preview' }).click()
    await expect
      .poll(() => card.locator('img').evaluate((img: HTMLImageElement) => img.naturalWidth))
      .toBeGreaterThan(0)
    await expect(card.getByRole('button', { name: 'Retry preview' })).toHaveCount(0)
    expect(calls).toBe(2)
    if (status === 403)
      await page.screenshot({
        path: 'test-results/preview-capacity-mobile-recovered.png',
        fullPage: true,
      })
  })
}

test('busy retries are bounded and navigating away cancels waiting work', async ({
  page,
  request,
}) => {
  const { items } = await seed(request, 6)
  let calls = 0
  const byPath = new Map<string, number>()
  await page.route(/\/api\/templates\/[^/]+\/preview\.webp/, async (route) => {
    calls++
    const path = new URL(route.request().url()).pathname
    byPath.set(path, (byPath.get(path) ?? 0) + 1)
    await route.fulfill({ status: 503, headers: { 'Retry-After': '1' }, body: 'Busy' })
  })
  await page.goto('/#/templates')
  const card = page.locator('article').filter({ hasText: items[0].name })
  await card.scrollIntoViewIfNeeded()
  await expect(card.getByRole('button', { name: 'Retry preview' })).toBeVisible({ timeout: 15000 })
  expect(byPath.get(`/api/templates/${items[0].id}/preview.webp`)).toBe(4)
  await page.goto('/#/queue')
  const afterLeaving = calls
  await page.waitForTimeout(1500)
  expect(calls).toBe(afterLeaving)
  // Re-entering can start work: cancellation must not leak client queue slots.
  await page.unroute(/\/api\/templates\/[^/]+\/preview\.webp/)
  await page.goto('/#/templates')
  await card.scrollIntoViewIfNeeded()
  await expect
    .poll(() => card.locator('img').evaluate((img: HTMLImageElement) => img.naturalWidth), {
      timeout: 10000,
    })
    .toBeGreaterThan(0)
})
