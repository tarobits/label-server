import { test, expect } from './fixtures'
import type { APIRequestContext } from '@playwright/test'

async function accessChange(
  request: APIRequestContext,
  resource: string,
  payload: unknown,
  id?: string,
) {
  const method = id ? 'PUT' : 'POST'
  const preview = await request.post('/api/admin/access-preview', {
    data: { resource, method, identifier: id, payload },
  })
  expect(preview.ok(), await preview.text()).toBeTruthy()
  const response = await request.fetch(`/api/admin/${resource}${id ? `/${id}` : ''}`, {
    method,
    data: payload,
    headers: { 'X-Access-Confirmation': (await preview.json()).confirmation_token },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}

test('personal activity shows only own labels after printer access is removed', async ({
  request,
  browser,
  baseURL,
  page: adminPage,
}) => {
  const [printer] = await (await request.get('/api/printers')).json()
  const [profile] = await (await request.get('/api/tape-profiles')).json()
  const [cartridge] = await (await request.get('/api/cartridges')).json()
  expect(
    (
      await request.put(`/api/cartridges/${cartridge.id}/price`, {
        data: { price_minor: 0, currency: 'EUR' },
      })
    ).ok(),
  ).toBeTruthy()
  const role = await accessChange(request, 'roles', {
    name: 'Personal activity test',
    permissions: [{ kind: 'destination', destination_id: printer.id, level: 'print' }],
  })
  const user = await accessChange(request, 'users', {
    username: 'personal',
    password: 'personal-browser-password',
    role_ids: ['member', role.id],
  })
  const cartridgeAccess = {
    kind: 'cartridge',
    identifier: cartridge.id,
    grants: ['cartridge.view', 'cartridge.use'].map((permission) => ({
      principal_kind: 'role',
      principal_id: role.id,
      permission,
    })),
  }
  const accessPreview = await request.post('/api/resource-access/preview', {
    data: cartridgeAccess,
  })
  expect(accessPreview.ok(), await accessPreview.text()).toBeTruthy()
  const accessApplied = await request.post('/api/resource-access/apply', {
    data: cartridgeAccess,
    headers: { 'X-Access-Confirmation': (await accessPreview.json()).confirmation_token },
  })
  expect(accessApplied.ok(), await accessApplied.text()).toBeTruthy()
  const context = await browser.newContext({
    baseURL,
    storageState: { cookies: [], origins: [] },
    extraHTTPHeaders: {},
  })
  try {
    const login = await context.request.post('/api/auth/login', {
      data: { username: 'personal', password: 'personal-browser-password' },
    })
    expect(login.ok()).toBeTruthy()
    const page = await context.newPage()
    await page.goto(`/#/new?template=text&profile=${cartridge.profile_id}`)
    const preview = page.waitForResponse(
      (response) =>
        response.url().endsWith('/api/preview') &&
        response.ok() &&
        response.request().postDataJSON()?.data?.text === 'My personal label',
    )
    await page.getByLabel('Label text', { exact: true }).fill('My personal label')
    await preview
    await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
    await expect(page).toHaveURL(/#\/queue/)
    expect(
      (
        await request.post('/api/jobs', {
          data: { tape_profile: profile.id, copies: 2, data: { text: 'Other private label' } },
        })
      ).ok(),
    ).toBeTruthy()
    const printed = await request.post('/api/queue/print')
    expect(printed.ok(), await printed.text()).toBeTruthy()
    await expect
      .poll(async () => (await (await request.get('/api/batches')).json())[0]?.state)
      .toBe('printed')
    await accessChange(request, 'users', { disabled: false, role_ids: [] }, user.id)
    await page.reload()
    await page.goto('/#/activity?requester_id=another-user')
    const requester = page.getByRole('combobox', { name: 'Requester', exact: true })
    await expect(requester).toBeDisabled()
    await expect(requester).toHaveValue(user.id)
    await expect(requester.locator('option:checked')).toHaveText('personal')
    const batch = page.locator('.activity-batch')
    await expect(batch).toHaveCount(1)
    await expect(batch).toContainText('Your labels')
    await expect(batch).toContainText('Restricted printer')
    await batch.locator('summary', { hasText: 'Details' }).click()
    await expect(batch).toContainText('My personal label')
    await expect(batch).not.toContainText('Other private label')
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 })
      await page.screenshot({
        path: `test-results/personal-activity-${width}.png`,
        fullPage: false,
        animations: 'disabled',
      })
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
        width,
      )
    }
    await batch.getByRole('link', { name: 'Details →', exact: true }).click()
    await expect(page.getByText('My personal label', { exact: true }).first()).toBeVisible()
    await expect(page.locator('main')).not.toContainText('Other private label')
    await adminPage.goto('/#/activity')
    const adminRequester = adminPage.getByRole('combobox', { name: 'Requester', exact: true })
    await expect(adminRequester).toBeEnabled()
    await expect(adminRequester).toHaveValue('')
  } finally {
    await context.close()
  }
})
