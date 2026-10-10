import { test, expect } from './fixtures'

test('retry after a committed but lost response creates only one job', async ({ page }) => {
  await page.goto('/#/new?template=text')
  await page.getByLabel('Label text', { exact: true }).fill('Lost response')
  let firstKey = ''
  await page.route(
    '**/api/jobs',
    async (route) => {
      firstKey = route.request().headers()['idempotency-key'] ?? ''
      const committed = await route.fetch()
      expect(committed.status()).toBe(201)
      await route.abort('failed')
    },
    { times: 1 },
  )
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  expect(firstKey).not.toBe('')
  const retry = page.waitForRequest(
    (request) => request.url().endsWith('/api/jobs') && request.method() === 'POST',
  )
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  expect((await retry).headers()['idempotency-key']).toBe(firstKey)
  await expect(page).toHaveURL(/#\/queue$/)
  const jobs = await (await page.request.get('/api/jobs')).json()
  expect(jobs).toHaveLength(1)
  await page.goto('/#/new?template=text')
  await page.getByLabel('Label text', { exact: true }).fill('Intentional second job')
  const next = page.waitForRequest(
    (request) => request.url().endsWith('/api/jobs') && request.method() === 'POST',
  )
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  expect((await next).headers()['idempotency-key']).not.toBe(firstKey)
})

test('narrow tape elements fit the production printable band and print', async ({ page }) => {
  const tape = await (
    await page.request.post('/api/tape-profiles', {
      data: { name: 'Narrow tape', width_mm: 3.5, auto_print_threshold: 1 },
    })
  ).json()
  const cartridge = await (
    await page.request.post('/api/cartridges', {
      data: { name: 'Narrow', profile_id: tape.id, nominal_length_mm: 8000 },
    })
  ).json()
  await page.request.put('/api/printer/active-tape', { data: { cartridge_id: cartridge.id } })
  await page.request.put('/api/printer/mock', { data: { tape_width_mm: 3.5, connected: true } })
  await page.goto('/#/templates/new')
  await page.getByLabel('Template name', { exact: true }).fill('Narrow design')
  await page.getByRole('combobox', { name: 'Tape width (mm)', exact: true }).selectOption('3.5')
  await page.getByRole('button', { name: 'Add text', exact: true }).click()
  await page.getByLabel('Content', { exact: true }).fill('Narrow')
  expect(
    Number(await page.getByLabel('Height (mm)', { exact: true }).inputValue()),
  ).toBeGreaterThan(0)
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page).toHaveURL(/templates\/[^/]+\/edit/)
  const template = page.url().split('/templates/')[1].split('/')[0]
  const response = await page.request.post('/api/jobs', {
    data: { template, tape_profile: tape.id, data: {} },
  })
  expect(response.status()).toBe(201)
  const job = await response.json()
  await expect
    .poll(async () => (await (await page.request.get(`/api/jobs/${job.id}`)).json()).status)
    .toBe('printed')
})
