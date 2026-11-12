import { test, expect } from './fixtures'
import type { APIRequestContext, Page } from '@playwright/test'

test('pressing a template preview keeps the whole card clickable during press feedback', async ({
  page,
  request,
}) => {
  const items = await seedTemplates(request, page)
  await page.goto('/#/new?template=text')
  await page.getByRole('button', { name: 'Change template', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Choose template', exact: true })
  await dialog.getByRole('searchbox').fill('Packing 01')
  const preview = dialog.locator(`[data-template-id="${items[0].id}"] .template-preview`)
  await preview.scrollIntoViewIfNeeded()
  await page.evaluate(async () => {
    await Promise.all(
      document
        .getAnimations()
        .filter((a) => a.effect?.getComputedTiming().iterations !== Infinity)
        .map((a) => a.finished.catch(() => {})),
    )
  })
  const box = (await preview.boundingBox())!
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  // Hold longer than the press animation; the release must hit the same control.
  await page.waitForTimeout(200)
  await page.mouse.up()
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('button', { name: 'Change template', exact: true })).toHaveJSProperty(
    'value',
    items[0].id,
  )
})

async function seedTemplates(request: APIRequestContext, page: Page) {
  const items = []
  for (let index = 1; index <= 26; index++) {
    const response = await request.post('/api/templates', {
      data: {
        name: index === 25 ? 'Café equipment' : `Packing ${String(index).padStart(2, '0')}`,
        scope: index % 2 ? 'personal' : 'global',
        document: {
          width_mm: index === 24 ? 12 : 24,
          length_mm: 60,
          out_of_bounds: 'clip',
          fields: index === 25 ? [{ name: 'asset', label: 'Equipment ID', sample: 'Rack 7' }] : [],
          elements: [
            {
              id: 'text',
              kind: 'text',
              x: 2,
              y: 2,
              width: 50,
              height: 8,
              font_size: 3,
              content: index === 25 ? '{{asset}}' : `Packing ${index}`,
            },
          ],
        },
      },
    })
    expect(response.ok(), await response.text()).toBeTruthy()
    items.push(await response.json())
  }
  // The physical test adapter is TZe-only. Supply one fixed-media catalogue entry
  // to exercise filtering of designs for other printer families.
  await page.route('**/api/templates', async (route) => {
    const response = await route.fetch()
    const values = await response.json()
    await route.fulfill({
      json: values.map((item: { id: string; document: object }) =>
        item.id === items[25].id
          ? {
              ...item,
              document: {
                ...item.document,
                media: { media_family: 'fixed_label', label_length_mm: 60 },
              },
            }
          : item,
      ),
    })
  })
  return items
}

test('picker searches, filters and paginates without losing drafts; recent choices survive reload', async ({
  page,
  request,
}) => {
  const items = await seedTemplates(request, page)
  await page.goto('/#/new?template=text')
  const text = page.getByLabel('Label text', { exact: true })
  await text.fill('Keep my draft')
  const trigger = page.getByRole('button', { name: 'Change template', exact: true })
  await trigger.click()
  const dialog = page.getByRole('dialog', { name: 'Choose template', exact: true })
  const search = dialog.getByRole('searchbox', { name: 'Search templates', exact: true })
  await expect(search).toBeFocused()
  await expect(dialog.locator('article')).toHaveCount(12)
  await expect(dialog.getByText('Page 1 of 3', { exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(dialog.getByText('Page 2 of 3', { exact: true })).toBeVisible()
  await search.fill('missing template')
  await expect(dialog.getByText('No matching templates.', { exact: true })).toBeVisible()
  await search.press('Enter')
  await expect(dialog).toBeVisible()
  await search.press('Escape')
  await expect(dialog).not.toBeVisible()
  await expect(trigger).toBeFocused()
  await expect(text).toHaveValue('Keep my draft')
  await page.route('**/api/jobs', (route) =>
    route.request().method() === 'POST'
      ? route.fulfill({
          status: 422,
          json: {
            detail: [
              {
                loc: ['body', 'template'],
                msg: 'Template no longer available',
                type: 'value_error',
              },
            ],
          },
        })
      : route.continue(),
  )
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  await expect(
    page.getByRole('alert').filter({ hasText: 'Template no longer available' }),
  ).toBeVisible()
  await page.unroute('**/api/jobs')
  await trigger.click()
  await search.fill('CAFE equipment')
  await expect(dialog.locator('article')).toHaveCount(1)
  await expect(
    dialog.getByRole('button', { name: 'Use Café equipment', exact: true }),
  ).toBeVisible()
  await search.fill('Equipment ID')
  await expect(dialog.locator('article')).toHaveCount(1)
  await dialog.getByRole('button', { name: 'Clear filters', exact: true }).click()
  await dialog.getByRole('combobox', { name: 'Tape width', exact: true }).selectOption('12')
  await expect(dialog.getByRole('button', { name: 'Use Packing 24', exact: true })).toBeVisible()
  await expect(dialog.locator('article')).toHaveCount(1)
  await dialog.getByRole('combobox', { name: 'Visibility', exact: true }).selectOption('personal')
  await expect(dialog.getByText('No matching templates.', { exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: 'Clear filters', exact: true }).click()
  await dialog.getByRole('combobox', { name: 'Media', exact: true }).selectOption('fixed_label')
  await expect(dialog.locator('article')).toHaveCount(1)
  await dialog.getByRole('checkbox', { name: 'Compatible with destination', exact: true }).check()
  await expect(dialog.getByText('No matching templates.', { exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: 'Clear filters', exact: true }).click()
  await search.fill('Packing 23')
  await dialog.getByRole('button', { name: 'Use Packing 23', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(dialog).not.toBeVisible()
  await expect(trigger).toHaveJSProperty('value', items[22].id)
  await expect(page).toHaveURL(new RegExp(`template=${items[22].id}`))
  await page.reload()
  await trigger.click()
  await expect(dialog.locator('article').first()).toHaveAttribute('data-template-id', items[22].id)
  await expect(dialog.locator('article').first().getByText('Recent', { exact: true })).toBeVisible()
  // Stored IDs never reintroduce templates the server no longer makes available.
  await page.route('**/api/templates', async (route) => {
    const response = await route.fetch()
    const values = await response.json()
    await route.fulfill({ json: values.filter((item: { id: string }) => item.id !== items[22].id) })
  })
  await page.reload()
  await trigger.click()
  await search.fill('Packing 23')
  await expect(dialog.getByText('No matching templates.', { exact: true })).toBeVisible()
})

for (const [width, height] of [
  [1024, 600],
  [390, 844],
]) {
  test(`template picker fits ${width} × ${height} with scrollable results and visible controls`, async ({
    page,
    request,
  }) => {
    await seedTemplates(request, page)
    await page.setViewportSize({ width, height })
    await page.goto('/#/new?template=text')
    await page.getByRole('button', { name: 'Change template', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Choose template', exact: true })
    await expect(dialog.locator('article')).toHaveCount(12)
    await expect
      .poll(() =>
        dialog
          .locator('.template-preview img')
          .first()
          .evaluate((img) => (img as HTMLImageElement).naturalWidth),
      )
      .toBeGreaterThan(0)
    await page.screenshot({
      path: `test-results/template-picker-${width}.png`,
      animations: 'disabled',
    })
    const bounds = (await dialog.boundingBox())!
    expect(bounds.x).toBeGreaterThanOrEqual(0)
    expect(bounds.y).toBeGreaterThanOrEqual(0)
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width)
    expect(bounds.y + bounds.height).toBeLessThanOrEqual(height)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
    const results = dialog.getByRole('region', { name: 'Template results', exact: true })
    expect(
      await results.evaluate((element) => element.scrollHeight > element.clientHeight),
    ).toBeTruthy()
    const next = dialog.getByRole('button', { name: 'Next', exact: true })
    const nextBox = (await next.boundingBox())!
    expect(nextBox.y + nextBox.height).toBeLessThanOrEqual(height)
    await next.click()
    await expect(dialog.getByText('Page 2 of 3', { exact: true })).toBeVisible()
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    await expect(page.getByRole('button', { name: 'Change template', exact: true })).toBeFocused()
    await page.screenshot({
      path: `test-results/new-label-picker-closed-${width}.png`,
      animations: 'disabled',
    })
  })
}

test('picker tolerates unavailable browser storage and failed previews', async ({ page }) => {
  await page.addInitScript(() => {
    Storage.prototype.getItem = () => {
      throw new Error('Storage unavailable')
    }
    Storage.prototype.setItem = () => {
      throw new Error('Storage unavailable')
    }
  })
  await page.route('**/api/templates/*/preview.webp?**', (route) => route.fulfill({ status: 503 }))
  await page.goto('/#/new?template=text')
  await page.getByRole('button', { name: 'Change template', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Choose template', exact: true })
  await expect(dialog.getByText('Preview unavailable', { exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: 'Retry preview', exact: true }).click()
  await expect(dialog).toBeVisible()
  await dialog.locator('article .picker-select').click()
  await expect(dialog).not.toBeVisible()
  await expect(page.getByRole('button', { name: 'Change template', exact: true })).toHaveJSProperty(
    'value',
    'text',
  )
})

for (const [width, height] of [
  [1024, 600],
  [390, 844],
]) {
  test(`CSV template picker preserves imports and fits ${width} × ${height}`, async ({
    page,
    request,
  }) => {
    const items = await seedTemplates(request, page)
    await page.setViewportSize({ width, height })
    await page.goto('/#/runs?template=text')
    await page.getByLabel('Run name', { exact: true }).fill('Equipment import')
    const csv = page.getByLabel('CSV content', { exact: true })
    await csv.fill('Asset\nRack 7')
    await page.getByRole('button', { name: 'Read CSV', exact: true }).click()
    await page.getByRole('combobox', { name: 'Label text', exact: true }).selectOption('Asset')
    const trigger = page.getByRole('button', { name: 'Change template', exact: true })
    await trigger.click()
    const dialog = page.getByRole('dialog', { name: 'Choose template', exact: true })
    const search = dialog.getByRole('searchbox', { name: 'Search templates', exact: true })
    await expect(search).toBeFocused()
    await expect(dialog.locator('article')).toHaveCount(12)
    await page.screenshot({
      path: `test-results/csv-template-picker-${width}.png`,
      animations: 'disabled',
    })
    const bounds = (await dialog.boundingBox())!
    expect(bounds.x).toBeGreaterThanOrEqual(0)
    expect(bounds.y).toBeGreaterThanOrEqual(0)
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width)
    expect(bounds.y + bounds.height).toBeLessThanOrEqual(height)
    await search.press('Escape')
    await expect(dialog).toBeHidden()
    await expect(trigger).toBeFocused()
    await expect(csv).toHaveValue('Asset\nRack 7')
    await expect(page.getByRole('combobox', { name: 'Label text', exact: true })).toHaveValue(
      'Asset',
    )
    await trigger.click()
    await search.fill('Packing 26')
    await expect(dialog.locator('article')).toHaveCount(1)
    await dialog.getByRole('checkbox', { name: 'Compatible with destination', exact: true }).check()
    await expect(dialog.getByText('No matching templates.', { exact: true })).toBeVisible()
    await search.fill('Equipment ID')
    await dialog.getByRole('button', { name: 'Use Café equipment', exact: true }).click()
    await expect(dialog).toBeHidden()
    await expect(trigger).toHaveJSProperty('value', items[24].id)
    await expect(page).toHaveURL(new RegExp(`template=${items[24].id}`))
    await expect(page.getByLabel('Run name', { exact: true })).toHaveValue('Equipment import')
    await expect(csv).toHaveValue('Asset\nRack 7')
    await expect(page.getByRole('combobox', { name: 'Label text', exact: true })).toHaveCount(0)
    await page.getByRole('combobox', { name: 'Equipment ID', exact: true }).selectOption('Asset')
    await trigger.scrollIntoViewIfNeeded()
    await page.screenshot({
      path: `test-results/csv-template-picker-closed-${width}.png`,
      animations: 'disabled',
    })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
    await page.reload()
    await trigger.click()
    await expect(dialog.locator('article').first()).toHaveAttribute(
      'data-template-id',
      items[24].id,
    )
  })
}
