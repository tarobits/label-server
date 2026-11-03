import { test, expect } from './fixtures'

for (const width of [1280, 390]) {
  test(`administrators rename accounts and verified email signs in at ${width}px`, async ({
    page,
    request,
  }) => {
    await page.setViewportSize({ width, height: 844 })
    const before = (await (await request.get('/api/auth/session')).json()).user
    const address = `${'a'.repeat(64)}@example.invalid`
    expect(
      (
        await request.put('/api/auth/email', {
          data: { email: address, current_password: 'browser-owner-password' },
        })
      ).status(),
    ).toBe(202)
    const [message] = await (await request.get('/api/test/emails')).json()
    const token = message.body.match(/token=([^\s]+)/)[1]
    expect((await request.post('/api/auth/email/verify', { data: { token } })).status()).toBe(204)
    await page.goto('/#/admin')
    await page.getByRole('button', { name: 'Edit owner', exact: true }).click()
    const editor = page.getByRole('dialog', { name: /^Edit / })
    const username = editor.getByLabel('Username', { exact: true })
    await expect(username).toBeFocused()
    await username.fill('Room.Admin')
    await page.screenshot({
      path: `test-results/account-rename-${width}.png`,
      animations: 'disabled',
    })
    const reviewButton = editor.getByRole('button', { name: 'Review account changes', exact: true })
    await expect(reviewButton).toBeEnabled()
    await reviewButton.click()
    const review = page.getByRole('dialog', { name: 'Review effective access', exact: true })
    await expect(review.getByText('owner → room.admin', { exact: true })).toBeVisible()
    await review.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(username).toHaveValue('Room.Admin')
    await reviewButton.click()
    await review.getByRole('button', { name: 'Confirm access changes', exact: true }).click()
    await expect(editor).toBeHidden()
    const account = page.locator('.account-menu > summary')
    await expect(account).toHaveAccessibleName('Account: room.admin')
    const after = (await (await request.get('/api/auth/session')).json()).user
    expect(after.id).toBe(before.id)
    expect(after.username).toBe('room.admin')
    expect(
      (
        await request.post('/api/auth/login', {
          data: { username: 'owner', password: 'browser-owner-password' },
        })
      ).status(),
    ).toBe(401)
    await account.click()
    await page.getByRole('button', { name: 'Sign out', exact: true }).click()
    await page.getByLabel('Username or email', { exact: true }).fill(address.toUpperCase())
    await page.getByLabel('Password', { exact: true }).fill('browser-owner-password')
    await page.screenshot({
      path: `test-results/email-signin-${width}.png`,
      animations: 'disabled',
    })
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(account).toHaveAccessibleName('Account: room.admin')
    await page.goto('/#/account')
    await expect(page.getByRole('heading', { name: 'Account email', exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Recovery email', exact: true })).toHaveCount(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
  })
}
