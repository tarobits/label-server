import { test, expect } from './fixtures'
import type { APIRequestContext } from '@playwright/test'

async function seedLibrary(request: APIRequestContext) {
  const groups = []
  for (const name of ['Facilities', 'Operations']) {
    const payload = { name, members: [] }
    const preview = await request.post('/api/admin/access-preview', {
      data: { resource: 'groups', method: 'POST', payload },
    })
    expect(preview.ok()).toBeTruthy()
    const response = await request.post('/api/admin/groups', {
      data: payload,
      headers: { 'X-Access-Confirmation': (await preview.json()).confirmation_token },
    })
    expect(response.ok()).toBeTruthy()
    groups.push(await response.json())
  }
  const templates = []
  for (const [name, scope, width, group, field] of [
    ['Network cables', 'personal', 24, null, 'asset_id'],
    ['Storage boxes', 'personal', 12, null, null],
    ['Door signs', 'group', 24, groups[0].id, null],
    ['Asset inventory', 'group', 12, groups[1].id, null],
    ['Shipping labels', 'global', 24, null, null],
  ] as const) {
    const response = await request.post('/api/templates', {
      data: {
        name,
        scope,
        group_id: group,
        document: {
          width_mm: width,
          length_mm: 60,
          out_of_bounds: 'clip',
          fields: field ? [{ name: field, label: 'Equipment ID', sample: 'RACK-07' }] : [],
          elements: [
            {
              id: 'text',
              kind: 'text',
              x: 2,
              y: 2,
              width: 56,
              height: width - 4,
              font_size: 3,
              content: field ? `{{${field}}}` : name,
            },
          ],
        },
      },
    })
    expect(response.ok(), await response.text()).toBeTruthy()
    templates.push(await response.json())
  }
  return { groups, templates }
}

test('the library separates scopes and combines search, tape width, and group filters', async ({
  page,
  request,
}) => {
  const { groups } = await seedLibrary(request)
  const reads: string[] = []
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === '/api/templates') reads.push(request.url())
  })
  await page.goto('/#/templates')
  const cards = page.locator('article')
  await expect(cards).toHaveCount(6)
  for (const name of ['Personal templates', 'Group templates', 'Global templates'])
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
  await expect(cards.filter({ hasText: 'Door signs' })).toContainText('Facilities')
  await expect
    .poll(() =>
      page
        .locator('.template-preview img')
        .evaluateAll((images) =>
          images.every((image) => (image as HTMLImageElement).naturalWidth > 0),
        ),
    )
    .toBe(true)
  await page.screenshot({
    path: 'test-results/template-library-desktop.png',
    fullPage: true,
    animations: 'disabled',
  })
  const scopes = page.getByRole('group', { name: 'Template visibility', exact: true })
  await scopes.getByRole('button', { name: 'Personal', exact: true }).click()
  await expect(cards).toHaveCount(2)
  await expect(scopes.getByRole('button', { name: 'Personal', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  const search = page.getByRole('searchbox', { name: 'Search templates', exact: true })
  await search.fill('EQUIPMENT')
  await expect(cards).toHaveCount(1)
  await expect(cards.first()).toContainText('Network cables')
  await search.fill('  network   cables  ')
  await expect(cards).toHaveCount(1)
  await page.getByRole('combobox', { name: 'Tape width', exact: true }).selectOption('12')
  await expect(cards).toHaveCount(0)
  await expect(page.getByText('No matching templates.', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Clear filters', exact: true }).click()
  await expect(cards).toHaveCount(6)
  await scopes.getByRole('button', { name: 'Groups', exact: true }).click()
  await expect(cards).toHaveCount(2)
  await page
    .getByRole('combobox', { name: 'Template group', exact: true })
    .selectOption(groups[0].id)
  await expect(cards).toHaveCount(1)
  await expect(cards.first()).toContainText('Door signs')
  await search.fill('operations')
  await expect(cards).toHaveCount(0)
  await page.getByRole('combobox', { name: 'Template group', exact: true }).selectOption('')
  await expect(cards).toHaveCount(1)
  await expect(cards.first()).toContainText('Asset inventory')
  expect(reads).toHaveLength(1)
})

test('template filters survive reload and returning from the editor', async ({ page, request }) => {
  const { templates } = await seedLibrary(request)
  await page.goto('/#/templates?scope=personal&width=24&q=network')
  const cards = page.locator('article')
  await expect(cards).toHaveCount(1)
  await cards.getByRole('link', { name: 'Edit visually', exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`/templates/${templates[0].id}/edit`))
  await page.goBack()
  await expect(cards).toHaveCount(1)
  await expect(page.getByRole('searchbox', { name: 'Search templates', exact: true })).toHaveValue(
    'network',
  )
  await page.reload()
  await expect(cards).toHaveCount(1)
  await expect(page.getByRole('combobox', { name: 'Tape width', exact: true })).toHaveValue('24')
  const search = page.getByRole('searchbox', { name: 'Search templates', exact: true })
  await search.fill('')
  await search.pressSequentially('Network cables', { delay: 10 })
  await expect(search).toHaveValue('Network cables')
  await expect(cards).toHaveCount(1)
})

test('renaming a template group refreshes its cached library name', async ({ page, request }) => {
  const { groups } = await seedLibrary(request)
  await page.goto(`/#/templates?scope=group&group=${groups[0].id}`)
  await expect(page.locator('article')).toContainText('Facilities')
  await page.getByRole('link', { name: 'Administration', exact: true }).click()
  await page.getByRole('button', { name: 'Template groups', exact: true }).click()
  await page.getByRole('button', { name: 'Edit group Facilities', exact: true }).click()
  await page.getByLabel('Group name', { exact: true }).fill('Building services')
  await page.getByRole('button', { name: 'Review group changes', exact: true }).click()
  await page
    .getByRole('dialog', { name: 'Review effective access', exact: true })
    .getByRole('button', { name: 'Confirm access changes', exact: true })
    .click()
  await expect(
    page.getByRole('button', { name: 'Edit group Building services', exact: true }),
  ).toBeVisible()
  await page.getByRole('link', { name: 'Templates', exact: true }).click()
  await expect(page.locator('article').filter({ hasText: 'Door signs' })).toContainText(
    'Building services',
  )
  await page
    .getByRole('group', { name: 'Template visibility', exact: true })
    .getByRole('button', { name: 'Groups', exact: true })
    .click()
  await expect(
    page
      .getByRole('combobox', { name: 'Template group', exact: true })
      .getByRole('option', { name: 'Building services', exact: true }),
  ).toHaveCount(1)
})

for (const reducedMotion of ['no-preference', 'reduce'] as const) {
  test(`template browsing is keyboard accessible on mobile with ${reducedMotion}`, async ({
    page,
    request,
  }) => {
    await seedLibrary(request)
    await page.emulateMedia({ reducedMotion })
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/#/templates')
    const scopes = page.getByRole('group', { name: 'Template visibility', exact: true })
    const all = scopes.getByRole('button', { name: 'All', exact: true })
    await all.focus()
    await page.keyboard.press('Tab')
    const personal = scopes.getByRole('button', { name: 'Personal', exact: true })
    await expect(personal).toBeFocused()
    await page.keyboard.press('Space')
    await expect(personal).toHaveAttribute('aria-pressed', 'true')
    await expect(page.locator('article')).toHaveCount(2)
    await page.keyboard.press('Tab')
    await page.keyboard.press('Enter')
    const group = page.getByRole('combobox', { name: 'Template group', exact: true })
    await expect(group).toBeVisible()
    await page.keyboard.press('Tab')
    await page.keyboard.press('Space')
    await expect(group).toBeHidden()
    await expect(page.locator('article')).toHaveCount(2)
    await expect(page.locator('html')).toHaveAttribute(
      'data-motion',
      reducedMotion === 'reduce' ? 'reduce' : 'full',
    )
    await page.screenshot({
      path: `test-results/template-library-mobile-${reducedMotion}.png`,
      fullPage: true,
    })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  })
}
