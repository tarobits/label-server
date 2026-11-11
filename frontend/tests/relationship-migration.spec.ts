import { test, expect } from './fixtures'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

test(
  'replacement prerequisites preserve the draft and return the created resource',
  { tag: '@empty-fleet' },
  async ({ page, request }) => {
    const session = await (await request.get('/api/auth/session')).json()
    await page.route('**/api/auth/session', (route) =>
      route.fulfill({
        json: { ...session, migration_required: true, relationship_migration_required: true },
      }),
    )
    await page.route('**/api/migration/relationships**', async (route) => {
      const path = new URL(route.request().url()).pathname
      if (path.endsWith('/creation/preview'))
        return route.fulfill({
          json: {
            confirmation_token: 'reviewed',
            name: route.request().postDataJSON().values.name,
          },
        })
      if (path.endsWith('/creation') && route.request().method() === 'POST')
        return route.fulfill({ json: { id: 'new-profile', name: 'Restored tape' } })
      if (path.endsWith('/creation'))
        return route.fulfill({
          json: {
            parent: 'cartridges',
            resources: {
              cartridges: {
                label: 'Cartridge',
                fields: [
                  { key: 'name', label: 'Name', type: 'text', required: true },
                  {
                    key: 'profile_id',
                    label: 'Tape profile',
                    type: 'reference',
                    resource: 'tape_profiles',
                    required: true,
                  },
                ],
              },
              tape_profiles: {
                label: 'Tape profile',
                fields: [{ key: 'name', label: 'Name', type: 'text', required: true }],
              },
            },
          },
        })
      if (path.endsWith('/targets')) return route.fulfill({ json: [] })
      if (path.endsWith('/rows'))
        return route.fulfill({
          json: [
            {
              token: 'a'.repeat(64),
              name: 'Printer',
              missing: 'old-cartridge',
              nullable: true,
              revoke_only: false,
            },
          ],
        })
      return route.fulfill({
        json: {
          ready: false,
          relationships: [
            {
              table: 'printer_state',
              column: 'active_cartridge_id',
              parent: 'cartridges',
              count: 1,
            },
          ],
        },
      })
    })
    await page.goto('/')
    await page.getByRole('button', { name: 'Reassign', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('button', { name: 'Create replacement' }).click()
    await dialog.getByLabel('Name', { exact: true }).fill('Preserved cartridge name')
    await dialog.getByLabel('Creation reason', { exact: true }).fill('Preserved cartridge reason')
    await dialog.getByRole('button', { name: 'Create tape profile', exact: true }).click()
    await dialog.getByRole('button', { name: 'Back', exact: true }).click()
    await expect(dialog.getByLabel('Name', { exact: true })).toHaveValue('Preserved cartridge name')
    await dialog.getByRole('button', { name: 'Create tape profile', exact: true }).click()
    await dialog.getByLabel('Name', { exact: true }).fill('Restored tape')
    await dialog.getByLabel('Creation reason', { exact: true }).fill('Verified tape details')
    await dialog.getByRole('button', { name: 'Review replacement' }).click()
    await dialog.getByRole('button', { name: 'Confirm creation' }).click()
    await expect(dialog.getByLabel('Name', { exact: true })).toHaveValue('Preserved cartridge name')
    await expect(dialog.getByLabel('Creation reason', { exact: true })).toHaveValue(
      'Preserved cartridge reason',
    )
    await expect(dialog.getByRole('combobox', { name: 'Tape profile', exact: true })).toHaveValue(
      'new-profile',
    )
    await dialog.getByRole('button', { name: 'Review replacement' }).click()
    await expect(dialog.getByText('Create Preserved cartridge name?')).toBeVisible()
    await dialog.getByRole('button', { name: 'Edit details' }).click()
    await expect(dialog.getByLabel('Name', { exact: true })).toHaveValue('Preserved cartridge name')
  },
)

for (const width of [1280, 390]) {
  test(
    `relationship repair and restart screen at ${width}px`,
    { tag: '@empty-fleet' },
    async ({ page, request }) => {
      const session = await (await request.get('/api/auth/session')).json()
      await page.route('**/api/auth/session', (route) =>
        route.fulfill({
          json: { ...session, migration_required: true, relationship_migration_required: true },
        }),
      )
      let repaired = false
      let ready = false
      let workspaceReads = 0
      page.on('request', (request) => {
        if (new URL(request.url()).pathname === '/api/workspace') workspaceReads++
      })
      await page.route('**/api/migration/relationships**', async (route) => {
        const path = new URL(route.request().url()).pathname
        if (path.endsWith('/repair')) {
          expect(route.request().postDataJSON().target).toBe('new-club')
          expect(route.request().postDataJSON().reason).toBe('Verified by administrator')
          repaired = true
          return route.fulfill({ json: { saved: true } })
        }
        if (path.endsWith('/complete')) {
          ready = true
          return route.fulfill({ json: { restart_required: true } })
        }
        if (path.endsWith('/creation/preview')) {
          expect(route.request().postDataJSON().values.name).toBe('New workshop group')
          return route.fulfill({
            json: { confirmation_token: 'test-confirmation', name: 'New workshop group' },
          })
        }
        if (path.endsWith('/creation')) {
          if (route.request().method() === 'POST') {
            expect(route.request().headers()['x-access-confirmation']).toBe('test-confirmation')
            return route.fulfill({ json: { id: 'new-club', name: 'New workshop group' } })
          }
          return route.fulfill({
            json: {
              parent: 'user_groups',
              resources: {
                user_groups: {
                  label: 'Permission group',
                  note: 'New groups have no members.',
                  fields: [
                    { key: 'name', label: 'Name', type: 'text', required: true, maxlength: 100 },
                  ],
                },
              },
            },
          })
        }
        if (path.endsWith('/targets'))
          return route.fulfill({ json: [{ id: 'club', name: 'Workshop members' }] })
        if (path.endsWith('/rows'))
          return route.fulfill({
            json: repaired
              ? []
              : [
                  {
                    token: 'a'.repeat(64),
                    name: 'Workshop equipment label',
                    missing: 'removed-group',
                    nullable: false,
                    revoke_only: false,
                  },
                ],
          })
        return route.fulfill({
          json: {
            ready,
            relationships: repaired
              ? []
              : [{ table: 'label_templates', column: 'group_id', parent: 'user_groups', count: 1 }],
          },
        })
      })
      await page.setViewportSize({ width, height: 850 })
      await page.emulateMedia({ reducedMotion: width === 390 ? 'reduce' : 'no-preference' })
      await page.goto('/')
      await expect(
        page.getByRole('heading', { name: 'Repair database relationships' }),
      ).toBeVisible()
      await expect(page.getByRole('navigation', { name: 'Main navigation' })).toHaveCount(0)
      await page.getByRole('button', { name: 'Reassign', exact: true }).click()
      const dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible()
      await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
      await expect(dialog).not.toBeVisible()
      await expect(page.getByRole('button', { name: 'Reassign', exact: true })).toBeFocused()
      await page.getByRole('button', { name: 'Reassign', exact: true }).click()
      await dialog.getByRole('button', { name: 'Create replacement', exact: true }).click()
      await dialog.getByRole('button', { name: 'Back', exact: true }).click()
      await dialog.getByRole('button', { name: 'Create replacement', exact: true }).click()
      await dialog.getByLabel('Name', { exact: true }).fill('New workshop group')
      await dialog
        .getByLabel('Creation reason', { exact: true })
        .fill('Restore the intended resource')
      await dialog.getByRole('button', { name: 'Review replacement' }).click()
      await expect(dialog.getByText('Create New workshop group?')).toBeVisible()
      await expect(dialog.getByRole('button', { name: 'Confirm creation' })).toBeEnabled()
      await mkdir(resolve('../.impeccable/review'), { recursive: true })
      await page.screenshot({
        path: resolve(
          `../.impeccable/review/creation-${width === 1280 ? 'desktop' : 'mobile'}.png`,
        ),
        fullPage: true,
        animations: 'disabled',
      })
      await dialog.getByRole('button', { name: 'Confirm creation' }).click()
      await expect(dialog.getByRole('combobox', { name: 'Replacement', exact: true })).toHaveValue(
        'new-club',
      )
      await expect(dialog.getByLabel('Find replacement', { exact: true })).toBeFocused()
      await dialog.getByLabel('Reason', { exact: true }).fill('Verified by administrator')
      await mkdir(resolve('../.impeccable/review'), { recursive: true })
      await page.screenshot({
        path: resolve(`../.impeccable/review/${width === 1280 ? 'desktop' : 'mobile'}.png`),
        fullPage: true,
        animations: 'disabled',
      })
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
      await dialog.getByRole('button', { name: 'Save assignment' }).click()
      await expect(dialog).not.toBeVisible()
      await expect(page.getByText('All references have valid targets.')).toBeVisible()
      await page.getByRole('button', { name: 'Prepare maintenance restart' }).click()
      await expect(page.getByRole('status')).toContainText('Ready for a maintenance restart')
      await expect(page.getByRole('button', { name: 'Prepare maintenance restart' })).toHaveCount(0)
      await page.screenshot({
        path: resolve(`../.impeccable/review/${width === 1280 ? 'desktop' : 'mobile'}-ready.png`),
        fullPage: true,
        animations: 'disabled',
      })
      expect(workspaceReads).toBe(0)
    },
  )
}
