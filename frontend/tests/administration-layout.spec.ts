import { test, expect } from './fixtures'
import type { APIRequestContext } from '@playwright/test'

async function change(request: APIRequestContext, resource: string, payload: unknown) {
  const preview = await request.post('/api/admin/access-preview', {
    data: { resource, method: 'POST', payload },
  })
  expect(preview.ok()).toBeTruthy()
  const response = await request.post(`/api/admin/${resource}`, {
    data: payload,
    headers: { 'X-Access-Confirmation': (await preview.json()).confirmation_token },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}

test('administration isolates sections and keeps account editing focused and reversible', async ({
  page,
  request,
}) => {
  for (let index = 1; index <= 8; index++) {
    await change(request, 'users', {
      username: `operator${index}`,
      password: 'operator-password-123',
      role_ids: ['member'],
    })
  }
  await page.goto('/#/admin')
  const nav = page.getByRole('navigation', { name: 'Administration sections' })
  await expect(nav.getByRole('heading', { name: 'Accounts', exact: true })).toBeVisible()
  await expect(nav.getByRole('heading', { name: 'General', exact: true })).toBeVisible()
  await expect(nav.getByRole('button', { name: 'Users', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  )
  await expect(page.getByLabel('Role name', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Edit operator8', exact: true })).toBeVisible()
  await page.screenshot({
    animations: 'disabled',
    path: 'test-results/administration-users-desktop.png',
    fullPage: true,
  })
  const edit = page.getByRole('button', { name: 'Edit operator8', exact: true })
  await edit.click()
  const editor = page.getByRole('dialog', { name: 'Edit operator8', exact: true })
  await expect(editor).toBeVisible()
  await expect(editor.getByRole('checkbox', { name: 'Disable account', exact: true })).toBeFocused()
  await expect(
    editor.getByRole('button', { name: 'Review account changes', exact: true }),
  ).toBeDisabled()
  await page.keyboard.press('Shift+Tab')
  await page.keyboard.press('Shift+Tab')
  expect(await editor.evaluate((element) => element.contains(document.activeElement))).toBe(true)
  await page.keyboard.press('Escape')
  await expect(editor).toBeHidden()
  await expect(edit).toBeFocused()
  await edit.click()
  await editor.getByRole('checkbox', { name: 'Disable account', exact: true }).check()
  await editor.getByRole('button', { name: 'Review account changes', exact: true }).click()
  const review = page.getByRole('dialog', { name: 'Review effective access', exact: true })
  await expect(review.getByRole('row')).toHaveCount(2)
  await expect(review.getByText('operator8', { exact: true })).toBeVisible()
  await expect(review.getByText('operator1', { exact: true })).toBeHidden()
  await review.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(editor.getByRole('checkbox', { name: 'Disable account', exact: true })).toBeChecked()
  await editor.getByRole('button', { name: 'Review account changes', exact: true }).click()
  await review.getByRole('button', { name: 'Confirm access changes', exact: true }).click()
  await expect(editor).toBeHidden()
  await expect(edit).toBeFocused()
  expect(
    (await (await request.get('/api/admin/users')).json()).find(
      (user: { username: string }) => user.username === 'operator8',
    ).disabled,
  ).toBe(true)
  await page.getByLabel('Search users', { exact: true }).fill('operator8')
  await expect(page.getByRole('button', { name: /^Edit / })).toHaveCount(1)
  await nav.getByRole('button', { name: 'Roles', exact: true }).click()
  await expect(page.getByLabel('Search users', { exact: true })).toHaveCount(0)
  await expect(page).toHaveURL(/section=roles/)
  await page.reload()
  await expect(nav.getByRole('button', { name: 'Roles', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  )
})

test('role summaries and collaboration modal stay compact across desktop and mobile', async ({
  page,
  request,
}) => {
  const printers = await (await request.get('/api/printers')).json()
  await change(request, 'roles', {
    name: 'Print operators',
    permissions: [{ kind: 'destination', destination_id: printers[0].id, level: 'print' }],
  })
  const members = []
  for (const username of ['alex', 'lois', 'mika']) {
    const user = await change(request, 'users', {
      username,
      password: 'operator-password-123',
      role_ids: ['member'],
    })
    members.push({
      user_id: user.id,
      can_create: true,
      can_edit_others: false,
      can_delete_others: false,
    })
  }
  await change(request, 'groups', { name: 'Cable team', members })
  await page.goto('/#/admin?section=roles')
  await expect(page.getByText('Desk printer · Print', { exact: true })).toBeVisible()
  await expect(page.getByText('permission objects', { exact: false })).toHaveCount(0)
  await page.getByRole('button', { name: 'Edit role Print operators', exact: true }).click()
  const role = page.getByRole('dialog')
  await expect(role.getByLabel('Role name', { exact: true })).toBeFocused()
  await expect(
    role.getByRole('button', { name: 'Review role changes', exact: true }),
  ).toBeDisabled()
  await role.getByLabel('Role name', { exact: true }).fill('Print staff')
  await role.getByRole('button', { name: 'Review role changes', exact: true }).click()
  const review = page.getByRole('dialog', { name: 'Review effective access', exact: true })
  await expect(review.getByText('No effective access changes.', { exact: true })).toBeVisible()
  await review.getByRole('button', { name: 'Cancel', exact: true }).click()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Content groups', exact: true }).click()
  await page.getByRole('button', { name: 'Edit group Cable team', exact: true }).click()
  const group = page.getByRole('dialog', { name: 'Edit Cable team', exact: true })
  await expect(
    group.getByRole('button', { name: 'Review group changes', exact: true }),
  ).toBeDisabled()
  await page.screenshot({
    animations: 'disabled',
    path: 'test-results/administration-group-desktop.png',
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBeLessThanOrEqual(390)
  expect(await group.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
  await page.screenshot({
    animations: 'disabled',
    path: 'test-results/administration-group-mobile.png',
  })
  await group
    .getByRole('checkbox', { name: 'Allow alex to edit others’ templates', exact: true })
    .check()
  await expect(
    group.getByRole('checkbox', { name: 'Allow alex to delete others’ templates', exact: true }),
  ).not.toBeChecked()
  await group
    .getByRole('checkbox', { name: 'Allow alex to edit others’ templates', exact: true })
    .uncheck()
  await expect(
    group.getByRole('button', { name: 'Review group changes', exact: true }),
  ).toBeDisabled()
  await page.keyboard.press('Escape')
  await expect(
    page.getByRole('button', { name: 'Edit group Cable team', exact: true }),
  ).toBeFocused()
  await page
    .getByRole('combobox', { name: 'Administration section', exact: true })
    .selectOption('settings')
  await expect(page.getByRole('heading', { name: 'Account settings', exact: true })).toBeVisible()
  await page.screenshot({
    animations: 'disabled',
    path: 'test-results/administration-sidebar-mobile.png',
    fullPage: true,
  })
})

test('registration codes apply per-group collaboration rights when redeemed', async ({
  page,
  request,
  playwright,
  baseURL,
}) => {
  const editable = await change(request, 'groups', { name: 'Cable team', members: [] })
  const readonly = await change(request, 'groups', { name: 'Reference team', members: [] })
  await change(request, 'groups', { name: 'Unselected team', members: [] })
  await page.goto('/#/admin?section=codes')
  await page.getByRole('button', { name: 'New registration code', exact: true }).click()
  const editor = page.getByRole('dialog', { name: 'New registration code', exact: true })
  await editor.getByLabel('Code label', { exact: true }).fill('Custom collaboration')
  await expect(
    editor.getByRole('checkbox', { name: 'Create templates in Cable team', exact: true }),
  ).toHaveCount(0)
  await editor.getByRole('checkbox', { name: 'Cable team', exact: true }).check()
  await expect(
    editor.getByRole('checkbox', { name: 'Create templates in Cable team', exact: true }),
  ).toBeChecked()
  await editor
    .getByRole('checkbox', { name: 'Create templates in Cable team', exact: true })
    .uncheck()
  await editor
    .getByRole('checkbox', { name: 'Edit others’ templates in Cable team', exact: true })
    .check()
  await editor.getByRole('checkbox', { name: 'Create images in Cable team', exact: true }).check()
  await editor
    .getByRole('checkbox', { name: 'Delete others’ fonts in Cable team', exact: true })
    .check()
  await editor.getByRole('checkbox', { name: 'Reference team', exact: true }).check()
  await editor
    .getByRole('checkbox', { name: 'Create templates in Reference team', exact: true })
    .uncheck()
  await editor.getByRole('checkbox', { name: 'Unselected team', exact: true }).check()
  await editor
    .getByRole('checkbox', { name: 'Delete others’ templates in Unselected team', exact: true })
    .check()
  await editor.getByRole('checkbox', { name: 'Unselected team', exact: true }).uncheck()
  await page.screenshot({
    path: 'test-results/registration-group-permissions-desktop.png',
    animations: 'disabled',
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBeLessThanOrEqual(390)
  expect(await editor.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
  await page.screenshot({
    path: 'test-results/registration-group-permissions-mobile.png',
    animations: 'disabled',
  })
  await editor.getByRole('button', { name: 'Create registration code', exact: true }).click()
  await expect(editor).toBeHidden()
  const code = await page
    .getByRole('textbox', { name: 'New registration code', exact: true })
    .inputValue()
  const expected = {
    [editable.id]: {
      can_create: false,
      can_edit_others: true,
      can_delete_others: false,
      images: { can_create: true, can_edit_others: false, can_delete_others: false },
      fonts: { can_create: false, can_edit_others: false, can_delete_others: true },
    },
    [readonly.id]: {
      can_create: false,
      can_edit_others: false,
      can_delete_others: false,
      images: { can_create: false, can_edit_others: false, can_delete_others: false },
      fonts: { can_create: false, can_edit_others: false, can_delete_others: false },
    },
  }
  expect(
    (await (await request.get('/api/admin/registration-codes')).json())[0].group_permissions,
  ).toEqual(expected)
  const newcomer = await playwright.request.newContext({
    baseURL,
    storageState: { cookies: [], origins: [] },
  })
  try {
    const result = await newcomer.post('/api/auth/register', {
      data: { username: 'invited', password: 'invited-password-123', registration_code: code },
    })
    expect(result.ok(), await result.text()).toBeTruthy()
    expect((await result.json()).user.group_memberships).toEqual(expected)
  } finally {
    await newcomer.dispose()
  }
  await page
    .getByRole('combobox', { name: 'Administration section', exact: true })
    .selectOption('roles')
  await expect(page.locator('optgroup[label="Accounts"] option')).toHaveCount(4)
  await expect(page.locator('optgroup[label="General"] option')).toHaveCount(3)
})
