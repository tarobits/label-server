import { test, expect } from './fixtures'

test('a removed template fades from its own grid cell without changing size', async ({
  page,
  request,
}) => {
  for (const name of ['Motion card one', 'Motion card two', 'Motion card three']) {
    expect(
      (
        await request.post('/api/templates', {
          data: {
            name,
            document: { fields: [], elements: [] },
          },
        })
      ).ok(),
    ).toBe(true)
  }
  await page.goto('/#/templates')
  await expect(page.locator('.route-surface')).not.toHaveClass(/page-enter-active/)
  const card = page
    .locator('article')
    .filter({ has: page.getByRole('heading', { name: 'Motion card two', exact: true }) })
  await card.scrollIntoViewIfNeeded()
  const before = (await card.boundingBox())!
  await page.addStyleTag({ content: '.collection-leave-active { transition-duration: 1000ms; }' })
  await card.getByRole('button', { name: 'Archive', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(card).toHaveClass(/collection-leave-active/)
  const during = (await card.boundingBox())!
  // The slight exit scale may change the bounds by a few pixels, never a cell.
  expect(Math.abs(during.x - before.x)).toBeLessThan(8)
  expect(Math.abs(during.y - before.y)).toBeLessThan(8)
  expect(Math.abs(during.width - before.width)).toBeLessThan(12)
  await page.screenshot({ path: 'test-results/card-exit.png' })
  await expect(card).toHaveCount(0)
})

test('navigation keeps the current page while loading, then hands over without a document reload', async ({
  page,
}) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/#/templates')
  await expect(page.getByRole('link', { name: 'Create template', exact: true })).toBeVisible()
  await expect(page.locator('.route-surface')).not.toHaveClass(/page-enter-active/)
  const current = await page.locator('.route-surface').elementHandle()
  await page.evaluate(() => Object.assign(window, { navigationSentinel: 'same document' }))
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/font-assets', async (route) => {
    await gate
    await route.continue()
  })
  await page.getByRole('link', { name: 'Fonts', exact: true }).click()
  await expect(page.getByRole('progressbar', { name: 'Loading page' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Templates', exact: true })).toBeVisible()
  expect(await current!.evaluate((node) => node.isConnected)).toBe(true)
  release()
  await expect(page).toHaveURL(/#\/fonts$/)
  await expect(page.locator('.route-surface')).toHaveClass(/page-enter-active/)
  await expect
    .poll(() => page.locator('.route-surface').evaluate((node) => node.getAnimations().length))
    .toBeGreaterThan(0)
  const frames = await page.locator('.route-surface').evaluate((node) => {
    const animations = node.getAnimations()
    animations.forEach((animation) => {
      animation.pause()
      animation.currentTime = 100
    })
    return animations.flatMap((animation) => (animation.effect as KeyframeEffect).getKeyframes())
  })
  expect(frames.some((frame) => frame.transform && frame.transform !== 'none')).toBe(true)
  await page.screenshot({ path: 'test-results/page-handoff.png' })
  await page
    .locator('.route-surface')
    .evaluate((node) => node.getAnimations().forEach((animation) => animation.finish()))
  await expect(page.locator('.route-surface')).not.toHaveClass(/page-enter-active/)
  expect(
    await page.evaluate(
      () => (window as unknown as { navigationSentinel: string }).navigationSentinel,
    ),
  ).toBe('same document')
  await expect(page.getByRole('progressbar', { name: 'Loading page' })).toHaveCount(0)
  const marker = page.locator('nav[aria-label="Main navigation"] > .motion-indicator')
  const selected = page.getByRole('link', { name: 'Fonts', exact: true })
  await expect
    .poll(async () => {
      const [a, b] = await Promise.all([marker.boundingBox(), selected.boundingBox()])
      return Math.abs(a!.y - b!.y) + Math.abs(a!.width - b!.width)
    })
    .toBeLessThan(1)
  expect(errors).toEqual([])
})

for (const reducedMotion of ['no-preference', 'reduce'] as const) {
  test(`inspector tabs swipe in both directions and preserve fields with ${reducedMotion}`, async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion })
    await page.goto('/#/templates/new')
    await page.getByRole('button', { name: 'Add text', exact: true }).click()
    await page.getByRole('textbox', { name: 'Content', exact: true }).fill('Keep this text')
    const content = await page
      .getByRole('textbox', { name: 'Content', exact: true })
      .elementHandle()
    const tabs = page.getByRole('tablist', { name: 'Element settings' })
    for (const [tab, direction] of [
      ['Style', 1],
      ['Content', -1],
    ] as const) {
      await tabs.getByRole('tab', { name: tab, exact: true }).click()
      const frames = await page.locator('.editor-property-sections').evaluate((node) => {
        const animations = node.getAnimations()
        animations.forEach((animation) => {
          animation.pause()
          animation.currentTime = 70
        })
        return animations.flatMap((animation) =>
          (animation.effect as KeyframeEffect).getKeyframes(),
        )
      })
      expect(frames.length).toBeGreaterThan(0)
      if (reducedMotion === 'reduce') expect(frames.some((frame) => frame.transform)).toBe(false)
      else
        expect(frames).toContainEqual(
          expect.objectContaining({ transform: `translateX(${direction * 24}px)` }),
        )
      await page.screenshot({ path: `test-results/inspector-swipe-${tab}-${reducedMotion}.png` })
      await page
        .locator('.editor-property-sections')
        .evaluate((node) => node.getAnimations().forEach((animation) => animation.finish()))
    }
    expect(await content!.evaluate((node) => node.isConnected)).toBe(true)
    await expect(page.getByRole('textbox', { name: 'Content', exact: true })).toHaveValue(
      'Keep this text',
    )
    await page.setViewportSize({ width: 390, height: 844 })
    await page.locator('.editor-properties').scrollIntoViewIfNeeded()
    await tabs.getByRole('tab', { name: 'Layout', exact: true }).click()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  })
}

test('queue navigation leaves label previews collapsed and does not start label morphs', async ({
  page,
  request,
}) => {
  await page.addInitScript(() => {
    document.startViewTransition = () => {
      throw new Error('Unexpected label morph')
    }
  })
  await page.goto('/#/new')
  await page.getByLabel('Label text', { exact: true }).fill('Ordinary queue arrival')
  await expect(page.getByAltText('Rendered label preview')).toBeVisible()
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  await expect(page).toHaveURL(/#\/queue$/)
  await expect(page.locator('.queue-preview')).toBeVisible()
  await expect(page.locator('.queue-preview[open]')).toHaveCount(0)
  expect(await (await request.get('/api/jobs')).json()).toHaveLength(1)
})

test('a newer navigation wins while another page is loading', async ({ page }) => {
  await page.goto('/#/templates')
  await expect(page.getByRole('link', { name: 'Create template', exact: true })).toBeVisible()
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/font-assets', async (route) => {
    await gate
    await route.continue()
  })
  await page.getByRole('link', { name: 'Fonts', exact: true }).click()
  await expect(page.getByRole('progressbar', { name: 'Loading page' })).toBeVisible()
  await page.getByRole('link', { name: 'Images', exact: true }).click()
  await expect(page).toHaveURL(/#\/images$/)
  release()
  await expect(page.getByRole('heading', { name: 'Image library', exact: true })).toBeVisible()
  await expect(page.locator('.route-surface')).not.toHaveClass(/page-enter-active/)
  await expect(page.getByRole('progressbar', { name: 'Loading page' })).toHaveCount(0)
  await expect(page).toHaveURL(/#\/images$/)
  await page.goBack()
  await expect(page).toHaveURL(/#\/templates$/)
  await expect(page.getByRole('link', { name: 'Create template', exact: true })).toBeVisible()
})

test('selecting the current page cancels a pending handoff', async ({ page }) => {
  await page.goto('/#/templates')
  await expect(page.getByRole('link', { name: 'Create template', exact: true })).toBeVisible()
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/font-assets', async (route) => {
    await gate
    await route.continue()
  })
  await page.getByRole('link', { name: 'Fonts', exact: true }).click()
  await expect(page.getByRole('progressbar', { name: 'Loading page' })).toBeVisible()
  await page.getByRole('link', { name: 'Templates', exact: true }).click()
  await expect(page.getByRole('progressbar', { name: 'Loading page' })).toHaveCount(0)
  release()
  await expect(page).toHaveURL(/#\/templates$/)
  await expect(page.getByRole('link', { name: 'Create template', exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Images', exact: true }).click()
  await expect(page).toHaveURL(/#\/images$/)
  await expect(page.getByRole('heading', { name: 'Image library', exact: true })).toBeVisible()
})

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
  test(`editor disclosure content expands and collapses with ${reducedMotion}`, async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion })
    await page.goto('/#/templates/new')
    await page.getByRole('button', { name: 'Add text', exact: true }).click()
    await page.getByRole('tab', { name: 'Style', exact: true }).click()
    const toggle = page.getByRole('button', { name: 'Spacing & padding', exact: true })
    const section = page.locator('.property-section').filter({ has: toggle })
    const body = section.locator('.disclosure-body')
    await toggle.scrollIntoViewIfNeeded()
    await page.addStyleTag({
      content: '.property-section { --motion-enter: 1000ms; --motion-state: 1000ms; }',
    })
    await toggle.focus()
    await page.keyboard.press('Enter')
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
    const full = await section
      .locator('.disclosure-content')
      .evaluate((el) => el.getBoundingClientRect().height)
    if (reducedMotion === 'no-preference') {
      await expect.poll(() => body.evaluate((el) => el.getAnimations().length)).toBe(1)
      await body.evaluate((el) => {
        const [animation] = el.getAnimations()
        animation.pause()
        animation.currentTime = 200
      })
      const partial = (await body.boundingBox())!.height
      expect(partial).toBeGreaterThan(0)
      expect(partial).toBeLessThan(full)
      await page.screenshot({ path: 'test-results/editor-details-expanding.png' })
      // Focusing a field settles the panel before precision editing starts.
      await page.getByLabel('Left padding (mm)', { exact: true }).focus()
    } else {
      expect(await body.evaluate((el) => el.getAnimations().length)).toBe(0)
    }
    await expect(body).toHaveAttribute('data-expanding', 'false')
    const field = page.getByLabel('Left padding (mm)', { exact: true })
    await field.fill('1.5')
    await toggle.focus()
    await page.keyboard.press('Enter')
    await expect(body).toHaveAttribute('inert', '')
    if (reducedMotion === 'no-preference') {
      await expect.poll(() => body.evaluate((el) => el.getAnimations().length)).toBe(1)
      await body.evaluate((el) => {
        const [animation] = el.getAnimations()
        animation.pause()
        animation.currentTime = 200
      })
      const partial = (await body.boundingBox())!.height
      expect(partial).toBeGreaterThan(0)
      expect(partial).toBeLessThan(full)
      await page.screenshot({ path: 'test-results/editor-details-collapsing.png' })
      // Reopening starts at the currently rendered height rather than jumping.
      await page.keyboard.press('Enter')
      await expect(toggle).toHaveAttribute('aria-expanded', 'true')
      await expect.poll(() => body.evaluate((el) => el.getAnimations().length)).toBe(1)
      const from = await body.evaluate(
        (el) => (el.getAnimations()[0]!.effect as KeyframeEffect).getKeyframes()[0]!.height,
      )
      expect(parseFloat(String(from))).toBeCloseTo(partial, 0)
      await page.emulateMedia({ reducedMotion: 'reduce' })
      await expect(body).toHaveAttribute('data-expanding', 'false')
    } else {
      await expect(body).toBeHidden()
      await page.keyboard.press('Enter')
    }
    await expect(field).toHaveValue('1.5')
    await page.keyboard.press('Enter')
    await expect(body).toBeHidden()
    await expect(toggle).toBeFocused()
  })

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
    // Disclosure motion must also work without native intrinsic-size transitions.
    await page.addStyleTag({ content: 'details::details-content { transition: none !important; }' })
    const details = page.locator('.queue-label-details')
    const summary = details.locator('summary')
    await expect(details).toBeVisible()
    const closed = (await details.boundingBox())!.height
    if (reducedMotion === 'no-preference')
      await page.addStyleTag({
        content: 'details { --motion-state: 1000ms; --motion-enter: 1000ms; }',
      })
    await summary.focus()
    await page.keyboard.press('Enter')
    await expect(details).toHaveAttribute('open', '')
    if (reducedMotion === 'no-preference') {
      await expect
        .poll(() =>
          details.evaluate((element) => {
            const visible = element
              .querySelector('.disclosure-body')!
              .getBoundingClientRect().height
            const full = element
              .querySelector('.disclosure-content')!
              .getBoundingClientRect().height
            return visible > 0 && visible < full
          }),
        )
        .toBe(true)
    }
    await page.evaluate(
      () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))),
    )
    const midway = await details.evaluate((element) => {
      return {
        visible: element.querySelector('.disclosure-body')!.getBoundingClientRect().height,
        full: element.querySelector('.disclosure-content')!.getBoundingClientRect().height,
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
        details.locator('.disclosure-body').evaluate((el) => el.getBoundingClientRect().height),
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
    const expandedHeight = (await details.boundingBox())!.height
    await page.keyboard.press('Enter')
    await expect(summary).toHaveAttribute('aria-expanded', 'false')
    if (reducedMotion === 'no-preference') {
      await expect
        .poll(async () => {
          const height = (await details.boundingBox())!.height
          return height > closed && height < expandedHeight
        })
        .toBe(true)
      await expect(details.locator('.disclosure-body')).toHaveAttribute('inert', '')
      await page.screenshot({ path: 'test-results/details-collapsing.png' })
    }
    await expect(details.locator('.label-details')).toBeHidden()
    await expect(details).not.toHaveAttribute('open')
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
