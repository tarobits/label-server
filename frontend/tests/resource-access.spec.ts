import { test, expect } from './fixtures'
import type { Page } from '@playwright/test'

async function settle(page: Page) {
  await page.evaluate(async () => {
    await Promise.all(
      document
        .getAnimations()
        .filter((animation) => animation.effect?.getTiming().iterations !== Infinity)
        .map((animation) => animation.finished.catch(() => {})),
    )
  })
}

test('resource access creates locations and previews inherited grants on desktop and mobile', async ({
  page,
}) => {
  await page.goto('/#/resource-access')
  await page.getByRole('button', { name: 'New location', exact: true }).click()
  await page.getByLabel('Location name', { exact: true }).fill('Packing room')
  await page
    .getByRole('combobox', { name: 'User or role', exact: true })
    .selectOption({ label: 'Role: Member' })
  await page.getByLabel('Use cartridge', { exact: true }).check()
  await page.getByRole('button', { name: 'Review changes', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Review access changes' })).toBeVisible()
  await page.getByRole('button', { name: 'Confirm access changes', exact: true }).click()
  await expect(page.getByRole('dialog')).not.toBeVisible()
  await page.getByRole('button', { name: 'Manage Desk printer', exact: true }).click()
  await page
    .getByRole('combobox', { name: 'Location', exact: true })
    .selectOption({ label: 'Packing room' })
  await page
    .getByRole('combobox', { name: 'User or role', exact: true })
    .selectOption({ label: 'Role: Member' })
  await page.getByLabel('Hold/resume printing', { exact: true }).check()
  await settle(page)
  await page.screenshot({ path: 'test-results/resource-access-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('combobox', { name: 'Location', exact: true }).scrollIntoViewIfNeeded()
  await settle(page)
  await page.screenshot({ path: 'test-results/resource-access-mobile.png', fullPage: true })
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBeLessThanOrEqual(390)
  await page.getByRole('button', { name: 'Review changes', exact: true }).click()
  await page.getByRole('button', { name: 'Confirm access changes', exact: true }).click()
  await expect(page.getByRole('dialog')).not.toBeVisible()
  await page.getByRole('button', { name: 'Manage Desk printer', exact: true }).click()
  await expect(
    page.getByRole('combobox', { name: 'Location', exact: true }).locator('option:checked'),
  ).toHaveText('Packing room')
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('dialog')).not.toBeVisible()
})

test('upgrade opens resumable ownership migration and releases the gate only after review', async ({
  page,
  request,
}) => {
  expect((await request.post('/api/test/ownership-upgrade')).ok()).toBeTruthy()
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Set up ownership', exact: true })).toBeVisible()
  await expect(
    page.getByText('Printing is paused until these assignments are confirmed.', { exact: false }),
  ).toBeVisible()
  await page.getByLabel('Select all inventory', { exact: true }).check()
  await page
    .getByRole('combobox', { name: 'Owner for selected', exact: true })
    .selectOption({ label: 'owner' })
  await page.getByRole('button', { name: 'Assign owner', exact: true }).click()
  await page.getByRole('button', { name: 'Save progress', exact: true }).click()
  await expect(page.getByText('Progress saved.', { exact: true })).toBeVisible()
  await page.reload()
  await expect(
    page
      .getByRole('combobox', { name: 'Owner of Desk printer', exact: true })
      .locator('option:checked'),
  ).toHaveText('owner')
  await settle(page)
  await page.screenshot({ path: 'test-results/migration-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await settle(page)
  await page.screenshot({ path: 'test-results/migration-mobile.png', fullPage: true })
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBeLessThanOrEqual(390)
  await page.getByRole('button', { name: 'Review migration', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Resulting balances', exact: true })).toBeVisible()
  expect((await (await request.get('/api/migration')).json()).required).toBe(true)
  await page.getByRole('button', { name: 'Complete migration', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Set up ownership', exact: true }),
  ).not.toBeVisible()
  expect((await (await request.get('/api/migration')).json()).required).toBe(false)
})
