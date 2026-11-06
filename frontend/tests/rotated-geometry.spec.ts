import { test, expect } from './fixtures'
import { showEditorSettings } from './editor-settings'
import type { Page } from '@playwright/test'

async function bounds(page: Page) {
  return page.locator('.object-boundary').evaluate((node) => {
    const rect = node as SVGRectElement
    const matrix = rect.ownerSVGElement!.getScreenCTM()!.inverse().multiply(rect.getScreenCTM()!)
    const points = [
      [0, 0],
      [1, 0],
      [0, 1],
      [1, 1],
    ].map(([x, y]) =>
      new DOMPoint(
        rect.x.baseVal.value + x! * rect.width.baseVal.value,
        rect.y.baseVal.value + y! * rect.height.baseVal.value,
      ).matrixTransform(matrix),
    )
    const x = Math.min(...points.map((p) => p.x)),
      y = Math.min(...points.map((p) => p.y))
    return {
      x,
      y,
      width: Math.max(...points.map((p) => p.x)) - x,
      height: Math.max(...points.map((p) => p.y)) - y,
    }
  })
}

for (const rotation of [0, 90, 180, 270]) {
  test(`rotated text at ${rotation} degrees resizes on label axes with a fixed top-left`, async ({
    page,
    request,
  }, info) => {
    const response = await request.post('/api/templates', {
      data: {
        name: 'Rotated text',
        document: {
          version: 2,
          length_mm: 40,
          elements: [
            {
              id: 'text',
              logic_name: 'text1',
              kind: 'text',
              x: 6,
              y: 6,
              width: 8,
              height: 6,
              rotation,
              content: 'Loïs',
            },
          ],
        },
      },
    })
    expect(response.ok()).toBeTruthy()
    const template = await response.json()
    await page.goto(`/#/templates/${template.id}/edit?element=text`)
    await showEditorSettings(page, 'Position & size')
    if (rotation === 90) await page.setViewportSize({ width: 402, height: 874 })
    const before = await bounds(page)
    expect(Number(await page.getByLabel('X (mm)', { exact: true }).inputValue())).toBeCloseTo(
      before.x,
    )
    expect(Number(await page.getByLabel('Y (mm)', { exact: true }).inputValue())).toBeCloseTo(
      before.y,
    )
    if (rotation === 90)
      await page
        .locator('.editor-board')
        .screenshot({ path: `test-results/rotated-before-${info.project.name}.png` })
    const rendered = page.waitForResponse(
      (response) => response.url().endsWith('/api/preview') && response.ok(),
    )
    await page.getByLabel('Height (mm)', { exact: true }).fill('2')
    await page.getByLabel('Height (mm)', { exact: true }).press('Tab')
    await expect.poll(async () => (await bounds(page)).height).toBeCloseTo(2)
    const after = await bounds(page)
    expect(after.width).toBeCloseTo(before.width)
    expect(after.x).toBeCloseTo(before.x)
    expect(after.y).toBeCloseTo(before.y)
    await rendered
    if (rotation === 90)
      await page
        .locator('.editor-board')
        .screenshot({ path: `test-results/rotated-after-${info.project.name}.png` })
    await page.getByLabel('X (mm)', { exact: true }).fill('3')
    await page.getByLabel('Y (mm)', { exact: true }).fill('4')
    await page.getByLabel('Y (mm)', { exact: true }).press('Tab')
    await expect.poll(async () => (await bounds(page)).x).toBeCloseTo(3)
    await expect.poll(async () => (await bounds(page)).y).toBeCloseTo(4)
    await page.getByRole('button', { name: 'Save template', exact: true }).click()
    await expect(page.getByText('Revision 2', { exact: true })).toBeVisible()
    await page.reload()
    await showEditorSettings(page, 'Position & size')
    const restored = await bounds(page)
    expect(restored.x).toBeCloseTo(3)
    expect(restored.y).toBeCloseTo(4)
    expect(restored.width).toBeCloseTo(before.width)
    expect(restored.height).toBeCloseTo(2)
  })
}

test('lines expose length and stroke without an empty cross-axis dimension', async ({
  page,
  request,
}, info) => {
  const response = await request.post('/api/templates', {
    data: {
      name: 'Line geometry',
      document: {
        length_mm: 50,
        elements: [{ id: 'line', kind: 'line', x: 5, y: 2, width: 12, height: 8, stroke: 0.5 }],
      },
    },
  })
  const template = await response.json()
  await page.goto(`/#/templates/${template.id}/edit?element=line`)
  await showEditorSettings(page, 'Position & size')
  const original = await bounds(page)
  expect(original.height).toBeCloseTo(0.5)
  expect(original.y).toBeCloseTo(5.75)
  await expect(page.getByLabel('Width (mm)', { exact: true })).toHaveCount(0)
  await expect(page.getByLabel('Height (mm)', { exact: true })).toHaveCount(0)
  for (const rotation of [90, 0, 90, 0]) {
    await showEditorSettings(page, 'Position & size')
    await page
      .getByRole('combobox', { name: 'Direction', exact: true })
      .selectOption(String(rotation))
    await page.getByLabel('Length (mm)', { exact: true }).fill('10')
    await page.getByLabel('Length (mm)', { exact: true }).press('Tab')
    await showEditorSettings(page, 'Appearance')
    await page.getByLabel('Stroke (mm)', { exact: true }).fill('1')
    await page.getByLabel('Stroke (mm)', { exact: true }).press('Tab')
    const actual = await bounds(page)
    expect(actual.x).toBeCloseTo(original.x)
    expect(actual.y).toBeCloseTo(original.y)
    expect(actual.width).toBeCloseTo(rotation % 180 ? 1 : 10)
    expect(actual.height).toBeCloseTo(rotation % 180 ? 10 : 1)
    await expect(page.getByRole('button', { name: 'Save template', exact: true })).toBeEnabled()
  }
  await page
    .locator('.editor-board')
    .screenshot({ path: `test-results/line-geometry-${info.project.name}.png` })
})

test('vertical lines can be added directly within the printable tape', async ({ page }) => {
  await page.goto('/#/templates/new')
  await page.getByRole('button', { name: 'Add vertical line', exact: true }).click()
  await showEditorSettings(page, 'Position & size')
  await expect(page.getByRole('combobox', { name: 'Direction', exact: true })).toHaveValue('90')
  await expect(page.getByRole('combobox', { name: 'Rotation', exact: true })).toHaveCount(0)
  const actual = await bounds(page)
  expect(actual.width).toBeCloseTo(0.3)
  expect(actual.height).toBeGreaterThan(10)
  expect(actual.y).toBeGreaterThanOrEqual(0)
  expect(actual.y + actual.height).toBeLessThanOrEqual(24)
  await page.getByLabel('Length (mm)', { exact: true }).fill('12')
  await page.getByLabel('Length (mm)', { exact: true }).press('Tab')
  await expect.poll(async () => (await bounds(page)).height).toBeCloseTo(12)
})

test('dragging a legacy line preserves its stroke position and resizing changes only length', async ({
  page,
  request,
}) => {
  const response = await request.post('/api/templates', {
    data: {
      name: 'Line drag',
      document: {
        length_mm: 50,
        elements: [{ id: 'line', kind: 'line', x: 5, y: 2, width: 12, height: 8, stroke: 0.5 }],
      },
    },
  })
  const template = await response.json()
  await page.goto(`/#/templates/${template.id}/edit?element=line`)
  await showEditorSettings(page, 'Position & size')
  await page.getByLabel('Snap 0.5 mm', { exact: true }).uncheck()
  for (const direction of [0, 90]) {
    await page
      .getByRole('combobox', { name: 'Direction', exact: true })
      .selectOption(String(direction))
    await page.locator('.object-boundary').scrollIntoViewIfNeeded()
    const before = await bounds(page)
    const box = (await page.locator('.object-boundary').boundingBox())!
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.down()
    await page.mouse.move(box.x + box.width / 2 + 16, box.y + box.height / 2 + 8)
    await page.mouse.up()
    const moved = await bounds(page)
    expect(moved.x).toBeCloseTo(before.x + 2)
    expect(moved.y).toBeCloseTo(before.y + 1)
    expect(moved.width).toBeCloseTo(before.width)
    expect(moved.height).toBeCloseTo(before.height)
    const handle = (await page.locator('.editor-canvas circle').boundingBox())!
    await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2)
    await page.mouse.down()
    await page.mouse.move(
      handle.x + handle.width / 2 + (direction ? 0 : 8),
      handle.y + handle.height / 2 + (direction ? 8 : 0),
    )
    await page.mouse.up()
    const resized = await bounds(page)
    expect(resized.x).toBeCloseTo(moved.x)
    expect(resized.y).toBeCloseTo(moved.y)
    expect(resized.width).toBeCloseTo(moved.width + (direction ? 0 : 1))
    expect(resized.height).toBeCloseTo(moved.height + (direction ? 1 : 0))
  }
})
