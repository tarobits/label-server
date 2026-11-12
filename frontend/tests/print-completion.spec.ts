import { test, expect } from './fixtures'
import { chooseTemplate } from './template-picker-helpers'

for (const width of [390, 1280]) {
  test(`per-item completion preference persists at ${width}px`, async ({ page, request }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/#/new')
    await page.getByLabel('Label text', { exact: true }).fill('Completion preference')
    const choice = page.getByRole('checkbox', { name: 'Notify when printed', exact: true })
    await expect(choice).toBeChecked()
    await choice.uncheck()
    await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
    await expect(page).toHaveURL(/#\/queue/)
    const [job] = await (await request.get('/api/jobs')).json()
    expect(job.notify_on_completion).toBe(false)
    const details = page.locator('.queue-label-details summary')
    await details.click()
    await expect(choice).not.toBeChecked()
    await choice.check()
    await expect
      .poll(
        async () => (await (await request.get(`/api/jobs/${job.id}`)).json()).notify_on_completion,
      )
      .toBe(true)
    await expect(choice).toBeChecked()
    await details.click()
    await expect(choice).toBeHidden()
    await details.click()
    await expect(choice).toBeChecked()
    await page.screenshot({
      path: `test-results/completion-queue-${width}.png`,
      fullPage: true,
      animations: 'disabled',
    })
    await page.reload()
    await details.click()
    await expect(choice).toBeChecked()
    await choice.uncheck()
    await expect
      .poll(
        async () => (await (await request.get(`/api/jobs/${job.id}`)).json()).notify_on_completion,
      )
      .toBe(false)
    await page.route(`**/api/jobs/${job.id}/completion-notification`, (route) =>
      route.fulfill({ status: 409, json: { detail: 'Unable to save preference' } }),
    )
    await choice.click()
    await expect(choice).not.toBeChecked()
    await expect(page.getByRole('alert')).toContainText('Unable to save preference')
    await page.unroute(`**/api/jobs/${job.id}/completion-notification`)
    await page.goto('/#/queue?state=printed')
    await expect(page.getByRole('combobox', { name: 'Job status', exact: true })).toHaveValue(
      'printed',
    )
  })
}

test('CSV completion preferences survive preparation and submission', async ({ page, request }) => {
  await page.goto('/#/runs')
  await chooseTemplate(page, 'text')
  await page.getByLabel('CSV content', { exact: true }).fill('Title\nNotify\nSilent')
  await page.getByRole('button', { name: 'Read CSV', exact: true }).click()
  await page.getByRole('combobox', { name: 'Label text', exact: true }).selectOption('Title')
  await page.getByLabel('Notify when record 3 is printed', { exact: true }).uncheck()
  await page.getByRole('button', { name: 'Validate and preview run', exact: true }).click()
  await expect(page).toHaveURL(/#\/runs\/[^/]+$/)
  await page.getByRole('button', { name: 'Submit entire run', exact: true }).click()
  await expect(page.getByText('Run submitted.', { exact: false })).toBeVisible()
  const jobs = await (await request.get('/api/jobs')).json()
  expect(
    jobs.find((job: { source_row: number }) => job.source_row === 2).notify_on_completion,
  ).toBe(true)
  expect(
    jobs.find((job: { source_row: number }) => job.source_row === 3).notify_on_completion,
  ).toBe(false)
})
