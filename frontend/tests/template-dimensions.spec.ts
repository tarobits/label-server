import { test, expect } from './fixtures'

test('template dimensions distinguish fixed geometry from input-driven automatic width', async ({
  page,
  request,
}) => {
  const response = await request.post('/api/templates', {
    data: {
      name: 'Input sizing',
      document: {
        width_mm: 24,
        length_mm: 60,
        auto_length: true,
        out_of_bounds: 'clip',
        fields: [{ name: 'text', label: 'Text', sample: 'Sample' }],
        elements: [
          {
            id: 'text',
            kind: 'text',
            x: 2,
            y: 2,
            width: 40,
            height: 12,
            content: '{{text}}',
          },
        ],
      },
    },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  const original = await response.json()
  const path = `/api/templates/${original.id}`
  await page.goto('/#/templates')
  const card = page
    .locator('article')
    .filter({ has: page.getByRole('heading', { name: 'Input sizing', exact: true }) })
  await expect(card).toContainText('43 mm long')
  await expect(card).not.toContainText('60 mm long')
  await expect(card).not.toContainText('Variable length')

  original.document.elements[0].auto_width = true
  const edited = await request.put(path, {
    data: { name: original.name, document: original.document, expected_revision: 1 },
  })
  expect(edited.ok(), await edited.text()).toBeTruthy()
  await page.reload()
  await expect(card).toContainText('Variable length')
  await card.getByRole('button', { name: 'History', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: /^History:/ })
  await expect(dialog.locator('.revision-dimensions')).toContainText('Variable length')
  await dialog.getByRole('button', { name: 'View revision 1', exact: true }).click()
  await expect(dialog.locator('.revision-dimensions')).toContainText('24 mm wide · 43 mm long')
  await expect(dialog.locator('.revision-dimensions')).not.toContainText('Variable length')
  await page.screenshot({
    path: 'test-results/template-calculated-length.png',
    animations: 'disabled',
  })
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(dialog).not.toBeVisible()

  // A literal caption can size itself automatically while keeping a constant
  // physical length. Neither the stored 60 mm nor a variable label is correct.
  const current = await edited.json()
  current.document.elements[0].content = 'Fixed caption'
  const fixed = await request.put(path, {
    data: { name: current.name, document: current.document, expected_revision: 2 },
  })
  expect(fixed.ok(), await fixed.text()).toBeTruthy()
  const calculated = await fixed.json()
  expect(calculated.length_mm).not.toBe(60)
  await page.reload()
  await expect(card).toContainText(`${calculated.length_mm} mm long`)
  await expect(card).not.toContainText('Variable length')
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          document
            .getAnimations()
            .filter(
              (animation) =>
                animation.playState === 'running' &&
                animation.effect?.getTiming().iterations !== Infinity,
            ).length,
      ),
    )
    .toBe(0)
  await page.screenshot({ path: 'test-results/template-fixed-length.png', animations: 'disabled' })
})
