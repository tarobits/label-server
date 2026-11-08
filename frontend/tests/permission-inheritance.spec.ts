import { test, expect } from './fixtures'
import type { APIRequestContext } from '@playwright/test'
async function change(request: APIRequestContext, data: object) {
  const preview = await request.post('/api/resource-access/preview', { data })
  expect(preview.ok(), await preview.text()).toBeTruthy()
  const result = await request.post('/api/resource-access/apply', {
    data,
    headers: { 'X-Access-Confirmation': (await preview.json()).confirmation_token },
  })
  expect(result.ok(), await result.text()).toBeTruthy()
}
async function createUser(request: APIRequestContext) {
  const payload = { username: 'alice', password: 'browser-alice-password', role_ids: ['member'] }
  const preview = await request.post('/api/admin/access-preview', {
    data: { resource: 'users', method: 'POST', payload },
  })
  expect(preview.ok(), await preview.text()).toBeTruthy()
  const response = await request.post('/api/admin/users', {
    data: payload,
    headers: { 'X-Access-Confirmation': (await preview.json()).confirmation_token },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}
for (const width of [1280, 390]) {
  test(`location ownership, filters, overrides and access graph at ${width}px`, async ({
    page,
    request,
  }) => {
    await page.setViewportSize({ width, height: 900 })
    const alice = await createUser(request)
    const printer = (await (await request.get('/api/printers')).json())[0]
    const cartridge = (await (await request.get('/api/cartridges')).json())[0]
    await page.goto('/#/resource-access')
    await page.getByRole('button', { name: 'New location', exact: true }).click()
    let dialog = page.getByRole('dialog')
    await dialog.getByLabel('Location name').fill('Packing room')
    await dialog.getByRole('combobox', { name: 'Owner', exact: true }).selectOption(alice.id)
    await dialog.getByRole('button', { name: 'Review changes', exact: true }).click()
    dialog = page.getByRole('dialog', { name: 'Review access changes', exact: true })
    await dialog.getByRole('button', { name: 'Confirm access changes', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    let catalog = await (await request.get('/api/resource-access')).json()
    const room = catalog.locations.find((item: { name: string }) => item.name === 'Packing room')
    expect(room.owner_id).toBe(alice.id)
    await change(request, { kind: 'printer', identifier: printer.id, location_id: room.id })
    await change(request, { kind: 'cartridge', identifier: cartridge.id, location_id: room.id })
    await page.reload()
    await page.getByRole('button', { name: 'Manage Packing room', exact: true }).click()
    dialog = page.getByRole('dialog', { name: 'Packing room', exact: true })
    await dialog
      .getByRole('combobox', { name: 'User or role', exact: true })
      .selectOption('role:member')
    const printerRules = dialog.getByRole('group', { name: 'Printer permissions', exact: true })
    const cartridgeRules = dialog.getByRole('group', { name: 'Cartridge permissions', exact: true })
    await printerRules
      .getByRole('combobox', { name: 'View printer', exact: true })
      .selectOption('allow')
    await printerRules
      .getByRole('combobox', { name: 'Submit requests', exact: true })
      .selectOption('allow')
    await printerRules
      .getByRole('combobox', { name: 'Submit directly', exact: true })
      .selectOption('allow')
    await expect(
      printerRules.getByRole('combobox', { name: 'Submit requests', exact: true }),
    ).toHaveValue('inherit')
    await printerRules
      .getByRole('combobox', { name: 'Submit requests', exact: true })
      .selectOption('allow')
    await expect(
      printerRules.getByRole('combobox', { name: 'Submit directly', exact: true }),
    ).toHaveValue('inherit')
    await cartridgeRules
      .getByRole('combobox', { name: 'View cartridge', exact: true })
      .selectOption('allow')
    await cartridgeRules
      .getByRole('combobox', { name: 'Use cartridge', exact: true })
      .selectOption('allow')
    await dialog.getByRole('button', { name: 'Review changes', exact: true }).click()
    dialog = page.getByRole('dialog', { name: 'Review access changes', exact: true })
    await dialog.getByRole('button', { name: 'Confirm access changes', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    await page
      .getByRole('combobox', { name: 'Filter by owner', exact: true })
      .selectOption(alice.id)
    await expect(page.locator('tbody tr')).toHaveCount(1)
    await expect(page.locator('tbody')).toContainText('Packing room')
    await page.getByRole('combobox', { name: 'Filter by owner', exact: true }).selectOption('')
    await page
      .getByRole('combobox', { name: 'Filter by location', exact: true })
      .selectOption(room.id)
    await page.getByRole('combobox', { name: 'Show', exact: true }).selectOption('cartridge')
    await expect(page.locator('tbody tr')).toHaveCount(1)
    await page.getByRole('button', { name: `Manage ${cartridge.name}`, exact: true }).click()
    dialog = page.getByRole('dialog', { name: cartridge.name, exact: true })
    await dialog
      .getByRole('combobox', { name: 'User or role', exact: true })
      .selectOption(`user:${alice.id}`)
    await expect(dialog.getByText(/Saved: Has access through Packing room/).first()).toBeVisible()
    await dialog.getByRole('combobox', { name: 'Use cartridge', exact: true }).selectOption('deny')
    await dialog.getByRole('button', { name: 'Review changes', exact: true }).click()
    dialog = page.getByRole('dialog', { name: 'Review access changes', exact: true })
    await dialog.getByRole('button', { name: 'Confirm access changes', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    await page
      .getByRole('button', { name: `Permissions graph for ${cartridge.name}`, exact: true })
      .click()
    dialog = page.getByRole('dialog', { name: 'Permissions graph', exact: true })
    await dialog.getByRole('combobox', { name: 'User', exact: true }).selectOption(alice.id)
    await dialog
      .getByRole('combobox', { name: 'Permission', exact: true })
      .selectOption('cartridge.use')
    await expect(dialog.getByText('Deny · Applies', { exact: true })).toBeVisible()
    await expect(dialog.getByText('Allow · Overridden', { exact: true })).toBeVisible()
    await expect(dialog.getByText('Location: Packing room', { exact: true })).toBeVisible()
    await dialog
      .getByRole('combobox', { name: 'Resource', exact: true })
      .selectOption(`location:${room.id}`)
    await expect(dialog.getByText('Deny · Applies', { exact: true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
    await page.screenshot({
      path: `test-results/access-graph-${width}.png`,
      animations: 'disabled',
      fullPage: true,
    })
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    catalog = await (await request.get('/api/resource-access')).json()
    expect(
      catalog.resources
        .find((item: { id: string }) => item.id === cartridge.id)
        .grants.some((rule: { effect: string }) => rule.effect === 'deny'),
    ).toBeTruthy()
    await page.goto('/#/admin?section=roles')
    await page.getByRole('button', { name: 'New role', exact: true }).click()
    dialog = page.getByRole('dialog', { name: 'New role', exact: true })
    await dialog.getByLabel('Role name', { exact: true }).fill('Packing staff')
    await dialog.locator('summary').filter({ hasText: 'Packing room' }).click()
    await dialog.getByRole('combobox', { name: 'Use cartridge', exact: true }).selectOption('allow')
    await dialog
      .getByRole('combobox', { name: 'Configure printer', exact: true })
      .selectOption('deny')
    await dialog.getByRole('button', { name: 'Review role changes', exact: true }).click()
    await page.getByRole('button', { name: 'Confirm access changes', exact: true }).click()
    await expect(page.getByText('Role saved.', { exact: true })).toBeVisible()
    const role = (await (await request.get('/api/admin/roles')).json()).find(
      (item: { name: string }) => item.name === 'Packing staff',
    )
    expect(role.permissions).toEqual([
      {
        kind: 'location_permissions',
        location_id: room.id,
        permissions: ['cartridge.use'],
        denied_permissions: ['printer.configure'],
      },
    ])
    if (width < 600) {
      await page.getByRole('combobox', { name: 'Administration section' }).selectOption('users')
    } else {
      await page.getByRole('button', { name: 'Users', exact: true }).click()
    }
    await page.getByRole('link', { name: 'Permissions graph for alice', exact: true }).click()
    dialog = page.getByRole('dialog', { name: 'Permissions graph', exact: true })
    await expect(dialog.getByRole('combobox', { name: 'User', exact: true })).toHaveValue(alice.id)
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(dialog).not.toBeVisible()
  })
}
