import { test, expect } from './fixtures'

for (const width of [402, 1280]) {
  test(`navigation selection follows live badges at ${width}px`, async ({
    page,
    request,
  }, info) => {
    test.setTimeout(45000)
    await page.setViewportSize({ width, height: 874 })
    await page.goto('/#/requests')
    const navigation = page.getByRole('navigation', { name: 'Main navigation' })
    const selected = navigation.locator('a.selected')
    await expect(selected).toContainText('Print requests')
    const aligned = async () => {
      const menu = navigation.getByRole('button', { name: 'Menu', exact: true })
      if ((await menu.isVisible()) && (await menu.getAttribute('aria-expanded')) !== 'true') {
        await menu.click()
      }
      await expect(selected).toBeVisible()
      await expect
        .poll(() =>
          navigation.evaluate((nav) => {
            const link = nav.querySelector('a.selected')!.getBoundingClientRect()
            const marker = nav.querySelector('.motion-indicator')!.getBoundingClientRect()
            return Math.max(
              Math.abs(link.x - marker.x),
              Math.abs(link.y - marker.y),
              Math.abs(link.width - marker.width),
              Math.abs(link.height - marker.height),
            )
          }),
        )
        .toBeLessThan(1)
    }
    await aligned()
    const [printer] = await (await request.get('/api/printers')).json()
    const [profile] = await (await request.get('/api/tape-profiles')).json()
    const input = {
      destination_id: printer.id,
      tape_profile: profile.id,
      data: { text: 'Live badge' },
    }
    const created = await request.post('/api/requests', { data: { kind: 'job', input } })
    expect(created.ok()).toBeTruthy()
    expect((await request.post('/api/jobs', { data: input })).ok()).toBeTruthy()
    await expect(selected.locator('.nav-count')).toHaveText('1', { timeout: 18000 })
    await expect(navigation.locator('a[href="#/queue"] .nav-count')).toHaveText('1')
    await aligned()
    await selected.scrollIntoViewIfNeeded()
    await aligned()
    await navigation.screenshot({
      path: `test-results/request-navigation-${info.project.name}-${width}.png`,
    })
    if (width === 402) {
      await page.setViewportSize({ width: 820, height: 402 })
      await aligned()
      await page.setViewportSize({ width: 402, height: 874 })
      await aligned()
    }
    const id = (await created.json()).id
    expect(
      (
        await request.post(`/api/requests/${id}/reject`, {
          data: { reason: 'Layout check complete' },
        })
      ).ok(),
    ).toBeTruthy()
    await expect(selected.locator('.nav-count')).toHaveCount(0, { timeout: 18000 })
    await aligned()
    await navigation.locator('a[href="#/templates"]').click()
    await expect(selected).toContainText('Templates')
    await aligned()
    await navigation.locator('a[href="#/requests"]').click()
    await expect(selected).toContainText('Print requests')
    await aligned()
  })
}

for (const length of [12, 96]) {
  test(`request preview preserves physical proportions for ${length}mm labels`, async ({
    page,
    request,
  }, info) => {
    const [printer] = await (await request.get('/api/printers')).json()
    const [profile] = await (await request.get('/api/tape-profiles')).json()
    const templateResponse = await request.post('/api/templates', {
      data: {
        name: 'Physical preview proportions',
        document: {
          width_mm: 24,
          length_mm: length,
          auto_length: false,
          print_resolution: 'high',
          elements: [{ id: 'square', kind: 'rectangle', x: 2, y: 6, width: 8, height: 8 }],
        },
      },
    })
    expect(templateResponse.ok(), await templateResponse.text()).toBeTruthy()
    const template = await templateResponse.json()
    const response = await request.post('/api/requests', {
      data: {
        kind: 'job',
        input: {
          template: template.id,
          destination_id: printer.id,
          tape_profile: profile.id,
          data: {},
        },
      },
    })
    expect(response.ok(), await response.text()).toBeTruthy()
    const saved = await response.json()
    await page.goto(`/#/requests/${saved.id}`)
    const image = page.getByRole('img', { name: 'Requested label 1' })
    await expect
      .poll(() => image.evaluate((img: HTMLImageElement) => img.naturalWidth))
      .toBeGreaterThan(0)
    for (const viewport of [
      { width: 402, height: 874 },
      { width: 820, height: 402 },
      { width: 1280, height: 900 },
    ]) {
      await page.setViewportSize(viewport)
      await expect(image).toHaveCSS('object-fit', 'fill')
      await expect
        .poll(async () => {
          const box = (await image.boundingBox())!
          return Math.abs(
            box.width / box.height - saved.labels[0].length_mm / saved.labels[0].width_mm,
          )
        })
        .toBeLessThan(0.01)
      expect((await image.boundingBox())!.height).toBeLessThanOrEqual(320)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
      if (viewport.width === 402) {
        await expect(page.locator('.route-surface')).toHaveCSS('opacity', '1')
        await page.screenshot({
          path: `test-results/request-preview-${info.project.name}-${length}.png`,
          fullPage: true,
          animations: 'disabled',
        })
      }
    }
  })
}
