import { test, expect } from './fixtures'

test('notification bell reads and reopens an inbox on desktop and mobile', async ({
  page,
  request,
}) => {
  expect((await request.post('/api/test/inbox')).ok()).toBeTruthy()
  await page.goto('/')
  const bell = page.getByRole('button', { name: 'Notifications, 1 unread', exact: true })
  await bell.click()
  const dialog = page.getByRole('dialog', { name: 'Notifications', exact: true })
  await expect(dialog.getByText('Labels ready', { exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: 'Mark read', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Notifications', exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: 'Mark unread', exact: true }).click()
  await expect(bell).toBeVisible()
  await page.evaluate(async () => {
    await Promise.all(
      document
        .getAnimations()
        .filter((a) => a.effect?.getTiming().iterations !== Infinity)
        .map((a) => a.finished.catch(() => {})),
    )
  })
  await page.screenshot({ path: 'test-results/inbox-desktop.png', fullPage: true })
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await bell.click()
  await dialog.getByLabel('Unread only', { exact: true }).check()
  await dialog.getByRole('button', { name: 'Mark all read', exact: true }).click()
  await expect(dialog.getByText('No unread notifications.', { exact: true })).toBeVisible()
  await page.evaluate(async () => {
    await Promise.all(
      document
        .getAnimations()
        .filter((a) => a.effect?.getTiming().iterations !== Infinity)
        .map((a) => a.finished.catch(() => {})),
    )
  })
  await page.screenshot({ path: 'test-results/inbox-mobile.png', fullPage: true })
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBeLessThanOrEqual(390)
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(dialog).not.toBeVisible()
})
