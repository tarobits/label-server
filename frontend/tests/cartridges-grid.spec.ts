import type { Page } from '@playwright/test'
import { test, expect } from './fixtures'

async function cardLayout(page: Page) {
  return page.locator('.cartridge-card').evaluateAll((cards) =>
    cards.map((card) => {
      const box = card.getBoundingClientRect()
      const children = [...card.children]
        .map((child) => child.getBoundingClientRect())
        .filter((rect) => rect.height > 0)
      return {
        x: box.x,
        y: box.y,
        width: box.width,
        height: box.height,
        clearance: children.slice(1).map((rect, index) => rect.top - children[index]!.bottom),
        contained: children.every(
          (rect) => rect.left >= box.left && rect.right <= box.right && rect.bottom <= box.bottom,
        ),
      }
    }),
  )
}
function alignedRows(cards: Awaited<ReturnType<typeof cardLayout>>) {
  const rows = new Map<number, typeof cards>()
  for (const card of cards) {
    // Optional notes, badges and forms grow naturally (DESIGN.md). Check
    // clearance and containment rather than imposing fixed internal rows.
    expect(card.contained).toBe(true)
    for (const gap of card.clearance) expect(gap).toBeGreaterThanOrEqual(11.5)
    const y = Math.round(card.y)
    rows.set(y, [...(rows.get(y) ?? []), card])
  }
  for (const row of rows.values()) {
    // Optional removal explanations below the actions have different heights.
    const heights = row.map((card) => card.height)
    expect(Math.max(...heights) - Math.min(...heights)).toBeLessThan(1)
  }
  return [...rows.values()]
}

test('cartridge cards form an aligned responsive grid even while correcting an estimate', async ({
  page,
  request,
}) => {
  const profileResponse = await request.post('/api/tape-profiles', {
    data: {
      name: 'Black lettering on extra bright yellow tape for network infrastructure identification',
      width_mm: 24,
      auto_print_threshold: 1000,
    },
  })
  expect(profileResponse.ok()).toBeTruthy()
  const profile = await profileResponse.json()
  const names = [
    'Long cassette name for labeling network infrastructure in the equipment room',
    'Spare cassette',
    'Another spare cassette with a longer descriptive name',
    'Storage cassette',
    'Last spare cassette',
  ]
  for (const [index, name] of names.entries()) {
    expect(
      (
        await request.post('/api/cartridges', {
          data: {
            profile_id: profile.id,
            name,
            nominal_length_mm: 8000,
            remaining_mm: 8000 - index * 1000,
          },
        })
      ).ok(),
    ).toBeTruthy()
  }
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/#/cartridges')
  await expect(page.locator('.cartridge-card')).toHaveCount(6)
  const initial = await cardLayout(page)
  const desktopRows = alignedRows(initial)
  expect(desktopRows).toHaveLength(2)
  expect(desktopRows.every((row) => row.length === 3)).toBe(true)
  await page.screenshot({ path: 'test-results/cartridges-grid-desktop.png', fullPage: true })

  const correcting = page
    .locator('.cartridge-card')
    .filter({ hasText: 'Spare cassette' })
    .filter({ has: page.getByRole('heading', { name: 'Spare cassette', exact: true }) })
  await correcting.getByRole('button', { name: 'Correct estimate', exact: true }).click()
  await correcting.getByLabel('Remaining tape (m)', { exact: true }).fill('4.25')
  alignedRows(await cardLayout(page))
  await correcting.getByRole('button', { name: 'Save estimate', exact: true }).click()
  await expect(correcting).toContainText('4.25 m')
  await expect(correcting.getByLabel('Remaining tape (m)', { exact: true })).toHaveCount(0)
  alignedRows(await cardLayout(page))

  await page.getByRole('button', { name: 'Register cartridge', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Register a cartridge', exact: true }),
  ).toBeVisible()
  const registering = await cardLayout(page)
  alignedRows(registering)
  registering.forEach((card, index) => expect(card.width).toBeCloseTo(initial[index]!.width, 3))
  await page.locator('form').getByRole('button', { name: 'Cancel', exact: true }).click()

  await page.setViewportSize({ width: 390, height: 844 })
  const mobile = await cardLayout(page)
  expect(new Set(mobile.map((card) => Math.round(card.x))).size).toBe(1)
  expect(new Set(mobile.map((card) => Math.round(card.y))).size).toBe(6)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await correcting.getByRole('button', { name: 'Correct estimate', exact: true }).click()
  await expect(correcting.getByLabel('Remaining tape (m)', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await page.evaluate(() => {
    ;(document.activeElement as HTMLElement | null)?.blur()
    window.scrollTo(0, 0)
  })
  await page.screenshot({ path: 'test-results/cartridges-grid-mobile.png', fullPage: true })
  await correcting.getByRole('button', { name: 'Cancel', exact: true }).click()
})
