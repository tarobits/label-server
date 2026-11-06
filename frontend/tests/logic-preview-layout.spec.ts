import { test, expect } from './fixtures'

for (const mode of ['fixed', 'logic', 'automatic'] as const) {
  test(`logic previews preserve physical proportions with ${mode} length`, async ({
    page,
    request,
  }, info) => {
    const templateDocument = {
      version: 2,
      width_mm: 24,
      length_mm: mode === 'fixed' ? 12 : 60,
      auto_length: mode === 'automatic',
      print_resolution: 'high',
      elements: [
        { id: 'square', logic_name: 'square', kind: 'rectangle', x: 2, y: 6, width: 8, height: 8 },
      ],
      logic: {
        version: 1,
        variables: {},
        bindings:
          mode === 'logic'
            ? [
                {
                  target: 'label',
                  property: 'length_mm',
                  expression: { kind: 'literal', value: 96 },
                },
              ]
            : [],
      },
    }
    const created = await request.post('/api/templates', {
      data: { name: 'Preview proportions', document: templateDocument },
    })
    expect(created.ok(), await created.text()).toBeTruthy()
    const template = await created.json()
    const response = page.waitForResponse(
      (response) => response.url().endsWith('/api/preview') && response.ok(),
    )
    await page.goto(`/#/templates/${template.id}/edit`)
    const rendered = await (await response).json()
    if (mode !== 'fixed') expect(rendered.length_mm).not.toBe(templateDocument.length_mm)
    const workspace = page.locator('.logic-workspace')
    await workspace.getByRole('button', { name: 'Template logic', exact: true }).click()
    for (const width of [1280, 402]) {
      await page.setViewportSize({ width, height: 900 })
      for (const tab of ['Nodes', 'Source']) {
        await workspace.getByRole('tab', { name: tab, exact: true }).click()
        const image = workspace.getByRole('img', {
          name: tab === 'Nodes' ? 'Logic label preview' : 'Source label preview',
          exact: true,
        })
        await expect(image).toBeVisible()
        await expect
          .poll(async () => {
            const box = (await image.boundingBox())!
            return Math.abs(box.width / box.height - rendered.length_mm / rendered.width_mm)
          })
          .toBeLessThan(0.01)
        expect((await image.boundingBox())!.height).toBeLessThanOrEqual(140.1)
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
          true,
        )
        await image.scrollIntoViewIfNeeded()
        await image.screenshot({
          path: `test-results/logic-preview-${info.project.name}-${mode}-${tab}-${width}.png`,
        })
      }
    }
  })
}
