import { test, expect } from './fixtures'

test('named logic objects retain technical identifiers in pickers, graph and source completion', async ({
  page,
  request,
}) => {
  const created = await request.post('/api/templates', {
    data: {
      name: 'Named logic',
      document: {
        version: 2,
        width_mm: 24,
        length_mm: 60,
        elements: [
          {
            id: 'title',
            logic_name: 'text1',
            name: 'Product title',
            kind: 'text',
            x: 2,
            y: 4,
            width: 40,
            height: 12,
            content: 'Title',
          },
        ],
        logic: {
          version: 1,
          variables: {},
          bindings: [
            { target: 'title', property: 'bold', expression: { kind: 'literal', value: true } },
          ],
        },
      },
    },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
  const template = await created.json()
  await page.goto(`/#/templates/${template.id}/edit`)
  const workspace = page.locator('.logic-workspace')
  await workspace.getByRole('button', { name: 'Template logic', exact: true }).click()
  await expect(
    workspace.getByRole('article', { name: 'Product title (text1.bold)', exact: true }),
  ).toBeVisible()
  await workspace.getByRole('button', { name: 'Add node', exact: true }).click()
  const target = workspace.getByRole('combobox', { name: 'Property target', exact: true })
  await expect(target.locator('option[value="text1"]')).toHaveText('Product title (text1)')
  await target.selectOption('text1')
  await workspace.getByRole('button', { name: 'Add node', exact: true }).click()
  await workspace.getByRole('tab', { name: 'Source', exact: true }).click()
  const editor = workspace.getByRole('textbox', { name: 'Logic source' })
  await editor.fill('text')
  await editor.press('Control+Space')
  const completion = workspace.locator('.cm-tooltip-autocomplete')
  await expect(completion).toContainText('Product title (text1)')
  await completion.getByText('Product title (text1)', { exact: true }).click()
  await expect(editor).toHaveText('text1')
  await page.screenshot({ path: 'test-results/named-logic-source.png', animations: 'disabled' })
})
