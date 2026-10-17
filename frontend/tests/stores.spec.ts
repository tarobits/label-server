import type { APIRequestContext } from '@playwright/test'
import { test, expect } from './fixtures'

async function createMember(request: APIRequestContext) {
  const payload = {
    username: 'cache-member',
    password: 'cache-member-password',
    role_ids: ['member'],
  }
  const preview = await request.post('/api/admin/access-preview', {
    data: { resource: 'users', method: 'POST', payload },
  })
  expect(preview.ok()).toBeTruthy()
  const created = await request.post('/api/admin/users', {
    data: payload,
    headers: { 'X-Access-Confirmation': (await preview.json()).confirmation_token },
  })
  expect(created.ok()).toBeTruthy()
  return payload
}

test('catalogs are route-scoped and queue filters reuse cached reads until a mutation', async ({
  page,
  request,
}) => {
  const [profile] = await (await request.get('/api/tape-profiles')).json()
  expect(
    (
      await request.post('/api/jobs', {
        data: { tape_profile: profile.id, data: { text: 'Cached queue label' } },
      })
    ).ok(),
  ).toBeTruthy()
  const reads: string[] = []
  page.on('request', (outgoing) => {
    if (outgoing.method() === 'GET') {
      const url = new URL(outgoing.url())
      if (url.pathname.startsWith('/api/')) reads.push(url.pathname + url.search)
    }
  })
  await page.goto('/#/')
  await expect(page.getByRole('heading', { name: 'Your printers', exact: true })).toBeVisible()
  expect(
    reads.filter((path) =>
      ['/templates', '/font-assets', '/image-assets', '/notifications'].some(
        (catalog) => path === '/api' + catalog,
      ),
    ),
  ).toEqual([])

  await page
    .getByRole('navigation')
    .getByRole('link', { name: /^Print queue/ })
    .click()
  await expect(page.getByText('Cached queue label', { exact: true })).toBeVisible()
  const queuedReads = () =>
    reads.filter(
      (path) => path.startsWith('/api/queue/groups?') && path.includes('copy_state=queued'),
    ).length
  expect(queuedReads()).toBe(1)
  await page.getByRole('combobox', { name: 'Job status', exact: true }).selectOption('printed')
  await expect(
    page.getByRole('heading', { name: 'No printed labels here.', exact: true }),
  ).toBeVisible()
  await page.getByRole('combobox', { name: 'Job status', exact: true }).selectOption('queued')
  await expect(page.getByText('Cached queue label', { exact: true })).toBeVisible()
  expect(queuedReads()).toBe(1)
  await page.getByRole('link', { name: 'Tape profiles', exact: true }).click()
  await expect(page.getByRole('heading', { name: profile.name, exact: true })).toBeVisible()
  await page
    .getByRole('navigation')
    .getByRole('link', { name: /^Print queue/ })
    .click()
  await expect(page.getByText('Cached queue label', { exact: true })).toBeVisible()
  expect(queuedReads()).toBe(1)

  await page.getByRole('link', { name: 'New label', exact: true }).click()
  await page.getByLabel('Label text', { exact: true }).fill('Fresh after mutation')
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  await expect(page.getByText('Fresh after mutation', { exact: true })).toBeVisible()
  expect(queuedReads()).toBe(2)
})

test('request details avoid the list read and refresh immediately after approval', async ({
  page,
  request,
}) => {
  const [profile] = await (await request.get('/api/tape-profiles')).json()
  const created = await request.post('/api/requests', {
    data: { kind: 'job', input: { tape_profile: profile.id, data: { text: 'Cached request' } } },
  })
  expect(created.ok()).toBeTruthy()
  const pending = await created.json()
  const reads: string[] = []
  page.on('request', (outgoing) => {
    if (outgoing.method() === 'GET') reads.push(new URL(outgoing.url()).pathname)
  })
  await page.goto(`/#/requests/${pending.id}`)
  await expect(
    page.getByText('These labels are saved for review and have not entered the print queue.', {
      exact: true,
    }),
  ).toBeVisible()
  expect(reads.filter((path) => path === '/api/requests')).toHaveLength(0)
  expect(reads.filter((path) => path === `/api/requests/${pending.id}`)).toHaveLength(1)
  await page.getByRole('button', { name: 'Back to requests', exact: true }).click()
  await expect(page.getByText('Cached request', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'View request', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Approve and queue', exact: true })).toBeVisible()
  expect(reads.filter((path) => path === '/api/requests')).toHaveLength(1)
  expect(reads.filter((path) => path === `/api/requests/${pending.id}`)).toHaveLength(1)
  await page.getByRole('button', { name: 'Approve and queue', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(page.getByRole('link', { name: 'View print queue', exact: true })).toBeVisible()
  expect(reads.filter((path) => path === `/api/requests/${pending.id}`)).toHaveLength(2)
})

test('hidden tabs pause reads and resume dynamic queue updates on visibility', async ({ page }) => {
  const reads: string[] = []
  page.on('request', (outgoing) => {
    if (outgoing.method() === 'GET' && new URL(outgoing.url()).pathname.startsWith('/api/'))
      reads.push(outgoing.url())
  })
  await page.goto('/#/queue')
  await expect(
    page.getByRole('heading', { name: 'No queued labels here.', exact: true }),
  ).toBeVisible()
  const baseline = reads.length
  const queueBaseline = reads.filter((url) => new URL(url).pathname === '/api/queue/groups').length
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: true })
    document.dispatchEvent(new Event('visibilitychange'))
    window.dispatchEvent(new Event('focus'))
  })
  await page.waitForTimeout(5500)
  expect(reads).toHaveLength(baseline)
  await page.evaluate(() => {
    delete (document as unknown as Record<string, unknown>).hidden
    document.dispatchEvent(new Event('visibilitychange'))
    window.dispatchEvent(new Event('focus'))
  })
  await expect
    .poll(() => reads.filter((url) => new URL(url).pathname === '/api/queue/groups').length)
    .toBe(queueBaseline + 1)
  await expect(
    page.getByRole('heading', { name: 'No queued labels here.', exact: true }),
  ).toBeVisible()
})

test('a delayed private queue response cannot enter the next user session or cache', async ({
  page,
  request,
}) => {
  const member = await createMember(request)
  const [profile] = await (await request.get('/api/tape-profiles')).json()
  expect(
    (
      await request.post('/api/jobs', {
        data: { tape_profile: profile.id, data: { text: 'Private owner label' } },
      })
    ).ok(),
  ).toBeTruthy()
  let release!: () => void,
    ready!: () => void,
    complete!: () => void,
    delayed = false
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  const captured = new Promise<void>((resolve) => {
    ready = resolve
  })
  const delivered = new Promise<void>((resolve) => {
    complete = resolve
  })
  await page.route('**/api/queue/groups?*', async (route) => {
    if (delayed) return route.continue()
    delayed = true
    const original = await route.fetch()
    const body = await original.text()
    expect(body).toContain('Private owner label')
    ready()
    await gate
    await route.fulfill({ status: original.status(), contentType: 'application/json', body })
    complete()
  })
  try {
    await page.goto('/#/queue')
    await captured
    await page.getByRole('button', { name: 'Sign out', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
    await page.getByLabel('Username', { exact: true }).fill(member.username)
    await page.getByLabel('Password', { exact: true }).fill(member.password)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(
      page.getByRole('heading', { name: 'No queued labels here.', exact: true }),
    ).toBeVisible()
    release()
    await delivered
    await expect(page.getByText('Private owner label', { exact: true })).toHaveCount(0)
    await page.getByRole('link', { name: 'Print requests', exact: true }).click()
    await expect(
      page.getByRole('heading', { name: 'Your print requests', exact: true }),
    ).toBeVisible()
    await page.getByRole('link', { name: 'Print queue', exact: true }).click()
    await expect(
      page.getByRole('heading', { name: 'No queued labels here.', exact: true }),
    ).toBeVisible()
    await expect(page.getByText('Private owner label', { exact: true })).toHaveCount(0)
  } finally {
    release()
  }
})
