import type { Page, Locator, APIRequestContext } from '@playwright/test'
import { test, expect } from './fixtures'
async function template(request: APIRequestContext) {
  const result = await request.post('/api/templates', {
    data: {
      name: 'Conditional layout',
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
  expect(result.ok(), await result.text()).toBeTruthy()
  return result.json()
}
async function settled(workspace: Locator) {
  await expect(workspace.getByText('Checking…', { exact: true })).toBeHidden()
  await expect(workspace.getByRole('alert')).toHaveCount(0)
}
async function add(workspace: Locator, name: string) {
  await workspace.getByRole('button', { name: 'Add node', exact: true }).click()
  await workspace.getByLabel('Search nodes', { exact: true }).fill(name)
  await workspace.locator('.node-options').getByRole('button', { name, exact: true }).click()
  await settled(workspace)
}
async function output(workspace: Locator, target: string, property: string) {
  await workspace.getByRole('button', { name: 'Add node', exact: true }).click()
  await workspace
    .getByRole('combobox', { name: 'Property target', exact: true })
    .selectOption(target)
  await workspace.getByRole('combobox', { name: 'Property', exact: true }).selectOption(property)
  await workspace.getByRole('button', { name: 'Bind property', exact: true }).click()
  await settled(workspace)
}
async function connect(workspace: Locator, source: string, destination: string, keyboard = false) {
  const first = workspace.getByRole('button', { name: new RegExp(`^${source} output`) })
  const second = workspace.getByRole('button', { name: new RegExp(`^${destination} input`) })
  if (keyboard) {
    await first.focus()
    await first.press('Enter')
    await second.focus()
    await second.press('Space')
  } else {
    await first.click()
    await second.click()
  }
  await settled(workspace)
}
async function save(page: Page, revision: number) {
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page.getByText(`Revision ${revision}`, { exact: true })).toBeVisible()
}
test('node canvas builds conditional heights with intermediates and preserves layout on reload', async ({
  page,
  request,
}) => {
  const original = await template(request)
  await page.goto(`/#/templates/${original.id}/edit`)
  const workspace = page.locator('.logic-workspace')
  await workspace.getByRole('button', { name: 'Template logic', exact: true }).click()
  await expect(workspace.getByRole('button', { name: 'Add node', exact: true })).toBeVisible()
  await add(workspace, 'Filled')
  await connect(workspace, 'Subtitle', 'Filled Value')
  await add(workspace, 'Intermediate variable')
  await workspace.getByLabel('Variable name', { exact: true }).fill('hasSubtitle')
  await workspace.getByRole('heading', { level: 3 }).click()
  await settled(workspace)
  await connect(workspace, 'Filled', 'hasSubtitle Value')
  await add(workspace, 'If')
  await workspace.getByLabel('Then', { exact: true }).fill('12')
  await workspace.getByLabel('Else', { exact: true }).fill('14')
  await workspace.getByRole('heading', { level: 3 }).click()
  await settled(workspace)
  await connect(workspace, 'hasSubtitle', 'If Condition', true)
  await output(workspace, 'text1', 'height')
  await connect(workspace, 'If', 'text1.height Value')
  await output(workspace, 'text2', 'visible')
  await connect(workspace, 'hasSubtitle', 'text2.visible Value')
  await expect(workspace.locator('.socket-text svg circle')).not.toHaveCount(0)
  await expect(workspace.locator('.socket-number svg path')).not.toHaveCount(0)
  await expect(workspace.locator('.socket-boolean svg rect')).not.toHaveCount(0)
  await save(page, 2)
  const saved = await (await request.get(`/api/templates/${original.id}`)).json()
  expect(saved.document.logic.variables.hasSubtitle).toBeTruthy()
  const present = await request.post('/api/preview', {
    data: { document: saved.document, data: { subtitle: 'Details' } },
  })
  expect(present.ok(), await present.text()).toBeTruthy()
  expect((await present.json()).resolved_elements[0].height).toBe(12)
  const absent = await request.post('/api/preview', {
    data: { document: saved.document, data: { subtitle: '' } },
  })
  expect(absent.ok(), await absent.text()).toBeTruthy()
  const elements = (await absent.json()).resolved_elements
  expect(elements[0].height).toBe(14)
  expect(elements[1].visible).toBe(false)
  await workspace.getByRole('button', { name: 'Frame nodes', exact: true }).click()
  await workspace.screenshot({ path: 'test-results/logic-desktop.png' })
  await page.reload()
  await workspace.getByRole('button', { name: 'Template logic', exact: true }).click()
  await expect(workspace.locator('.logic-node')).toHaveCount(
    saved.document.logic_editor.nodes.length,
  )
  await expect(workspace.locator('.logic-wires path')).toHaveCount(5)
  await page.setViewportSize({ width: 390, height: 844 })
  await workspace.getByRole('button', { name: 'Frame nodes', exact: true }).click()
  await workspace.getByRole('button', { name: 'Expand view', exact: true }).click()
  await expect
    .poll(
      async () =>
        (await workspace.getByLabel('Logic node canvas', { exact: true }).boundingBox())!.height,
    )
    .toBeGreaterThan(600)
  await workspace.getByRole('button', { name: 'Restore view', exact: true }).click()
  await expect
    .poll(
      async () =>
        (await workspace.getByLabel('Logic node canvas', { exact: true }).boundingBox())!.height,
    )
    .toBe(480)
  await workspace.screenshot({ path: 'test-results/logic-mobile.png' })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await workspace.getByRole('button', { name: 'Template logic', exact: true }).click()
  await expect(workspace.getByLabel('Logic node canvas', { exact: true })).toBeHidden()
})
test('socket cancellation, incompatible types, cycles, dragging and length modes', async ({
  page,
  request,
}) => {
  const original = await template(request)
  await page.goto(`/#/templates/${original.id}/edit`)
  const workspace = page.locator('.logic-workspace')
  await workspace.getByRole('button', { name: 'Template logic', exact: true }).click()
  await add(workspace, 'Add')
  const textOutput = workspace.getByRole('button', { name: 'Subtitle output (text)', exact: true })
  await textOutput.click()
  await workspace.getByRole('button', { name: 'Add A input (number)', exact: true }).click()
  await expect(workspace.locator('.logic-status')).toContainText('needs number')
  await textOutput.press('Escape')
  await expect(textOutput).toHaveAttribute('aria-pressed', 'false')
  await textOutput.click()
  await textOutput.click()
  await expect(textOutput).toHaveAttribute('aria-pressed', 'false')
  await add(workspace, 'Intermediate variable')
  await connect(workspace, 'Add', 'value1 Value')
  await workspace.getByRole('button', { name: 'value1 output (number)', exact: true }).click()
  await workspace.getByRole('button', { name: 'Add A input (number)', exact: true }).click()
  await expect(workspace.locator('.logic-status')).toContainText('cycle')
  await textOutput.press('Escape')
  await output(workspace, 'label', 'length_mm')
  await workspace.getByLabel('Value', { exact: true }).fill('80')
  await workspace.getByRole('heading', { level: 3 }).click()
  await settled(workspace)
  await save(page, 2)
  await expect(page.getByLabel('Label length (mm)', { exact: true })).toHaveValue('80')
  await expect(page.getByLabel('Label length (mm)', { exact: true })).toBeDisabled()
  await page.getByLabel('Automatic label length', { exact: true }).check()
  await settled(workspace)
  await expect(workspace.getByText('Inactive · automatic sizing', { exact: true })).toBeVisible()
  await save(page, 3)
  let saved = await (await request.get(`/api/templates/${original.id}`)).json()
  expect(saved.document.logic.bindings).toHaveLength(0)
  await page.getByLabel('Automatic label length', { exact: true }).uncheck()
  await settled(workspace)
  await save(page, 4)
  saved = await (await request.get(`/api/templates/${original.id}`)).json()
  expect(saved.document.logic.bindings[0].expression.value).toBe(80)
  const header = workspace.getByLabel('Move Add', { exact: true })
  const before = await header.boundingBox()
  await header.hover()
  await page.mouse.down()
  await page.mouse.move(before!.x + 60, before!.y + 40)
  await page.mouse.up()
  await expect.poll(async () => (await header.boundingBox())!.x).not.toBe(before!.x)
  await save(page, 5)
})

test('invalid graph edits retain the preview and valid edits participate in undo', async ({
  page,
  request,
}) => {
  const original = await template(request)
  original.document.version = 2
  original.document.elements.forEach((element: { logic_name: string }, index: number) => {
    element.logic_name = `text${index + 1}`
  })
  original.document.logic = {
    version: 1,
    variables: {},
    bindings: [
      {
        target: 'title',
        property: 'height',
        expression: {
          kind: 'call',
          operation: 'if',
          arguments: [
            { kind: 'literal', value: true },
            { kind: 'literal', value: 12 },
            {
              kind: 'call',
              operation: 'divide',
              arguments: [
                { kind: 'literal', value: 1 },
                { kind: 'literal', value: 0 },
              ],
            },
          ],
        },
      },
    ],
  }
  expect(
    (
      await request.put(`/api/templates/${original.id}`, {
        data: { name: original.name, document: original.document, expected_revision: 1 },
      })
    ).ok(),
  ).toBeTruthy()
  await page.goto(`/#/templates/${original.id}/edit`)
  const workspace = page.locator('.logic-workspace')
  await workspace.getByRole('button', { name: 'Template logic', exact: true }).click()
  await workspace.getByLabel('Move If', { exact: true }).click()
  const preview = await workspace
    .getByRole('img', { name: 'Logic label preview' })
    .getAttribute('src')
  await expect(workspace.getByRole('combobox', { name: 'Value type', exact: true })).toBeDisabled()
  await workspace
    .getByRole('combobox', { name: 'Node', exact: true })
    .selectOption({ label: 'Divide' })
  await workspace.getByLabel('A', { exact: true }).fill('')
  await workspace.getByRole('heading', { level: 3 }).click()
  await expect(workspace.getByRole('alert')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save template', exact: true })).toBeDisabled()
  expect(
    await workspace.getByRole('img', { name: 'Logic label preview' }).getAttribute('src'),
  ).toBe(preview)
  await workspace.getByRole('button', { name: 'Revert node changes', exact: true }).click()
  await settled(workspace)
  await workspace.getByLabel('Move If', { exact: true }).click()
  await workspace.getByLabel('Then', { exact: true }).fill('10')
  await workspace.getByRole('heading', { level: 3 }).click()
  await settled(workspace)
  await page.getByRole('button', { name: 'Undo', exact: true }).click()
  await expect(workspace.getByLabel('Then', { exact: true })).toHaveValue('12')
  await page.getByRole('button', { name: 'Redo', exact: true }).click()
  await expect(workspace.getByLabel('Then', { exact: true })).toHaveValue('10')
  await settled(workspace)
  await save(page, 3)
  const saved = await (await request.get(`/api/templates/${original.id}`)).json()
  expect(saved.document.logic.variables).toEqual({})
  expect(saved.document.logic.bindings[0].expression.arguments[2].operation).toBe('divide')
})

test('image sockets accept uploads and drag connections', async ({ page, request }) => {
  const original = await template(request)
  original.document.version = 2
  original.document.elements = [
    {
      id: 'picture',
      logic_name: 'picture',
      kind: 'image',
      x: 2,
      y: 4,
      width: 15,
      height: 15,
      visible: false,
    },
  ]
  expect(
    (
      await request.put(`/api/templates/${original.id}`, {
        data: { name: original.name, document: original.document, expected_revision: 1 },
      })
    ).ok(),
  ).toBeTruthy()
  await page.goto(`/#/templates/${original.id}/edit`)
  const workspace = page.locator('.logic-workspace')
  await workspace.getByRole('button', { name: 'Template logic', exact: true }).click()
  await add(workspace, 'Image value')
  const imageSocket = workspace.getByRole('button', {
    name: 'Image value output (image)',
    exact: true,
  })
  await expect(imageSocket.locator('svg path')).toHaveAttribute('d', 'M12 3 22 20H2Z')
  await workspace.getByLabel('Upload value', { exact: true }).setInputFiles({
    name: 'node-image.svg',
    mimeType: 'image/svg+xml',
    buffer: Buffer.from(
      '<svg viewBox="0 0 20 20"><rect x="2" y="2" width="16" height="16"/></svg>',
    ),
  })
  await expect(workspace.getByRole('combobox', { name: 'Value', exact: true })).not.toHaveValue('')
  await settled(workspace)
  await output(workspace, 'picture', 'image_asset')
  await workspace.getByRole('button', { name: 'Image value output (image)', exact: true }).dragTo(
    workspace.getByRole('button', {
      name: 'picture.image_asset Value input (image)',
      exact: true,
    }),
  )
  await settled(workspace)
  await expect(workspace.locator('.logic-wires path')).toHaveCount(1)
  await expect(workspace.locator('.socket-image svg path').first()).toHaveAttribute(
    'd',
    'M12 3 22 20H2Z',
  )
  await save(page, 3)
  const saved = await (await request.get(`/api/templates/${original.id}`)).json()
  expect(saved.document.logic.bindings[0].expression.value.image_asset).toMatch(/^[a-f0-9]{64}$/)
  await workspace
    .getByRole('combobox', { name: 'Node', exact: true })
    .selectOption({ label: 'Image value' })
  await workspace.getByRole('combobox', { name: 'Value', exact: true }).selectOption('')
  await settled(workspace)
  await expect(imageSocket.locator('svg path')).toHaveAttribute('d', 'M12 3 22 20H2Z')
  await add(workspace, 'Intermediate variable')
  await connect(workspace, 'Image value', 'value1 Value')
  await expect(
    workspace
      .getByRole('button', { name: 'value1 output (image)', exact: true })
      .locator('svg path'),
  ).toHaveAttribute('d', 'M12 3 22 20H2Z')
  await save(page, 4)
})

test.describe('touch node editing', () => {
  test.use({ hasTouch: true, viewport: { width: 390, height: 844 } })
  test('mobile taps connect distant nodes using the node picker', async ({ page, request }) => {
    const original = await template(request)
    await page.goto(`/#/templates/${original.id}/edit`)
    const workspace = page.locator('.logic-workspace')
    await workspace.getByRole('button', { name: 'Template logic', exact: true }).tap()
    await add(workspace, 'Filled')
    const picker = workspace.getByRole('combobox', { name: 'Node', exact: true })
    await picker.selectOption({ label: 'Subtitle' })
    await workspace.getByRole('button', { name: 'Subtitle output (text)', exact: true }).tap()
    await picker.selectOption({ label: 'Filled' })
    await workspace.getByRole('button', { name: 'Filled Value input (text)', exact: true }).tap()
    await settled(workspace)
    await expect(workspace.locator('.logic-wires path')).toHaveCount(1)
    await workspace.getByRole('button', { name: 'Filled output (boolean)', exact: true }).tap()
    await workspace
      .getByLabel('Logic node canvas', { exact: true })
      .tap({ position: { x: 280, y: 420 } })
    await expect(
      workspace.getByRole('button', { name: 'Filled output (boolean)', exact: true }),
    ).toHaveAttribute('aria-pressed', 'false')
    await workspace.screenshot({ path: 'test-results/logic-touch.png' })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await save(page, 2)
  })
})

for (const operation of ['If', 'Equal', 'Not equal']) {
  test(`${operation} uses matching value sockets and rejects mixed connections`, async ({
    page,
    request,
  }, info) => {
    const original = await template(request)
    await page.goto(`/#/templates/${original.id}/edit`)
    const workspace = page.locator('.logic-workspace')
    await workspace.getByRole('button', { name: 'Template logic', exact: true }).click()
    await add(workspace, operation)
    const type = workspace.getByRole('combobox', { name: 'Value type', exact: true })
    await expect(type).toHaveCount(1)
    await type.selectOption('text')
    await settled(workspace)
    const [a, b] = operation === 'If' ? ['Then', 'Else'] : ['A', 'B']
    await expect(workspace.getByRole('textbox', { name: a, exact: true })).toBeVisible()
    await expect(workspace.getByRole('textbox', { name: b, exact: true })).toBeVisible()
    for (const operand of [a, b, 'Condition'])
      await expect(
        workspace.getByRole('combobox', { name: `${operand} type`, exact: true }),
      ).toHaveCount(0)
    await connect(workspace, 'Subtitle', `${operation} ${a}`)
    await expect(type).toBeDisabled()
    await add(workspace, 'Boolean value')
    const boolean = workspace.getByRole('button', {
      name: 'Boolean value output (boolean)',
      exact: true,
    })
    await boolean.click()
    await workspace
      .getByRole('button', { name: `${operation} ${b} input (text)`, exact: true })
      .click()
    await expect(workspace.locator('.logic-status')).toContainText(
      'needs text; the output is boolean',
    )
    await expect(
      workspace.getByRole('button', { name: `${operation} ${b} input (text)`, exact: true }),
    ).not.toHaveClass(/connected/)
    await boolean.press('Escape')
    await connect(workspace, 'Subtitle', `${operation} ${b}`, true)
    await workspace
      .getByRole('combobox', { name: 'Node', exact: true })
      .selectOption({ label: operation })
    await workspace.getByRole('button', { name: `Disconnect ${a}`, exact: true }).click()
    await workspace.getByRole('button', { name: `Disconnect ${b}`, exact: true }).click()
    await settled(workspace)
    await expect(type).toBeEnabled()
    await type.selectOption('boolean')
    await settled(workspace)
    await connect(workspace, 'Boolean value', `${operation} ${a}`)
    await connect(workspace, 'Boolean value', `${operation} ${b}`)
    await expect(workspace.getByRole('alert')).toHaveCount(0)
    await save(page, 2)
    if (operation === 'If') {
      await workspace.locator('.node-inspector').evaluate((element) => {
        element.scrollTop = 0
      })
      await workspace.screenshot({ path: info.outputPath('if-types-desktop.png') })
      await page.setViewportSize({ width: 390, height: 844 })
      await workspace
        .getByRole('combobox', { name: 'Node', exact: true })
        .selectOption({ label: 'If' })
      await workspace
        .locator('.node-inspector')
        .screenshot({ path: info.outputPath('if-types-mobile.png') })
    }
  })
}

test('changing a shared type preserves existing downstream connections when rejected', async ({
  page,
  request,
}) => {
  const original = await template(request)
  await page.goto(`/#/templates/${original.id}/edit`)
  const workspace = page.locator('.logic-workspace')
  await workspace.getByRole('button', { name: 'Template logic', exact: true }).click()
  await add(workspace, 'If')
  await workspace.getByLabel('Then', { exact: true }).fill('12')
  await workspace.getByLabel('Else', { exact: true }).fill('14')
  await workspace.getByRole('heading', { level: 3 }).click()
  await settled(workspace)
  await output(workspace, 'text1', 'height')
  await connect(workspace, 'If', 'text1.height Value')
  await workspace.getByRole('combobox', { name: 'Node', exact: true }).selectOption({ label: 'If' })
  const type = workspace.getByRole('combobox', { name: 'Value type', exact: true })
  await type.selectOption('text')
  await expect(type).toHaveValue('number')
  await expect(workspace.getByLabel('Then', { exact: true })).toHaveValue('12')
  await expect(workspace.getByLabel('Else', { exact: true })).toHaveValue('14')
  await expect(workspace.locator('.logic-status')).toContainText('height needs number')
  await expect(
    workspace.getByRole('button', { name: 'text1.height Value input (number)', exact: true }),
  ).toHaveClass(/connected/)
  await save(page, 2)
})

test('disconnecting and removing old typed wires repairs incompatible hidden defaults', async ({
  page,
  request,
}) => {
  const original = await template(request)
  const document = original.document
  document.version = 2
  document.elements.forEach((element: { logic_name: string }, index: number) => {
    element.logic_name = `text${index + 1}`
  })
  document.logic = {
    version: 1,
    variables: {},
    bindings: [
      {
        target: 'title',
        property: 'content',
        expression: {
          kind: 'call',
          operation: 'if',
          node_id: 'conditional',
          arguments: [
            { kind: 'literal', value: true },
            { kind: 'literal', value: 'Caption', node_id: 'caption' },
            { kind: 'literal', value: 'Caption', node_id: 'caption' },
          ],
        },
      },
    ],
  }
  document.logic_editor = {
    version: 1,
    x: 24,
    y: 24,
    zoom: 0.7,
    nodes: [
      {
        id: 'caption',
        kind: 'literal',
        type: 'text',
        value: 'Caption',
        x: 0,
        y: 0,
        inputs: [],
        defaults: [],
      },
      {
        id: 'conditional',
        kind: 'call',
        type: 'text',
        operation: 'if',
        x: 300,
        y: 0,
        inputs: [null, 'caption', 'caption'],
        defaults: [true, 0, 0],
      },
      {
        id: 'output',
        kind: 'output',
        type: 'text',
        target: 'title',
        property: 'content',
        x: 600,
        y: 0,
        inputs: ['conditional'],
        defaults: [''],
      },
    ],
  }
  const response = await request.put(`/api/templates/${original.id}`, {
    data: { name: original.name, document, expected_revision: 1 },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  await page.goto(`/#/templates/${original.id}/edit`)
  const workspace = page.locator('.logic-workspace')
  await workspace.getByRole('button', { name: 'Template logic', exact: true }).click()
  await workspace.getByRole('combobox', { name: 'Node', exact: true }).selectOption({ label: 'If' })
  await workspace.getByRole('button', { name: 'Disconnect Then', exact: true }).click()
  await settled(workspace)
  await expect(workspace.getByRole('textbox', { name: 'Then', exact: true })).toHaveValue('')
  await workspace
    .getByRole('combobox', { name: 'Node', exact: true })
    .selectOption({ label: 'Text value' })
  await workspace.getByRole('button', { name: 'Remove node', exact: true }).click()
  await settled(workspace)
  await workspace.getByRole('combobox', { name: 'Node', exact: true }).selectOption({ label: 'If' })
  await expect(workspace.getByRole('textbox', { name: 'Else', exact: true })).toHaveValue('')
  await expect(workspace.getByRole('combobox', { name: 'Value type', exact: true })).toHaveValue(
    'text',
  )
  await save(page, 3)
  const saved = await (await request.get(`/api/templates/${original.id}`)).json()
  expect(
    saved.document.logic.bindings[0].expression.arguments.map(
      (argument: { value: unknown }) => argument.value,
    ),
  ).toEqual([true, '', ''])
})

test('polymorphic nodes expose one node-level type selector above their inputs', async ({
  page,
  request,
}, info) => {
  const original = await template(request)
  await page.goto(`/#/templates/${original.id}/edit`)
  const workspace = page.locator('.logic-workspace')
  await workspace.getByRole('button', { name: 'Template logic', exact: true }).click()
  for (const name of ['Filled', 'Intermediate variable']) {
    await add(workspace, name)
    const selector = workspace.getByRole('combobox', { name: 'Value type', exact: true })
    await expect(selector).toHaveCount(1)
    await selector.selectOption('text')
    await settled(workspace)
    const input = workspace.getByRole('textbox', { name: 'Value', exact: true })
    await expect(input).toBeVisible()
    const nodeName = name === 'Filled' ? name : 'value1'
    await connect(workspace, 'Subtitle', `${nodeName} Value`)
    // The shared control stays at node level while the individual input becomes a wire.
    await expect(selector).toBeVisible()
    await expect(selector).toBeDisabled()
    await workspace.getByRole('button', { name: 'Disconnect Value', exact: true }).click()
    await settled(workspace)
    await expect(selector).toBeEnabled()
    await selector.selectOption('number')
    await settled(workspace)
    await expect(workspace.getByRole('spinbutton', { name: 'Value', exact: true })).toBeVisible()
  }
  await workspace.locator('.node-inspector').evaluate((element) => {
    element.scrollTop = 0
  })
  await workspace.screenshot({ path: info.outputPath('shared-type-desktop.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await workspace
    .locator('.node-inspector')
    .screenshot({ path: info.outputPath('shared-type-mobile.png') })
})

test('empty image types keep triangle connectors across configurable nodes', async ({
  page,
  request,
}, info) => {
  const original = await template(request)
  await page.goto(`/#/templates/${original.id}/edit`)
  const workspace = page.locator('.logic-workspace')
  await workspace.getByRole('button', { name: 'Template logic', exact: true }).click()
  for (const name of ['If', 'Equal', 'Filled', 'Intermediate variable']) {
    await add(workspace, name)
    await workspace.getByRole('combobox', { name: 'Value type', exact: true }).selectOption('image')
    await settled(workspace)
    const label = name === 'Intermediate variable' ? 'value1' : name
    const ports = name === 'If' ? ['Then', 'Else'] : name === 'Equal' ? ['A', 'B'] : ['Value']
    for (const port of ports)
      await expect(
        workspace
          .getByRole('button', { name: `${label} ${port} input (image)`, exact: true })
          .locator('svg path'),
      ).toHaveAttribute('d', 'M12 3 22 20H2Z')
    if (name === 'If' || name === 'Intermediate variable')
      await expect(
        workspace
          .getByRole('button', { name: `${label} output (image)`, exact: true })
          .locator('svg path'),
      ).toHaveAttribute('d', 'M12 3 22 20H2Z')
    else
      await expect(
        workspace
          .getByRole('button', { name: `${label} output (boolean)`, exact: true })
          .locator('svg rect'),
      ).toBeVisible()
  }
  await workspace.screenshot({ path: info.outputPath('empty-image-triangles.png') })
})
