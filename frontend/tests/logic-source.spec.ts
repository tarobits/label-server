import { test, expect } from './fixtures'
import type { APIRequestContext, Locator, Page } from '@playwright/test'

async function openEditor(page: Page, request: APIRequestContext) {
  const response = await request.post('/api/templates', {
    data: {
      name: 'Source layout',
      document: {
        width_mm: 24,
        length_mm: 60,
        auto_length: false,
        fields: [
          { name: 'subtitle', label: 'Subtitle', required: false, default: '', sample: 'Details' },
        ],
        elements: [
          { id: 'title', kind: 'text', x: 2, y: 4, width: 35, height: 14, content: 'Title' },
          {
            id: 'subtitle-element',
            kind: 'text',
            x: 2,
            y: 18,
            width: 35,
            height: 2,
            content: '{{subtitle}}',
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
  await workspace.getByRole('tab', { name: 'Source', exact: true }).click()
  await expect(workspace.getByRole('textbox', { name: 'Logic source' })).toBeVisible()
  return { workspace, template }
}
async function edit(workspace: Locator, source: string) {
  const editor = workspace.getByRole('textbox', { name: 'Logic source' })
  await editor.fill(source)
  await expect(editor).toHaveText(source.replaceAll('\n', ''))
}
async function valid(workspace: Locator) {
  await expect(workspace.getByText('Checking source…', { exact: true })).toBeHidden()
  await expect(
    workspace.getByRole('button', { name: 'Revert source changes', exact: true }),
  ).toBeHidden()
  await expect(workspace.locator('.source-diagnostics')).toHaveCount(0)
}
async function save(page: Page, request: APIRequestContext, id: string, revision: number) {
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page.getByText(`Revision ${revision}`, { exact: true })).toBeVisible()
  return (await request.get(`/api/templates/${id}`)).json()
}
const source =
  '// Conditional subtitle\nlet hasSubtitle = filled(subtitle);\ntext1.height = if(hasSubtitle, 12, 14);\ntext2.visible = hasSubtitle;'

test('source search and reference translate without discarding an unsaved program', async ({
  page,
  request,
}) => {
  const { workspace } = await openEditor(page, request)
  await edit(workspace, source)
  await valid(workspace)
  await workspace.getByRole('textbox', { name: 'Logic source' }).press('ControlOrMeta+f')
  const search = workspace.locator('.cm-search input[name="search"]')
  await search.fill('subtitle')
  await search.dispatchEvent('change')
  await page.evaluate(() => {
    Object.defineProperty(navigator, 'languages', { configurable: true, value: ['de-DE'] })
    window.dispatchEvent(new Event('languagechange'))
  })
  await expect(search).toHaveAttribute('aria-label', 'Suchen')
  await expect(search).toHaveValue('subtitle')
  await expect(workspace.locator('.cm-content')).toHaveText(source.replaceAll('\n', ''))
  await workspace.locator('.cm-search button[name="close"]').click()
  await expect(workspace.locator('.cm-search')).toHaveCount(0)
  await page.evaluate(() => {
    Object.defineProperty(navigator, 'languages', { configurable: true, value: ['en'] })
    window.dispatchEvent(new Event('languagechange'))
  })
  await expect(workspace.getByRole('textbox', { name: 'Logic source' })).toHaveText(
    source.replaceAll('\n', ''),
  )
  await valid(workspace)
})

test('source, nodes, layout, comments, and undo round-trip through saving', async ({
  page,
  request,
}, info) => {
  const { workspace, template } = await openEditor(page, request)
  await edit(workspace, source)
  await valid(workspace)
  const first = await save(page, request, template.id, 2)
  expect(first.document.logic_editor.source).toBe(source)
  const preview = await request.post('/api/preview', {
    data: { document: first.document, data: { subtitle: 'Details' } },
  })
  expect(preview.ok(), await preview.text()).toBeTruthy()
  expect(
    (await preview.json()).resolved_elements.find((item: { id: string }) => item.id === 'title')
      .height,
  ).toBe(12)
  await workspace.getByRole('tab', { name: 'Nodes', exact: true }).click()
  await workspace.getByRole('combobox', { name: 'Node', exact: true }).selectOption({ label: 'If' })
  const selected = workspace.locator('.logic-node.selected')
  const box = await selected.boundingBox()
  expect(box).toBeTruthy()
  await page.mouse.move(box!.x + 70, box!.y + 20)
  await page.mouse.down()
  await page.mouse.move(box!.x + 140, box!.y + 65, { steps: 8 })
  await page.mouse.up()
  const moved = await save(page, request, template.id, 3)
  const node = moved.document.logic_editor.nodes.find(
    (node: { operation: string }) => node.operation === 'if',
  )
  await workspace.getByRole('tab', { name: 'Source', exact: true }).click()
  const changed = source.replace('12, 14', '10, 14')
  await edit(workspace, changed)
  await valid(workspace)
  const updated = await save(page, request, template.id, 4)
  expect(
    updated.document.logic_editor.nodes.find(
      (candidate: { id: string }) => candidate.id === node.id,
    ),
  ).toMatchObject({ x: node.x, y: node.y })
  await page.getByRole('button', { name: 'Undo', exact: true }).click()
  await expect(workspace.getByRole('textbox', { name: 'Logic source' })).toContainText('12, 14')
  await page.getByRole('button', { name: 'Redo', exact: true }).click()
  await expect(workspace.getByRole('textbox', { name: 'Logic source' })).toContainText('10, 14')
  await workspace.getByRole('tab', { name: 'Nodes', exact: true }).click()
  await workspace.getByRole('combobox', { name: 'Node', exact: true }).selectOption({ label: 'If' })
  await workspace.getByLabel('Then', { exact: true }).fill('9')
  await workspace.getByRole('heading', { level: 3 }).click()
  await expect(workspace.getByText('Checking…', { exact: true })).toBeHidden()
  await workspace.getByRole('tab', { name: 'Source', exact: true }).click()
  await expect(workspace.getByRole('textbox', { name: 'Logic source' })).toContainText('9')
  await expect(workspace.getByRole('textbox', { name: 'Logic source' })).not.toContainText(
    '// Conditional',
  )
  const final = await save(page, request, template.id, 5)
  await page.reload()
  await workspace.getByRole('button', { name: 'Template logic', exact: true }).click()
  await workspace.getByRole('tab', { name: 'Source', exact: true }).click()
  await expect(workspace.getByRole('textbox', { name: 'Logic source' })).toContainText(
    final.document.logic_editor.source.replaceAll('\n', ''),
  )
  await workspace.screenshot({ path: info.outputPath('source-desktop.png') })
})

test('invalid source retains the preview, reports locations, and blocks saving until corrected', async ({
  page,
  request,
}, info) => {
  const { workspace } = await openEditor(page, request)
  await edit(workspace, source)
  await valid(workspace)
  const preview = workspace.locator('.source-preview img')
  await expect(preview).toBeVisible()
  const lastPreview = await preview.getAttribute('src')
  const before = await workspace.locator('.code-host').boundingBox()
  await edit(workspace, source + '\ntext1.width = true;')
  const issue = workspace.locator('.source-diagnostics').getByRole('button')
  await expect(issue).toContainText('Line 5')
  const after = await workspace.locator('.code-host').boundingBox()
  expect(after!.y).toBeCloseTo(before!.y, 0)
  await expect(page.getByRole('button', { name: 'Save template', exact: true })).toBeDisabled()
  await expect(preview).toHaveAttribute('src', lastPreview!)
  await issue.click()
  await expect(workspace.getByRole('textbox', { name: 'Logic source' })).toBeFocused()
  await workspace.screenshot({ path: info.outputPath('source-diagnostic.png') })
  await workspace.getByRole('tab', { name: 'Nodes', exact: true }).click()
  await expect(workspace.getByRole('button', { name: 'Add node', exact: true })).toBeDisabled()
  await workspace.getByRole('tab', { name: 'Source', exact: true }).click()
  await workspace.getByRole('button', { name: 'Revert source changes' }).click()
  await expect(workspace.getByRole('textbox', { name: 'Logic source' })).toHaveText(
    source.replaceAll('\n', ''),
  )
  await valid(workspace)
  await edit(workspace, 'label.length_mm = 50;')
  await valid(workspace)
  await edit(workspace, '')
  await valid(workspace)
  await workspace.getByRole('tab', { name: 'Nodes', exact: true }).click()
  await expect(workspace.locator('.logic-node').filter({ hasText: 'label.length_mm' })).toHaveCount(
    0,
  )
})

test('source completion, reference search, contextual help, and narrow-screen disclosures', async ({
  page,
  request,
  context,
  baseURL,
}, info) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: baseURL })
  const { workspace } = await openEditor(page, request)
  await edit(workspace, 'text1.')
  const editor = workspace.getByRole('textbox', { name: 'Logic source' })
  await editor.press('Control+Space')
  await expect(workspace.locator('.cm-tooltip-autocomplete')).toContainText('height')
  await workspace.locator('.cm-tooltip-autocomplete').getByText('height', { exact: true }).click()
  await expect(editor).toHaveText('text1.height')
  await editor.press('End')
  await page.keyboard.insertText(' = 12;')
  await valid(workspace)
  await edit(workspace, source)
  await valid(workspace)
  await editor.press('Tab')
  await expect(editor).not.toBeFocused()
  await workspace.getByRole('button', { name: 'Reference', exact: true }).click()
  const reference = workspace.getByRole('region', { name: 'Logic reference' })
  await reference.getByLabel('Search reference').fill('conditional subtitle')
  await expect(reference.getByRole('heading', { level: 3 })).toContainText('Conditional subtitle')
  await reference.getByRole('button', { name: 'Copy example', exact: true }).click()
  await expect(reference.getByRole('status')).toContainText('copied')
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain('filled(subtitle)')
  await workspace.screenshot({ path: info.outputPath('reference-desktop.png') })
  await workspace.getByRole('button', { name: 'Reference', exact: true }).click()
  await expect(reference).toBeHidden()
  await editor.getByText('filled', { exact: true }).hover()
  await workspace.getByRole('button', { name: 'Open reference', exact: true }).click()
  await expect(reference.getByRole('heading', { level: 3 })).toHaveText('filled')
  await workspace.getByRole('button', { name: 'Reference', exact: true }).click()
  await expect(reference).toBeHidden()
  await workspace.getByRole('tab', { name: 'Nodes', exact: true }).click()
  await workspace.getByRole('combobox', { name: 'Node', exact: true }).selectOption({ label: 'If' })
  await workspace.getByRole('button', { name: 'Node reference', exact: true }).click()
  await expect(reference.getByRole('heading', { level: 3 })).toHaveText('if')
  await reference.getByLabel('Search reference').fill('image')
  await workspace.getByRole('button', { name: 'Node reference', exact: true }).click()
  await expect(reference.getByRole('heading', { level: 3 })).toHaveText('if')
  await page.setViewportSize({ width: 390, height: 844 })
  await workspace.getByRole('button', { name: 'Reference', exact: true }).click()
  await expect(reference).toBeHidden()
  await workspace.getByRole('tab', { name: 'Source', exact: true }).click()
  await editor.scrollIntoViewIfNeeded()
  await workspace.screenshot({ path: info.outputPath('source-mobile.png') })
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBeTruthy()
  await workspace.getByRole('button', { name: 'Reference', exact: true }).click()
  await reference.getByLabel('Search reference').fill('automatic length')
  await expect(reference).toBeVisible()
  await reference.screenshot({ path: info.outputPath('reference-mobile.png') })
  await workspace.getByRole('button', { name: 'Reference', exact: true }).click()
  await expect(reference).toBeHidden()
})

test('source changes retain detached nodes and inactive manual length without reviving removed outputs', async ({
  page,
  request,
}) => {
  const { workspace, template } = await openEditor(page, request)
  await edit(workspace, 'label.length_mm = 50; text1.height = 12;')
  await valid(workspace)
  await workspace.getByRole('tab', { name: 'Nodes', exact: true }).click()
  await workspace.getByRole('button', { name: 'Add node', exact: true }).click()
  await workspace
    .locator('.node-options')
    .getByRole('button', { name: 'Number value', exact: true })
    .click()
  await expect(workspace.getByText('Checking…', { exact: true })).toBeHidden()
  const first = await save(page, request, template.id, 2)
  const detached = first.document.logic_editor.nodes.find(
    (node: { kind: string }) => node.kind === 'literal',
  )
  expect(detached).toBeTruthy()
  await page.getByRole('checkbox', { name: 'Automatic label length', exact: true }).check()
  await workspace.getByRole('tab', { name: 'Source', exact: true }).click()
  await expect(workspace.getByRole('textbox', { name: 'Logic source' })).not.toContainText(
    'label.length_mm',
  )
  await edit(workspace, 'text1.height = 10;')
  await valid(workspace)
  const automatic = await save(page, request, template.id, 3)
  expect(automatic.document.logic.bindings).toHaveLength(1)
  expect(automatic.document.logic_editor.nodes).toEqual(
    expect.arrayContaining([expect.objectContaining({ id: detached.id })]),
  )
  expect(
    automatic.document.logic_editor.nodes.find(
      (node: { target: string }) => node.target === 'label',
    ).defaults[0],
  ).toBe(50)
  await page.getByRole('checkbox', { name: 'Automatic label length', exact: true }).uncheck()
  await expect(workspace.getByRole('textbox', { name: 'Logic source' })).toContainText(
    'label.length_mm',
  )
  const manual = await save(page, request, template.id, 4)
  expect(
    manual.document.logic.bindings.find((binding: { target: string }) => binding.target === 'label')
      .expression.value,
  ).toBe(50)
  await edit(workspace, '')
  await valid(workspace)
  const cleared = await save(page, request, template.id, 5)
  expect(cleared.document.logic.bindings).toHaveLength(0)
  expect(
    cleared.document.logic_editor.nodes.some((node: { kind: string }) => node.kind === 'output'),
  ).toBe(false)
  expect(cleared.document.logic_editor.nodes).toEqual(
    expect.arrayContaining([expect.objectContaining({ id: detached.id })]),
  )
})
