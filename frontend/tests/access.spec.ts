import { test, expect } from './fixtures'
import type { APIRequestContext } from '@playwright/test'
async function adminChange(
  request: APIRequestContext,
  resource: string,
  method: string,
  payload: unknown,
  identifier?: string,
) {
  const preview = await request.post('/api/admin/access-preview', {
    data: { resource, method, payload, identifier },
  })
  expect(preview.ok(), await preview.text()).toBeTruthy()
  const result = await request.fetch(
    `/api/admin/${resource}${identifier ? '/' + identifier : ''}`,
    {
      method,
      data: payload,
      headers: { 'X-Access-Confirmation': (await preview.json()).confirmation_token },
    },
  )
  expect(result.ok(), await result.text()).toBeTruthy()
  return result.json()
}

test('invite a member, request approval, and approve frozen labels without exposing administration', async ({
  page,
  request,
  browser,
  baseURL,
}) => {
  const printers = await (await request.get('/api/printers')).json()
  const destination = await (
    await request.post('/api/printer-groups', {
      data: { name: 'Cable station', printer_ids: [printers[0].id] },
    })
  ).json()
  await adminChange(request, 'groups', 'POST', { name: 'Cable team', members: [] })
  await adminChange(request, 'roles', 'POST', {
    name: 'Cable requests',
    permissions: [{ kind: 'destination', destination_id: destination.id, level: 'request' }],
  })
  await page.goto('/#/admin')
  await page.getByRole('button', { name: 'Registration codes', exact: true }).click()
  await page.getByRole('button', { name: 'New registration code', exact: true }).click()
  await page.getByLabel('Code label', { exact: true }).fill('Cable team invitation')
  await page.getByLabel('Cable team', { exact: true }).check()
  await page.getByRole('checkbox', { name: 'Cable requests', exact: true }).check()
  await page.getByRole('button', { name: 'Create registration code', exact: true }).click()
  const code = await page
    .getByRole('textbox', { name: 'New registration code', exact: true })
    .inputValue()
  expect(code).not.toBe('')

  const memberContext = await browser.newContext({
    baseURL,
    storageState: { cookies: [], origins: [] },
    extraHTTPHeaders: {},
  })
  const member = await memberContext.newPage()
  try {
    await member.goto('/#/new')
    await expect(member.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
    await expect(member.getByRole('navigation')).toHaveCount(0)
    await member.getByRole('button', { name: 'Create an account', exact: true }).click()
    await member.getByLabel('Username', { exact: true }).fill('member')
    await member.getByLabel('Password', { exact: true }).fill('member-password-123')
    await member.getByLabel('Registration code', { exact: false }).fill(code)
    await member.getByRole('button', { name: 'Create account', exact: true }).click()
    await expect(member.getByRole('link', { name: 'Administration', exact: true })).toHaveCount(0)
    await expect(member.getByRole('link', { name: 'Printers & groups', exact: true })).toHaveCount(
      0,
    )
    await member.getByLabel('Label text').fill('Member cable label')
    await expect(
      member.getByRole('combobox', { name: 'Print destination', exact: true }),
    ).toHaveValue(destination.id)
    expect(await (await member.request.get('/api/printers')).json()).toEqual([])
    await member.getByRole('button', { name: 'Request printing', exact: true }).click()
    await expect(
      member.getByText('Label sent for approval. Nothing has been queued yet.'),
    ).toBeVisible()
    await expect(member.getByText('Member cable label', { exact: true })).toBeVisible()
    expect(await (await request.get('/api/jobs')).json()).toHaveLength(0)
    await member.reload()
    await expect(member.getByText('Member cable label', { exact: true })).toBeVisible()
    await page.goto('/#/requests')
    await page.getByRole('link', { name: 'View request', exact: true }).click()
    const preview = page.getByRole('img', { name: 'Requested label 1' })
    await expect(preview).toBeVisible()
    await expect
      .poll(() => preview.evaluate((img: HTMLImageElement) => img.naturalWidth))
      .toBeGreaterThan(0)
    await page.screenshot({ path: 'test-results/access-request-review.png', fullPage: true })
    await page.getByRole('button', { name: 'Approve and queue' }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
    await expect(page.getByRole('link', { name: 'View print queue', exact: true })).toBeVisible()
    await expect.poll(async () => (await (await request.get('/api/jobs')).json()).length).toBe(1)
    await member.goto('/#/admin')
    await expect(member.getByRole('heading', { name: 'Access restricted' })).toBeVisible()
    await member.locator('.account-menu > summary').click()
    await member.getByRole('button', { name: 'Sign out', exact: true }).click()
    await expect(member.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
    await expect(member.getByRole('navigation')).toHaveCount(0)
    expect(
      await member.evaluate(() =>
        Object.keys(localStorage).filter((key) => /token|session|password/i.test(key)),
      ),
    ).toEqual([])
  } finally {
    await memberContext.close()
  }
})

test('administration saves roles, account access, and notification settings', async ({
  page,
  request,
}) => {
  await page.goto('/#/admin')
  await page.getByRole('button', { name: 'Roles', exact: true }).click()
  await page.getByRole('button', { name: 'New role', exact: true }).click()
  await page.getByLabel('Role name', exact()).fill('Trusted printers')
  const printers = await (await request.get('/api/printers')).json()
  await page
    .getByRole('combobox', { name: 'Access to Desk printer', exact: true })
    .selectOption('print')
  await page.getByRole('button', { name: 'Review role changes', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Review effective access' })).toBeVisible()
  expect(
    (await (await request.get('/api/admin/roles')).json()).some(
      (r: { name: string }) => r.name === 'Trusted printers',
    ),
  ).toBe(false)
  await adminChange(request, 'roles', 'POST', { name: 'Concurrent role', permissions: [] })
  await page.getByRole('button', { name: 'Confirm access changes', exact: true }).click()
  await expect(
    page.getByText('Access changed since the previous preview.', { exact: false }),
  ).toBeVisible()
  await page.screenshot({ path: 'test-results/access-effective-preview.png', fullPage: true })
  await page.getByRole('button', { name: 'Confirm access changes', exact: true }).click()
  await expect(page.getByText('Role saved.', { exact: true })).toBeVisible()
  const roles = await (await request.get('/api/admin/roles')).json()
  expect(roles.find((r: { name: string }) => r.name === 'Trusted printers').permissions).toEqual([
    { kind: 'destination', destination_id: printers[0].id, level: 'print' },
  ])
  await page.getByRole('button', { name: 'Account settings', exact: true }).click()
  await page.getByLabel('Approval notification delay (seconds)', { exact: false }).fill('120')
  await page.getByRole('button', { name: 'Save account settings', exact: true }).click()
  await expect(page.getByText('Account settings saved.', { exact: true })).toBeVisible()
  expect(
    (await (await request.get('/api/admin/settings')).json())
      .approval_notification_debounce_seconds,
  ).toBe(120)
  await page.setViewportSize({ width: 390, height: 844 })
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBeLessThanOrEqual(390)
  await page.screenshot({ path: 'test-results/access-administration-mobile.png', fullPage: true })
})

test('revoked access pauses queued labels while their owner can cancel and an administrator can release', async ({
  page,
  request,
  browser,
  baseURL,
}) => {
  const printers = await (await request.get('/api/printers')).json()
  const role = await adminChange(request, 'roles', 'POST', {
    name: 'Desk printing',
    permissions: [{ kind: 'destination', destination_id: printers[0].id, level: 'print' }],
  })
  await adminChange(request, 'users', 'POST', {
    username: 'printeruser',
    password: 'member-password-123',
    role_ids: [role.id],
  })
  const context = await browser.newContext({
    baseURL,
    storageState: { cookies: [], origins: [] },
    extraHTTPHeaders: {},
  })
  const member = await context.newPage()
  try {
    await member.goto('/#/new')
    await member.getByLabel('Username', exact()).fill('printeruser')
    await member.getByLabel('Password', exact()).fill('member-password-123')
    await member.getByRole('button', { name: 'Sign in', exact: true }).click()
    for (const text of ['Keep for administrator', 'Cancel myself']) {
      await member.goto('/#/new')
      await member.getByLabel('Label text').fill(text)
      await member.getByLabel('Process name', exact()).fill(text)
      await member.getByRole('button', { name: 'Add to queue', exact: true }).click()
      await expect(member.locator('.queue-label-name').filter({ hasText: text })).toBeVisible()
    }
    await member.goto('/#/runs')
    await member.getByLabel('Run name', exact()).fill('Draft before revocation')
    await member.getByLabel('CSV content', exact()).fill('text\nSaved draft')
    await member.getByRole('button', { name: 'Read CSV', exact: true }).click()
    await member.getByRole('button', { name: 'Validate and preview run', exact: true }).click()
    await expect(member).toHaveURL(/runs\/[^/]+/)
    await page.goto('/#/admin')
    await page.getByRole('button', { name: 'Edit printeruser', exact: true }).click()
    await page.getByRole('checkbox', { name: 'Desk printing', exact: true }).uncheck()
    await page.getByRole('button', { name: 'Review account changes', exact: true }).click()
    await page.getByRole('button', { name: 'Confirm access changes', exact: true }).click()
    await expect(
      page.getByRole('link', { name: 'Review paused labels', exact: true }),
    ).toBeVisible()
    await member.goto('/#/queue')
    const row = member.getByRole('row').filter({ hasText: 'Cancel myself' })
    await row.getByRole('button', { name: 'Remove', exact: true }).click()
    await member.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
    await expect(member.getByText('Cancel myself', exact())).toHaveCount(0)
    await member.getByRole('link', { name: 'CSV runs', exact: true }).click()
    await expect(
      member.getByRole('link', { name: 'Draft before revocation', exact: true }),
    ).toBeVisible()
    await expect(member.getByRole('heading', { name: 'Import CSV', exact: true })).toHaveCount(0)
    await member.getByRole('button', { name: 'Delete draft', exact: true }).click()
    await member.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
    await expect(
      member.getByRole('link', { name: 'Draft before revocation', exact: true }),
    ).toHaveCount(0)
    await page.getByRole('link', { name: 'Review paused labels', exact: true }).click()
    // The member cancelled from another client; allow the live access-hold cache to refresh.
    await expect(page.getByRole('button', { name: 'Release copies', exact: true })).toHaveCount(1, {
      timeout: 15000,
    })
    await page.getByRole('button', { name: 'Release copies', exact: true }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
    await expect(page.getByText('No labels are paused for access review.', exact())).toBeVisible()
  } finally {
    await context.close()
  }
})

test('template collaboration settings stay independent and owners can edit after membership loss without printer access', async ({
  page,
  request,
  browser,
  baseURL,
}) => {
  const user = await adminChange(request, 'users', 'POST', {
    username: 'designer',
    password: 'designer-password-123',
    role_ids: [],
  })
  const group = await adminChange(request, 'groups', 'POST', {
    name: 'Design team',
    members: [
      { user_id: user.id, can_create: false, can_edit_others: false, can_delete_others: false },
    ],
  })
  await page.goto('/#/admin')
  await page.getByRole('button', { name: 'Template groups', exact: true }).click()
  await page.getByRole('button', { name: 'Edit group Design team', exact: true }).click()
  await page
    .getByRole('checkbox', { name: 'Allow designer to create group templates', exact: true })
    .check()
  await expect(
    page.getByRole('checkbox', { name: 'Allow designer to edit others’ templates', exact: true }),
  ).not.toBeChecked()
  await expect(
    page.getByRole('checkbox', { name: 'Allow designer to delete others’ templates', exact: true }),
  ).not.toBeChecked()
  await page.getByRole('button', { name: 'Review group changes', exact: true }).click()
  await page.getByRole('button', { name: 'Confirm access changes', exact: true }).click()
  await expect(page.getByText('Template group saved.', exact())).toBeVisible()
  const document = (await (await request.get('/api/templates/text')).json()).document
  document.out_of_bounds = 'clip'
  expect(
    (
      await request.post('/api/templates', {
        data: { name: 'Shared read-only', document, scope: 'group', group_id: group.id },
      })
    ).ok(),
  ).toBeTruthy()
  const context = await browser.newContext({
      baseURL,
      storageState: { cookies: [], origins: [] },
      extraHTTPHeaders: {},
    }),
    member = await context.newPage()
  try {
    await member.goto('/#/templates')
    await member.getByLabel('Username', exact()).fill('designer')
    await member.getByLabel('Password', exact()).fill('designer-password-123')
    await member.getByRole('button', { name: 'Sign in', exact: true }).click()
    const shared = member.locator('article').filter({ hasText: 'Shared read-only' })
    await expect(shared).toBeVisible()
    await expect(shared.getByRole('link', { name: 'Edit visually', exact: true })).toHaveCount(0)
    await expect(shared.getByRole('button', { name: 'Archive', exact: true })).toHaveCount(0)
    await member.getByRole('link', { name: 'Create template', exact: true }).click()
    await member.getByLabel('Template name', exact()).fill('Owned group template')
    await member.getByRole('button', { name: 'Add text', exact: true }).click()
    await member
      .getByRole('combobox', { name: 'Template visibility', exact: true })
      .selectOption('group')
    await member.getByRole('combobox', { name: 'User group', exact: true }).selectOption(group.id)
    await member.getByRole('button', { name: 'Save template', exact: true }).click()
    await expect(member).toHaveURL(/templates\/[^/]+\/edit/)
    await adminChange(request, 'groups', 'PUT', { name: 'Design team', members: [] }, group.id)
    await member.reload()
    await member.getByLabel('Template name', exact()).fill('Owned after membership loss')
    await member.getByRole('button', { name: 'Save template', exact: true }).click()
    await expect(member.getByText('Template revision saved.', { exact: false })).toBeVisible()
    await member.getByRole('link', { name: 'Templates', exact: true }).click()
    const own = member.locator('article').filter({ hasText: 'Owned after membership loss' })
    await own.getByRole('button', { name: 'Archive', exact: true }).click()
    await member.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
    await expect(own).toHaveCount(0)
  } finally {
    await context.close()
  }
})

test('group-only moderators reach scoped queue controls without physical configuration access', async ({
  page,
  request,
  browser,
  baseURL,
}) => {
  const printers = await (await request.get('/api/printers')).json()
  const group = await (
    await request.post('/api/printer-groups', {
      data: { name: 'Moderated group', printer_ids: [printers[0].id] },
    })
  ).json()
  const role = await adminChange(request, 'roles', 'POST', {
    name: 'Group moderator',
    permissions: [{ kind: 'destination', destination_id: group.id, level: 'moderator' }],
  })
  await adminChange(request, 'users', 'POST', {
    username: 'moderator',
    password: 'moderator-password-123',
    role_ids: [role.id],
  })
  const context = await browser.newContext({
      baseURL,
      storageState: { cookies: [], origins: [] },
      extraHTTPHeaders: {},
    }),
    member = await context.newPage()
  try {
    await member.goto('/#/')
    await member.getByLabel('Username', exact()).fill('moderator')
    await member.getByLabel('Password', exact()).fill('moderator-password-123')
    await member.getByRole('button', { name: 'Sign in', exact: true }).click()
    await member.getByRole('link', { name: 'Printers & groups', exact: true }).click()
    await expect(member.getByRole('button', { name: 'Configure', exact: true })).toHaveCount(0)
    await expect(member.getByRole('button', { name: 'Edit group', exact: true })).toHaveCount(0)
    await expect(member.getByRole('link', { name: 'Activity', exact: true })).toHaveCount(0)
    await member.getByRole('button', { name: 'Hold group', exact: true }).click()
    await expect(member.getByRole('button', { name: 'Resume group', exact: true })).toBeVisible()
    await member.getByRole('button', { name: 'Resume group', exact: true }).click()
    await expect(member.getByRole('button', { name: 'Hold group', exact: true })).toBeVisible()
    await member.goto('/#/new')
    await member.getByLabel('Label text').fill('Scoped group label')
    await expect(
      member.getByText('Labels wait for a ready group member', { exact: false }),
    ).toBeVisible()
    await member.getByRole('button', { name: 'Add to queue', exact: true }).click()
    await expect(member).toHaveURL(/#\/queue/)
    await member.getByRole('link', { name: 'Printers & groups', exact: true }).click()
    await expect(member).toHaveURL(/#\/printers/)
    await member.getByRole('button', { name: 'Print matching queue', exact: true }).click()
    await expect
      .poll(async () => (await (await request.get('/api/jobs')).json())[0]?.status)
      .toBe('printed')
    await page.goto('/#/activity')
    await expect(page.getByRole('heading', { name: 'Print batches', exact: true })).toBeVisible()
  } finally {
    await context.close()
  }
})

function exact() {
  return { exact: true }
}
