import { test, expect } from './fixtures'
import type { APIRequestContext } from '@playwright/test'

async function create(request: APIRequestContext, resource: string, payload: unknown) {
  const preview = await request.post('/api/admin/access-preview', {
    data: { resource, method: 'POST', payload },
  })
  expect(preview.ok(), await preview.text()).toBeTruthy()
  const result = await request.post(`/api/admin/${resource}`, {
    data: payload,
    headers: { 'X-Access-Confirmation': (await preview.json()).confirmation_token },
  })
  expect(result.ok(), await result.text()).toBeTruthy()
  return result.json()
}

test('operator requests missing price consent and requester accepts through the inbox', async ({
  page,
  request,
  browser,
  baseURL,
}) => {
  const [printer] = await (await request.get('/api/printers')).json()
  const [profile] = await (await request.get('/api/tape-profiles')).json()
  const [cartridge] = await (await request.get('/api/cartridges')).json()
  expect(
    (
      await request.put(`/api/cartridges/${cartridge.id}/price`, {
        data: { price_minor: 2000, currency: 'EUR' },
      })
    ).ok(),
  ).toBeTruthy()
  const role = await create(request, 'roles', {
    name: 'Print submitter',
    permissions: [
      {
        kind: 'destination_permissions',
        destination_id: printer.id,
        permissions: ['printer.view', 'printer.submit_directly'],
      },
    ],
  })
  await create(request, 'users', {
    username: 'requester',
    password: 'browser-requester-password',
    role_ids: ['member', role.id],
  })
  const context = await browser.newContext({
    baseURL,
    storageState: { cookies: [], origins: [] },
    extraHTTPHeaders: {},
  })
  try {
    const login = await context.request.post('/api/auth/login', {
      data: { username: 'requester', password: 'browser-requester-password' },
    })
    expect(login.ok()).toBeTruthy()
    const session = await login.json()
    const queued = await context.request.post('/api/jobs', {
      headers: { 'X-CSRF-Token': session.csrf_token },
      data: {
        destination_id: printer.id,
        tape_profile: profile.id,
        data: { text: 'Price approval label' },
        process_name: 'Price approval label',
        copies: 2,
      },
    })
    expect(queued.ok(), await queued.text()).toBeTruthy()
    const job = await queued.json()
    await page.goto('/#/queue')
    await page.getByRole('checkbox', { name: 'Select Price approval label', exact: true }).check()
    await page.getByRole('button', { name: /Print selected/ }).click()
    const confirm = page.getByRole('dialog', { name: 'Confirm action', exact: true })
    await expect(confirm).toContainText('no saved price')
    await confirm.getByRole('button', { name: 'Request price approval', exact: true }).click()
    await expect(
      page.getByRole('status').filter({ hasText: 'Price approval requested.' }),
    ).toBeVisible()
    expect((await (await request.get(`/api/jobs/${job.id}`)).json()).status).toBe('queued')
    const member = await context.newPage()
    await member.goto('/')
    await member.getByRole('button', { name: /Notifications/ }).click()
    const inbox = member.getByRole('dialog', { name: 'Notifications', exact: true })
    await inbox.getByRole('button', { name: /Printing needs your price approval/ }).click()
    const maximum = member.getByRole('spinbutton', { name: 'Maximum total (EUR)', exact: true })
    await expect(maximum).toBeVisible()
    await member.screenshot({
      path: 'test-results/cartridge-quote-desktop.png',
      fullPage: true,
      animations: 'disabled',
    })
    await member.setViewportSize({ width: 390, height: 844 })
    expect(await member.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      390,
    )
    await member.screenshot({
      path: 'test-results/cartridge-quote-mobile.png',
      fullPage: true,
      animations: 'disabled',
    })
    await member.getByRole('button', { name: 'Accept price', exact: true }).click()
    await expect(member.getByRole('status').filter({ hasText: /^Price accepted\.$/ })).toBeVisible()
    expect((await (await request.get(`/api/jobs/${job.id}`)).json()).status).toBe('queued')
    await page.getByRole('button', { name: /Print selected/ }).click()
    const consent = page.getByRole('dialog', { name: 'Approve cartridge use', exact: true })
    await expect(consent).toBeVisible()
    await consent.getByRole('checkbox').nth(0).check()
    await consent.getByRole('checkbox').nth(1).check()
    await consent.getByRole('button', { name: 'Approve selected copies', exact: true }).click()
    await expect
      .poll(async () => (await (await request.get(`/api/jobs/${job.id}`)).json()).status)
      .toBe('printed')
  } finally {
    await context.close()
  }
})
