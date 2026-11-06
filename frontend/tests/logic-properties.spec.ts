import { test, expect } from './fixtures'
import type { Locator, Page, APIRequestContext } from '@playwright/test'

async function open(page: Page, request: APIRequestContext, automatic = false) {
  const response = await request.post('/api/templates', {
    data: {
      name: 'Property inputs',
      document: {
        version: 2,
        width_mm: 24,
        length_mm: 60,
        auto_length: automatic,
        elements: [
          {
            id: 'title',
            logic_name: 'title',
            kind: 'text',
            x: 2,
            y: 4,
            width: 35,
            height: 12,
            content: 'Title',
            auto_width: automatic,
          },
          {
            id: 'subtitle',
            logic_name: 'subtitle',
            kind: 'text',
            x: 2,
            y: 17,
            width: 35,
            height: 4,
            content: 'Subtitle',
          },
        ],
      },
    },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  const template = await response.json()
  await page.goto(`/#/templates/${template.id}/edit`)
  const workspace = page.locator('.logic-workspace')
  await workspace.getByRole('button', { name: 'Template logic', exact: true }).click()
  return { workspace, template }
}
async function property(
  workspace: Locator,
  target: string,
  property: string,
  action: 'Read' | 'Bind',
) {
  await workspace.getByRole('button', { name: 'Add node', exact: true }).click()
  await workspace
    .getByRole('combobox', { name: 'Property target', exact: true })
    .selectOption(target)
  await workspace.getByRole('combobox', { name: 'Property', exact: true }).selectOption(property)
  await workspace.getByRole('button', { name: `${action} property`, exact: true }).click()
  await settled(workspace)
}
async function settled(workspace: Locator) {
  await expect(workspace.getByText('Checking…', { exact: true })).toBeHidden()
  await expect(workspace.getByText('Checking source…', { exact: true })).toBeHidden()
  await expect(
    workspace.getByRole('button', { name: 'Revert source changes', exact: true }),
  ).toBeHidden()
  await expect(workspace.getByRole('alert')).toHaveCount(0)
}

test('property nodes connect by click, preserve source and reject a property cycle', async ({
  page,
  request,
}, info) => {
  const { workspace, template } = await open(page, request)
  await property(workspace, 'title', 'height', 'Read')
  await property(workspace, 'subtitle', 'height', 'Bind')
  await workspace
    .getByRole('button', { name: 'Read title.height output (number)', exact: true })
    .click()
  await workspace
    .getByRole('button', { name: 'subtitle.height Value input (number)', exact: true })
    .click()
  // Keep the subtitle inside the tape after copying the taller title.
  await workspace.getByRole('tab', { name: 'Source', exact: true }).click()
  const editor = workspace.getByRole('textbox', { name: 'Logic source' })
  await expect(editor).toContainText('subtitle.height = title.height;')
  await editor.fill('subtitle.height = title.height / 3; title.height = 12;')
  await settled(workspace)
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page.getByText('Revision 2', { exact: true })).toBeVisible()
  let saved = await (await request.get(`/api/templates/${template.id}`)).json()
  expect(saved.document.logic.bindings[0].expression.arguments[0]).toMatchObject({
    kind: 'property',
    target: 'title',
    property: 'height',
  })
  await editor.fill('title.height = subtitle.height; subtitle.height = title.height;')
  await expect(workspace.locator('.source-diagnostics')).toContainText('Circular dependency')
  await expect(page.getByRole('button', { name: 'Save template', exact: true })).toBeDisabled()
  await workspace.getByRole('button', { name: 'Revert source changes', exact: true }).click()
  await settled(workspace)
  await workspace.getByRole('tab', { name: 'Nodes', exact: true }).click()
  await property(workspace, 'subtitle', 'height', 'Read')
  const picker = workspace.getByRole('combobox', { name: 'Node', exact: true })
  await picker.selectOption({ label: 'Read subtitle.height' })
  await workspace
    .getByRole('button', { name: 'Read subtitle.height output (number)', exact: true })
    .click()
  await picker.selectOption({ label: 'title.height' })
  await workspace
    .getByRole('button', { name: 'title.height Value input (number)', exact: true })
    .click()
  await expect(workspace.locator('.logic-status')).toContainText('cycle')
  await page.setViewportSize({ width: 402, height: 874 })
  await picker.selectOption({ label: 'Read title.height' })
  await expect(
    workspace.getByRole('button', { name: 'Read title.height output (number)', exact: true }),
  ).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await workspace.screenshot({
    path: `test-results/property-input-${info.project.name}.png`,
    animations: 'disabled',
  })
  await page.reload()
  await workspace.getByRole('button', { name: 'Template logic', exact: true }).click()
  await workspace.getByRole('tab', { name: 'Source', exact: true }).click()
  await expect(editor).toContainText('subtitle.height = title.height / 3;')
})

test('automatic dimensions are readable but their assignment inlets and defaults are disabled', async ({
  page,
  request,
}, info) => {
  const { workspace } = await open(page, request, true)
  await property(workspace, 'title', 'width', 'Read')
  await property(workspace, 'title', 'width', 'Bind')
  const widthInlet = workspace.getByRole('button', {
    name: 'title.width Value input (number)',
    exact: true,
  })
  await expect(widthInlet).toBeDisabled()
  await expect(workspace.getByLabel('Value', { exact: true })).toBeDisabled()
  await expect(
    workspace.getByRole('button', { name: 'Read title.width output (number)', exact: true }),
  ).toBeEnabled()
  await workspace.getByRole('button', { name: 'Add node', exact: true }).click()
  await workspace
    .getByRole('combobox', { name: 'Property target', exact: true })
    .selectOption('label')
  await workspace.getByRole('combobox', { name: 'Property', exact: true }).selectOption('length_mm')
  await expect(workspace.getByRole('button', { name: 'Read property', exact: true })).toBeDisabled()
  await workspace.getByRole('button', { name: 'Add node', exact: true }).click()
  await property(workspace, 'label', 'length_mm', 'Bind')
  await expect(
    workspace.getByRole('button', { name: 'Label.length_mm Value input (number)', exact: true }),
  ).toBeDisabled()
  await page.setViewportSize({ width: 402, height: 874 })
  await workspace.screenshot({
    path: `test-results/property-disabled-${info.project.name}.png`,
    animations: 'disabled',
  })
  await workspace.getByRole('tab', { name: 'Source', exact: true }).click()
  const editor = workspace.getByRole('textbox', { name: 'Logic source' })
  await editor.fill('title.width = 10;')
  await expect(workspace.locator('.source-diagnostics')).toContainText('automatic text width')
  await editor.fill('label.length_mm = 60;')
  await expect(workspace.locator('.source-diagnostics')).toContainText('automatic label length')
  await editor.fill('let measuredWidth = title.width; subtitle.x = measuredWidth + 4;')
  await settled(workspace)
  await expect(
    workspace.getByRole('img', { name: 'Source label preview', exact: true }),
  ).toBeVisible()
})

test('switching automatic text width preserves and restores its manual binding', async ({
  page,
  request,
}) => {
  const { workspace, template } = await open(page, request)
  await property(workspace, 'title', 'width', 'Bind')
  await workspace.getByLabel('Value', { exact: true }).fill('28')
  await workspace.getByLabel('Value', { exact: true }).press('Tab')
  await settled(workspace)
  await page.getByRole('button', { name: '1. text', exact: true }).click()
  await page
    .getByRole('tablist', { name: 'Element settings' })
    .getByRole('tab', { name: 'Layout', exact: true })
    .click()
  const automatic = page.getByLabel('Fit text box width to content', { exact: true })
  await automatic.check()
  await settled(workspace)
  const inlet = workspace.getByRole('button', {
    name: 'title.width Value input (number)',
    exact: true,
  })
  await expect(inlet).toBeDisabled()
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page.getByText('Revision 2', { exact: true })).toBeVisible()
  const saved = await (await request.get(`/api/templates/${template.id}`)).json()
  expect(saved.document.logic.bindings).toHaveLength(0)
  await automatic.uncheck()
  await settled(workspace)
  await expect(inlet).toBeEnabled()
  await expect(workspace.getByLabel('Value', { exact: true })).toHaveValue('28')
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page.getByText('Revision 3', { exact: true })).toBeVisible()
  const restored = await (await request.get(`/api/templates/${template.id}`)).json()
  expect(restored.document.logic.bindings[0]).toMatchObject({
    target: 'title',
    property: 'width',
    expression: { kind: 'literal', value: 28 },
  })
})
