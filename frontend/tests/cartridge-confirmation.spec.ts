import { test, expect } from './fixtures'
import type { Page } from '@playwright/test'

const detected = '12 mm · Incompatible tape · White on Red'
const message =
  'Is this the correct cartridge?\n\nSelected: Yellow cassette 1 · Black on Yellow 24 mm · 24 mm\nDetected: ' +
  detected +
  '\n\nInstall supported TZe tape\nSelected width: 24 mm; detected width: 12 mm.\n\nConfirming uses the selected cartridge width for printing. Eligible queued labels may print.'

async function detection(page: Page, coverCheck = false) {
  let accepted = false
  let pending = coverCheck
  let enabled = true
  const attempts: { cartridge_id: string | null; media_confirmation?: string }[] = []
  await page.route('**/api/printers/status', async (route) => {
    const response = await route.fetch()
    const statuses = await response.json()
    await route.fulfill({
      json: statuses.map((status: object) => ({
        ...status,
        printer_error: coverCheck
          ? pending
            ? 'Confirm the installed cartridge'
            : null
          : accepted
            ? null
            : 'Install supported TZe tape',
        detected_width_mm: 12,
        effective_width_mm: accepted ? 24 : 12,
        detected_media: detected,
        media_warning: coverCheck ? null : 'Install supported TZe tape',
        media_confirmed: accepted,
        cartridge_check_enabled: enabled,
        cartridge_check_pending: pending,
        cartridge_check_ready: true,
        cartridge_check_key: 'cover-open-key',
        diagnostics: {
          Media: detected,
          'Media type': 'Incompatible tape · 0xff (255)',
          'Tape color': 'Red · 0x04 (4)',
          'Text color': 'White · 0x01 (1)',
          'Errors 1': 'None · 0x00 (0)',
          'Errors 2': 'None · 0x00 (0)',
          'Status type': 'Status reply · 0x00 (0)',
          'Raw status (32 bytes)':
            '80 20 42 30 6b 30 00 00 00 00 0c ff 00 00 00 00 00 00 00 00 00 00 00 00 04 01 00 00 00 00 00 00',
        },
      })),
    })
  })
  await page.route('**/api/printers/*/cartridge-check', async (route) => {
    enabled = route.request().postDataJSON().enabled
    if (!enabled) pending = false
    await route.fulfill({ json: {} })
  })
  await page.route('**/api/printer/active-tape?*', async (route) => {
    const body = route.request().postDataJSON()
    attempts.push(body)
    if (body.media_confirmation !== 'detection-token') {
      await route.fulfill({
        status: 409,
        json: {
          detail: {
            code: 'cartridge_mismatch',
            message: coverCheck
              ? 'The printer was opened. Is this still the correct cartridge?\n\nSelected: Yellow cassette 1\nDetected: ' +
                detected +
                '\n\nEligible queued labels may print.'
              : message,
            confirmation: 'detection-token',
          },
        },
      })
    } else {
      accepted = true
      pending = false
      await route.fulfill({ json: {} })
    }
  })
  return attempts
}

test('saving review accounts for tape without triggering installation confirmation', async ({
  page,
  request,
}) => {
  const [profile] = await (await request.get('/api/tape-profiles')).json()
  const [installed] = await (await request.get('/api/cartridges')).json()
  await request.put('/api/printer/mock', { data: { fail_after: 0 } })
  const job = await (
    await request.post('/api/jobs', {
      data: { tape_profile: profile.id, data: { text: 'Review accounting' } },
    })
  ).json()
  await request.post('/api/queue/print')
  await expect
    .poll(async () => (await (await request.get(`/api/jobs/${job.id}`)).json()).status)
    .toBe('needs_review')
  const [batch] = await (await request.get('/api/batches')).json()
  const attempts = await detection(page, true)
  await page.goto(`/#/batches/${batch.id}`)
  await page.getByLabel('Decision for label 1', { exact: true }).selectOption('cancelled')
  await page.getByLabel('Total tape consumed by this attempt (mm)', { exact: true }).fill('100')
  await page.screenshot({
    path: 'test-results/review-cartridge-accounting.png',
    fullPage: true,
    animations: 'disabled',
  })
  await page.getByRole('button', { name: 'Save review', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Save review', exact: true })).toHaveCount(0)
  await expect(page.getByRole('dialog', { name: 'Confirm action' })).not.toBeVisible()
  expect(attempts).toEqual([])
  const status = await (await request.get('/api/status')).json()
  expect(status.active_cartridge_id).toBe(installed.id)
  const cartridges = await (await request.get('/api/cartridges')).json()
  expect(cartridges.find((c: { id: string }) => c.id === installed.id).remaining_mm).toBe(7900)
  // The outstanding physical-cartridge check remains available as its own action.
  await page.getByRole('link', { name: 'Printers & groups', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Confirm action' })).toBeVisible()
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Confirm action' })).not.toBeVisible()
  expect(attempts).toHaveLength(1)
})

test('installed cartridge mismatch can be cancelled and then confirmed on printers', async ({
  page,
  request,
}) => {
  const attempts = await detection(page)
  const [profile] = await (await request.get('/api/tape-profiles')).json()
  await request.post('/api/jobs', {
    data: { tape_profile: profile.id, data: { text: 'Confirmed width' } },
  })
  await page.goto('/#/printers')
  await page.getByRole('button', { name: 'Confirm cartridge', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Confirm action' })
  await expect(dialog).toContainText('12 mm · Incompatible tape · White on Red')
  await expect(dialog).toContainText('Selected width: 24 mm; detected width: 12 mm.')
  await expect(dialog.getByRole('button', { name: 'Cancel', exact: true })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  expect(attempts).toHaveLength(1)
  await expect(page.getByRole('button', { name: 'Confirm cartridge', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: 'Confirm cartridge', exact: true }).click()
  await page.screenshot({
    path: 'test-results/cartridge-confirmation-desktop.png',
    animations: 'disabled',
  })
  await dialog.getByRole('button', { name: 'Yes, I’m sure', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await expect(page.getByText('Using confirmed cartridge.', { exact: true })).toBeVisible()
  expect(attempts.at(-1)?.media_confirmation).toBe('detection-token')
  await page.goto('/#/')
  await expect(page.getByRole('button', { name: 'Print direct queue', exact: true })).toBeEnabled()
  await expect(page.getByText('Detected tape width does not match', { exact: false })).toHaveCount(
    0,
  )
})

test('cover confirmation asks once across pages and can be disabled per printer', async ({
  page,
}) => {
  const attempts = await detection(page, true)
  await page.goto('/#/new')
  const dialog = page.getByRole('dialog', { name: 'Confirm action' })
  await expect(dialog).toContainText('The printer was opened. Is this still the correct cartridge?')
  await page.screenshot({
    path: 'test-results/cartridge-cover-confirmation.png',
    animations: 'disabled',
  })
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await page.goto('/#/printers')
  await expect(dialog).not.toBeVisible()
  expect(attempts).toHaveLength(1)
  await expect(page.getByRole('button', { name: 'Confirm cartridge', exact: true })).toBeEnabled()
  const toggle = page.getByRole('checkbox', {
    name: 'Confirm cartridge after opening',
    exact: true,
  })
  await expect(toggle).toBeChecked()
  await toggle.uncheck()
  await expect(toggle).not.toBeChecked()
  await expect(page.getByRole('button', { name: 'Confirm cartridge', exact: true })).toHaveCount(0)
  await expect(dialog).not.toBeVisible()
})

test('accepting the cover prompt acknowledges the current cartridge', async ({ page }) => {
  const attempts = await detection(page, true)
  await page.goto('/#/')
  const dialog = page.getByRole('dialog', { name: 'Confirm action' })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Yes, I’m sure', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  expect(attempts).toHaveLength(2)
  expect(attempts.at(-1)?.media_confirmation).toBe('detection-token')
  await page.goto('/#/printers')
  await expect(page.getByRole('button', { name: 'Confirm cartridge', exact: true })).toHaveCount(0)
})

test('cartridge confirmation works in inventory and cancelled dropdown selection is restored', async ({
  page,
  request,
}) => {
  const attempts = await detection(page)
  const [profile] = await (await request.get('/api/tape-profiles')).json()
  const cart = await (
    await request.post('/api/cartridges', {
      data: {
        profile_id: profile.id,
        name: 'Third-party cassette',
        nominal_length_mm: 8000,
      },
    })
  ).json()
  await page.goto('/#/printers')
  const selector = page.getByRole('combobox', { name: 'Installed cartridge', exact: true })
  const original = await selector.inputValue()
  await selector.selectOption(cart.id)
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(selector).toHaveValue(original)
  await page.goto('/#/cartridges')
  const card = page
    .locator('article')
    .filter({ has: page.getByRole('heading', { name: 'Third-party cassette', exact: true }) })
  await card.getByRole('button', { name: 'Install cartridge', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click()
  expect(attempts.at(-1)?.media_confirmation).toBeUndefined()
  await page.getByRole('button', { name: 'Confirm cartridge', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Yes, I’m sure', exact: true }).click()
  await expect(page.getByText('Using confirmed cartridge.', { exact: true })).toBeVisible()
})

test('printer detection details show raw and decoded status with desktop and mobile closing interactions', async ({
  page,
}) => {
  await detection(page)
  await page.goto('/#/printers')
  const opener = page.getByRole('button', { name: 'Detected details', exact: true })
  await opener.click()
  const dialog = page.getByRole('dialog', { name: 'Desk printer · Detected details', exact: true })
  await expect(dialog).toContainText('Incompatible tape · 0xff (255)')
  await expect(dialog).toContainText('Red · 0x04 (4)')
  await expect(dialog).toContainText('White · 0x01 (1)')
  await expect(dialog).toContainText('Raw status (32 bytes)')
  await expect(dialog).toContainText('80 20 42 30 6b 30')
  await page.screenshot({
    path: 'test-results/printer-detection-desktop.png',
    animations: 'disabled',
  })
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  await expect(opener).toBeFocused()
  await page.setViewportSize({ width: 390, height: 844 })
  await opener.click()
  await expect(dialog).toBeVisible()
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
  await page.screenshot({
    path: 'test-results/printer-detection-mobile.png',
    animations: 'disabled',
  })
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await expect(opener).toBeFocused()
  await page.getByRole('button', { name: 'Confirm cartridge', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Confirm action' })).toBeVisible()
  await page.screenshot({
    path: 'test-results/cartridge-confirmation-mobile.png',
    animations: 'disabled',
  })
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click()
})
