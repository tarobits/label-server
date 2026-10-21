import { test, expect } from './fixtures'
import { showEditorSettings, showEditorTab } from './editor-settings'

test('task-based inspector keeps every setting editable and preserves values across tabs and reloads', async ({
  page,
  request,
}) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/#/templates/new')
  await page.getByLabel('Template name', { exact: true }).fill('Organized inspector')
  await page.getByRole('button', { name: 'Add text', exact: true }).click()
  const tabs = page.getByRole('tablist', { name: 'Element settings' })
  await expect(tabs.getByRole('tab')).toHaveText(['Content', 'Style', 'Layout'])
  await expect(tabs.getByRole('tab', { name: 'Content' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByLabel('X (mm)', { exact: true })).toBeHidden()
  await expect(page.getByLabel('Font size (mm)', { exact: true })).toBeHidden()
  await page.getByRole('textbox', { name: 'Content', exact: true }).fill('Rack 42')
  await tabs.getByRole('tab', { name: 'Content', exact: true }).focus()
  await page.keyboard.press('ArrowRight')
  await expect(tabs.getByRole('tab', { name: 'Style' })).toBeFocused()
  await page.getByLabel('Font size (mm)', { exact: true }).fill('4')
  await page.getByLabel('Bold', { exact: true }).check()
  await page
    .getByRole('combobox', { name: 'Horizontal text alignment', exact: true })
    .selectOption('center')
  await showEditorSettings(page, 'Spacing & padding')
  await page.getByLabel('Left padding (mm)', { exact: true }).fill('1.5')
  await page.getByLabel('Horizontal character spacing (mm)', { exact: true }).fill('0.2')
  await expect(page.getByRole('button', { name: 'Save template', exact: true })).toBeEnabled()
  await page.screenshot({
    path: 'test-results/inspector-style-desktop.png',
    animations: 'disabled',
  })
  await tabs.getByRole('tab', { name: 'Style' }).focus()
  await page.keyboard.press('End')
  await expect(tabs.getByRole('tab', { name: 'Layout' })).toBeFocused()
  await page.getByLabel('X (mm)', { exact: true }).fill('4')
  await page.getByLabel('Y (mm)', { exact: true }).fill('4')
  await page.getByLabel('Width (mm)', { exact: true }).fill('30')
  await page.getByLabel('Height (mm)', { exact: true }).fill('10')
  await expect(page.getByRole('button', { name: 'Distance holder', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Arrange', exact: true })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.locator('.editor-properties').scrollIntoViewIfNeeded()
  await page.screenshot({
    path: 'test-results/inspector-layout-mobile.png',
    animations: 'disabled',
  })
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page).toHaveURL(/#\/templates\/[^/]+\/edit/)
  const id = page.url().split('/templates/')[1]!.split('/')[0]!
  const saved = await (await request.get(`/api/templates/${id}`)).json()
  expect(saved.document.elements[0]).toMatchObject({
    content: 'Rack 42',
    x: 4,
    y: 4,
    width: 30,
    height: 10,
    font_size: 4,
    bold: true,
    align: 'center',
    padding_left: 1.5,
    character_spacing: 0.2,
  })
  await page.reload()
  await showEditorTab(page, 'Content')
  await expect(page.getByRole('textbox', { name: 'Content', exact: true })).toHaveValue('Rack 42')
  await showEditorSettings(page, 'Spacing & padding')
  await expect(page.getByLabel('Left padding (mm)', { exact: true })).toHaveValue('1.5')
  expect(errors).toEqual([])
})

test('element types expose meaningful tabs and selection stays aligned with rulers and inspector', async ({
  page,
  request,
}) => {
  const asset = await (
    await request.post('/api/image-assets?name=Workbench', {
      data: '<svg viewBox="0 0 20 10"><rect width="20" height="10"/></svg>',
      headers: { 'Content-Type': 'application/octet-stream' },
    })
  ).json()
  await page.goto('/#/templates/new')
  await page.getByRole('button', { name: 'Add QR code', exact: true }).click()
  const tabs = page.getByRole('tablist', { name: 'Element settings' })
  await expect(tabs.getByRole('tab')).toHaveText(['Content', 'Layout'])
  await showEditorSettings(page, 'Position & size')
  await page.getByLabel('Scale up to bounding box', { exact: true }).check()
  await page.getByLabel('QR margin (mm)', { exact: true }).fill('0.5')
  await page.evaluate(
    () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))),
  )
  expect(
    await page.getByLabel('QR margin (mm)', { exact: true }).evaluate((el) => {
      return el.closest('.disclosure-body')!.getAnimations().length
    }),
  ).toBe(0)
  await page.getByRole('button', { name: 'Add rectangle', exact: true }).click()
  await expect(tabs.getByRole('tab')).toHaveText(['Style', 'Layout'])
  await expect(tabs.getByRole('tab', { name: 'Style' })).toHaveAttribute('aria-selected', 'true')
  await page.getByLabel('Stroke (mm)', { exact: true }).fill('0.3')
  await page.getByRole('button', { name: 'Add image', exact: true }).click()
  await page.getByRole('combobox', { name: 'Image', exact: true }).selectOption(asset.id)
  await expect(tabs.getByRole('tab')).toHaveText(['Content', 'Style', 'Layout'])
  await showEditorSettings(page, 'Position & size')
  await expect(page.getByLabel('Preserve aspect ratio', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '1. qr', exact: true }).click()
  await expect(page.getByLabel('QR margin (mm)', { exact: true })).toHaveValue('0.5')
  const boundary = page.locator('.object-boundary.selected')
  const selectedWidth = Number(await boundary.getAttribute('width'))
  await expect(page.locator('.editor-ruler-top .ruler-selection')).toHaveAttribute(
    'width',
    String(selectedWidth * 8),
  )
  await showEditorTab(page, 'Content')
  await expect(page.getByRole('textbox', { name: 'Content', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save template', exact: true })).toBeEnabled()
  await page.screenshot({
    path: 'test-results/inspector-content-desktop.png',
    animations: 'disabled',
  })
})
