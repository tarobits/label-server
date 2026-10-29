import { test, expect } from './fixtures'
import { readFile } from 'node:fs/promises'
import type { APIRequestContext } from '@playwright/test'

async function create(request: APIRequestContext, resource: string, payload: unknown) {
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

test('cancelling a batch finishes its current upload and leaves remaining files ready', async ({
  page,
  request,
}) => {
  let releaseUpload = () => {}
  const paused = new Promise<void>((resolve) => {
    releaseUpload = resolve
  })
  let attempts = 0
  await page.route('**/api/image-assets?*', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    attempts++
    await paused
    await route.continue()
  })
  try {
    await page.goto('/#/images')
    await page.getByLabel('Image files', { exact: true }).setInputFiles(
      [1, 2].map((size) => ({
        name: `square-${size}.svg`,
        mimeType: 'image/svg+xml',
        buffer: Buffer.from(
          `<svg viewBox="0 0 20 20"><rect width="${size}" height="${size}"/></svg>`,
        ),
      })),
    )
    await page.getByRole('button', { name: 'Upload images', exact: true }).click()
    const cancel = page.getByRole('button', { name: 'Cancel remaining', exact: true })
    await expect(cancel).toBeVisible()
    await expect(cancel).toHaveCSS('animation-name', 'feedback-arrive')
    await page.screenshot({
      path: 'test-results/images-upload-cancel-visible.png',
      animations: 'disabled',
    })
    await cancel.click()
    await expect(cancel).toBeDisabled()
    releaseUpload()
    await expect(cancel).toHaveCount(0)
    const results = page.getByRole('list', { name: 'Upload results' })
    await expect(results.getByText('Uploaded', { exact: true })).toHaveCount(1)
    await expect(results.getByText('Ready', { exact: true })).toHaveCount(1)
    expect(attempts).toBe(1)
    expect(await (await request.get('/api/image-assets')).json()).toHaveLength(1)
    await page.screenshot({
      path: 'test-results/images-upload-cancel-finished.png',
      animations: 'disabled',
    })
  } finally {
    releaseUpload()
  }
})

test('a group image uploader sees only authorized scopes and separate personal font access', async ({
  request,
  browser,
  baseURL,
}) => {
  const role = await create(request, 'roles', {
    name: 'Font uploads',
    permissions: [{ kind: 'application', permission: 'fonts.create_personal' }],
  })
  const user = await create(request, 'users', {
    username: 'designer',
    password: 'designer-password-123',
    role_ids: [role.id],
  })
  await create(request, 'groups', {
    name: 'Artwork',
    members: [{ user_id: user.id, images: { can_create: true } }],
  })
  const context = await browser.newContext({
    baseURL,
    storageState: { cookies: [], origins: [] },
    extraHTTPHeaders: {},
  })
  const page = await context.newPage()
  try {
    await page.goto('/#/images')
    await page.getByLabel('Username', { exact: true }).fill('designer')
    await page.getByLabel('Password', { exact: true }).fill('designer-password-123')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Upload images', exact: true })).toBeVisible()
    const visibility = page.getByRole('combobox', { name: 'Visibility', exact: true })
    await expect(visibility).toHaveValue('group')
    await expect(visibility.locator('option')).toHaveText(['Group'])
    await expect(
      page.getByRole('combobox', { name: 'Group', exact: true }).locator('option'),
    ).toHaveText(['Artwork'])
    await page.getByLabel('Image files', { exact: true }).setInputFiles({
      name: 'team.svg',
      mimeType: 'image/svg+xml',
      buffer: Buffer.from('<svg viewBox="0 0 20 20"><rect width="20" height="20"/></svg>'),
    })
    await page.getByRole('button', { name: 'Upload image', exact: true }).click()
    await expect(page.getByRole('cell', { name: 'Artwork', exact: true })).toBeVisible()
    await page.goto('/#/fonts')
    await expect(visibility).toHaveValue('personal')
    await expect(visibility.locator('option')).toHaveText(['Personal'])
    await expect(page.getByRole('combobox', { name: 'Group', exact: true })).toHaveCount(0)
  } finally {
    await context.close()
  }
})

for (const kind of ['images', 'fonts'] as const) {
  test(`bulk ${kind} uploads preserve successes on retry and support independent sharing`, async ({
    page,
    request,
  }) => {
    const singular = kind === 'images' ? 'image' : 'font'
    const groupPayload = { name: 'Design team', members: [] }
    const preview = await request.post('/api/admin/access-preview', {
      data: { resource: 'groups', method: 'POST', payload: groupPayload },
    })
    const groupResponse = await request.post('/api/admin/groups', {
      data: groupPayload,
      headers: { 'X-Access-Confirmation': (await preview.json()).confirmation_token },
    })
    expect(groupResponse.ok()).toBeTruthy()
    const group = await groupResponse.json()
    const files =
      kind === 'images'
        ? [
            {
              name: 'square.svg',
              mimeType: 'image/svg+xml',
              buffer: Buffer.from('<svg viewBox="0 0 20 20"><rect width="20" height="20"/></svg>'),
            },
            {
              name: 'circle.svg',
              mimeType: 'image/svg+xml',
              buffer: Buffer.from(
                '<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="10"/></svg>',
              ),
            },
          ]
        : [
            {
              name: 'NotoSans.ttf',
              mimeType: 'font/ttf',
              buffer: await readFile('../app/fonts/NotoSans.ttf'),
            },
            {
              name: 'NotoSans-Bold.ttf',
              mimeType: 'font/ttf',
              buffer: await readFile('../app/fonts/NotoSans-Bold.ttf'),
            },
          ]
    let attempts = 0
    await page.route(`**/api/${singular}-assets?*`, async (route) => {
      if (route.request().method() !== 'POST') return route.continue()
      attempts++
      if (attempts === 2)
        return route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Upload interrupted. Try again.' }),
        })
      await route.continue()
    })
    await page.goto(`/#/${kind}`)
    const upload = page
      .locator('section')
      .filter({ has: page.getByRole('heading', { name: `Upload ${kind}`, exact: true }) })
    await upload.getByRole('combobox', { name: 'Visibility', exact: true }).selectOption('group')
    await upload.getByRole('combobox', { name: 'Group', exact: true }).selectOption(group.id)
    await upload
      .getByLabel(kind === 'images' ? 'Image files' : 'Font files', { exact: true })
      .setInputFiles(files)
    await upload.getByRole('button', { name: `Upload ${kind}`, exact: true }).click()
    const results = upload.getByRole('list', { name: 'Upload results' })
    await expect(results.getByText('Uploaded', { exact: true })).toHaveCount(1)
    await expect(results.getByText('Failed', { exact: true })).toHaveCount(1)
    await expect(results.getByText('Upload interrupted. Try again.', { exact: true })).toBeVisible()
    await upload.getByRole('button', { name: 'Retry failed uploads', exact: true }).click()
    await expect(results.getByText('Uploaded', { exact: true })).toHaveCount(2)
    expect(attempts).toBe(3)
    const assets = await (await request.get(`/api/${singular}-assets`)).json()
    expect(assets).toHaveLength(2)
    expect(
      assets.every(
        (asset: { scope: string; group_id: string }) =>
          asset.scope === 'group' && asset.group_id === group.id,
      ),
    ).toBe(true)
    const row = page.locator('tbody tr').filter({ hasText: assets[0].id.slice(0, 12) })
    const sharing = row.locator('.asset-sharing')
    await sharing.locator('summary').click()
    await expect(sharing.getByRole('button', { name: 'Save sharing', exact: true })).toBeVisible()
    await sharing.getByRole('combobox', { name: 'Visibility', exact: true }).selectOption('global')
    await sharing.getByRole('button', { name: 'Save sharing', exact: true }).click()
    // Scope changes move this row out of the group-filtered locator.
    const globalRow = page
      .locator('tbody tr')
      .filter({ has: page.getByRole('cell', { name: 'Global', exact: true }) })
      .filter({ has: page.locator('.asset-sharing') })
    await expect(globalRow).toHaveCount(1)
    await expect(
      globalRow.getByRole('button', { name: 'Save sharing', exact: true }),
    ).toBeDisabled()
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({
      path: `test-results/${kind}-bulk-sharing-desktop.png`,
      animations: 'disabled',
      fullPage: true,
    })
    await globalRow.locator('summary').click()
    await expect(globalRow.getByRole('button', { name: 'Save sharing', exact: true })).toBeHidden()
    await globalRow.locator('summary').click()
    await expect(globalRow.getByRole('button', { name: 'Save sharing', exact: true })).toBeVisible()
    await page.setViewportSize({ width: 390, height: 844 })
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({
      path: `test-results/${kind}-upload-mobile.png`,
      animations: 'disabled',
    })
    await globalRow.locator('summary').scrollIntoViewIfNeeded()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
    await page.screenshot({
      path: `test-results/${kind}-bulk-sharing-mobile.png`,
      animations: 'disabled',
    })
    await page.reload()
    const saved = await (await request.get(`/api/${singular}-assets`)).json()
    expect(saved.map((asset: { scope: string }) => asset.scope).sort()).toEqual(['global', 'group'])
  })
}
