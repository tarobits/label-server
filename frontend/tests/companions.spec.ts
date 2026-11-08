import { test, expect } from './fixtures'
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { createServer } from 'node:net'
import { resolve } from 'node:path'

async function location(request: import('@playwright/test').APIRequestContext) {
  const body = { kind: 'location', identifier: crypto.randomUUID(), name: 'Packing room' }
  const preview = await (await request.post('/api/resource-access/preview', { data: body })).json()
  expect(
    (
      await request.post('/api/resource-access/apply', {
        data: body,
        headers: { 'X-Access-Confirmation': preview.confirmation_token },
      })
    ).ok(),
  ).toBeTruthy()
  return body.identifier
}

for (const width of [1280, 390]) {
  test(`account PIN and companion controls retain validation and spacing at ${width}px`, async ({
    page,
    request,
  }) => {
    await page.setViewportSize({ width, height: 900 })
    await location(request)
    await page.goto('/#/account')
    const settings = page.getByRole('region', { name: 'Companion PIN', exact: true })
    await settings.getByRole('button', { name: 'Set PIN', exact: true }).click()
    await expect(
      settings.locator('.validation-summary, .field-error, [aria-invalid="true"]'),
    ).toHaveCount(0)
    await settings.getByLabel('Current password', { exact: true }).fill('browser-owner-password')
    await settings.getByLabel('New PIN', { exact: true }).fill('246810')
    await settings.getByLabel('Confirm PIN', { exact: true }).fill('246810')
    await settings.getByRole('button', { name: 'Save PIN', exact: true }).click()
    await expect(settings.getByRole('status')).toHaveText('PIN saved.')
    await expect(settings.getByLabel('New PIN', { exact: true })).not.toBeVisible()
    await settings.getByRole('button', { name: 'Change PIN', exact: true }).click()
    await expect(settings.getByLabel('New PIN', { exact: true })).toBeVisible()
    const validation = settings.locator('.validation-summary, .field-error, [aria-invalid="true"]')
    await expect(validation).toHaveCount(0)
    const saveButton = settings.getByRole('button', { name: 'Save PIN', exact: true })
    const removeButton = settings.getByRole('button', { name: 'Remove PIN', exact: true })
    const saveBox = (await saveButton.boundingBox())!
    const removeBox = (await removeButton.boundingBox())!
    expect(
      Math.max(removeBox.x - saveBox.x - saveBox.width, removeBox.y - saveBox.y - saveBox.height),
    ).toBeGreaterThanOrEqual(8)
    await saveButton.click()
    await expect(settings.locator('.validation-summary')).toBeVisible()
    await settings.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(settings.getByLabel('New PIN', { exact: true })).not.toBeVisible()
    await settings.getByRole('button', { name: 'Change PIN', exact: true }).click()
    await expect(settings.getByLabel('New PIN', { exact: true })).toBeVisible()
    await expect(settings.getByLabel('New PIN', { exact: true })).toHaveValue('')
    await expect(validation).toHaveCount(0)
    await page.screenshot({
      path: `test-results/pin-reopened-${width}.png`,
      fullPage: true,
      animations: 'disabled',
    })
    await settings.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(settings.getByLabel('New PIN', { exact: true })).not.toBeVisible()
    await page.goto('/#/companions')
    await page.getByRole('button', { name: 'Add companion', exact: true }).click()
    let dialog = page.getByRole('dialog', { name: 'Add companion', exact: true })
    await dialog.getByLabel('Name', { exact: true }).fill('Packing station')
    await dialog
      .getByRole('combobox', { name: 'Station user', exact: true })
      .selectOption({ label: 'owner' })
    await expect(dialog.getByText(/Anyone with the shared deployment PIN/)).toBeVisible()
    await dialog.getByRole('button', { name: 'Create companion', exact: true }).click()
    const keyDialog = page.getByRole('dialog', { name: 'Companion API key', exact: true })
    await expect(keyDialog).toBeVisible()
    const keyInput = keyDialog.getByLabel('API key', { exact: true })
    await keyInput.focus()
    const keyBox = (await keyInput.boundingBox())!
    const copyBox = (await keyDialog
      .getByRole('button', { name: 'Copy key', exact: true })
      .boundingBox())!
    expect(copyBox.y - keyBox.y - keyBox.height).toBeGreaterThanOrEqual(16)
    await page.screenshot({
      path: `test-results/companion-key-${width}.png`,
      mask: [keyInput],
      animations: 'disabled',
    })
    await keyDialog.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(keyDialog).not.toBeVisible()
    const addBox = (await page
      .getByRole('button', { name: 'Add companion', exact: true })
      .boundingBox())!
    const notice = page.getByRole('status').filter({ hasText: 'Companion saved.' })
    const noticeBox = (await notice.boundingBox())!
    expect(noticeBox.y - addBox.y - addBox.height).toBeGreaterThanOrEqual(16)
    await page.screenshot({
      path: `test-results/companion-spacing-${width}.png`,
      animations: 'disabled',
    })
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    dialog = page.getByRole('dialog', { name: 'Packing station', exact: true })
    await dialog
      .getByRole('combobox', { name: 'Station user', exact: true })
      .selectOption({ label: 'User picker' })
    await expect(dialog.getByText(/Anyone with the shared deployment PIN/)).not.toBeVisible()
    await dialog.getByRole('button', { name: 'Review changes', exact: true }).click()
    await expect(dialog.getByRole('button', { name: 'Confirm changes', exact: true })).toBeVisible()
    await page.setViewportSize({ width: 390, height: 844 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
    await page.screenshot({ path: 'test-results/companions-mobile.png', animations: 'disabled' })
    await dialog.getByRole('button', { name: 'Confirm changes', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    expect((await (await request.get('/api/companions')).json())[0].bound_user_id).toBeNull()
  })
}

test('station dashboard locks controls, prints a selected queue and swaps cartridges', async ({
  page,
  request,
  baseURL,
}) => {
  const locationId = await location(request)
  const user = (await (await request.get('/api/auth/session')).json()).user
  const station = await (
    await request.post('/api/companions', {
      data: { name: 'Packing station', location_id: locationId, bound_user_id: user.id },
    })
  ).json()
  const listener = createServer().listen(0, '127.0.0.1')
  await once(listener, 'listening')
  const address = listener.address()
  if (!address || typeof address === 'string') throw new Error('No station port')
  const port = address.port
  await new Promise<void>((done) => listener.close(() => done()))
  const url = `http://127.0.0.1:${port}`
  const server = spawn(
    resolve('../.venv/bin/python'),
    [resolve('../tests/companion_ui_server.py')],
    {
      cwd: resolve('..'),
      env: {
        ...process.env,
        PYTHONPATH: resolve('..'),
        LABEL_STATION_UI_PORT: String(port),
        LABEL_COMPANION_SERVER_URL: baseURL!,
        LABEL_COMPANION_PUBLIC_URL: url,
        LABEL_COMPANION_API_KEY: station.api_key,
        LABEL_COMPANION_SINGLE_USER_ID: user.id,
        LABEL_COMPANION_SHARED_PIN: '246810',
        LABEL_COMPANION_PRINTERS: '[]',
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    },
  )
  let output = ''
  server.stdout.on('data', (data) => (output += data))
  server.stderr.on('data', (data) => (output += data))
  try {
    await expect
      .poll(
        async () => {
          if (server.exitCode !== null)
            throw new Error(output.replaceAll(station.api_key, '[redacted]'))
          return fetch(`${url}/api/station`)
            .then((r) => r.json())
            .then((state) => state.online)
            .catch(() => false)
        },
        { timeout: 30000 },
      )
      .toBe(true)
    await page.context().setExtraHTTPHeaders({})
    await page.goto(url)
    await expect(page.getByRole('button', { name: 'Controls', exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: 'Unlock', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Unlock station', exact: true })
    await expect(dialog.getByLabel('User', { exact: true })).toHaveCount(0)
    await dialog.getByLabel('PIN', { exact: true }).fill('246810')
    await dialog.getByRole('button', { name: 'Unlock', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    await page.getByRole('button', { name: 'Add printer', exact: true }).click()
    const registration = page.getByRole('dialog', { name: 'Add printer', exact: true })
    await registration.getByLabel('Name', { exact: true }).fill('Station printer')
    await registration.getByLabel('USB serial', { exact: true }).fill('UI-STATION')
    await registration.getByRole('button', { name: 'Add printer', exact: true }).click()
    await expect(registration).not.toBeVisible()
    await expect(page.getByRole('heading', { name: 'Station printer', exact: true })).toBeVisible()
    const state = await (await fetch(`${url}/api/station`)).json()
    const printer = state.printers[0].id
    const [profile] = await (await request.get('/api/tape-profiles')).json()
    const cartridge = await (
      await request.post('/api/cartridges', {
        data: { profile_id: profile.id, name: 'Station cartridge', nominal_length_mm: 8000 },
      })
    ).json()
    await expect
      .poll(async () => {
        const response = await request.put(`/api/printer/active-tape?printer_id=${printer}`, {
          data: { cartridge_id: cartridge.id, move_location: false },
        })
        if (!response.ok()) {
          expect(response.status()).toBe(409)
          expect((await response.json()).detail).toBe('Printer is busy; try again when it is idle')
        }
        return response.ok()
      })
      .toBe(true)
    const original = await (
      await request.post('/api/jobs', {
        data: {
          destination_id: printer,
          tape_profile: profile.id,
          data: { text: 'Packing labels' },
          process_name: 'Packing labels',
          copies: 2,
        },
      })
    ).json()
    await page.getByRole('button', { name: 'Controls', exact: true }).click()
    const queue = page.getByRole('region', { name: 'Printer queue', exact: true })
    await expect(
      queue.getByRole('checkbox', { name: 'Packing labels 2 copies · owner', exact: true }),
    ).toBeVisible()
    await page.getByRole('button', { name: 'Hold printer', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Resume printer', exact: true })).toBeVisible()
    await queue.getByRole('checkbox').check()
    await page.screenshot({
      path: 'test-results/station-desktop.png',
      fullPage: true,
      animations: 'disabled',
    })
    await page.setViewportSize({ width: 390, height: 844 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
    await page.screenshot({
      path: 'test-results/station-mobile.png',
      fullPage: true,
      animations: 'disabled',
    })
    await page.getByRole('button', { name: 'Print selected (2)', exact: true }).click()
    await expect
      .poll(async () => (await (await request.get(`/api/jobs/${original.id}`)).json()).status, {
        timeout: 20000,
      })
      .toBe('printed')
    await page.getByRole('combobox', { name: 'Cartridge', exact: true }).selectOption(cartridge.id)
    // Status polling can briefly own the printer lock even after a batch completes.
    // Retry the same explicit UI operation when the server asks us to try again.
    await expect(async () => {
      await page.getByRole('button', { name: 'Install cartridge', exact: true }).click()
      const locationDialog = page.getByRole('dialog', { name: 'Cartridge location', exact: true })
      await locationDialog
        .getByRole('button', { name: 'Move location and install', exact: true })
        .click()
      await expect(locationDialog).not.toBeVisible()
      await expect(page.getByRole('status')).toHaveText('Cartridge installed.')
      await expect(page.getByRole('alert')).toHaveCount(0)
      expect(
        (await (await request.get('/api/cartridges')).json()).find(
          (c: { id: string }) => c.id === cartridge.id,
        ).location_id,
      ).toBe(locationId)
    }).toPass({ timeout: 15000 })
    await page.getByRole('button', { name: 'Configure printer', exact: true }).click()
    const configuration = page.getByRole('dialog', { name: 'Printer configuration', exact: true })
    await expect(configuration).toBeVisible()
    await configuration.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(configuration).not.toBeVisible()
    await page.getByRole('button', { name: 'Remove printer', exact: true }).click()
    const removal = page.getByRole('dialog', { name: 'Confirm action', exact: true })
    await removal.getByRole('button', { name: 'Remove printer', exact: true }).click()
    await expect(
      page.getByRole('heading', { name: 'Station printer', exact: true }),
    ).not.toBeVisible()
    await page.getByRole('button', { name: 'Restore printer', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Station printer', exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Lock', exact: true }).click()
    await expect(queue).not.toBeVisible()
    await expect(page.getByRole('heading', { name: 'Station printer', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Unlock', exact: true })).toBeVisible()
  } finally {
    if (server.exitCode === null) {
      const exited = once(server, 'exit')
      server.kill('SIGTERM')
      await exited
    }
  }
})
