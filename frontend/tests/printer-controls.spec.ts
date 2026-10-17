import { test, expect } from './fixtures'
import type { APIRequestContext, Page } from '@playwright/test'

async function simulateActivePrinter(page: Page, printerId: string) {
  let mode: 'after_current' | 'emergency' | null = null
  const calls: { printerId: string; mode: string }[] = []
  await page.route('**/api/printers/status', async (route) => {
    const response = await route.fetch()
    const statuses = await response.json()
    await route.fulfill({
      response,
      json: statuses.map((status: { printer_id: string }) =>
        status.printer_id === printerId
          ? {
              ...status,
              printing: 'simulated-active-batch',
              stop_requested: mode,
              automatic_printing_held: mode !== null,
            }
          : status,
      ),
    })
  })
  await page.route('**/api/printers/*/stop', async (route) => {
    expect(route.request().method()).toBe('POST')
    const requestedId = decodeURIComponent(new URL(route.request().url()).pathname.split('/')[3])
    const requestedMode = route.request().postDataJSON().mode
    calls.push({ printerId: requestedId, mode: requestedMode })
    expect(requestedId).toBe(printerId)
    expect(['after_current', 'emergency']).toContain(requestedMode)
    mode = requestedMode
    await route.fulfill({ status: 202, json: { printer_id: printerId, stop_requested: mode } })
  })
  return calls
}

async function adminCreate(request: APIRequestContext, resource: string, payload: unknown) {
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

test('physical printer controls stop after a label, upgrade to emergency, and explain manual cutting', async ({
  page,
  request,
}) => {
  const printer = (await (await request.get('/api/printers')).json())[0]
  const otherResponse = await request.post('/api/printers', {
    data: { name: 'Other printer', usb_serial: 'UI-OTHER-CONTROLS' },
  })
  expect(otherResponse.ok(), await otherResponse.text()).toBeTruthy()
  const other = await otherResponse.json()
  // The legacy selection points elsewhere; each card must still target its physical printer.
  await page.addInitScript((id) => localStorage.setItem('selectedPrinter', id), other.id)
  const calls = await simulateActivePrinter(page, printer.id)
  await page.setViewportSize({ width: 1440, height: 1100 })
  await page.goto('/#/')
  const device = page.getByRole('article', { name: `Printer ${printer.name}`, exact: true })
  const idle = page.getByRole('article', { name: 'Printer Other printer', exact: true })
  const stop = device.getByRole('button', { name: 'Stop after current label', exact: true })
  const emergency = device.getByRole('button', { name: 'Emergency stop', exact: true })
  await expect(stop).toBeEnabled()
  await expect(emergency).toBeEnabled()
  await expect(idle.getByRole('button', { name: 'Stop after current label' })).toBeDisabled()
  await expect(idle.getByRole('button', { name: 'Emergency stop', exact: true })).toBeDisabled()
  await expect(device.getByRole('button', { name: 'Cut tape', exact: true })).toBeDisabled()
  await expect(device).toContainText('Manual cut over USB is unavailable.')
  await expect(device).toContainText('double-press the printer’s power button to feed and cut.')
  await stop.click()
  await expect(stop).toBeDisabled()
  await expect(device.getByRole('status')).toHaveText(
    'Stopping after the current label. The remaining batch will need review.',
  )
  await expect(device.getByRole('button', { name: 'Resume automatic printing' })).toBeDisabled()
  await expect(emergency).toBeEnabled()
  await expect(idle.getByRole('button', { name: 'Hold automatic printing' })).toBeEnabled()
  await expect(idle.getByRole('status')).toHaveCount(0)
  expect(calls).toEqual([{ printerId: printer.id, mode: 'after_current' }])
  await emergency.click()
  await expect(emergency).toBeDisabled()
  await expect(stop).toBeDisabled()
  await expect(device.getByRole('status')).toHaveText(
    'Emergency stop requested. The current label may finish. Review the batch before printing again.',
  )
  expect(calls).toEqual([
    { printerId: printer.id, mode: 'after_current' },
    { printerId: printer.id, mode: 'emergency' },
  ])
  // All simulated control requests were intercepted; the isolated backend remains idle.
  const statuses = await (await request.get('/api/printers/status')).json()
  expect(
    statuses.every(
      (status: { printing: string | null; automatic_printing_held: boolean }) =>
        status.printing === null && !status.automatic_printing_held,
    ),
  ).toBe(true)
  await page.screenshot({ path: 'test-results/printer-stop-controls.png', fullPage: true })
})

test('printer moderators can stop after the current label without emergency or cutter controls', async ({
  request,
  browser,
  baseURL,
}) => {
  const printer = (await (await request.get('/api/printers')).json())[0]
  const role = await adminCreate(request, 'roles', {
    name: 'Desk queue moderators',
    permissions: [{ kind: 'destination', destination_id: printer.id, level: 'moderator' }],
  })
  await adminCreate(request, 'users', {
    username: 'queuemoderator',
    password: 'queue-moderator-password',
    role_ids: [role.id],
  })
  const context = await browser.newContext({
    baseURL,
    storageState: { cookies: [], origins: [] },
    extraHTTPHeaders: {},
  })
  try {
    const page = await context.newPage()
    const calls = await simulateActivePrinter(page, printer.id)
    await page.goto('/#/')
    await page.getByLabel('Username', { exact: true }).fill('queuemoderator')
    await page.getByLabel('Password', { exact: true }).fill('queue-moderator-password')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    const device = page.getByRole('article', { name: `Printer ${printer.name}`, exact: true })
    await expect(device).toBeVisible()
    const stop = device.getByRole('button', { name: 'Stop after current label', exact: true })
    await expect(stop).toBeEnabled()
    await expect(device.getByRole('button', { name: 'Emergency stop', exact: true })).toHaveCount(0)
    await expect(device.getByRole('button', { name: 'Cut tape', exact: true })).toHaveCount(0)
    await expect(device.getByRole('link', { name: 'Configure', exact: true })).toHaveCount(0)
    await stop.click()
    await expect(stop).toBeDisabled()
    expect(calls).toEqual([{ printerId: printer.id, mode: 'after_current' }])
  } finally {
    await context.close()
  }
})
