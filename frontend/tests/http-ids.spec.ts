import { test, expect } from './fixtures'

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

test.beforeEach(async ({ page }) => {
  // Match HTTP LAN origins, where randomUUID is absent but getRandomValues exists.
  await page.addInitScript(() => {
    Object.defineProperty(window.crypto, 'randomUUID', { value: undefined, configurable: true })
  })
})

test('HTTP label submission keeps its retry key after a committed response is lost', async ({
  page,
  request,
}) => {
  const errors: string[] = []
  const previewFailures: number[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('response', (response) => {
    if (response.url().endsWith('/api/preview') && !response.ok())
      previewFailures.push(response.status())
  })
  const keys: string[] = []
  await page.route('**/api/jobs', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    keys.push(route.request().headers()['idempotency-key'] ?? '')
    const response = await route.fetch()
    expect(response.status()).toBe(201)
    if (keys.length === 1)
      await route.fulfill({ status: 503, json: { detail: 'Simulated lost submission response' } })
    else await route.fulfill({ response })
  })

  await page.goto('/#/new?template=text')
  await expect(page.getByText('Label text is required', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Add to queue', exact: true })).toBeDisabled()
  await page.getByLabel('Label text', { exact: true }).fill('HTTP retry label')
  await expect(page.getByAltText('Rendered label preview')).toBeVisible()
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Simulated lost submission response')
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  await expect(page).toHaveURL(/#\/queue$/)

  expect(keys).toHaveLength(2)
  expect(keys[0]).toMatch(uuid)
  expect(keys[1]).toBe(keys[0])
  const jobs = await (await request.get('/api/jobs')).json()
  expect(jobs).toHaveLength(1)
  expect(jobs[0].payload.text).toBe('HTTP retry label')
  expect(previewFailures).toEqual([])
  expect(errors).toEqual([])
})

test('HTTP editor creates and duplicates elements with distinct UUIDs', async ({
  page,
  request,
}) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/#/templates/new')
  await page.getByLabel('Template name', { exact: true }).fill('HTTP editor template')
  await page.getByRole('button', { name: 'Add text', exact: true }).click()
  await page.getByRole('button', { name: 'Arrange', exact: true }).click()
  await page.getByRole('button', { name: 'Duplicate element', exact: true }).click()
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page).toHaveURL(/#\/templates\/[^/]+\/edit/)
  const id = page.url().split('/templates/')[1]!.split('/')[0]!
  const template = await (await request.get(`/api/templates/${id}`)).json()
  const ids = template.document.elements.map((element: { id: string }) => element.id)
  expect(ids).toHaveLength(2)
  expect(new Set(ids).size).toBe(2)
  for (const id of ids) expect(id).toMatch(uuid)
  expect(errors).toEqual([])
})

test('HTTP CSV preparation retries reuse the saved draft without queuing labels', async ({
  page,
  request,
}) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  const keys: string[] = []
  await page.route('**/api/runs/prepare', async (route) => {
    keys.push(route.request().postDataJSON().request_key)
    const response = await route.fetch()
    expect(response.ok()).toBeTruthy()
    if (keys.length === 1)
      await route.fulfill({ status: 503, json: { detail: 'Simulated lost draft response' } })
    else await route.fulfill({ response })
  })
  await page.goto('/#/runs')
  await page.getByLabel('Run name', { exact: true }).fill('HTTP CSV draft')
  await page.getByLabel('CSV content', { exact: true }).fill('text\nFirst\nSecond')
  await page.getByRole('button', { name: 'Read CSV', exact: true }).click()
  await page.getByRole('button', { name: 'Validate and preview run', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Simulated lost draft response')
  await page.getByRole('button', { name: 'Validate and preview run', exact: true }).click()
  await expect(page).toHaveURL(/#\/runs\/[^/]+$/)
  await expect(page.getByAltText('CSV label preview')).toBeVisible()
  expect(keys).toHaveLength(2)
  expect(keys[0]).toMatch(uuid)
  expect(keys[1]).toBe(keys[0])
  expect(await (await request.get('/api/runs')).json()).toHaveLength(1)
  expect(await (await request.get('/api/jobs')).json()).toEqual([])
  expect(errors).toEqual([])
})
