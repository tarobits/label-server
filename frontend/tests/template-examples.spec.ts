import { test, expect } from './fixtures'

for (const width of [1280, 390]) {
  test(`saved examples drive unsaved canvas and enforce text lengths at ${width}px`, async ({
    page,
    request,
  }) => {
    await page.setViewportSize({ width, height: 900 })
    const created = await request.post('/api/templates', {
      data: {
        name: 'Example gallery',
        document: {
          fields: [
            { name: 'caption', label: 'Caption', sample: '', default: 'Sample', required: false },
          ],
          elements: [
            {
              id: 'title',
              kind: 'text',
              x: 2,
              y: 4,
              width: 40,
              height: 12,
              content: '{{caption}}',
            },
          ],
        },
      },
    })
    expect(created.ok(), await created.text()).toBeTruthy()
    const template = await created.json()
    await page.goto(`/#/templates/${template.id}/edit`)
    const panel = page.getByRole('region', { name: 'Preview inputs', exact: true })
    const canvas = page.locator('.editor-canvas image')
    await expect(canvas).toBeVisible()
    const original = await canvas.getAttribute('href')
    await panel.getByRole('button', { name: 'Add example', exact: true }).click()
    await expect(panel.getByLabel('Caption', { exact: true })).toHaveValue('Sample')
    await panel.getByLabel('Example name', { exact: true }).fill('Short')
    await panel.getByLabel('Caption', { exact: true }).fill('Hi')
    await expect(canvas).not.toHaveAttribute('href', original!)
    const short = await canvas.getAttribute('href')
    await panel.getByRole('button', { name: 'Duplicate', exact: true }).click()
    await panel.getByLabel('Example name', { exact: true }).fill('Long')
    await panel.getByLabel('Caption', { exact: true }).fill('A longer caption')
    await expect(canvas).not.toHaveAttribute('href', short!)
    await panel.getByRole('button', { name: 'Previous example', exact: true }).click()
    await expect(panel.getByLabel('Caption', { exact: true })).toHaveValue('Hi')
    await expect(canvas).toHaveAttribute('href', short!)
    await page.getByRole('button', { name: 'Add text', exact: true }).click()
    await expect(canvas).not.toHaveAttribute('href', short!)
    expect(
      (await (await request.get(`/api/templates/${template.id}`)).json()).document.elements,
    ).toHaveLength(1)
    const row = page.locator('.variable-row').first()
    await row.getByLabel('Variable name', { exact: true }).fill('message')
    await row.getByLabel('Minimum length', { exact: true }).fill('2')
    await row.getByLabel('Maximum length', { exact: true }).fill('20')
    await row.getByLabel('Field label', { exact: true }).click()
    await panel.getByLabel('Caption', { exact: true }).fill('x')
    await expect
      .poll(() =>
        panel
          .getByLabel('Caption', { exact: true })
          .evaluate((input) => (input as HTMLTextAreaElement).validationMessage),
      )
      .toContain('at least 2')
    await expect(canvas).toHaveCount(0)
    await panel.getByLabel('Caption', { exact: true }).fill('Hi')
    await page.getByRole('button', { name: 'Save template', exact: true }).click()
    await expect(page.getByText('Revision 2', { exact: true })).toBeVisible()
    const saved = (await (await request.get(`/api/templates/${template.id}`)).json()).document
    expect(saved.preview_examples.map((item: { data: object }) => item.data)).toEqual([
      { message: 'Hi' },
      { message: 'A longer caption' },
    ])
    expect(saved.fields[0]).toMatchObject({ min_length: 2, max_length: 20 })
    await page.reload()
    await panel.getByRole('button', { name: 'Previous example', exact: true }).click()
    await expect(panel.getByLabel('Example name', { exact: true })).toHaveValue('Long')
    await panel.scrollIntoViewIfNeeded()
    for (const name of ['Previous example', 'Next example']) {
      const button = panel.getByRole('button', { name, exact: true })
      await expect(button).toHaveCSS('height', '44px')
      await expect(button.locator('svg')).toHaveCSS('width', '20px')
    }
    await panel.screenshot({
      path: `test-results/template-examples-${width}.png`,
      animations: 'disabled',
    })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
    await panel.getByRole('button', { name: 'Delete example', exact: true }).click()
    await expect(panel.getByLabel('Example name', { exact: true })).toHaveValue('Short')
    await page.getByRole('button', { name: 'Undo', exact: true }).click()
    await expect(
      panel.getByRole('combobox', { name: 'Example', exact: true }).locator('option'),
    ).toHaveCount(3)
    await panel.getByRole('combobox', { name: 'Example', exact: true }).selectOption('')
    await expect(panel.getByLabel('Example name', { exact: true })).not.toBeVisible()
    await page.goto(`/#/new?template=${template.id}`)
    const input = page.getByRole('textbox', { name: 'Caption', exact: true })
    await input.fill('x')
    await expect
      .poll(() => input.evaluate((node) => (node as HTMLTextAreaElement).validationMessage))
      .toContain('at least 2')
    await input.fill('x'.repeat(21))
    await expect
      .poll(() => input.evaluate((node) => (node as HTMLTextAreaElement).validationMessage))
      .toContain('at most 20')
    await input.fill('Hi')
    await expect
      .poll(() => input.evaluate((node) => (node as HTMLTextAreaElement).validationMessage))
      .toBe('')
    await expect(page.getByRole('button', { name: 'Add to queue', exact: true })).toBeEnabled()
  })
}

test('barcode, Data Matrix and Aztec controls render and save', async ({ page, request }) => {
  await page.goto('/#/templates/new')
  await page.getByLabel('Template name', { exact: true }).fill('Codes')
  for (const [label, kind, content] of [
    ['barcode', 'barcode', '12345678'],
    ['Data Matrix', 'datamatrix', 'Matrix payload'],
    ['Aztec code', 'aztec', 'Aztec payload'],
  ]) {
    await page.getByRole('button', { name: `Add ${label}`, exact: true }).click()
    await page.getByRole('textbox', { name: 'Content', exact: true }).fill(content!)
    await expect(page.locator('.editor-canvas image')).toBeVisible()
    if (kind === 'barcode') {
      for (const [format, value] of [
        ['ean13', '5901234123457'],
        ['ean8', '96385074'],
        ['code39', 'ABC-42'],
        ['code128', '12345678'],
      ]) {
        await page.getByRole('textbox', { name: 'Content', exact: true }).fill(value!)
        await page
          .getByRole('combobox', { name: 'Barcode format', exact: true })
          .selectOption(format!)
        await expect(page.getByRole('button', { name: 'Save template', exact: true })).toBeEnabled()
      }
      await page.getByLabel('Show caption', { exact: true }).uncheck()
      await expect(page.getByLabel('Caption size (mm)', { exact: true })).not.toBeVisible()
      await page.getByLabel('Show caption', { exact: true }).check()
      await expect(page.getByLabel('Caption size (mm)', { exact: true })).toBeVisible()
    }
  }
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page).toHaveURL(/#\/templates\/[^/]+\/edit/)
  const id = page.url().split('/templates/')[1]!.split('/')[0]!
  const saved = (await (await request.get(`/api/templates/${id}`)).json()).document
  expect(saved.elements.map((item: { kind: string }) => item.kind)).toEqual([
    'barcode',
    'datamatrix',
    'aztec',
  ])
  await page.reload()
  await expect(page.locator('.editor-canvas image')).toBeVisible()
  await page.getByRole('button', { name: '1. barcode', exact: true }).click()
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await page.locator('.editor-properties').scrollIntoViewIfNeeded()
    await page.screenshot({ path: `test-results/code-editor-${width}.png`, animations: 'disabled' })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
  }
})
