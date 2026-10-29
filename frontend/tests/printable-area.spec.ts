import { test, expect } from './fixtures'

test('changing 24 mm to 12 mm keeps unclipped text warnings clear and the guide contrasting', async ({
  page,
  request,
}) => {
  const [wide] = await (await request.get('/api/tape-profiles')).json()
  const narrow = await (
    await request.post('/api/tape-profiles', {
      data: {
        name: 'White on dark red',
        width_mm: 12,
        foreground: '#ffffff',
        background: '#800020',
      },
    })
  ).json()
  const saved = await (
    await request.post('/api/templates', {
      data: {
        name: 'Narrowed caption',
        document: {
          width_mm: 24,
          length_mm: 60,
          out_of_bounds: 'clip',
          elements: [
            {
              id: 'caption',
              kind: 'text',
              x: 1,
              y: 1,
              width: 30,
              height: 11,
              content: 'Readable caption',
            },
          ],
        },
      },
    })
  ).json()
  await page.goto(`/#/templates/${saved.id}/edit`)
  const guide = page.locator('.printable-border')
  await expect(guide).toHaveAttribute('stroke', '#000000')
  const response = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/preview') &&
      response.request().postDataJSON().document?.width_mm === 12,
  )
  await page.getByRole('combobox', { name: 'Tape profile', exact: true }).selectOption(narrow.id)
  const preview = await (await response).json()
  expect(preview.warnings).toEqual([])
  await expect(guide).toHaveAttribute('stroke', '#ffffff')
  await expect(page.getByText('Device raster preview', { exact: false })).toBeVisible()
  await expect(page.locator('.alert.warning')).toHaveCount(0)
  const clip = preview.svg.match(
    /<clipPath id="printable"><rect x="[^"]+" y="([^"]+)" width="[^"]+" height="([^"]+)"/,
  )
  expect(Number(await guide.getAttribute('y'))).toBeCloseTo(Number(clip[1]), 8)
  expect(Number(await guide.getAttribute('height'))).toBeCloseTo(Number(clip[2]), 8)
  await page.screenshot({
    path: 'test-results/printable-border-dark-red-desktop.png',
    animations: 'disabled',
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.locator('.editor-canvas').scrollIntoViewIfNeeded()
  await page.screenshot({
    path: 'test-results/printable-border-dark-red-mobile.png',
    animations: 'disabled',
  })
  await page.getByRole('combobox', { name: 'Tape profile', exact: true }).selectOption(wide.id)
  await expect(guide).toHaveAttribute('stroke', '#000000')
  await page.getByRole('combobox', { name: 'Tape profile', exact: true }).selectOption(narrow.id)
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Save template', exact: true })).toBeDisabled()
  const cartridge = await (
    await request.post('/api/cartridges', {
      data: { profile_id: narrow.id, name: 'Narrow cassette', nominal_length_mm: 8000 },
    })
  ).json()
  await request.put('/api/printer/mock', { data: { tape_width_mm: 12, connected: true } })
  expect(
    (await request.put('/api/printer/active-tape', { data: { cartridge_id: cartridge.id } })).ok(),
  ).toBeTruthy()
  const queued = await request.post('/api/jobs', {
    data: { template: saved.id, tape_profile: narrow.id, data: {} },
  })
  expect(queued.status(), await queued.text()).toBe(201)
  const job = await queued.json()
  expect((await request.post('/api/queue/print')).status()).toBe(202)
  await expect
    .poll(async () => (await (await request.get(`/api/jobs/${job.id}`)).json()).status)
    .toBe('printed')
})
