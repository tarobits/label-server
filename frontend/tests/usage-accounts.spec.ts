import { test, expect } from './fixtures'
import type { APIRequestContext } from '@playwright/test'

async function create(request: APIRequestContext, resource: string, payload: unknown) {
  const preview = await request.post('/api/admin/access-preview', {
    data: { resource, method: 'POST', payload },
  })
  expect(preview.ok(), await preview.text()).toBeTruthy()
  const response = await request.post(`/api/admin/${resource}`, {
    data: payload,
    headers: { 'X-Access-Confirmation': (await preview.json()).confirmation_token },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}

test('balances include printing, payments and corrections with individual views on desktop and mobile', async ({
  page,
  request,
}) => {
  const other = await create(request, 'users', {
    username: 'other-user',
    password: 'browser-other-password',
    role_ids: ['member'],
  })
  const cartridges = await (await request.get('/api/cartridges')).json()
  expect(
    (
      await request.put(`/api/cartridges/${cartridges[0].id}/price`, {
        data: { price_minor: 2000, currency: 'EUR' },
      })
    ).ok(),
  ).toBeTruthy()
  expect(
    (
      await request.post('/api/jobs', {
        data: {
          tape_profile: cartridges[0].profile_id,
          copies: 2,
          data: { text: 'Charged printing' },
        },
      })
    ).ok(),
  ).toBeTruthy()
  expect((await request.post('/api/queue/print')).ok()).toBeTruthy()
  await expect
    .poll(async () => (await (await request.get('/api/usage')).json()).accounts[0]?.balances.EUR)
    .toMatch(/^-/)
  const original = await (await request.get('/api/usage')).json()
  await page.goto('/#/usage')
  await expect(page.locator('.account-balance')).toContainText('-€')
  const details = page.locator('.account-adjustment')
  await details.locator('summary').click()
  await details.getByLabel('Amount', { exact: true }).fill('10')
  await details.getByLabel('Reason', { exact: true }).fill('Cash payment')
  await details.getByRole('button', { name: 'Record adjustment', exact: true }).click()
  await expect(details.getByRole('status')).toContainText('+€10.00 recorded for owner.')
  await expect(details.getByRole('alert')).toHaveCount(0)
  await expect(page.locator('.adjustment-entry')).toHaveCount(1)
  await details.getByRole('combobox', { name: 'Adjustment', exact: true }).selectOption('subtract')
  await details.getByLabel('Amount', { exact: true }).fill('2')
  await details.getByLabel('Reason', { exact: true }).fill('Payment correction')
  await details.getByRole('button', { name: 'Record adjustment', exact: true }).click()
  await expect(page.locator('.adjustment-entry')).toHaveCount(2)
  const after = await (await request.get('/api/usage')).json()
  expect(Number(after.accounts[0].balances.EUR)).toBeCloseTo(
    8 + Number(original.accounts[0].balances.EUR),
    6,
  )
  expect(after.users).toEqual(original.users)
  await details.locator('summary').click()
  await expect(details.getByLabel('Amount', { exact: true })).toBeHidden()
  await details.locator('summary').click()
  await expect(details.getByLabel('Amount', { exact: true })).toBeVisible()
  await details.locator('summary').click()
  await expect(details.getByLabel('Amount', { exact: true })).toBeHidden()
  await page.screenshot({
    path: 'test-results/usage-accounts-desktop.png',
    fullPage: true,
    animations: 'disabled',
  })

  await page.getByRole('combobox', { name: 'View', exact: true }).selectOption(other.id)
  await expect(page.locator('.usage-accounts')).toContainText('other-user')
  await expect(page.locator('.usage-entry')).toHaveCount(0)
  await expect(page.locator('.adjustment-entry')).toHaveCount(0)
  await details.locator('summary').click()
  await expect(details.getByRole('combobox', { name: 'User', exact: true })).toHaveValue(other.id)
  await details.getByLabel('Amount', { exact: true }).fill('5')
  await details.getByLabel('Reason', { exact: true }).fill('Payment received')
  await details.getByRole('button', { name: 'Record adjustment', exact: true }).click()
  await expect(page.locator('.account-balance')).toContainText('€5.00')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({
    path: 'test-results/usage-accounts-mobile.png',
    fullPage: true,
    animations: 'disabled',
  })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await details.locator('summary').click()
  await expect(details.getByLabel('Amount', { exact: true })).toBeHidden()
  await page.getByRole('combobox', { name: 'View', exact: true }).selectOption('all')
  await expect(page.getByRole('heading', { name: 'Account balances', exact: true })).toBeVisible()
  await page
    .locator('.usage-accounts')
    .getByRole('link', { name: 'other-user', exact: true })
    .click()
  await expect(page.getByRole('combobox', { name: 'View', exact: true })).toHaveValue(other.id)
  await expect(page.locator('.adjustment-entry')).toHaveCount(1)
})

test('usage readers and account editors get independent controls without administrator access', async ({
  page,
  request,
  browser,
  baseURL,
}) => {
  await page.goto('/#/admin?section=roles')
  await page.getByRole('button', { name: 'New role', exact: true }).click()
  const editor = page.getByRole('dialog', { name: 'New role', exact: true })
  await expect(
    editor.getByRole('checkbox', { name: 'View other users’ usage and balances', exact: true }),
  ).toBeVisible()
  await expect(
    editor.getByRole('checkbox', { name: 'Edit usage accounts', exact: true }),
  ).toBeVisible()
  const readerRole = await create(request, 'roles', {
    name: 'Usage readers',
    permissions: [{ kind: 'application', permission: 'usage.view_others' }],
  })
  const editorRole = await create(request, 'roles', {
    name: 'Account editors',
    permissions: [{ kind: 'application', permission: 'usage.edit_accounts' }],
  })
  const reader = await create(request, 'users', {
    username: 'usage-reader',
    password: 'browser-reader-password',
    role_ids: [readerRole.id],
  })
  await create(request, 'users', {
    username: 'account-editor',
    password: 'browser-editor-password',
    role_ids: [editorRole.id],
  })
  const context = await browser.newContext({
    baseURL,
    storageState: { cookies: [], origins: [] },
    extraHTTPHeaders: {},
  })
  const member = await context.newPage()
  try {
    await member.goto('/#/usage')
    await member.getByLabel('Username', { exact: true }).fill('account-editor')
    await member.getByLabel('Password', { exact: true }).fill('browser-editor-password')
    await member.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(
      member.getByRole('heading', { name: 'Account balance', exact: true }),
    ).toBeVisible()
    await expect(member.getByRole('combobox', { name: 'View', exact: true })).toHaveCount(0)
    const details = member.locator('.account-adjustment')
    await details.locator('summary').click()
    await details.getByRole('combobox', { name: 'User', exact: true }).selectOption(reader.id)
    await details.getByLabel('Amount', { exact: true }).fill('7.25')
    await details.getByLabel('Reason', { exact: true }).fill('Bank transfer')
    await details.getByRole('button', { name: 'Record adjustment', exact: true }).click()
    await expect(details.getByRole('status')).toContainText('+€7.25 recorded for usage-reader.')
    await expect(member.locator('.account-balance')).toContainText('No charges or payments yet')
    await expect(member.locator('.adjustment-entry')).toHaveCount(0)
    await context.clearCookies()
    await member.reload()
    await member.getByLabel('Username', { exact: true }).fill('usage-reader')
    await member.getByLabel('Password', { exact: true }).fill('browser-reader-password')
    await member.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(member.locator('.account-balance')).toContainText('€7.25')
    await expect(member.getByRole('combobox', { name: 'View', exact: true })).toBeVisible()
    await expect(member.locator('.account-adjustment')).toHaveCount(0)
    await member.getByRole('combobox', { name: 'View', exact: true }).selectOption('all')
    await expect(
      member.getByRole('heading', { name: 'Account balances', exact: true }),
    ).toBeVisible()
    await expect(member.locator('.adjustment-entry')).toContainText('account-editor')
    await expect(member.locator('.account-adjustment')).toHaveCount(0)
  } finally {
    await context.close()
  }
})
