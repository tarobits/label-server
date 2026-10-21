import { showEditorSettings } from './editor-settings'
import { test, expect } from './fixtures'

for (const mode of ['blocked', 'quota'] as const) {
  test(`workspace stays usable with ${mode} storage`, async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.addInitScript((mode) => {
      if (mode === 'blocked')
        Object.defineProperty(window, 'localStorage', {
          get() {
            throw new DOMException('Storage blocked', 'SecurityError')
          },
        })
      else
        Storage.prototype.setItem = () => {
          throw new DOMException('Storage full', 'QuotaExceededError')
        }
    }, mode)
    await page.goto('/#/')
    await expect(page.getByRole('heading', { name: 'Your printers', exact: true })).toBeVisible()
    await page.getByRole('link', { name: 'New label', exact: true }).click()
    await page.getByLabel('Label text', { exact: true }).fill('Storage fallback')
    await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
    await expect(page).toHaveURL(/#\/queue$/)
    expect(errors).toEqual([])
  })
}

test('editor drags ignore other pointers and recover after cancellation, capture loss, and blur', async ({
  page,
  request,
}) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  const created = await request.post('/api/templates', {
    data: {
      name: 'Gesture recovery',
      document: {
        length_mm: 90,
        elements: [{ id: 'box', kind: 'rectangle', x: 20, y: 5, width: 8, height: 4 }],
      },
    },
  })
  expect(created.ok()).toBe(true)
  const template = await created.json()
  await page.goto(`/#/templates/${template.id}/edit?element=box`)
  await showEditorSettings(page, 'Position & size')
  const canvas = page.locator('.editor-canvas')
  const boundary = page.locator('.object-boundary')
  const x = page.getByLabel('X (mm)', { exact: true })
  const begin = async () => {
    await boundary.scrollIntoViewIfNeeded()
    const box = (await boundary.boundingBox())!
    const start = { x: box.x + box.width / 2, y: box.y + box.height / 2 }
    await page.mouse.move(start.x, start.y)
    await page.mouse.down()
    return start
  }
  const start = await begin()
  await page.mouse.move(start.x + 16, start.y)
  await expect(x).toHaveValue('22')
  await boundary.dispatchEvent('pointerdown', {
    pointerId: 2,
    pointerType: 'touch',
    isPrimary: false,
    button: 0,
    clientX: start.x,
    clientY: start.y,
  })
  await canvas.dispatchEvent('pointermove', {
    pointerId: 2,
    pointerType: 'touch',
    clientX: start.x + 160,
    clientY: start.y,
  })
  await canvas.dispatchEvent('pointercancel', { pointerId: 2, pointerType: 'touch' })
  await expect(x).toHaveValue('22')
  await page.mouse.move(start.x + 24, start.y)
  await expect(x).toHaveValue('23')
  await page.mouse.up()
  for (const interruption of ['pointercancel', 'lostpointercapture', 'blur']) {
    const before = Number(await x.inputValue())
    const origin = await begin()
    await page.mouse.move(origin.x + 16, origin.y)
    await expect(x).toHaveValue(String(before + 2))
    if (interruption === 'blur') await page.evaluate(() => window.dispatchEvent(new Event('blur')))
    else await canvas.dispatchEvent(interruption, { pointerId: 1, pointerType: 'mouse' })
    await page.mouse.move(origin.x + 32, origin.y)
    await expect(x).toHaveValue(String(before + 2))
    expect(await canvas.evaluate((el) => el.hasPointerCapture(1))).toBe(false)
    await page.mouse.up()
  }
  const before = Number(await x.inputValue())
  const final = await begin()
  await page.mouse.move(final.x + 16, final.y)
  await page.mouse.up()
  await expect(x).toHaveValue(String(before + 2))
  await page.getByRole('button', { name: 'Undo', exact: true }).click()
  await expect(x).toHaveValue(String(before))
  expect(errors).toEqual([])
})

test('long names and multilingual content wrap within mobile cards and account controls', async ({
  page,
  request,
}) => {
  const name = '装置📦مرحبا' + 'X'.repeat(80)
  const created = await request.post('/api/templates', {
    data: { name, document: { elements: [] } },
  })
  expect(created.ok()).toBe(true)
  await page.route('**/api/auth/session', async (route) => {
    const response = await route.fetch()
    const session = await response.json()
    session.user.username = 'u'.repeat(64)
    await route.fulfill({ response, json: session })
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/#/templates')
  const card = page
    .locator('article')
    .filter({ has: page.getByRole('heading', { name, exact: true }) })
  await expect(card).toBeVisible()
  await page.screenshot({
    path: 'test-results/harden-long-names.png',
    fullPage: true,
    animations: 'disabled',
  })
  expect(await card.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.locator('.account-menu > summary').click()
  await expect(page.getByRole('button', { name: 'Sign out', exact: true })).toBeInViewport()
})

test('malformed API errors remain readable and failed submissions keep their input', async ({
  page,
}) => {
  await page.goto('/#/new')
  await page.getByLabel('Label text', { exact: true }).fill('Preserve this label')
  await page.route('**/api/jobs', (route) =>
    route.fulfill({
      status: 422,
      json: {
        detail: [
          null,
          { loc: 'broken', msg: 42 },
          { loc: ['body', 'copies'], msg: 'Choose fewer copies' },
        ],
      },
    }),
  )
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Choose fewer copies')
  await expect(page.getByLabel('Label text', { exact: true })).toHaveValue('Preserve this label')
})

test('request detail errors offer retry and failed previews can recover', async ({
  page,
  request,
}) => {
  const [printer] = await (await request.get('/api/printers')).json()
  const [profile] = await (await request.get('/api/tape-profiles')).json()
  const created = await request.post('/api/requests', {
    data: {
      kind: 'job',
      input: {
        destination_id: printer.id,
        tape_profile: profile.id,
        data: { text: 'Preview recovery' },
      },
    },
  })
  expect(created.ok(), await created.text()).toBe(true)
  const item = await created.json()
  let failDetail = true,
    failPreview = true
  await page.route(`**/api/requests/${item.id}`, async (route) => {
    if (failDetail) {
      failDetail = false
      await route.fulfill({ status: 503, json: { detail: 'Temporarily unavailable' } })
    } else await route.continue()
  })
  await page.route(`**/api/requests/${item.id}/labels/0/preview*`, async (route) => {
    if (failPreview) {
      failPreview = false
      await route.fulfill({ status: 503, body: 'Unavailable' })
    } else await route.continue()
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`/#/requests/${item.id}`)
  await expect(page.getByText('No pending requests.', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('alert')).toContainText('Temporarily unavailable')
  await page.screenshot({
    path: 'test-results/harden-request-load-error.png',
    animations: 'disabled',
  })
  await page.getByRole('alert').getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Retry preview', exact: true })).toBeVisible()
  await page.screenshot({
    path: 'test-results/harden-request-preview-error.png',
    animations: 'disabled',
  })
  await page.getByRole('button', { name: 'Retry preview', exact: true }).click()
  await expect
    .poll(() =>
      page.getByAltText('Requested label 1').evaluate((el: HTMLImageElement) => el.naturalWidth),
    )
    .toBeGreaterThan(0)
  await expect(page.getByRole('button', { name: 'Approve and queue', exact: true })).toBeEnabled()
})

test('template previews can retry a transient failure', async ({ page }) => {
  let fail = true
  await page.route('**/api/templates/text/preview.webp*', async (route) => {
    if (fail) {
      fail = false
      await route.fulfill({ status: 503, body: 'Unavailable' })
    } else await route.continue()
  })
  await page.goto('/#/templates')
  await page.getByRole('button', { name: 'Retry preview', exact: true }).click()
  await expect
    .poll(() =>
      page
        .getByAltText('Preview of Simple text')
        .evaluate((el: HTMLImageElement) => el.naturalWidth),
    )
    .toBeGreaterThan(0)
})

for (const mode of ['existing', 'new'] as const) {
  test(`${mode} templates keep edits made while a save is in flight`, async ({ page, request }) => {
    const existing =
      mode === 'existing'
        ? await (
            await request.post('/api/templates', {
              data: { name: 'Before save', document: { elements: [] } },
            })
          ).json()
        : null
    await page.goto(existing ? `/#/templates/${existing.id}/edit` : '/#/templates/new')
    const name = page.getByLabel('Template name', { exact: true })
    await name.fill('Submitted name')
    let release!: () => void, captured!: () => void
    const held = new Promise<void>((resolve) => (release = resolve))
    const intercepted = new Promise<void>((resolve) => (captured = resolve))
    let first = true
    await page.route(
      existing ? `**/api/templates/${existing.id}` : '**/api/templates',
      async (route) => {
        if (!first || route.request().method() !== (existing ? 'PUT' : 'POST'))
          return route.continue()
        first = false
        const response = await route.fetch()
        captured()
        await held
        await route.fulfill({ response })
      },
    )
    try {
      await page.getByRole('button', { name: 'Save template', exact: true }).click()
      await intercepted
      await name.fill('Edited during save')
      release()
      await expect(page.getByRole('button', { name: 'Save template', exact: true })).toBeEnabled()
      await expect(name).toHaveValue('Edited during save')
      await expect(page.getByText('Unsaved changes', { exact: true })).toBeVisible()
      const templates = await (await request.get('/api/templates')).json()
      expect(templates.some((item: { name: string }) => item.name === 'Submitted name')).toBe(true)
      await page.getByRole('button', { name: 'Save template', exact: true }).click()
      await expect(page.getByText('Unsaved changes', { exact: true })).toHaveCount(0)
      await expect(page).toHaveURL(/#\/templates\/[^/]+\/edit/)
      await expect(name).toHaveValue('Edited during save')
    } finally {
      release()
    }
  })
}

test('transport and unreadable responses preserve a submission retry key', async ({
  page,
  request,
}) => {
  await page.goto('/#/new')
  const text = page.getByLabel('Label text', { exact: true })
  await text.fill('Reliable submission')
  const keys: string[] = []
  await page.route('**/api/jobs', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    keys.push(route.request().headers()['idempotency-key']!)
    if (keys.length === 1) return route.abort('failed')
    if (keys.length === 2) return route.fulfill({ status: 429, body: 'Rate limited' })
    if (keys.length === 3)
      return route.fulfill({ status: 503, body: '<h1>Gateway unavailable</h1>' })
    const response = await route.fetch()
    if (keys.length === 4)
      return route.fulfill({ status: 201, body: '<h1>Unreadable success</h1>' })
    return route.fulfill({ response })
  })
  for (const message of [
    'Cannot reach the server.',
    'Too many requests.',
    'The server could not complete the request.',
    'The server returned an unreadable response. Check its status',
  ]) {
    await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText(message)
    await expect(text).toHaveValue('Reliable submission')
  }
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  await expect(page).toHaveURL(/#\/queue$/)
  expect(new Set(keys).size).toBe(1)
  expect(await (await request.get('/api/jobs')).json()).toHaveLength(1)
})

test('a timed-out submission stays under user control and can be retried', async ({
  page,
  request,
}) => {
  await page.addInitScript(() => {
    const fetch = window.fetch.bind(window)
    let timeout = true
    window.fetch = (input, options) => {
      if (timeout && input === '/api/jobs' && options?.method === 'POST') {
        timeout = false
        return Promise.reject(new DOMException('Timed out', 'TimeoutError'))
      }
      return fetch(input, options)
    }
  })
  await page.goto('/#/new')
  await page.getByLabel('Label text', { exact: true }).fill('Timeout recovery')
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('The request timed out. Check its status')
  expect(await (await request.get('/api/jobs')).json()).toHaveLength(0)
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  await expect(page).toHaveURL(/#\/queue$/)
  expect(await (await request.get('/api/jobs')).json()).toHaveLength(1)
})
