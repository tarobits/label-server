import { test, expect } from './fixtures'
import type { APIRequestContext, Locator, PlaywrightWorkerArgs } from '@playwright/test'

async function change(
  request: APIRequestContext,
  resource: string,
  payload: unknown,
  identifier?: string,
) {
  const method = identifier ? 'PUT' : 'POST'
  const preview = await request.post('/api/admin/access-preview', {
    data: { resource, method, payload, identifier },
  })
  expect(preview.ok(), await preview.text()).toBeTruthy()
  const saved = await request.fetch(`/api/admin/${resource}${identifier ? '/' + identifier : ''}`, {
    method,
    data: payload,
    headers: { 'X-Access-Confirmation': (await preview.json()).confirmation_token },
  })
  expect(saved.ok(), await saved.text()).toBeTruthy()
  return saved.json()
}

async function account(
  admin: APIRequestContext,
  playwright: PlaywrightWorkerArgs['playwright'],
  baseURL: string | undefined,
  destination: string,
  name: string,
  level: string,
) {
  const role = await change(admin, 'roles', {
    name: `${name} access`,
    permissions: [{ kind: 'destination', destination_id: destination, level }],
  })
  const password = 'browser-attribution-password'
  const user = await change(admin, 'users', { username: name, password, role_ids: [role.id] })
  const request = await playwright.request.newContext({
    baseURL,
    storageState: { cookies: [], origins: [] },
    extraHTTPHeaders: {},
  })
  const login = await request.post('/api/auth/login', { data: { username: name, password } })
  expect(login.ok()).toBeTruthy()
  const headers = { 'X-CSRF-Token': (await login.json()).csrf_token }
  return { request, headers, user }
}

async function people(root: Locator, requester: string, approver: string) {
  await expect(
    root.locator('.print-attribution > div').filter({ hasText: 'Requested by' }),
  ).toContainText(requester)
  await expect(
    root.locator('.print-attribution > div').filter({ hasText: 'Approved by' }),
  ).toContainText(approver)
}

test('activity separates label requester, approver, release and manual batch starter', async ({
  page,
  request,
  playwright,
  baseURL,
}) => {
  const [printer] = await (await request.get('/api/printers')).json()
  const [profile] = await (await request.get('/api/tape-profiles')).json()
  const requester = await account(request, playwright, baseURL, printer.id, 'requester', 'request')
  const operator = await account(request, playwright, baseURL, printer.id, 'operator', 'moderator')
  try {
    const submitted = await requester.request.post('/api/requests', {
      headers: requester.headers,
      data: {
        kind: 'job',
        input: {
          destination_id: printer.id,
          tape_profile: profile.id,
          data: { text: 'Approved history' },
        },
      },
    })
    expect(submitted.status(), await submitted.text()).toBe(201)
    const approval = await request.post(`/api/requests/${(await submitted.json()).id}/approve`)
    expect(approval.ok(), await approval.text()).toBeTruthy()
    const [jobId] = (await approval.json()).job_ids
    await change(request, 'users', { disabled: false, role_ids: [] }, requester.user.id)
    expect((await request.get('/api/access-holds')).ok()).toBeTruthy()
    expect((await request.post(`/api/access-holds/${jobId}/release`)).ok()).toBeTruthy()
    const flush = await operator.request.post(`/api/destinations/${printer.id}/print`, {
      headers: operator.headers,
    })
    expect(flush.status(), await flush.text()).toBe(202)
    await expect
      .poll(async () => (await (await request.get(`/api/jobs/${jobId}`)).json()).status)
      .toBe('printed')

    await page.goto('/#/activity')
    const batch = page.locator('.activity-batch').first()
    await people(batch, 'requester', 'owner')
    await expect(batch.locator('.batch-trigger')).toContainText('Manually started by operator')
    await expect(batch.locator('.release-attribution')).toContainText('owner')
    await page.screenshot({
      path: 'test-results/activity-attribution.png',
      fullPage: true,
      animations: 'disabled',
    })
    await batch.getByRole('link', { name: 'Details →' }).click()
    const row = page.locator('tbody tr').filter({ hasText: 'Approved history' })
    await people(row, 'requester', 'owner')
    await expect(row.locator('.release-attribution')).toContainText('owner')
    await expect(page.locator('.batch-trigger')).toContainText('Manually started by operator')
    await page.screenshot({
      path: 'test-results/label-attribution-desktop.png',
      fullPage: true,
      animations: 'disabled',
    })
    await page.setViewportSize({ width: 390, height: 844 })
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
      .toBe(true)
    await page.screenshot({ path: 'test-results/label-attribution-mobile.png', fullPage: true })
    await page.locator('.table-scroll').evaluate((element) => {
      const people = element.querySelector<HTMLElement>('.review-attribution')
      if (people) element.scrollLeft = people.offsetLeft
    })
    await page.screenshot({
      path: 'test-results/label-people-mobile.png',
      fullPage: true,
      animations: 'disabled',
    })

    // Direct submissions attribute both requested/approved fields to their submitter.
    const direct = await operator.request.post('/api/jobs', {
      headers: operator.headers,
      data: {
        destination_id: printer.id,
        tape_profile: profile.id,
        data: { text: 'Direct history' },
      },
    })
    expect(direct.status(), await direct.text()).toBe(201)
    const directId = (await direct.json()).id
    expect((await request.post(`/api/destinations/${printer.id}/print`)).status()).toBe(202)
    await expect
      .poll(async () => (await (await request.get(`/api/jobs/${directId}`)).json()).status)
      .toBe('printed')
    await page.goto('/#/activity')
    const latest = page.locator('.activity-batch').first()
    await people(latest, 'operator', 'operator')
    await expect(latest.getByText('Direct printing', { exact: false })).toBeVisible()
    await expect(latest.locator('.batch-trigger')).toContainText('Manually started by owner')
  } finally {
    await requester.request.dispose()
    await operator.request.dispose()
  }
})

test('administrator must confirm a draft author access discrepancy before overriding', async ({
  page,
  request,
  playwright,
  baseURL,
}) => {
  const [printer] = await (await request.get('/api/printers')).json()
  const [profile] = await (await request.get('/api/tape-profiles')).json()
  const author = await account(request, playwright, baseURL, printer.id, 'draftauthor', 'request')
  try {
    const prepared = await author.request.post('/api/runs/prepare', {
      headers: author.headers,
      data: {
        request_key: 'delegated-draft',
        name: 'Delegated draft',
        destination_id: printer.id,
        template: 'text',
        expected_revision: 2,
        tape_profile: profile.id,
        csv_text: 'Text\nDelegated history\n',
        mapping: { text: 'Text' },
        rows: [{ source_row: 2, copies: 1 }],
      },
    })
    expect(prepared.ok(), await prepared.text()).toBeTruthy()
    const run = (await prepared.json()).run
    await page.goto(`/#/runs/${run.id}`)
    await page.getByRole('button', { name: 'Submit entire run', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('administrator authorization')
    await expect(dialog).toContainText('draftauthor')
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    expect((await (await request.get(`/api/runs/${run.id}`)).json()).submitted_at).toBeNull()
    const queued = await (await request.get('/api/jobs')).json()
    expect(queued).toHaveLength(0)

    await page.getByRole('button', { name: 'Submit entire run', exact: true }).click()
    await expect(dialog).toBeVisible()
    await page.screenshot({
      path: 'test-results/delegated-print-confirmation.png',
      fullPage: true,
      animations: 'disabled',
    })
    await dialog.getByRole('button', { name: 'Confirm', exact: true }).click()
    await expect(page.getByText('Run submitted.', { exact: false })).toBeVisible()
    const [job] = await (await request.get('/api/jobs')).json()
    expect(job.owner_id).toBe(author.user.id)
    expect(job.attribution.authorization.kind).toBe('override')
    expect((await request.post(`/api/destinations/${printer.id}/print`)).status()).toBe(202)
    await expect
      .poll(async () => (await (await request.get(`/api/jobs/${job.id}`)).json()).status)
      .toBe('printed')
    await page.goto('/#/activity')
    const batch = page.locator('.activity-batch').first()
    await people(batch, 'draftauthor (owner)', 'owner')
    await expect(batch.getByText('Administrator override', { exact: false })).toBeVisible()
  } finally {
    await author.request.dispose()
  }
})
