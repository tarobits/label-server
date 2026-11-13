import { chooseTapeProfile, tapeProfileControl } from './tape-profile-picker-helpers'
import { test, expect } from './fixtures'
import { chooseTemplate, templateControl } from './template-picker-helpers'
import type { Profile } from '../src/shared/types'

for (const path of ['/new', '/runs']) {
  test(`${path} selects saved template profiles and preserves explicit overrides`, async ({
    page,
    request,
  }) => {
    const active: Profile = (await (await request.get('/api/tape-profiles')).json())[0]
    const saved: Profile = await (
      await request.post('/api/tape-profiles', {
        data: { name: 'Saved template tape', width_mm: 24 },
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
    const tapeSelect = tapeProfileControl(page)
    const templateSelect = templateControl(page)

    await page.goto(`/#${path}`)
    await expect(templateSelect).toHaveJSProperty('value', '')
    await page.goto('/#/templates')
    await page
      .locator('article')
      .filter({ has: page.getByRole('heading', { name: 'Saved profile template', exact: true }) })
      .getByRole('link', { name: path === '/new' ? 'Use template' : 'Use with CSV', exact: true })
      .click()
    await expect(tapeSelect).toHaveJSProperty('value', saved.id)
    await chooseTapeProfile(page, active.id)
    await expect(page).toHaveURL(new RegExp(`profile=${active.id}`))
    await page.reload()
    await expect(tapeSelect).toHaveJSProperty('value', active.id)

    await chooseTemplate(page, other.id)
    await chooseTemplate(page, template.id)
    await expect(tapeSelect).toHaveJSProperty('value', saved.id)
    await chooseTemplate(page, legacy.id)
    await expect(tapeSelect).toHaveJSProperty('value', saved.id)
    await chooseTemplate(page, missing.id)
    await expect(tapeSelect).toHaveJSProperty('value', '')

    await page.goto(`/#${path}?template=${other.id}&profile=${saved.id}`)
    await expect(templateSelect).toHaveJSProperty('value', other.id)
    await expect(tapeSelect).toHaveJSProperty('value', saved.id)
    await page.goto(`/#${path}?template=${template.id}`)
    await expect(templateSelect).toHaveJSProperty('value', template.id)
    await expect(tapeSelect).toHaveJSProperty('value', saved.id)
    const profiles: Profile[] = await (await request.get('/api/tape-profiles')).json()
    await page.route('**/api/tape-profiles', (route) =>
      route.fulfill({
        json: profiles.map((profile) => ({
          ...profile,
          available: profile.id !== saved.id,
        })),
      }),
    )
    // A stale explicit link and an unavailable template suggestion must not select it.
    await page.goto(`/#${path}?template=${template.id}&profile=${saved.id}`)
    await page.reload()
    await expect(tapeSelect).toHaveJSProperty('value', '')
    await chooseTapeProfile(page, active.id)
    await chooseTemplate(page, other.id)
    await chooseTemplate(page, template.id)
    await expect(tapeSelect).toHaveJSProperty('value', '')
    await chooseTapeProfile(page, active.id)
    await expect(tapeSelect).toHaveJSProperty('value', active.id)
    await page.unroute('**/api/tape-profiles')
    await page.route('**/api/tape-profiles', (route) =>
      route.fulfill({ json: profiles.map((profile) => ({ ...profile, available: false })) }),
    )
    await page.goto(`/#${path}`)
    await page.reload()
    await expect(templateSelect).toHaveJSProperty('value', '')
    await expect(tapeSelect).toHaveJSProperty('value', '')
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
  const tape = tapeProfileControl(page)
  await expect(tape).toHaveJSProperty('value', narrow.id)
  await expect(page.getByRole('combobox', { name: 'Tape width (mm)', exact: true })).toHaveCount(0)
  await tape.click()
  await expect(
    page
      .getByRole('dialog', { name: 'Choose tape profile', exact: true })
      .getByRole('button', { name: 'Use Black on white', exact: true }),
  ).toHaveCount(0)
  await page
    .getByRole('dialog', { name: 'Choose tape profile', exact: true })
    .getByRole('button', { name: 'Close', exact: true })
    .click()
  const canvas = page.locator('svg.editor-canvas')
  await expect(canvas).toHaveAttribute('viewBox', / 12$/)
  await chooseTapeProfile(page, active.id)
  await expect(canvas).toHaveAttribute('viewBox', / 24$/)
  await page.getByRole('button', { name: 'Undo', exact: true }).click()
  await expect(tape).toHaveJSProperty('value', narrow.id)
  await expect(canvas).toHaveAttribute('viewBox', / 12$/)
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page).toHaveURL(/templates\/[^/]+\/edit/)
  const id = page.url().split('/templates/')[1].split('/')[0]
  const saved = await (await request.get(`/api/templates/${id}`)).json()
  expect(saved.document.width_mm).toBe(12)
  expect(saved.document.preview_tape.id).toBe(narrow.id)
  await page.reload()
  await expect(tape).toHaveJSProperty('value', narrow.id)
  await expect(canvas).toHaveAttribute('viewBox', / 12$/)
  await expect(page.getByRole('button', { name: 'Save template', exact: true })).toBeEnabled()
  await page.screenshot({ path: 'test-results/template-profile-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: 'test-results/template-profile-mobile.png' })
})
