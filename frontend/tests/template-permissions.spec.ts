import { test, expect } from './fixtures'
import type { APIRequestContext } from '@playwright/test'

async function change(request: APIRequestContext, resource: string, payload: unknown) {
  const preview = await request.post('/api/admin/access-preview', {
    data: { resource, method: 'POST', payload },
  })
  expect(preview.ok()).toBeTruthy()
  const created = await request.post(`/api/admin/${resource}`, {
    data: payload,
    headers: { 'X-Access-Confirmation': (await preview.json()).confirmation_token },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
  return created.json()
}

test('administrators grant global creation independently and authors start in their allowed scope', async ({
  page,
  request,
  browser,
  baseURL,
}) => {
  await page.goto('/#/admin?section=roles')
  await page.getByRole('button', { name: 'New role', exact: true }).click()
  const editor = page.getByRole('dialog', { name: 'New role', exact: true })
  await editor.getByLabel('Role name', { exact: true }).fill('Global authors')
  for (const label of [
    'Create personal templates',
    'Create global templates',
    'Edit other users’ global templates',
    'Delete other users’ global templates',
  ]) {
    await expect(editor.getByRole('checkbox', { name: label, exact: true })).toBeVisible()
  }
  await editor.getByRole('checkbox', { name: 'Create global templates', exact: true }).check()
  await page.screenshot({
    path: 'test-results/template-role-permissions.png',
    animations: 'disabled',
  })
  await editor.getByRole('button', { name: 'Review role changes', exact: true }).click()
  await page
    .getByRole('dialog', { name: 'Review effective access', exact: true })
    .getByRole('button', { name: 'Confirm access changes', exact: true })
    .click()
  await expect(editor).toBeHidden()
  const roles = await (await request.get('/api/admin/roles')).json()
  const role = roles.find((value: { name: string }) => value.name === 'Global authors')
  expect(role.permissions).toEqual([{ kind: 'application', permission: 'templates.create_global' }])
  const user = await change(request, 'users', {
    username: 'globalauthor',
    password: 'author-password-123',
    role_ids: [role.id],
  })
  const context = await browser.newContext({
    baseURL,
    storageState: { cookies: [], origins: [] },
    extraHTTPHeaders: {},
  })
  const author = await context.newPage()
  try {
    await author.goto('/#/templates')
    await author.getByLabel('Username', { exact: true }).fill('globalauthor')
    await author.getByLabel('Password', { exact: true }).fill('author-password-123')
    await author.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(
      author.getByRole('button', { name: 'Duplicate template', exact: true }),
    ).toHaveCount(0)
    await author.getByRole('link', { name: 'Create template', exact: true }).click()
    const visibility = author.getByRole('combobox', { name: 'Template visibility', exact: true })
    await expect(visibility).toHaveValue('global')
    await expect(visibility.locator('option[value="personal"]')).toHaveCount(0)
    await author.getByLabel('Template name', { exact: true }).fill('Global author design')
    await author.getByRole('button', { name: 'Add text', exact: true }).click()
    await author.getByRole('button', { name: 'Save template', exact: true }).click()
    await expect(author).toHaveURL(/templates\/[^/]+\/edit/)
    const created = (await (await request.get('/api/templates')).json()).find(
      (value: { name: string }) => value.name === 'Global author design',
    )
    expect(created).toMatchObject({ scope: 'global', owner_id: user.id })
  } finally {
    await context.close()
  }
})

test('global collaborators edit and delete shared templates without creation or sharing access', async ({
  page,
  request,
  browser,
  baseURL,
}) => {
  const role = await change(request, 'roles', {
    name: 'Global collaborators',
    permissions: [
      { kind: 'application', permission: 'templates.edit_global' },
      { kind: 'application', permission: 'templates.delete_global' },
    ],
  })
  await change(request, 'users', {
    username: 'collaborator',
    password: 'collaborator-password-123',
    role_ids: [role.id],
  })
  const document = (await (await request.get('/api/templates/text')).json()).document
  document.out_of_bounds = 'clip'
  const created = await request.post('/api/templates', {
    data: { name: 'Team standard', scope: 'global', document },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
  const original = await created.json()
  const context = await browser.newContext({
    baseURL,
    storageState: { cookies: [], origins: [] },
    extraHTTPHeaders: {},
  })
  const collaborator = await context.newPage()
  try {
    await collaborator.goto('/#/templates')
    await collaborator.getByLabel('Username', { exact: true }).fill('collaborator')
    await collaborator.getByLabel('Password', { exact: true }).fill('collaborator-password-123')
    await collaborator.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(
      collaborator.getByRole('link', { name: 'Create template', exact: true }),
    ).toHaveCount(0)
    await expect(
      collaborator.getByRole('button', { name: 'Duplicate template', exact: true }),
    ).toHaveCount(0)
    const card = collaborator.locator('article').filter({ hasText: 'Team standard' })
    await card.getByRole('link', { name: 'Edit visually', exact: true }).click()
    await expect(
      collaborator.getByRole('combobox', { name: 'Template visibility', exact: true }),
    ).toBeDisabled()
    await collaborator.getByLabel('Template name', { exact: true }).fill('Updated team standard')
    await collaborator.getByRole('button', { name: 'Save template', exact: true }).click()
    await expect(collaborator.getByText('Template revision saved.', { exact: false })).toBeVisible()
    expect((await (await request.get(`/api/templates/${original.id}`)).json()).owner_id).toBe(
      original.owner_id,
    )
    await collaborator.getByRole('link', { name: 'Templates', exact: true }).click()
    await collaborator
      .locator('article')
      .filter({ hasText: 'Updated team standard' })
      .getByRole('button', { name: 'Delete template', exact: true })
      .click()
    await collaborator
      .getByRole('dialog')
      .getByRole('button', { name: 'Confirm', exact: true })
      .click()
    await expect(
      collaborator.locator('article').filter({ hasText: 'Updated team standard' }),
    ).toHaveCount(0)
    await collaborator.goto('/#/templates/new')
    await expect(
      collaborator.getByRole('heading', { name: 'Access restricted', exact: true }),
    ).toBeVisible()
    await page.goto('/#/admin?section=trash')
    await expect(
      page.getByRole('button', { name: 'Restore Updated team standard', exact: true }),
    ).toBeVisible()
  } finally {
    await context.close()
  }
})
