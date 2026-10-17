import { test, expect } from './fixtures'

test('an empty cassette pauses automatic printing, alerts once, and resumes after correction', async ({
  page,
  request,
}) => {
  const cartridges = await (await request.get('/api/cartridges')).json()
  const cartridge = cartridges[0]
  const profiles = await (await request.get('/api/tape-profiles')).json()
  const profile = profiles.find((item: { id: string }) => item.id === cartridge.profile_id)
  expect(
    (
      await request.put(`/api/cartridges/${cartridge.id}/remaining`, {
        data: { remaining_mm: 0 },
      })
    ).ok(),
  ).toBeTruthy()
  expect(
    (
      await request.put(`/api/tape-profiles/${profile.id}`, {
        data: {
          name: profile.name,
          width_mm: profile.width_mm,
          foreground: profile.foreground,
          background: profile.background,
          auto_print_threshold: 2,
          waiting_notification_enabled: profile.waiting_notification_enabled,
          waiting_notification_interval_seconds: profile.waiting_notification_interval_seconds,
        },
      })
    ).ok(),
  ).toBeTruthy()
  const submitted = await request.post('/api/jobs', {
    data: {
      tape_profile: profile.id,
      data: { text: 'Waiting for replacement tape' },
      copies: 2,
    },
  })
  expect(submitted.ok()).toBeTruthy()
  const job = await submitted.json()
  await page.goto('/#/')
  const card = page
    .locator('article')
    .filter({ has: page.getByRole('heading', { name: 'Desk printer', exact: true }) })
  await expect(card).toContainText('Installed cartridge is estimated empty')
  const unchanged = await (await request.get(`/api/jobs/${job.id}`)).json()
  expect(unchanged.labels.map((copy: { state: string }) => copy.state)).toEqual([
    'queued',
    'queued',
  ])
  expect(await (await request.get('/api/batches')).json()).toEqual([])
  const states = await (await request.get('/api/printers/status')).json()
  expect(states[0].automatic_printing_held).toBe(false)

  await page.getByRole('link', { name: 'Activity', exact: true }).click()
  const notice = page.locator('.notification').filter({ hasText: 'Installed cartridge is empty' })
  await expect(notice).toHaveCount(1)
  await expect(notice).toContainText('Desk printer')
  await expect(notice).toContainText('Yellow cassette 1')
  await expect(notice).toContainText('estimated 0 mm')
  await expect(page.getByText('ntfy not configured', { exact: true })).toBeVisible()
  // Allow repeated worker ticks so one depletion episode cannot generate repeated alerts.
  await page.waitForTimeout(1100)
  const notices = await (await request.get('/api/notifications')).json()
  expect(notices.filter((item: { kind: string }) => item.kind === 'empty_tape')).toHaveLength(1)
  expect(await (await request.get('/api/batches')).json()).toEqual([])

  expect(
    (
      await request.put(`/api/cartridges/${cartridge.id}/remaining`, {
        data: { remaining_mm: 8000 },
      })
    ).ok(),
  ).toBeTruthy()
  await expect
    .poll(async () => {
      const completed = await (await request.get(`/api/jobs/${job.id}`)).json()
      return completed.labels.map((copy: { state: string }) => copy.state)
    })
    .toEqual(['printed', 'printed'])
  const resumedStates = await (await request.get('/api/printers/status')).json()
  expect(resumedStates[0].automatic_printing_held).toBe(false)
  await page.getByRole('link', { name: 'Overview', exact: true }).click()
  // This correction came from another client; allow the shared cartridge cache to expire.
  await expect(card).not.toContainText('Installed cartridge is estimated empty', {
    timeout: 15000,
  })
})
