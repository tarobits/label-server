import { test, expect } from './fixtures'

const message = 'The label server is currently unable to be reached.'

test('cached app opens offline and reconnects without a reload', async ({ page, context }) => {
  await page.goto('/#/queue')
  await page.evaluate(() => navigator.serviceWorker.ready.then(() => undefined))
  await context.setOffline(true)
  await page.reload()
  const unavailable = page.getByRole('dialog', { name: 'Server unavailable' })
  await expect(unavailable).toBeVisible({ timeout: 10000 })
  await expect(unavailable).toContainText(message)
  await page.keyboard.press('Escape')
  await expect(unavailable).toBeVisible()
  await page.evaluate(() => document.body.setAttribute('data-preserved', 'offline-launch'))
  for (const [name, width, height] of [
    ['phone', 390, 844],
    ['tablet', 820, 1180],
  ] as const) {
    await page.setViewportSize({ width, height })
    await page.screenshot({ path: `test-results/offline-${name}.png`, animations: 'disabled' })
  }
  await context.setOffline(false)
  await expect(unavailable).not.toBeVisible({ timeout: 10000 })
  await expect(page.getByRole('heading', { name: 'Print queue', exact: true })).toBeVisible()
  await expect(page.locator('body')).toHaveAttribute('data-preserved', 'offline-launch')
  await expect(page).toHaveURL(/#\/queue$/)
})

test('outage and recovery preserve a mounted editor, its draft and keyboard focus', async ({
  page,
  context,
}) => {
  await page.goto('/#/templates/new')
  const name = page.getByLabel('Template name', { exact: true })
  await name.fill('Keep this unsaved draft')
  await name.evaluate((element) => element.setAttribute('data-preserved', 'editor'))
  await context.setOffline(true)
  const unavailable = page.getByRole('dialog', { name: 'Server unavailable' })
  await expect(unavailable).toBeVisible({ timeout: 10000 })
  await expect(unavailable).toHaveCSS('animation-name', 'dialog-arrive')
  await expect(unavailable).toHaveCSS('transition-duration', '0.1s, 0.1s, 0.1s, 0.1s')
  await context.setOffline(false)
  await expect(unavailable).not.toBeVisible({ timeout: 10000 })
  await expect(name).toHaveValue('Keep this unsaved draft')
  await expect(name).toHaveAttribute('data-preserved', 'editor')
  await expect(name).toBeFocused()
})

for (const status of [502, 530, 200]) {
  test(`proxy HTML with status ${status} uses the cached unavailable screen and supports Retry`, async ({
    page,
    request,
  }) => {
    await page.goto('/#/templates')
    await page.evaluate(() => navigator.serviceWorker.ready.then(() => undefined))
    expect((await request.post('/api/test/outage', { data: { status } })).ok()).toBe(true)
    const origin = await request.get('/')
    expect(origin.status()).toBe(status)
    expect(await origin.text()).toContain('Cloudflare error 1033')
    await page.reload()
    const unavailable = page.getByRole('dialog', { name: 'Server unavailable' })
    await expect(unavailable).toContainText(message, { timeout: 10000 })
    await expect(unavailable).toBeVisible()
    await unavailable.getByRole('button', { name: 'Retry' }).click()
    await expect(unavailable).toBeVisible()
    expect((await request.post('/api/test/outage', { data: { status: null } })).ok()).toBe(true)
    // A tunnel can recover without an online event on the device.
    if (status !== 530) await unavailable.getByRole('button', { name: 'Retry' }).click()
    await expect(unavailable).not.toBeVisible({ timeout: 10000 })
    await expect(page.getByRole('heading', { name: 'Templates', exact: true })).toBeVisible()
    expect((await request.get('/api/not-a-route')).status()).toBe(404)
    expect((await request.get('/openapi.json')).headers()['content-type']).toContain(
      'application/json',
    )
  })
}

test('an expired session is handled as authentication, not server unavailability', async ({
  page,
}) => {
  await page.route('**/api/workspace', (route) =>
    route.fulfill({ status: 401, json: { detail: 'Sign in to continue' } }),
  )
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible()
  await expect(page.getByRole('dialog', { name: 'Server unavailable' })).not.toBeVisible()
})

test('an isolated API failure keeps its normal error when the server is healthy', async ({
  page,
}) => {
  await page.route('**/api/workspace', (route) =>
    route.fulfill({ status: 500, json: { detail: 'Workspace failed' } }),
  )
  await page.goto('/')
  await expect(page.getByRole('alert')).toContainText('Workspace failed')
  await expect(page.getByRole('dialog', { name: 'Server unavailable' })).not.toBeVisible()
})

test('a failed label submission is not replayed when the server returns', async ({
  page,
  request,
}) => {
  await page.goto('/#/new')
  await page.getByLabel('Label text', { exact: true }).fill('Do not replay this label')
  let submissions = 0
  await page.route('**/api/jobs', async (route) => {
    if (route.request().method() === 'POST') {
      submissions++
      expect((await request.post('/api/test/outage', { data: { status: 502 } })).ok()).toBe(true)
    }
    await route.continue()
  })
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  const unavailable = page.getByRole('dialog', { name: 'Server unavailable' })
  await expect(unavailable).toBeVisible()
  expect(submissions).toBe(1)
  expect((await request.post('/api/test/outage', { data: { status: null } })).ok()).toBe(true)
  await unavailable.getByRole('button', { name: 'Retry' }).click()
  await expect(unavailable).not.toBeVisible()
  await expect(page.getByLabel('Label text', { exact: true })).toHaveValue(
    'Do not replay this label',
  )
  expect(await (await request.get('/api/jobs')).json()).toEqual([])
  expect(submissions).toBe(1)
})
