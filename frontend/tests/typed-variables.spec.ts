import type { APIRequestContext } from '@playwright/test'
import { test, expect } from './fixtures'

const artwork = {
  name: 'variable-art.svg',
  mimeType: 'image/svg+xml',
  buffer: Buffer.from(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><rect x="2" y="2" width="16" height="16"/></svg>',
  ),
}
async function typedTemplate(request: APIRequestContext) {
  const response = await request.post('/api/templates', {
    data: {
      name: 'Typed inputs',
      document: {
        version: 2,
        width_mm: 24,
        length_mm: 60,
        fields: [
          {
            name: 'quantity',
            label: 'Quantity',
            type: 'number',
            default: 0,
            sample: 2,
            minimum: 0,
            maximum: 10,
          },
          { name: 'enabled', label: 'Enabled', type: 'boolean', default: false },
          { name: 'optional', label: 'Optional flag', type: 'boolean', required: false },
          { name: 'photo', label: 'Photo', type: 'image', required: false },
        ],
        elements: [
          {
            id: 'caption',
            logic_name: 'caption',
            kind: 'text',
            x: 2,
            y: 4,
            width: 35,
            height: 12,
            content: '{{quantity}} / {{enabled}}',
          },
          {
            id: 'picture',
            logic_name: 'picture',
            kind: 'image',
            x: 40,
            y: 4,
            width: 12,
            height: 12,
            visible: false,
          },
        ],
        logic: {
          version: 1,
          variables: {},
          bindings: [
            {
              target: 'picture',
              property: 'image_asset',
              expression: { kind: 'reference', name: 'photo' },
            },
            {
              target: 'picture',
              property: 'visible',
              expression: {
                kind: 'call',
                operation: 'filled',
                arguments: [{ kind: 'reference', name: 'photo' }],
              },
            },
          ],
        },
      },
    },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}

test('editor upgrades typed definitions, animates limits and restores changes with undo', async ({
  page,
  request,
}) => {
  const response = await request.post('/api/templates', {
    data: {
      name: 'Variable authoring',
      document: {
        width_mm: 24,
        length_mm: 60,
        fields: [{ name: 'count', label: 'Count', default: '3', sample: '4' }],
        elements: [
          { id: 'title', kind: 'text', x: 2, y: 4, width: 45, height: 12, content: '{{count}}' },
        ],
      },
    },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  const original = await response.json()
  await page.goto(`/#/templates/${original.id}/edit`)
  const row = page.locator('.variable-row').first()
  await row.getByRole('combobox', { name: 'Type', exact: true }).selectOption('number')
  await expect(row.getByLabel('Minimum', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Undo', exact: true }).click()
  await expect(row.getByRole('combobox', { name: 'Type', exact: true })).toHaveValue('text')
  await expect(row.getByLabel('Minimum', { exact: true })).toBeHidden()
  await expect(row.getByLabel('Sample value', { exact: true })).toHaveValue('4')
  await page.getByRole('button', { name: 'Redo', exact: true }).click()
  await expect(row.getByLabel('Minimum', { exact: true })).toBeVisible()
  await row.getByLabel('Variable name', { exact: true }).fill('quantity')
  await row.getByLabel('Field label', { exact: true }).click()
  await row.getByLabel('Default value', { exact: true }).fill('0')
  await row.getByLabel('Minimum', { exact: true }).fill('0')
  await row.getByLabel('Maximum', { exact: true }).fill('10')
  await row.getByLabel('Field label', { exact: true }).click()
  await page.getByRole('button', { name: 'Add variable', exact: true }).click()
  const boolean = page.locator('.variable-row').nth(1)
  await boolean.getByRole('combobox', { name: 'Type', exact: true }).selectOption('boolean')
  await boolean.getByRole('combobox', { name: 'Default value', exact: true }).selectOption('false')
  await page.getByRole('button', { name: 'Add variable', exact: true }).click()
  const image = page.locator('.variable-row').nth(2)
  await image.getByRole('combobox', { name: 'Type', exact: true }).selectOption('image')
  const uploaded = page.waitForResponse(
    (response) =>
      response.url().includes('/api/image-assets?') && response.request().method() === 'POST',
  )
  await image.getByLabel('Upload sample value', { exact: true }).setInputFiles(artwork)
  const asset = await (await uploaded).json()
  await expect(image.getByRole('combobox', { name: 'Sample value', exact: true })).toHaveValue(
    asset.id,
  )
  await image.getByRole('combobox', { name: 'Default value', exact: true }).selectOption(asset.id)
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page.getByText('Revision 2', { exact: true })).toBeVisible()
  const saved = await (await request.get(`/api/templates/${original.id}`)).json()
  expect(saved.document.version).toBe(2)
  expect(saved.document.fields[0]).toMatchObject({
    name: 'quantity',
    type: 'number',
    default: 0,
    sample: 0,
    minimum: 0,
    maximum: 10,
  })
  expect(saved.document.fields[1].default).toBe(false)
  expect(saved.document.fields[2]).toMatchObject({
    type: 'image',
    sample: { image_asset: asset.id },
    default: { image_asset: asset.id },
  })
  expect(saved.document.elements[0]).toMatchObject({ content: '{{quantity}}', logic_name: 'text1' })
  await page
    .locator('.variable-fields')
    .screenshot({ path: 'test-results/typed-editor-desktop.png' })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.locator('.variable-fields').scrollIntoViewIfNeeded()
  await page
    .locator('.variable-fields')
    .screenshot({ path: 'test-results/typed-editor-mobile.png' })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('typed label inputs preserve zero, false, null and uploaded images in submission', async ({
  page,
  request,
}) => {
  const template = await typedTemplate(request)
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto(`/#/new?template=${template.id}`)
  await expect(page.getByLabel('Quantity', { exact: true })).toHaveValue('0')
  await expect(page.getByLabel('Enabled', { exact: true })).not.toBeChecked()
  await expect(page.getByRole('combobox', { name: 'Optional flag', exact: true })).toHaveValue('')
  await page.getByLabel('Quantity', { exact: true }).fill('11')
  await expect(page.getByRole('button', { name: 'Add to queue', exact: true })).toBeDisabled()
  await page.getByLabel('Quantity', { exact: true }).fill('0')
  // Let the valid preview finish before testing image input. Otherwise this
  // upload races the deliberately triggered previews for scarce render slots.
  await expect(page.getByRole('button', { name: 'Add to queue', exact: true })).toBeEnabled()
  const uploaded = page.waitForResponse(
    (response) =>
      response.url().includes('/api/image-assets?') && response.request().method() === 'POST',
  )
  await page.getByLabel('Upload photo', { exact: true }).setInputFiles(artwork)
  const uploadResponse = await uploaded
  expect(uploadResponse.ok(), await uploadResponse.text()).toBeTruthy()
  const asset = await uploadResponse.json()
  await expect(page.getByRole('combobox', { name: 'Photo', exact: true })).toHaveValue(asset.id)
  await page.getByRole('combobox', { name: 'Optional flag', exact: true }).selectOption('false')
  await page.getByRole('combobox', { name: 'Optional flag', exact: true }).selectOption('')
  await expect(page.getByRole('button', { name: 'Add to queue', exact: true })).toBeEnabled()
  await expect(page.getByRole('combobox', { name: 'Photo', exact: true })).toContainText(
    'variable-art.svg',
  )
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: 'test-results/typed-label-mobile.png', fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  const submitted = page.waitForResponse(
    (response) => response.url().endsWith('/api/jobs') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  const result = await submitted
  expect(result.ok(), await result.text()).toBeTruthy()
  expect(result.request().postDataJSON().data).toEqual({
    quantity: 0,
    enabled: false,
    optional: null,
    photo: { image_asset: asset.id },
  })
  expect(errors).toEqual([])
})

test('renaming inputs and duplicating or deleting elements preserves valid bindings', async ({
  page,
  request,
}) => {
  const template = await typedTemplate(request)
  await page.goto(`/#/templates/${template.id}/edit`)
  const photo = page.locator('.variable-row').nth(3)
  await photo.getByLabel('Variable name', { exact: true }).fill('artwork')
  await photo.getByLabel('Field label', { exact: true }).click()
  await photo.getByRole('button', { name: 'Remove variable', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Remove references' })).toBeVisible()
  await expect(page.locator('.variable-row')).toHaveCount(4)
  await page.getByRole('button', { name: '2. image', exact: true }).click()
  await page.getByRole('tab', { name: 'Content', exact: true }).click()
  await page.getByRole('button', { name: 'Duplicate element', exact: true }).click()
  await expect(page.locator('.element-list button')).toHaveCount(3)
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page.getByText('Revision 2', { exact: true })).toBeVisible()
  const saved = await (await request.get(`/api/templates/${template.id}`)).json()
  expect(saved.document.logic.bindings[0].expression.name).toBe('artwork')
  expect(saved.document.logic.bindings[1].expression.arguments[0].name).toBe('artwork')
  expect(saved.document.logic.bindings).toHaveLength(4)
  expect(saved.document.elements[2].logic_name).not.toBe(saved.document.elements[1].logic_name)
  expect(saved.document.logic.bindings[2].target).toBe(saved.document.elements[2].id)
  expect(saved.document.logic.bindings[2].expression.node_id).toBeTruthy()
  expect(saved.document.logic.bindings[2].expression.node_id).not.toBe(
    saved.document.logic.bindings[3].expression.arguments[0].node_id,
  )
  await page.getByRole('button', { name: 'Delete element', exact: true }).click()
  await expect(page.locator('.element-list button')).toHaveCount(2)
  await page.getByRole('button', { name: 'Undo', exact: true }).click()
  await expect(page.locator('.element-list button')).toHaveCount(3)
  await page.getByRole('button', { name: 'Redo', exact: true }).click()
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page.getByText('Revision 3', { exact: true })).toBeVisible()
  const removed = await (await request.get(`/api/templates/${template.id}`)).json()
  expect(removed.document.logic.bindings).toHaveLength(2)
})

test('CSV maps image cells, reports typed row errors and saves typed draft values', async ({
  page,
  request,
}) => {
  const template = await typedTemplate(request)
  await page.goto(`/#/runs?template=${template.id}`)
  await page
    .getByLabel('CSV content', { exact: true })
    .fill('quantity,enabled,photo\n0,false,art\nwrong,true,art')
  await page.getByRole('button', { name: 'Read CSV', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Map images', exact: true })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Photo: art', exact: true })).toHaveCount(1)
  const uploaded = page.waitForResponse(
    (response) =>
      response.url().includes('/api/image-assets?') && response.request().method() === 'POST',
  )
  await page.getByLabel('Upload photo: art', { exact: true }).setInputFiles(artwork)
  const asset = await (await uploaded).json()
  await expect(page.getByRole('combobox', { name: 'Photo: art', exact: true })).toHaveValue(
    asset.id,
  )
  await page.getByRole('button', { name: 'Validate and preview run', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Record 3:' })).toBeVisible()
  await page.getByLabel('Select record 3', { exact: true }).uncheck()
  const prepared = page.waitForResponse((response) => response.url().endsWith('/api/runs/prepare'))
  await page.getByRole('button', { name: 'Validate and preview run', exact: true }).click()
  const result = await prepared
  expect(result.ok(), await result.text()).toBeTruthy()
  expect(result.request().postDataJSON().image_mapping).toEqual({
    photo: { art: { image_asset: asset.id } },
  })
  const draft = (await result.json()).run
  expect(draft.rows[0].payload).toMatchObject({
    quantity: 0,
    enabled: false,
    photo: { image_asset: asset.id },
  })
  await expect(page.getByRole('img', { name: 'CSV label preview', exact: true })).toBeVisible()
  await expect(page.locator('.csv-values')).toContainText('Uploaded image')
})
