import { readFile } from 'node:fs/promises'
import type { APIRequestContext } from '@playwright/test'
import { test, expect } from './fixtures'

async function createUser(request: APIRequestContext, username: string) {
  const payload = { username, password: 'deletion-test-password', role_ids: ['member'] }
  const preview = await request.post('/api/admin/access-preview', {
    data: { resource: 'users', method: 'POST', payload },
  })
  expect(preview.ok()).toBeTruthy()
  const result = await request.post('/api/admin/users', {
    data: payload,
    headers: { 'X-Access-Confirmation': (await preview.json()).confirmation_token },
  })
  expect(result.ok()).toBeTruthy()
  return result.json()
}

async function uploadAssets(request: APIRequestContext, headers: Record<string, string> = {}) {
  const image = await request.post('/api/image-assets?name=Shared%20artwork', {
    data: Buffer.from('<svg viewBox="0 0 20 20"><path d="M2 2H18V18H2Z"/></svg>'),
    headers: { ...headers, 'Content-Type': 'application/octet-stream' },
  })
  const font = await request.post('/api/font-assets', {
    data: await readFile('../app/fonts/NotoSans.ttf'),
    headers: { ...headers, 'Content-Type': 'application/octet-stream' },
  })
  expect(image.ok()).toBeTruthy()
  expect(font.ok()).toBeTruthy()
  return { image: await image.json(), font: await font.json() }
}

function document(image: string, font: string) {
  return {
    width_mm: 24,
    length_mm: 60,
    out_of_bounds: 'clip',
    fields: [],
    elements: [
      { id: 'picture', kind: 'image', x: 2, y: 2, width: 16, height: 16, image_asset: image },
      { id: 'caption', kind: 'text', x: 20, y: 2, width: 36, height: 16, content: 'Hello', font },
    ],
  }
}

test('account deletion confirms content removal, shows placeholders and restores the account', async ({
  page,
  request,
  playwright,
  baseURL,
}) => {
  await createUser(request, 'author')
  const author = await playwright.request.newContext({
    baseURL,
    storageState: { cookies: [], origins: [] },
    extraHTTPHeaders: {},
  })
  try {
    const login = await author.post('/api/auth/login', {
      data: { username: 'author', password: 'deletion-test-password' },
    })
    const headers = { 'X-CSRF-Token': (await login.json()).csrf_token }
    const { image, font } = await uploadAssets(author, headers)
    const layout = document(image.id, font.id)
    const own = await author.post('/api/templates', {
      data: { name: 'Author template', document: layout },
      headers,
    })
    expect(own.ok()).toBeTruthy()
    const dependent = await request.post('/api/templates', {
      data: { name: 'Dependent template', document: layout },
    })
    expect(dependent.ok(), await dependent.text()).toBeTruthy()
    const identifier = (await dependent.json()).id
    const profiles = await (await request.get('/api/tape-profiles')).json()
    const queued = await request.post('/api/jobs', {
      data: { template: identifier, tape_profile: profiles[0].id, data: {} },
    })
    expect(queued.ok()).toBeTruthy()

    await page.goto('/#/admin')
    await page.getByRole('button', { name: 'Delete account author', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Delete account', exact: true })
    await expect(dialog).toContainText('30 days')
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
    expect((await author.get('/api/templates')).status()).toBe(200)
    await page.getByRole('button', { name: 'Delete account author', exact: true }).click()
    await dialog.getByRole('button', { name: 'Delete account', exact: true }).click()
    await expect(page.getByText('Account deleted.', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Edit author', exact: true })).toHaveCount(0)
    expect((await author.get('/api/templates')).status()).toBe(401)
    expect((await (await request.get('/api/access-holds')).json()).length).toBe(1)

    await page.goto('/#/templates')
    const card = page.locator('article').filter({ hasText: 'Dependent template' })
    await expect(card.getByText('Image deleted.', { exact: false })).toBeVisible()
    await expect(card.getByText('Font deleted.', { exact: false })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Author template', exact: true })).toHaveCount(0)
    await card.getByRole('link', { name: 'Edit visually', exact: true }).click()
    await expect(
      page.getByText('Missing image in element picture.', { exact: false }),
    ).toBeVisible()
    await expect(page.getByText('Missing font in element caption.', { exact: false })).toBeVisible()
    await page.screenshot({ path: 'test-results/deletion-placeholders.png', fullPage: true })
    await page.goto(`/#/new?template=${identifier}`)
    await expect(
      page.getByText('Missing image in element picture.', { exact: false }),
    ).toBeVisible()
    await expect(page.getByRole('button', { name: 'Add to queue', exact: true })).toBeDisabled()

    await page.goto('/#/admin')
    await page.getByRole('button', { name: 'Deleted accounts and content', exact: true }).click()
    await page.getByRole('button', { name: 'Restore author', exact: true }).click()
    await page.getByRole('button', { name: 'Confirm access changes', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Edit author', exact: true })).toBeVisible()
    expect((await (await request.get('/api/image-assets')).json()).length).toBe(1)
    expect((await (await request.get('/api/font-assets')).json()).length).toBe(1)
    expect((await (await request.get('/api/access-holds')).json()).length).toBe(1)
    expect(
      (await (await request.get(`/api/templates/${identifier}`)).json()).asset_notices,
    ).toEqual([])
  } finally {
    await author.dispose()
  }
})

test('administrators delete referenced images, fonts and templates and restore them from trash', async ({
  page,
  request,
}) => {
  const { image, font } = await uploadAssets(request)
  const created = await request.post('/api/templates', {
    data: { name: 'Referenced design', document: document(image.id, font.id) },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
  const id = (await created.json()).id
  await page.goto('/#/images')
  await page
    .getByRole('row')
    .filter({ hasText: 'Shared artwork' })
    .getByRole('button', { name: 'Delete', exact: true })
    .click()
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(page.getByText('No images uploaded.', { exact: true })).toBeVisible()
  await page.goto('/#/fonts')
  await page.getByRole('button', { name: 'Delete font', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Delete font', exact: true })).toHaveCount(0)
  await page.goto('/#/templates')
  const card = page.locator('article').filter({ hasText: 'Referenced design' })
  await expect(card.getByText('Image deleted.', { exact: false })).toBeVisible()
  await expect(card.getByText('Font deleted.', { exact: false })).toBeVisible()
  await card.getByRole('button', { name: 'Delete template', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(card).toHaveCount(0)
  await page.goto('/#/admin')
  await page.getByRole('button', { name: 'Deleted accounts and content', exact: true }).click()
  for (const name of ['Shared artwork', font.family, 'Referenced design']) {
    await page.getByRole('button', { name: `Restore ${name}`, exact: true }).click()
    await expect(page.getByRole('button', { name: `Restore ${name}`, exact: true })).toHaveCount(0)
  }
  expect((await (await request.get(`/api/templates/${id}`)).json()).asset_notices).toEqual([])
})
