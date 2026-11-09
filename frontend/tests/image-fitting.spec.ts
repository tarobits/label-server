import { test, expect } from './fixtures'
import { showEditorSettings } from './editor-settings'

test('fit box follows logic-selected artwork, rotated geometry, and undo/redo', async ({
  page,
  request,
}) => {
  const upload = await request.post('/api/image-assets?name=Logic%20artwork', {
    data: Buffer.from('<svg viewBox="0 0 100 50"><rect width="100" height="50"/></svg>'),
    headers: { 'Content-Type': 'image/svg+xml' },
  })
  expect(upload.ok()).toBeTruthy()
  const asset = await upload.json()
  const document = {
    version: 2,
    width_mm: 24,
    length_mm: 60,
    out_of_bounds: 'clip',
    fields: [],
    elements: [
      {
        id: 'art',
        logic_name: 'image1',
        kind: 'image',
        x: 2,
        y: 2,
        width: 30,
        height: 8,
        image_asset: null,
        preserve_aspect: true,
        lock_aspect: true,
        image_scale: 0.5,
      },
    ],
  }
  const compiled = await request.post('/api/logic/compile', {
    data: { document, source: `image1.image_asset = image("${asset.id}");` },
  })
  const logic = await compiled.json()
  expect(logic.valid).toBeTruthy()
  const saved = await request.post('/api/templates', {
    data: { name: 'Logic artwork', document: { ...document, logic: logic.program } },
  })
  expect(saved.ok(), await saved.text()).toBeTruthy()
  const template = await saved.json()
  await page.goto(`/#/templates/${template.id}/edit?element=art`)
  await showEditorSettings(page, 'Position & size')
  const width = page.getByLabel('Width (mm)', { exact: true })
  const height = page.getByLabel('Height (mm)', { exact: true })
  const fit = page.getByRole('button', { name: 'Fit box to image', exact: true })
  await expect(width).toHaveValue('30')
  await expect(height).toHaveValue('8')
  await fit.click()
  await expect(width).toHaveValue('16')
  await expect(height).toHaveValue('8')
  await expect(width).toBeFocused()
  await expect(fit).not.toBeVisible()
  await page.getByRole('button', { name: 'Undo', exact: true }).click()
  await expect(width).toHaveValue('30')
  await expect(fit).toBeVisible()
  await page.getByRole('button', { name: 'Redo', exact: true }).click()
  await expect(width).toHaveValue('16')
  await expect(fit).not.toBeVisible()
  await page.getByRole('button', { name: 'Undo', exact: true }).click()
  await page.getByRole('combobox', { name: 'Rotation', exact: true }).selectOption('90')
  await expect(width).toHaveValue('8')
  await width.fill('6')
  await expect(height).toHaveValue('22.5')
  await fit.click()
  await expect(width).toHaveValue('6')
  await expect(height).toHaveValue('12')
  await expect(fit).not.toBeVisible()
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await page.reload()
  await showEditorSettings(page, 'Image adjustments')
  await expect(page.getByLabel('Image scale', { exact: true })).toHaveValue('0.5')
  await expect(page.getByLabel('Keep image proportions', { exact: true })).toBeChecked()
  await showEditorSettings(page, 'Position & size')
  await expect(width).toHaveValue('6')
  await expect(height).toHaveValue('12')
  await expect(fit).not.toBeVisible()
  await page.getByLabel('Lock box proportions', { exact: true }).uncheck()
  await width.fill('8')
  await expect(height).toHaveValue('12')
  await expect(fit).toBeVisible()
  await page.screenshot({ path: 'test-results/image-fit-reset.png', animations: 'disabled' })
})
