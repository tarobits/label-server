import { readFile } from 'node:fs/promises'
import { test, expect } from './fixtures'
import { showEditorTab } from './editor-settings'

test('named and numeric weights survive saving, undo and font changes', async ({
  page,
  request,
}) => {
  const upload = async (file: string) => {
    const result = await request.post('/api/font-assets', {
      data: await readFile(`../app/fonts/${file}`),
      headers: { 'Content-Type': 'application/octet-stream' },
    })
    expect(result.ok(), await result.text()).toBeTruthy()
    return result.json()
  }
  const variable = await upload('NotoSans-Variable.ttf')
  const fixed = await upload('NotoSans-Bold.ttf')
  await page.goto('/#/templates/new')
  await page.getByLabel('Template name', { exact: true }).fill('Weighted typography')
  await page.getByRole('button', { name: 'Add text', exact: true }).click()
  await showEditorTab(page, 'Style')
  const weight = page.getByRole('combobox', { name: 'Weight', exact: true })
  const numeric = page.getByLabel('Numeric weight', { exact: true })
  await expect(weight.locator('option')).toHaveText([
    'Thin',
    'Extra Light',
    'Light',
    'Regular',
    'Medium',
    'Semi Bold',
    'Bold',
    'Extra Bold',
    'Black',
  ])
  await weight.selectOption('300')
  await expect(numeric).toHaveValue('300')
  await numeric.fill('550.5')
  await numeric.press('Tab')
  await expect(weight).toHaveValue('550.5')
  await page.getByRole('button', { name: 'Undo', exact: true }).click()
  await expect(numeric).toHaveValue('300')
  await page.getByRole('button', { name: 'Redo', exact: true }).click()
  await expect(numeric).toHaveValue('550.5')
  await page.getByRole('combobox', { name: 'Font', exact: true }).selectOption(variable.id)
  await expect(numeric).toHaveValue('400')
  await weight.selectOption('600')
  await expect(page.getByRole('button', { name: 'Save template', exact: true })).toBeEnabled({
    timeout: 15000,
  })
  const saved = page.waitForResponse(
    (r) => r.url().endsWith('/api/templates') && r.request().method() === 'POST',
  )
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  const response = await saved
  expect(response.ok(), await response.text()).toBeTruthy()
  const template = await response.json()
  expect(template.document.elements[0].font_weight).toBe(600)
  await expect(page).toHaveURL(/#\/templates\/[^/]+\/edit/)
  await page.reload()
  await showEditorTab(page, 'Style')
  await expect(numeric).toHaveValue('600')
  await numeric.scrollIntoViewIfNeeded()
  await page.screenshot({ path: 'test-results/font-weights-desktop.png', animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  await numeric.scrollIntoViewIfNeeded()
  await page.screenshot({ path: 'test-results/font-weights-mobile.png', animations: 'disabled' })
  await page.getByRole('combobox', { name: 'Font', exact: true }).selectOption(fixed.id)
  await expect(numeric).toHaveValue('700')
  await expect(weight).toBeDisabled()
  await expect(numeric).toBeDisabled()
})
