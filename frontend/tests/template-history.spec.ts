import { randomBytes } from 'node:crypto'
import type { APIRequestContext, Page } from '@playwright/test'
import { test, expect } from './fixtures'
import type { Template } from '../src/types'

async function seedHistory(request: APIRequestContext, scope: 'personal' | 'global' = 'personal') {
  const [profile] = await (await request.get('/api/tape-profiles')).json()
  const created = await request.post('/api/templates', {
    data: {
      name: 'History original',
      scope,
      document: {
        width_mm: 24,
        length_mm: 60,
        out_of_bounds: 'clip',
        fields: [],
        preview_tape: {
          id: profile.id,
          name: profile.name,
          foreground: '#000000',
          background: '#ffcc00',
        },
        elements: [
          {
            id: 'caption',
            kind: 'text',
            x: 2,
            y: 2,
            width: 40,
            height: 12,
            content: 'Revision one',
          },
        ],
      },
    },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
  const original = (await created.json()) as Template
  const document = structuredClone(original.document)
  document.elements[0]!.content = 'Revision two'
  const edited = await request.put(`/api/templates/${original.id}`, {
    data: { name: 'History updated', scope, document, expected_revision: 1 },
  })
  expect(edited.ok(), await edited.text()).toBeTruthy()
  return { original, updated: (await edited.json()) as Template }
}

const history = (page: Page) => page.getByRole('dialog', { name: /^History:/ })
async function openHistory(page: Page) {
  await page.goto('/#/templates')
  await page
    .locator('article')
    .filter({ has: page.getByRole('heading', { name: 'History updated', exact: true }) })
    .getByRole('button', { name: 'History', exact: true })
    .click()
  const dialog = history(page)
  await expect(
    dialog.getByRole('img', { name: 'Preview of revision 2', exact: true }),
  ).toBeVisible()
  return dialog
}

test('history previews immutable layouts, names editors, and restores without deleting revisions', async ({
  page,
  request,
}) => {
  const { original } = await seedHistory(request)
  const dialog = await openHistory(page)
  await expect(
    dialog.getByRole('list', { name: 'Saved revisions' }).getByRole('listitem'),
  ).toHaveCount(2)
  await expect(
    dialog.getByRole('button', { name: 'View revision 2', exact: true }),
  ).toHaveAccessibleDescription(/owner/)
  await dialog.getByRole('button', { name: 'View revision 1', exact: true }).click()
  await expect(
    dialog.getByRole('img', { name: 'Preview of revision 1', exact: true }),
  ).toBeVisible()
  await expect(dialog.getByRole('heading', { name: 'History original', exact: true })).toBeVisible()
  await page.screenshot({
    path: 'test-results/template-history-desktop.png',
    fullPage: true,
    animations: 'disabled',
  })
  await dialog.getByRole('button', { name: 'Restore revision 1', exact: true }).click()
  const confirmation = page.getByRole('dialog', { name: 'Confirm action', exact: true })
  await expect(confirmation).toContainText('Restore revision 1 as a new revision?')
  await confirmation.getByRole('button', { name: 'Restore revision', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  const restored = await (await request.get(`/api/templates/${original.id}`)).json()
  expect(restored).toMatchObject({ name: original.name, document: original.document, revision: 3 })
  const card = page
    .locator('article')
    .filter({ has: page.getByRole('heading', { name: 'History original', exact: true }) })
  await card.getByRole('button', { name: 'History', exact: true }).click()
  await expect(dialog.getByRole('listitem')).toHaveCount(3)
  await expect(dialog).toContainText('Restored from revision 1')
  await expect(
    dialog.getByRole('button', { name: 'Restore revision 3', exact: true }),
  ).toBeDisabled()
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  await expect(card.getByRole('button', { name: 'History', exact: true })).toBeFocused()
})

test('editor restore warns about unsaved changes and cancellation preserves the draft', async ({
  page,
  request,
}) => {
  const { original } = await seedHistory(request)
  await page.goto(`/#/templates/${original.id}/edit`)
  const name = page.getByLabel('Template name', { exact: true })
  await expect(name).toHaveValue('History updated')
  await name.fill('Unsaved draft')
  await page.getByRole('button', { name: 'History', exact: true }).click()
  const dialog = history(page)
  await dialog.getByRole('button', { name: 'View revision 1', exact: true }).click()
  const restore = dialog.getByRole('button', { name: 'Restore revision 1', exact: true })
  await expect(restore).toBeEnabled()
  await restore.click()
  const confirmation = page.getByRole('dialog', { name: 'Confirm action', exact: true })
  await expect(confirmation).toContainText('Unsaved editor changes will be discarded.')
  await confirmation.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(dialog).toBeVisible()
  await expect(name).toHaveValue('Unsaved draft')
  await restore.click()
  await confirmation.getByRole('button', { name: 'Restore revision', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await expect(name).toHaveValue('History original')
  await expect(page.getByText('Unsaved changes', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Revision 3', { exact: true })).toBeVisible()
})

test('sharing an existing template makes the history audience explicit', async ({
  page,
  request,
}) => {
  const { original } = await seedHistory(request)
  await page.goto(`/#/templates/${original.id}/edit`)
  const visibility = page.getByRole('combobox', { name: 'Template visibility', exact: true })
  await expect(visibility).toHaveValue('personal')
  await visibility.selectOption('global')
  await expect(
    page.getByText('Sharing includes all saved revisions.', { exact: true }),
  ).toBeVisible()
  await visibility.selectOption('personal')
  await expect(
    page.getByText('Sharing includes all saved revisions.', { exact: true }),
  ).toHaveCount(0)
})

test('a late preview cannot replace the currently selected revision', async ({ page, request }) => {
  await seedHistory(request)
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/revisions/1/preview', async (route) => {
    await gate
    await route.continue()
  })
  const dialog = await openHistory(page)
  const started = page.waitForRequest(/\/revisions\/1\/preview$/)
  await dialog.getByRole('button', { name: 'View revision 1', exact: true }).click()
  await started
  await dialog.getByRole('button', { name: 'View revision 2', exact: true }).click()
  await expect(
    dialog.getByRole('img', { name: 'Preview of revision 2', exact: true }),
  ).toBeVisible()
  const response = page.waitForResponse(/\/revisions\/1\/preview$/)
  release()
  await response
  await expect(
    dialog.getByRole('button', { name: 'View revision 2', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true')
  await expect(dialog.getByRole('img', { name: 'Preview of revision 1', exact: true })).toHaveCount(
    0,
  )
})

test('conflicting restores require reloading history before retrying', async ({
  page,
  request,
}) => {
  const { original, updated } = await seedHistory(request)
  const dialog = await openHistory(page)
  await dialog.getByRole('button', { name: 'View revision 1', exact: true }).click()
  const changed = await request.put(`/api/templates/${original.id}`, {
    data: {
      name: 'Another edit',
      scope: updated.scope,
      document: updated.document,
      expected_revision: 2,
    },
  })
  expect(changed.ok()).toBeTruthy()
  await dialog.getByRole('button', { name: 'Restore revision 1', exact: true }).click()
  const confirmation = page.getByRole('dialog', { name: 'Confirm action', exact: true })
  await confirmation.getByRole('button', { name: 'Restore revision', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('Template changed or was archived')
  expect((await (await request.get(`/api/templates/${original.id}/revisions`)).json()).length).toBe(
    3,
  )
  await dialog.getByRole('button', { name: 'Reload history', exact: true }).click()
  await expect(dialog.getByRole('button', { name: 'View revision 3', exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: 'Restore revision 1', exact: true }).click()
  await confirmation.getByRole('button', { name: 'Restore revision', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  expect((await (await request.get(`/api/templates/${original.id}`)).json()).revision).toBe(4)
})

test('legacy editor attribution stays unrecorded and failed previews can be retried', async ({
  page,
  request,
}) => {
  await seedHistory(request)
  await page.route('**/templates/*/revisions', async (route) => {
    const response = await route.fetch()
    const entries = await response.json()
    entries[1].edited_by = null
    entries[1].created_at = null
    await route.fulfill({ json: entries })
  })
  let failed = false
  await page.route('**/revisions/1/preview', async (route) => {
    if (!failed) {
      failed = true
      await route.fulfill({ status: 503, json: { detail: 'Temporary preview failure' } })
    } else await route.continue()
  })
  const dialog = await openHistory(page)
  const revision = dialog.getByRole('button', { name: 'View revision 1', exact: true })
  await expect(revision).toHaveAccessibleDescription('Editor not recorded')
  await revision.click()
  await expect(dialog.getByRole('alert')).toContainText('Temporary preview failure')
  await expect(
    dialog.getByRole('button', { name: 'Restore revision 1', exact: true }),
  ).toBeDisabled()
  await dialog.getByRole('button', { name: 'Retry preview', exact: true }).click()
  await expect(
    dialog.getByRole('img', { name: 'Preview of revision 1', exact: true }),
  ).toBeVisible()
  await expect(
    dialog.getByRole('button', { name: 'Restore revision 1', exact: true }),
  ).toBeEnabled()
})

test('revisions with deleted artwork show placeholders and prevent restoring missing assets', async ({
  page,
  request,
}) => {
  const uploaded = await request.post('/api/image-assets?name=Historical-artwork', {
    data: Buffer.from('<svg viewBox="0 0 20 20"><path d="M2 2H18V18H2Z"/></svg>'),
    headers: { 'Content-Type': 'application/octet-stream' },
  })
  expect(uploaded.ok()).toBeTruthy()
  const asset = await uploaded.json()
  const created = await request.post('/api/templates', {
    data: {
      name: 'History original',
      document: {
        out_of_bounds: 'clip',
        elements: [
          { id: 'image', kind: 'image', x: 2, y: 2, width: 12, height: 12, image_asset: asset.id },
        ],
      },
    },
  })
  expect(created.ok()).toBeTruthy()
  const template = await created.json()
  expect(
    (
      await request.put(`/api/templates/${template.id}`, {
        data: { name: 'History updated', expected_revision: 1, document: {} },
      })
    ).ok(),
  ).toBeTruthy()
  expect((await request.delete(`/api/image-assets/${asset.id}/permanent`)).ok()).toBeTruthy()
  const dialog = await openHistory(page)
  await dialog.getByRole('button', { name: 'View revision 1', exact: true }).click()
  await expect(
    dialog.getByRole('img', { name: 'Preview of revision 1', exact: true }),
  ).toBeVisible()
  await expect(dialog).toContainText('Restore the missing assets before restoring this revision.')
  await expect(
    dialog.getByRole('button', { name: 'Restore revision 1', exact: true }),
  ).toBeDisabled()
})

test('read-only users can inspect shared history without restore actions', async ({
  request,
  browser,
  baseURL,
}) => {
  await seedHistory(request, 'global')
  const password = randomBytes(24).toString('base64url')
  const payload = { username: 'historyviewer', password, role_ids: [] }
  const preview = await request.post('/api/admin/access-preview', {
    data: { resource: 'users', method: 'POST', payload },
  })
  expect(preview.ok()).toBeTruthy()
  expect(
    (
      await request.post('/api/admin/users', {
        data: payload,
        headers: { 'X-Access-Confirmation': (await preview.json()).confirmation_token },
      })
    ).ok(),
  ).toBeTruthy()
  const context = await browser.newContext({
    baseURL,
    storageState: { cookies: [], origins: [] },
    extraHTTPHeaders: {},
  })
  try {
    const page = await context.newPage()
    await page.goto('/#/templates')
    await page.getByLabel('Username', { exact: true }).fill('historyviewer')
    await page.getByLabel('Password', { exact: true }).fill(password)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    const card = page
      .locator('article')
      .filter({ has: page.getByRole('heading', { name: 'History updated', exact: true }) })
    await card.getByRole('button', { name: 'History', exact: true }).click()
    const dialog = history(page)
    await dialog.getByRole('button', { name: 'View revision 1', exact: true }).click()
    await expect(
      dialog.getByRole('img', { name: 'Preview of revision 1', exact: true }),
    ).toBeVisible()
    await expect(dialog.getByRole('button', { name: /Restore revision/ })).toHaveCount(0)
  } finally {
    await context.close()
  }
})

for (const reducedMotion of ['no-preference', 'reduce'] as const) {
  test(`revision history fits mobile and keeps keyboard focus with ${reducedMotion}`, async ({
    page,
    request,
  }) => {
    const { original } = await seedHistory(request)
    await page.setViewportSize({ width: 390, height: 844 })
    await page.emulateMedia({ reducedMotion })
    await page.goto(`/#/templates/${original.id}/edit`)
    const trigger = page.getByRole('button', { name: 'History', exact: true })
    await expect(trigger).toBeVisible()
    await trigger.focus()
    await page.keyboard.press('Enter')
    const dialog = history(page)
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: 'View revision 1', exact: true }).click()
    await expect(
      dialog.getByRole('img', { name: 'Preview of revision 1', exact: true }),
    ).toBeVisible()
    const close = dialog.getByRole('button', { name: 'Close', exact: true })
    await close.focus()
    await page.keyboard.press('Shift+Tab')
    await expect(
      dialog.getByRole('button', { name: 'Restore revision 1', exact: true }),
    ).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(close).toBeFocused()
    await page.screenshot({
      path: `test-results/template-history-mobile-${reducedMotion}.png`,
      fullPage: true,
      animations: 'disabled',
    })
    const bounds = (await dialog.boundingBox())!
    expect(bounds.x).toBeGreaterThanOrEqual(0)
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(390)
    expect(await dialog.evaluate((element) => element.scrollWidth)).toBeLessThanOrEqual(
      await dialog.evaluate((element) => element.clientWidth),
    )
    await page.keyboard.press('Escape')
    await expect(dialog).not.toBeVisible()
    await expect(trigger).toBeFocused()
  })
}
