import { test, expect } from './fixtures'

test('administration reuses cached navigation data and reloads only mutated records', async ({
  page,
}) => {
  const paths = [
    '/api/admin/users',
    '/api/admin/roles',
    '/api/admin/groups',
    '/api/admin/registration-codes',
    '/api/admin/permissions',
    '/api/admin/settings',
    '/api/admin/notification-endpoints',
  ]
  const reads = Object.fromEntries(paths.map((path) => [path, 0]))
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname
    if (request.method() === 'GET' && path in reads) reads[path]!++
  })
  await page.goto('/#/admin')
  await expect(page.getByRole('button', { name: 'Edit owner', exact: true })).toBeVisible()
  await expect.poll(() => Object.values(reads)).toEqual(paths.map(() => 1))

  await page.getByRole('link', { name: 'Overview', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Administration', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Edit owner', exact: true })).toBeVisible()
  expect(Object.values(reads)).toEqual(paths.map(() => 1))

  // Saving a code must not reload unrelated forms or discard unsaved settings.
  await page.getByRole('button', { name: 'Account settings', exact: true }).click()
  const unsavedDelay = page.getByLabel('Approval notification delay (seconds)', { exact: false })
  await unsavedDelay.fill('123')
  await page.getByRole('button', { name: 'Registration codes', exact: true }).click()
  await page.getByLabel('Code label', { exact: true }).fill('Cache test invitation')
  await page.getByRole('button', { name: 'Create registration code', exact: true }).click()
  await expect(page.getByText('Cache test invitation', { exact: true })).toBeVisible()
  await expect(page.getByText('Registration code created.', { exact: false })).toBeVisible()
  await expect(unsavedDelay).toHaveValue('123')
  expect(reads['/api/admin/registration-codes']).toBe(2)
  for (const path of paths.filter((path) => path !== '/api/admin/registration-codes')) {
    expect(reads[path]).toBe(1)
  }
})
