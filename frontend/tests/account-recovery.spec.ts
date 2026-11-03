import { test, expect } from './fixtures'

test('verified recovery email, personal subscriptions, and forgotten password work end to end', async ({
  page,
  request,
  browser,
  baseURL,
}) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/#/account')
  const emailSettings = page.getByRole('region', { name: 'Email settings' })
  await emailSettings.getByRole('button', { name: 'Add email', exact: true }).click()
  await emailSettings.getByLabel('Email address', { exact: true }).fill('owner@example.invalid')
  await emailSettings.getByLabel('Account password', { exact: true }).fill('browser-owner-password')
  await emailSettings.getByRole('button', { name: 'Send verification link', exact: true }).click()
  await expect(emailSettings.getByRole('status')).toHaveText(
    'Check your email for a verification link.',
  )
  await expect(emailSettings.getByLabel('Email address', { exact: true })).toBeHidden()
  await expect
    .poll(async () => (await (await request.get('/api/test/emails')).json()).length)
    .toBe(1)
  const verification = (await (await request.get('/api/test/emails')).json())[0]
  expect(verification.recipient).toBe('owner@example.invalid')
  const verificationLink = verification.body.match(/https?:\/\/\S+/)[0]
  await page.goto(verificationLink)
  await expect(page).not.toHaveURL(/token=/)
  await page.getByRole('button', { name: 'Verify email', exact: true }).click()
  await expect(page.getByRole('status')).toHaveText('Email verified.')
  await page.getByRole('link', { name: 'Account settings', exact: true }).click()
  await expect(emailSettings.getByText('owner@example.invalid', { exact: true })).toBeVisible()
  await emailSettings
    .getByRole('checkbox', { name: 'Receive email notifications', exact: true })
    .check()
  await emailSettings
    .getByRole('checkbox', { name: 'All printers I can moderate', exact: true })
    .check()
  await emailSettings.getByRole('checkbox', { name: 'Empty cartridges', exact: true }).check()
  await emailSettings.getByRole('button', { name: 'Save email notifications', exact: true }).click()
  await expect(emailSettings.getByRole('status')).toHaveText('Email notifications saved.')
  await page.reload()
  await expect(
    emailSettings.getByRole('checkbox', { name: 'Receive email notifications', exact: true }),
  ).toBeChecked()
  await expect(
    emailSettings.getByRole('checkbox', { name: 'Empty cartridges', exact: true }),
  ).toBeChecked()
  await page.setViewportSize({ width: 390, height: 844 })
  await emailSettings.getByRole('heading', { name: 'Account email', exact: true }).click()
  await emailSettings.scrollIntoViewIfNeeded()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.screenshot({
    path: 'test-results/account-email-mobile.png',
    fullPage: true,
    animations: 'disabled',
  })
  await emailSettings
    .getByRole('checkbox', { name: 'Receive email notifications', exact: true })
    .uncheck()
  await expect(
    emailSettings.getByRole('checkbox', { name: 'Empty cartridges', exact: true }),
  ).toBeHidden()
  await emailSettings.getByRole('button', { name: 'Save email notifications', exact: true }).click()

  const anonymous = await browser.newContext({
    baseURL,
    storageState: { cookies: [], origins: [] },
  })
  const recovery = await anonymous.newPage()
  await recovery.goto('/')
  await recovery.getByRole('link', { name: 'Forgot password?', exact: true }).click()
  await recovery.getByLabel('Username', { exact: true }).fill('owner')
  await recovery.getByRole('button', { name: 'Send reset link', exact: true }).click()
  await expect(recovery.getByRole('status')).toContainText(
    'If this account has a verified email address',
  )
  await expect
    .poll(async () => (await (await request.get('/api/test/emails')).json()).length)
    .toBe(2)
  const reset = (await (await request.get('/api/test/emails')).json())[1]
  const resetLink = reset.body.match(/https?:\/\/\S+/)[0]
  await recovery.goto(resetLink)
  await expect(recovery).not.toHaveURL(/token=/)
  await recovery.getByLabel('New password', { exact: true }).fill('new-browser-owner-password')
  await recovery
    .getByLabel('Confirm new password', { exact: true })
    .fill('wrong-password-confirmation')
  await recovery.getByRole('button', { name: 'Reset password', exact: true }).click()
  await expect(recovery.locator('.field-error')).toHaveText('Passwords do not match.')
  await recovery
    .getByLabel('Confirm new password', { exact: true })
    .fill('new-browser-owner-password')
  await recovery.screenshot({
    path: 'test-results/reset-password-desktop.png',
    animations: 'disabled',
  })
  await recovery.getByRole('button', { name: 'Reset password', exact: true }).click()
  await expect(recovery.getByRole('status')).toHaveText(
    'Password reset. Sign in with your new password.',
  )
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  await recovery.getByRole('link', { name: 'Back to sign in', exact: true }).click()
  await recovery.getByLabel('Username or email', { exact: true }).fill('owner')
  await recovery.getByLabel('Password', { exact: true }).fill('new-browser-owner-password')
  await recovery.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(recovery.getByRole('link', { name: 'Overview', exact: true })).toBeVisible()
  await recovery.goto(resetLink)
  await recovery.getByLabel('New password', { exact: true }).fill('another-owner-password')
  await recovery.getByLabel('Confirm new password', { exact: true }).fill('another-owner-password')
  await recovery.getByRole('button', { name: 'Reset password', exact: true }).click()
  await expect(recovery.getByRole('alert')).toContainText('invalid or expired')
  expect(errors).toEqual([])
  await anonymous.close()
})

test('administrators can create and edit email alert destinations using the existing dialog', async ({
  page,
  request,
}) => {
  await page.goto('/#/admin')
  await page.getByRole('button', { name: 'Notification endpoints', exact: true }).click()
  await page.getByRole('button', { name: 'Add notification endpoint', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Endpoint name', { exact: true }).fill('Operations email')
  await dialog.getByRole('combobox', { name: 'Delivery method', exact: true }).selectOption('email')
  await expect(dialog.getByLabel('ntfy server URL', { exact: true })).toBeHidden()
  await dialog.getByLabel('Recipient email', { exact: true }).fill('operations@example.invalid')
  await dialog.getByRole('button', { name: 'Save notification endpoint', exact: true }).click()
  await expect(dialog).toBeHidden()
  const saved = await (await request.get('/api/admin/notification-endpoints')).json()
  expect(saved[0]).toMatchObject({
    transport: 'email',
    email: 'operations@example.invalid',
    has_token: false,
  })
  await page.getByRole('button', { name: 'Edit endpoint Operations email', exact: true }).click()
  await expect(dialog.getByLabel('Recipient email', { exact: true })).toHaveValue(
    'operations@example.invalid',
  )
  await page.screenshot({ path: 'test-results/email-endpoint-desktop.png', animations: 'disabled' })
  await dialog.getByRole('combobox', { name: 'Delivery method', exact: true }).selectOption('ntfy')
  await expect(dialog.getByLabel('ntfy server URL', { exact: true })).toBeVisible()
  await expect(dialog.getByLabel('Recipient email', { exact: true })).toBeHidden()
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(dialog).toBeHidden()
})
