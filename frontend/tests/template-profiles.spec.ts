import { test, expect } from './fixtures'
import type { Profile } from '../src/types'

for (const path of ['/new', '/runs']) {
  test(`${path} selects saved template profiles and preserves explicit overrides`, async ({
    page,
    request,
  }) => {
    const active: Profile = (await (await request.get('/api/tape-profiles')).json())[0]
    const saved: Profile = await (
      await request.post('/api/tape-profiles', {
        data: { name: 'Saved template tape', width_mm: 18 },
      })
    ).json()
    async function createTemplate(name: string, profile: Profile | null) {
      const response = await request.post('/api/templates', {
        data: {
          name,
          document: {
            width_mm: profile?.width_mm ?? 24,
            preview_tape: profile
              ? {
                  id: profile.id,
                  name: profile.name,
                  foreground: profile.foreground,
                  background: profile.background,
                }
              : null,
            elements: [],
            fields: [],
          },
        },
      })
      expect(response.ok(), await response.text()).toBeTruthy()
      return response.json()
    }
    const template = await createTemplate('Saved profile template', saved)
    const other = await createTemplate('Other saved profile template', active)
    const legacy = await createTemplate('Legacy template', null)
    const missing = await createTemplate('Missing profile template', { ...saved, id: 'deleted' })
    const tapeSelect = page.getByRole('combobox', { name: 'Tape profile', exact: true })
    const templateSelect = page.getByRole('combobox', { name: 'Template', exact: true })

    await page.goto('/#/templates')
    await page
      .locator('article')
      .filter({ has: page.getByRole('heading', { name: 'Saved profile template', exact: true }) })
      .getByRole('link', { name: path === '/new' ? 'Use template' : 'Use with CSV', exact: true })
      .click()
    await expect(tapeSelect).toHaveValue(saved.id)
    await tapeSelect.selectOption(active.id)
    await expect(page).toHaveURL(new RegExp(`profile=${active.id}`))
    await page.reload()
    await expect(tapeSelect).toHaveValue(active.id)

    await templateSelect.selectOption(other.id)
    await templateSelect.selectOption(template.id)
    await expect(tapeSelect).toHaveValue(saved.id)
    await templateSelect.selectOption(legacy.id)
    await expect(tapeSelect).toHaveValue(saved.id)
    await templateSelect.selectOption(missing.id)
    await expect(tapeSelect).toHaveValue(saved.id)

    await page.goto(`/#${path}?template=${other.id}&profile=${saved.id}`)
    await expect(templateSelect).toHaveValue(other.id)
    await expect(tapeSelect).toHaveValue(saved.id)
    await page.goto(`/#${path}?template=${template.id}`)
    await expect(templateSelect).toHaveValue(template.id)
    await expect(tapeSelect).toHaveValue(saved.id)
  })
}

test('template creation requires a tape profile', async ({ page }) => {
  await page.route('**/api/tape-profiles', (route) => route.fulfill({ json: [] }))
  await page.goto('/#/templates/new')
  await expect(page.getByRole('heading', { name: 'No tape profiles', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save template', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Add text', exact: true })).toHaveCount(0)
  await page.getByRole('link', { name: 'Create tape profile', exact: true }).click()
  await expect(page).toHaveURL(/#\/profiles$/)
})

test('template dimensions follow the tape profile through save, undo and reload', async ({
  page,
  request,
}) => {
  const active: Profile = (await (await request.get('/api/tape-profiles')).json())[0]
  const narrow: Profile = await (
    await request.post('/api/tape-profiles', {
      data: { name: 'Narrow editor tape', width_mm: 12 },
    })
  ).json()
  await page.goto(`/#/templates/new?profile=${narrow.id}`)
  const tape = page.getByRole('combobox', { name: 'Tape profile', exact: true })
  await expect(tape).toHaveValue(narrow.id)
  await expect(page.getByRole('combobox', { name: 'Tape width (mm)', exact: true })).toHaveCount(0)
  await expect(tape.getByRole('option', { name: 'Black on white', exact: true })).toHaveCount(0)
  const canvas = page.locator('svg.editor-canvas')
  await expect(canvas).toHaveAttribute('viewBox', / 12$/)
  await tape.selectOption(active.id)
  await expect(canvas).toHaveAttribute('viewBox', / 24$/)
  await page.getByRole('button', { name: 'Undo', exact: true }).click()
  await expect(tape).toHaveValue(narrow.id)
  await expect(canvas).toHaveAttribute('viewBox', / 12$/)
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page).toHaveURL(/templates\/[^/]+\/edit/)
  const id = page.url().split('/templates/')[1].split('/')[0]
  const saved = await (await request.get(`/api/templates/${id}`)).json()
  expect(saved.document.width_mm).toBe(12)
  expect(saved.document.preview_tape.id).toBe(narrow.id)
  await page.reload()
  await expect(tape).toHaveValue(narrow.id)
  await expect(canvas).toHaveAttribute('viewBox', / 12$/)
  await expect(page.getByRole('button', { name: 'Save template', exact: true })).toBeEnabled()
  await page.screenshot({ path: 'test-results/template-profile-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: 'test-results/template-profile-mobile.png' })
})
