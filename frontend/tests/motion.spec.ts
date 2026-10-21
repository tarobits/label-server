import { test, expect } from './fixtures'

test('preview edits and destination query changes preserve the form without replaying motion', async ({
  page,
  request,
}) => {
  const printer = await request.post('/api/printers', {
    data: { name: 'Second printer', usb_serial: 'UI-SECOND' },
  })
  expect(printer.ok()).toBeTruthy()
  const second = await printer.json()
  await page.goto('/#/new')
  const text = page.getByLabel('Label text', { exact: true })
  await text.fill('Cable 01')
  const image = page.getByAltText('Rendered label preview')
  await expect(image).toBeVisible()
  await expect.poll(() => image.evaluate((el) => el.getAnimations().length)).toBe(0)
  const original = await image.getAttribute('src')
  const node = await image.elementHandle()
  const form = await text.elementHandle()
  await page
    .getByRole('combobox', { name: 'Print destination', exact: true })
    .selectOption(second.id)
  await expect(page).toHaveURL(new RegExp(`destination=${second.id}`))
  await expect(text).toHaveValue('Cable 01')
  await text.fill('Cable 02')
  await expect(image).not.toHaveAttribute('src', original!)
  expect(await node!.evaluate((el) => el.isConnected)).toBe(true)
  expect(await form!.evaluate((el) => el === document.activeElement)).toBe(true)
  expect(await image.evaluate((el) => el.getAnimations().length)).toBe(0)
  expect(await page.locator('.route-surface').evaluate((el) => el.getAnimations().length)).toBe(0)
})

for (const reducedMotion of ['no-preference', 'reduce'] as const) {
  test(`detail panels support interrupted keyboard toggles with ${reducedMotion}`, async ({
    page,
    request,
  }) => {
    await page.emulateMedia({ reducedMotion })
    const [profile] = await (await request.get('/api/tape-profiles')).json()
    expect(
      (
        await request.post('/api/jobs', {
          data: { tape_profile: profile.id, data: { text: 'Disclosure motion' } },
        })
      ).ok(),
    ).toBe(true)
    await page.goto('/#/queue')
    const details = page.locator('.queue-label-details')
    const summary = details.locator('summary')
    await expect(details).toBeVisible()
    const closed = (await details.boundingBox())!.height
    if (reducedMotion === 'no-preference')
      await page.addStyleTag({
        content: 'details { --motion-state: 1000ms; --motion-exit: 1000ms; }',
      })
    await summary.focus()
    await page.keyboard.press('Enter')
    await expect(details).toHaveAttribute('open', '')
    await page.evaluate(
      () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))),
    )
    const midway = await details.evaluate((element) => {
      return {
        visible: parseFloat(getComputedStyle(element, '::details-content').blockSize),
        full: element.querySelector('.label-details')!.getBoundingClientRect().height,
      }
    })
    if (reducedMotion === 'no-preference') {
      expect(midway.visible).toBeGreaterThan(0)
      expect(midway.visible).toBeLessThan(midway.full)
      await page.screenshot({ path: 'test-results/details-expanding.png' })
    } else {
      expect(midway.visible).toBeCloseTo(midway.full, 0)
    }
    // Reverse a partly opened panel, then reopen before its exit finishes.
    await page.keyboard.press('Enter')
    await page.keyboard.press('Enter')
    await expect(details).toHaveAttribute('open', '')
    await expect
      .poll(() =>
        details.evaluate((el) => parseFloat(getComputedStyle(el, '::details-content').blockSize)),
      )
      .toBeCloseTo(midway.full, 0)
    expect((await details.boundingBox())!.height).toBeGreaterThan(closed)
    await expect(details.locator('.label-details')).toContainText('owner')
    await page.setViewportSize({ width: 390, height: 844 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
    await page.screenshot({
      path: `test-results/details-mobile-${reducedMotion}.png`,
      animations: 'disabled',
    })
    await page.keyboard.press('Enter')
    await expect(details.locator('.label-details')).toBeHidden()
    await expect(summary).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(page.locator('.queue-preview > summary')).toBeFocused()
  })

  test(`mobile motion preserves keyboard dialog behavior with ${reducedMotion}`, async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion })
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/#/admin?section=roles')
    const create = page.getByRole('button', { name: 'New role', exact: true })
    await create.focus()
    await page.keyboard.press('Enter')
    const dialog = page.getByRole('dialog', { name: 'New role', exact: true })
    const name = dialog.getByLabel('Role name', { exact: true })
    await expect(name).toBeFocused()
    await expect(dialog).toHaveCSS(
      'animation-name',
      reducedMotion === 'reduce' ? 'feedback-arrive' : 'dialog-arrive',
    )
    expect(await dialog.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true)
    await name.fill('Draft role')
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
    await expect(create).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(name).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(create).toBeFocused()
    await page.getByRole('link', { name: 'New label', exact: true }).click()
    if (reducedMotion === 'reduce')
      await page.addStyleTag({
        content: '.label-stage > .raster-preview { animation-play-state: paused; }',
      })
    await page.getByLabel('Label text', { exact: true }).fill('Mobile cable')
    const image = page.getByAltText('Rendered label preview')
    await expect(image).toBeVisible()
    await expect(image).toHaveCSS(
      'animation-name',
      reducedMotion === 'reduce' ? 'feedback-arrive' : 'label-feed',
    )
    if (reducedMotion === 'reduce') {
      const frames = await image.evaluate((el) =>
        el.getAnimations().flatMap((active) => (active.effect as KeyframeEffect).getKeyframes()),
      )
      expect(frames.length).toBeGreaterThan(0)
      expect(frames.some((frame) => frame.transform || frame.clipPath)).toBe(false)
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
    await page.screenshot({
      path: `test-results/motion-mobile-${reducedMotion}.png`,
      fullPage: true,
      animations: 'disabled',
    })
  })
}
