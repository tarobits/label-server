import { test, expect } from './fixtures'

test('templates save preview tape, display stored WebP cards and allow other print profiles', async ({
  page,
  request,
}) => {
  const tape = await (
    await request.post('/api/tape-profiles', {
      data: {
        name: 'Preview yellow',
        width_mm: 24,
        foreground: '#000000',
        background: '#ffe100',
      },
    })
  ).json()
  const other = await (
    await request.post('/api/tape-profiles', {
      data: {
        name: 'Print blue',
        width_mm: 24,
        foreground: '#0000ff',
        background: '#ffffff',
      },
    })
  ).json()
  const created = await request.post('/api/templates', {
    data: {
      name: 'Saved preview label',
      document: {
        width_mm: 24,
        length_mm: 60,
        fields: [],
        elements: [
          {
            id: 'text',
            kind: 'text',
            x: 2,
            y: 4,
            width: 50,
            height: 14,
            content: 'Stored preview',
          },
        ],
      },
    },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
  const template = await created.json()
  await page.goto(`/#/templates/${template.id}/edit`)
  await page.getByRole('combobox', { name: 'Preview tape', exact: true }).selectOption(tape.id)
  await expect(page.getByText('Unsaved changes', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Save template', exact: true }).click()
  await expect(page.getByText('Revision 2', { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('combobox', { name: 'Preview tape', exact: true })).toHaveValue(
    tape.id,
  )
  const saved = await (await request.get(`/api/templates/${template.id}`)).json()
  expect(saved.document.preview_tape.background).toBe('#ffe100')
  const thumbnail = await request.get(`/api/templates/${template.id}/preview.webp`)
  expect(thumbnail.headers()['content-type']).toBe('image/webp')
  const original = await thumbnail.body()
  expect(original.subarray(8, 12).toString()).toBe('WEBP')
  await page.goto('/#/templates')
  const card = page.locator('article').filter({ hasText: 'Saved preview label' })
  const image = card.getByRole('img', { name: 'Preview of Saved preview label' })
  await expect(image).toBeVisible()
  await expect
    .poll(() => image.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0)
  await expect(image).toHaveAttribute('src', /preview\.webp\?revision=2/)
  await page.screenshot({ path: 'test-results/template-webp-previews.png', fullPage: true })
  await request.put(`/api/tape-profiles/${tape.id}`, {
    data: {
      name: 'Edited yellow profile',
      width_mm: 24,
      foreground: '#ffffff',
      background: '#008000',
    },
  })
  expect(await (await request.get(`/api/templates/${template.id}/preview.webp`)).body()).toEqual(
    original,
  )
  await card.getByRole('button', { name: 'Duplicate template', exact: true }).click()
  await expect(page).toHaveURL(/templates\/[^/]+\/edit/)
  await expect(page.getByRole('combobox', { name: 'Preview tape', exact: true })).toHaveValue(
    tape.id,
  )
  const copyId = page.url().split('/templates/')[1].split('/')[0]
  const copy = await (await request.get(`/api/templates/${copyId}`)).json()
  expect(copy.document.preview_tape).toEqual(saved.document.preview_tape)
  await page.goto(`/#/new?template=${template.id}`)
  await page.getByRole('combobox', { name: 'Tape profile', exact: true }).selectOption(other.id)
  const queued = page.waitForResponse(
    (response) => response.url().endsWith('/api/jobs') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  const result = await queued
  expect(result.ok()).toBeTruthy()
  expect((await result.json()).profile_id).toBe(other.id)
  expect(await (await request.get(`/api/templates/${template.id}/preview.webp`)).body()).toEqual(
    original,
  )
})
