import { test, expect } from './fixtures'

test('queued copy counts can be saved or cancelled on mobile', async ({ page, request }) => {
  const [profile] = await (await request.get('/api/tape-profiles')).json()
  const job = await (
    await request.post('/api/jobs', {
      data: { tape_profile: profile.id, copies: 2, data: { text: 'Quantity check' } },
    })
  ).json()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/#/queue')
  const row = page
    .locator('tbody tr')
    .filter({ has: page.getByRole('button', { name: 'Change copies', exact: true }) })
  const change = row.getByRole('button', { name: 'Change copies', exact: true })
  await change.click()
  const dialog = page.getByRole('dialog', { name: 'Change copies', exact: true })
  await expect(dialog.getByLabel('Copies', { exact: true })).toBeFocused()
  await dialog.getByLabel('Copies', { exact: true }).fill('5')
  await page.screenshot({ path: 'test-results/change-copies-mobile.png', fullPage: true })
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(dialog).toBeHidden()
  await expect(change).toBeFocused()
  expect((await (await request.get(`/api/jobs/${job.id}`)).json()).copies).toBe(2)
  await change.click()
  await dialog.getByLabel('Copies', { exact: true }).fill('4')
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(dialog).toBeHidden()
  await expect(row).toContainText('4 queued')
  const updated = await (await request.get(`/api/jobs/${job.id}`)).json()
  expect(updated.copies).toBe(4)
  expect(updated.labels).toHaveLength(4)
})

test('pending copy edits invalidate an open approval and require a fresh review', async ({
  page,
  request,
}) => {
  const [profile] = await (await request.get('/api/tape-profiles')).json()
  const value = await (
    await request.post('/api/requests', {
      data: {
        kind: 'job',
        input: { tape_profile: profile.id, copies: 2, data: { text: 'Reviewed quantity' } },
      },
    })
  ).json()
  const path = `/api/requests/${value.id}`
  await page.goto(`/#/requests/${value.id}`)
  await page.getByRole('button', { name: 'Change copies', exact: true }).click()
  const edit = page.getByRole('dialog', { name: 'Change copies', exact: true })
  await edit.getByLabel('Copies', { exact: true }).fill('3')
  await edit.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(edit).toBeHidden()
  await expect(page.locator('.request-preview')).toContainText('3 copies')
  await page.getByRole('button', { name: 'Approve and queue', exact: true }).click()
  const confirmation = page.getByRole('dialog', { name: 'Confirm action', exact: true })
  await expect(confirmation).toBeVisible()
  expect(
    (
      await request.put(`${path}/labels/0/copies`, { data: { copies: 7, expected_revision: 2 } })
    ).ok(),
  ).toBeTruthy()
  await confirmation.getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(
    page.getByRole('alert').filter({ hasText: 'This request changed' }).first(),
  ).toBeVisible()
  expect((await (await request.get(path)).json()).status).toBe('pending')
  await expect(page.getByRole('button', { name: 'Reload request', exact: true })).toBeVisible({
    timeout: 12000,
  })
  await expect(page.getByRole('button', { name: 'Approve and queue', exact: true })).toBeDisabled()
  await page.screenshot({ path: 'test-results/request-copies-stale.png', fullPage: true })
  await page.getByRole('button', { name: 'Reload request', exact: true }).click()
  await expect(page.locator('.request-preview')).toContainText('7 copies')
  await page.getByRole('button', { name: 'Approve and queue', exact: true }).click()
  await confirmation.getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(page.getByRole('link', { name: 'View print queue', exact: true })).toBeVisible()
  const approved = await (await request.get(path)).json()
  expect((await (await request.get(`/api/jobs/${approved.job_ids[0]}`)).json()).copies).toBe(7)
})
