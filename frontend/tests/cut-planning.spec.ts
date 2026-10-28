import { test, expect } from './fixtures'

test('short 12 mm labels warn before queueing and retain waste in activity and CSV drafts', async ({
  page,
  request,
}) => {
  const tape = await (
    await request.post('/api/tape-profiles', {
      data: { name: 'White 12 mm', width_mm: 12, auto_print_threshold: 1000 },
    })
  ).json()
  const cartridge = await (
    await request.post('/api/cartridges', {
      data: { name: '12 mm cartridge', profile_id: tape.id, nominal_length_mm: 8000 },
    })
  ).json()
  expect(
    (
      await request.put('/api/printer/active-tape', {
        data: { cartridge_id: cartridge.id },
      })
    ).ok(),
  ).toBeTruthy()
  expect(
    (
      await request.put('/api/printer/mock', {
        data: { connected: true, tape_width_mm: 12 },
      })
    ).ok(),
  ).toBeTruthy()
  const response = await request.post('/api/templates', {
    data: {
      name: 'Variable short labels',
      document: {
        width_mm: 12,
        length_mm: 10,
        auto_length: true,
        fields: [{ name: 'text', label: 'Text', default: 'L1' }],
        elements: [
          {
            id: 'text',
            kind: 'text',
            x: 1,
            y: 2,
            width: 5,
            height: 8,
            auto_width: true,
            content: '{{text}}',
          },
        ],
      },
    },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  const template = await response.json()
  const previewPlan = (
    await (
      await request.post('/api/preview', {
        data: { template_id: template.id },
      })
    ).json()
  ).print_plan
  const unused = (previewPlan.breakdown.unused_mm * 2).toFixed(1)
  await page.goto(`/#/new?template=${template.id}&profile=${tape.id}`)
  const warning = page.getByRole('status').filter({ hasText: 'minimum cut length' })
  const templateWarning = page.getByRole('status').filter({ hasText: '10 mm template minimum' })
  await expect(warning).toContainText('1 label is below the 24.5 mm minimum cut length')
  await expect(templateWarning).toContainText('the label is extended to 10 mm')
  await expect(warning).toContainText('Hand trimming required')
  const panel = page.locator('.preview-panel')
  const image = panel.getByAltText('Rendered label preview')
  for (const height of [720, 900]) {
    await page.setViewportSize({ width: 1440, height })
    await expect
      .poll(async () => {
        const bounds = await panel.boundingBox()
        return !!bounds && bounds.y + bounds.height <= height
      })
      .toBe(true)
    await expect
      .poll(async () => {
        const bounds = await image.boundingBox()
        return !!bounds && bounds.y + bounds.height <= height
      })
      .toBe(true)
    await expect(templateWarning).toBeInViewport({ ratio: 1 })
    await expect(warning).toBeInViewport({ ratio: 1 })
    const shape = await image.boundingBox()
    expect(shape!.width / shape!.height).toBeCloseTo(10 / 12, 1)
  }
  await page.getByLabel('Copies', { exact: true }).fill('2')
  await expect(warning).toContainText('2 labels are below')
  await expect(warning).toContainText(`${unused} mm of extra unused tape estimated`)
  await page.screenshot({ path: 'test-results/short-label-desktop.png', animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  await panel.scrollIntoViewIfNeeded()
  await expect(templateWarning).toBeInViewport({ ratio: 1 })
  await expect(warning).toBeInViewport({ ratio: 1 })
  await page.screenshot({ path: 'test-results/short-label-mobile.png', animations: 'disabled' })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  // Both entering and leaving the warning use the existing feedback motion.
  await page.getByLabel('Text', { exact: true }).fill('A much longer label')
  await expect(warning).toHaveCount(0)
  await expect(templateWarning).toHaveCount(0)
  await page.getByLabel('Text', { exact: true }).fill('L1')
  await expect(warning).toContainText('2 labels are below')
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  await expect(page).toHaveURL(/#\/queue/)
  const queueDetails = page.locator('.queue-label-details').first()
  const queueUsage = queueDetails.getByRole('region', { name: 'Tape usage' })
  await expect(queueUsage).not.toBeVisible()
  await queueDetails.locator(':scope > summary').click()
  await expect(queueUsage.locator('dt')).toHaveText(['Design', 'Feed', 'Leader', 'Unused'])
  const queuePlan = (await (await request.get('/api/queue/groups?copy_state=queued')).json())[0]
    .print_plan
  await expect(queueUsage).toContainText(`${queuePlan.breakdown.feed_mm.toFixed(2)} mm`)
  await expect(queueUsage).toContainText(`${queuePlan.breakdown.unused_mm.toFixed(2)} mm`)
  await expect(queueUsage).toContainText('24.50 mm')
  await queueUsage.scrollIntoViewIfNeeded()
  await page.screenshot({
    path: 'test-results/queue-tape-details-mobile.png',
    animations: 'disabled',
  })
  await queueDetails.locator(':scope > summary').click()
  await expect(queueUsage).not.toBeVisible()
  expect((await request.post('/api/queue/print')).ok()).toBeTruthy()
  await expect
    .poll(async () => {
      const batches = await (await request.get('/api/batches')).json()
      return batches[0]?.state
    })
    .toBe('printed')
  await page.goto('/#/activity')
  const activityDetails = page.locator('.activity-labels').first()
  await expect(activityDetails.getByRole('region', { name: 'Tape usage' })).not.toBeVisible()
  await activityDetails.locator(':scope > summary').click()
  await expect(
    activityDetails.getByRole('region', { name: 'Tape usage' }).locator('dt'),
  ).toHaveText(['Design', 'Feed', 'Leader', 'Unused'])
  await expect(page.getByRole('status').filter({ hasText: 'minimum cut length' })).toContainText(
    `${unused} mm`,
  )
  await page.setViewportSize({ width: 1440, height: 1000 })
  await activityDetails.scrollIntoViewIfNeeded()
  await page.screenshot({
    path: 'test-results/activity-tape-details-desktop.png',
    animations: 'disabled',
  })
  await activityDetails.locator(':scope > summary').click()
  await expect(activityDetails.getByRole('region', { name: 'Tape usage' })).not.toBeVisible()
  const batches = await (await request.get('/api/batches')).json()
  await page.goto(`/#/batches/${batches[0].id}`)
  await expect(page.getByText(/Estimated cut length 24.5 mm/)).toHaveCount(2)
  await page.locator('.batch-tape-details > summary').click()
  await expect(page.getByRole('region', { name: 'Tape usage' }).locator('dt')).toHaveText([
    'Design',
    'Feed',
    'Leader',
    'Unused',
  ])

  const prepared = await request.post('/api/runs/prepare', {
    data: {
      name: 'Mixed short labels',
      request_key: 'browser-short-labels',
      template: template.id,
      expected_revision: template.revision,
      tape_profile: tape.id,
      csv_text: 'Text\nL1\nA much longer label\n',
      mapping: { text: 'Text' },
      rows: [
        { source_row: 2, copies: 2 },
        { source_row: 3, copies: 1 },
      ],
    },
  })
  expect(prepared.ok(), await prepared.text()).toBeTruthy()
  const run = (await prepared.json()).run
  await page.goto(`/#/runs/${run.id}`)
  await expect(page.getByRole('heading', { name: 'Mixed short labels', exact: true })).toBeVisible()
  const runWarning = page
    .locator('.inset')
    .getByRole('status')
    .filter({ hasText: 'minimum cut length' })
  await expect(runWarning).toContainText('2 labels are below')
  await expect(
    page.locator('.inset').getByRole('status').filter({ hasText: '10 mm template minimum' }),
  ).toBeVisible()
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
  await runWarning.scrollIntoViewIfNeeded()
  await page.screenshot({ path: 'test-results/short-label-csv-mobile.png', animations: 'disabled' })
  await page.setViewportSize({ width: 1440, height: 1000 })
  await runWarning.scrollIntoViewIfNeeded()
  await page.screenshot({
    path: 'test-results/short-label-csv-desktop.png',
    animations: 'disabled',
  })
})
