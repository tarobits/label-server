import type { APIRequestContext } from '@playwright/test'
import { test, expect } from './fixtures'

async function seed(request: APIRequestContext, count: number) {
  const assets: { id: string; name: string }[] = []
  for (let index = 0; index < count; index++) {
    const response = await request.post(`/api/image-assets?name=Artwork-${index}`, {
      data: `<svg viewBox="0 0 ${100 + index} 50"><rect width="50" height="50"/></svg>`,
      headers: { 'Content-Type': 'image/svg+xml' },
    })
    expect(response.ok(), await response.text()).toBeTruthy()
    assets.push(await response.json())
  }
  const response = await request.get(`/api/image-assets/${assets[0].id}/preview`)
  expect(response.ok()).toBeTruthy()
  return { assets, body: await response.body() }
}

test('image gallery and enlarged previews queue and retry busy responses', async ({
  page,
  request,
}) => {
  const { assets, body } = await seed(request, 6)
  const calls = new Map<string, number[]>()
  let active = 0
  let peak = 0
  await page.route('**/api/image-assets/*/preview*', async (route) => {
    const key = route.request().url()
    const times = calls.get(key) ?? []
    times.push(Date.now())
    calls.set(key, times)
    active++
    peak = Math.max(peak, active)
    try {
      await new Promise((resolve) => setTimeout(resolve, 100))
      await route.fulfill(
        times.length === 1
          ? { status: 503, headers: { 'Retry-After': '1' }, body: 'Busy' }
          : { contentType: 'image/png', body },
      )
    } finally {
      active--
    }
  })
  await page.goto('/#/images')
  for (const asset of assets) {
    const button = page.getByRole('button', { name: `Preview ${asset.name}`, exact: true })
    await button.scrollIntoViewIfNeeded()
    await expect(button).toBeEnabled({ timeout: 15000 })
    await expect
      .poll(() => button.locator('img').evaluate((img: HTMLImageElement) => img.naturalWidth))
      .toBeGreaterThan(0)
  }
  await page.getByRole('button', { name: `Preview ${assets[0].name}`, exact: true }).click()
  const dialog = page.getByRole('dialog', { name: assets[0].name, exact: true })
  await expect(dialog.getByRole('img')).toBeVisible()
  for (const times of calls.values()) {
    expect(times).toHaveLength(2)
    expect(times[1] - times[0]).toBeGreaterThanOrEqual(1000)
  }
  expect(peak).toBeLessThanOrEqual(2)
  await page.screenshot({ path: 'test-results/image-preview-desktop.png' })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: 'test-results/image-preview-mobile.png' })
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(dialog).toBeHidden()
})

test('image errors offer manual retry and closing an enlarged preview cancels retries', async ({
  page,
  request,
}) => {
  const { assets, body } = await seed(request, 1)
  let thumbnails = 0
  let large = 0
  await page.route('**/api/image-assets/*/preview*', async (route) => {
    if (route.request().url().includes('size=large')) {
      large++
      await route.fulfill({ status: 503, headers: { 'Retry-After': '1' }, body: 'Busy' })
    } else {
      thumbnails++
      await route.fulfill(
        thumbnails === 1 ? { status: 404, body: 'Missing' } : { contentType: 'image/png', body },
      )
    }
  })
  await page.goto('/#/images')
  await expect(page.getByRole('button', { name: 'Retry preview', exact: true })).toBeVisible()
  expect(thumbnails).toBe(1)
  await page.getByRole('button', { name: 'Retry preview', exact: true }).click()
  const button = page.getByRole('button', { name: `Preview ${assets[0].name}`, exact: true })
  await expect(button).toBeEnabled()
  expect(thumbnails).toBe(2)
  await button.click()
  await expect.poll(() => large).toBe(1)
  const dialog = page.getByRole('dialog', { name: assets[0].name, exact: true })
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(dialog).toBeHidden()
  await page.waitForTimeout(1200)
  expect(large).toBe(1)
  await page.unroute('**/api/image-assets/*/preview*')
  await button.click()
  await expect(dialog.getByRole('img')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
})
