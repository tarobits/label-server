import { test, expect } from './fixtures'

for (const width of [1280, 390]) {
  test(`account clicks work without browser pointer focus at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 })
    await page.goto('/#/templates')
    // Safari can blur the old control without focusing the clicked button.
    await page.evaluate(() => {
      document.addEventListener(
        'mousedown',
        (event) => {
          if (
            event.target instanceof Element &&
            event.target.closest('.account-menu, .account-flyout')
          ) {
            event.preventDefault()
            if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
          }
        },
        true,
      )
    })
    const trigger = page.locator('.account-menu > summary')
    const flyout = page.getByRole('group', { name: 'Account', exact: true })
    const settings = page.getByRole('link', { name: 'Account settings', exact: true })
    const signOut = page.getByRole('button', { name: 'Sign out', exact: true })
    await trigger.focus()
    await page.keyboard.press('Enter')
    await expect(settings).toBeFocused()
    await trigger.click()
    await expect(trigger).toHaveAttribute('aria-expanded', 'false')
    await expect(flyout).toHaveCount(0)
    await trigger.click()
    await expect(flyout).toBeVisible()
    await settings.focus()
    let attempts = 0
    await page.route('**/api/auth/logout', async (route) => {
      attempts++
      await route.abort('failed')
    })
    await signOut.click()
    await expect.poll(() => attempts).toBe(1)
    await expect(page.getByRole('alert')).toHaveText(/Could not sign out/)
    await expect(flyout).toBeVisible()
    await settings.click()
    await expect(page).toHaveURL(/#\/account$/)
    await expect(flyout).toHaveCount(0)
    await trigger.click()
    await expect(flyout).toBeVisible()
    await page.getByRole('heading', { name: 'Change password', exact: true }).click()
    await expect(flyout).toHaveCount(0)
  })
}

test('Tab closes the account flyout and the trigger can reopen it in either direction', async ({
  page,
}) => {
  await page.goto('/#/templates')
  const trigger = page.locator('.account-menu > summary')
  const flyout = page.getByRole('group', { name: 'Account', exact: true })
  const settings = page.getByRole('link', { name: 'Account settings', exact: true })
  const signOut = page.getByRole('button', { name: 'Sign out', exact: true })
  const next = page.getByRole('link', { name: 'New label', exact: true })
  await trigger.focus()
  await page.keyboard.press('Enter')
  await expect(settings).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(signOut).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(settings).toBeFocused()
  await page.keyboard.press('Tab')
  await page.keyboard.press('Tab')
  await expect(next).toBeFocused()
  await expect(trigger).toHaveAttribute('aria-expanded', 'false')
  await expect(flyout).toHaveCount(0)
  await page.keyboard.press('Shift+Tab')
  await expect(trigger).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(settings).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(trigger).toBeFocused()
  await expect(flyout).toHaveCount(0)
  await page.keyboard.press('Enter')
  await expect(settings).toBeFocused()
  // Returning to an open trigger must still allow Tab to enter the flyout.
  await trigger.focus()
  await page.keyboard.press('Tab')
  await expect(settings).toBeFocused()
  // Focus leaving by another route closes it too, without pulling focus back.
  await next.focus()
  await expect(next).toBeFocused()
  await expect(flyout).toHaveCount(0)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.keyboard.press('Shift+Tab')
  await expect(trigger).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(settings).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(signOut).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(next).toBeFocused()
  await expect(flyout).toHaveCount(0)
  await page.keyboard.press('Shift+Tab')
  await page.keyboard.press('Enter')
  await expect(settings).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(trigger).toBeFocused()
  await expect(flyout).toHaveCount(0)
})

for (const reducedMotion of ['no-preference', 'reduce'] as const) {
  test(`account flyout preserves navigation and animates with ${reducedMotion}`, async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion })
    await page.goto('/#/')
    // Keep the brief reduced-motion fade observable across browser/tool round trips.
    await page.addStyleTag({
      content: '.account-flyout-enter-active { transition-duration: 1000ms !important; }',
    })
    const account = page.locator('.account-menu'),
      summary = account.locator('summary')
    const navigation = page.getByRole('navigation', { name: 'Main navigation' })
    const before = (await navigation.boundingBox())!
    await summary.focus()
    await page.keyboard.press('Enter')
    const flyout = page.getByRole('group', { name: 'Account', exact: true })
    const settings = flyout.getByRole('link', { name: 'Account settings', exact: true })
    await expect(settings).toBeFocused()
    await expect(flyout).toBeVisible()
    const after = (await navigation.boundingBox())!
    expect(after.height).toBeCloseTo(before.height, 1)
    await expect
      .poll(() => flyout.evaluate((element) => element.getAnimations().length))
      .toBeGreaterThan(0)
    const frames = await flyout.evaluate((element) => {
      const animations = element.getAnimations()
      animations.forEach((animation) => {
        animation.pause()
        animation.currentTime = 80
      })
      return animations.flatMap((animation) => (animation.effect as KeyframeEffect).getKeyframes())
    })
    expect(frames.some((frame) => frame.transform && frame.transform !== 'none')).toBe(
      reducedMotion === 'no-preference',
    )
    await page.screenshot({ path: `test-results/account-flyout-midpoint-${reducedMotion}.png` })
    await flyout.evaluate((element) =>
      element.getAnimations().forEach((animation) => animation.finish()),
    )
    expect((await flyout.boundingBox())!.x).toBeGreaterThanOrEqual(
      (await page.locator('.sidebar').boundingBox())!.width,
    )
    await page.screenshot({
      path: 'test-results/account-flyout-desktop.png',
      animations: 'disabled',
    })
    if (reducedMotion === 'no-preference')
      await page.addStyleTag({ content: '.account-flyout { --motion-exit: 600ms; }' })
    await page.keyboard.press('Escape')
    if (reducedMotion === 'no-preference') {
      await expect(flyout).toHaveClass(/account-flyout-leave-active/)
      await expect
        .poll(() => flyout.evaluate((element) => element.getAnimations().length))
        .toBeGreaterThan(0)
      await flyout.evaluate((element) =>
        element.getAnimations().forEach((animation) => {
          animation.pause()
          animation.currentTime = 80
        }),
      )
      await page.screenshot({ path: 'test-results/account-flyout-exit.png' })
      await flyout.evaluate((element) =>
        element.getAnimations().forEach((animation) => animation.finish()),
      )
    }
    await expect(summary).toBeFocused()
    await expect(flyout).toHaveCount(0)
    await summary.click()
    await summary.click()
    await summary.click()
    await expect(flyout).not.toHaveAttribute('inert')
    await page.getByRole('link', { name: 'Templates', exact: true }).click()
    await expect(page).toHaveURL(/#\/templates$/)
    await expect(flyout).toHaveCount(0)
    await page.setViewportSize({ width: 390, height: 844 })
    await summary.click()
    await expect(flyout).toBeInViewport()
    const navBounds = (await navigation.boundingBox())!
    const panelBounds = (await flyout.boundingBox())!
    expect(panelBounds.y).toBeGreaterThanOrEqual(navBounds.y + navBounds.height)
    await page.screenshot({
      path: 'test-results/account-flyout-mobile.png',
      animations: 'disabled',
    })
    await settings.click()
    await expect(page).toHaveURL(/#\/account$/)
    await expect(page.getByRole('heading', { name: 'Change password', exact: true })).toBeVisible()
    await expect(page.getByLabel('Language', { exact: true })).toBeDisabled()
    await expect(page.getByLabel('Language', { exact: true })).toHaveValue('browser')
    await expect(page.getByLabel('Reduced motion', { exact: true })).toHaveValue('browser')
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
    await page.screenshot({
      path: 'test-results/account-settings-mobile.png',
      fullPage: true,
      animations: 'disabled',
    })
  })
}

test('motion overrides apply to CSS and JavaScript, persist, and can follow live browser changes', async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.goto('/#/account')
  const account = page.locator('.account-menu')
  const preference = page.getByLabel('Reduced motion', { exact: true })
  await preference.selectOption('on')
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'reduce')
  await expect(page.locator('html')).toHaveCSS('--motion-enter', /^(?:100ms|0?\.1s)$/)
  await expect(account.locator('.account-chevron')).toHaveCSS('transition-duration', '0s')
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'reduce')
  await expect(preference).toHaveValue('on')
  await preference.selectOption('off')
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'full')
  await expect(page.locator('html')).toHaveCSS('--motion-enter', /^(?:240ms|0?\.24s)$/)
  await page.goto('/#/templates/text/edit')
  await page.getByRole('button', { name: '1. text', exact: true }).click()
  const tabs = page.getByRole('tablist', { name: 'Element settings' })
  await tabs.getByRole('tab', { name: 'Style', exact: true }).click()
  const full = await page
    .locator('.editor-property-sections')
    .evaluate((element) =>
      element
        .getAnimations()
        .flatMap((animation) => (animation.effect as KeyframeEffect).getKeyframes()),
    )
  expect(full.some((frame) => frame.transform)).toBe(true)
  await page.goto('/#/account')
  await preference.selectOption('browser')
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'reduce')
  await expect(page.locator('.property-expand-enter-active')).toHaveCount(0)
  await page.goto('/#/templates/text/edit')
  await page.getByRole('button', { name: '1. text', exact: true }).click()
  await tabs.getByRole('tab', { name: 'Style', exact: true }).click()
  await tabs.getByRole('tab', { name: 'Content', exact: true }).click()
  const reduced = await page
    .locator('.editor-property-sections')
    .evaluate((element) =>
      element
        .getAnimations()
        .flatMap((animation) => (animation.effect as KeyframeEffect).getKeyframes()),
    )
  expect(reduced.length).toBeGreaterThan(0)
  expect(reduced.some((frame) => frame.transform)).toBe(false)
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'full')
})

test('motion preferences survive blocked storage and synchronize between tabs', async ({
  page,
  context,
}) => {
  await page.goto('/#/account')
  const second = await context.newPage()
  await second.goto('/#/')
  await page.getByLabel('Reduced motion', { exact: true }).selectOption('on')
  await expect(second.locator('html')).toHaveAttribute('data-motion', 'reduce')
  await second.close()
  await page.evaluate(() => {
    Storage.prototype.setItem = () => {
      throw new DOMException('Blocked', 'SecurityError')
    }
  })
  await page.getByLabel('Reduced motion', { exact: true }).selectOption('off')
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'full')
  await page.getByLabel('Reduced motion', { exact: true }).selectOption('browser')
  await expect(page.getByLabel('Reduced motion', { exact: true })).toHaveValue('browser')
})

test('failed sign-out keeps the account menu usable and successful sign-out clears the workspace', async ({
  page,
}) => {
  await page.goto('/#/')
  await page.locator('.account-menu > summary').focus()
  await page.keyboard.press('Enter')
  await page.keyboard.press('Tab')
  const signOut = page.getByRole('button', { name: 'Sign out', exact: true })
  await expect(signOut).toBeFocused()
  let release!: () => void
  let attempts = 0
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  page.on('request', (request) => {
    if (request.url().endsWith('/api/auth/logout')) attempts++
  })
  await page.route(
    '**/api/auth/logout',
    async (route) => {
      await gate
      await route.abort('failed')
    },
    { times: 1 },
  )
  await page.keyboard.press('Enter')
  await expect(signOut).toHaveAttribute('aria-disabled', 'true')
  await expect(signOut).toBeFocused()
  await page.keyboard.press('Enter')
  expect(attempts).toBe(1)
  release()
  await expect(page.getByRole('alert')).toHaveText(/Could not sign out/)
  await expect(signOut).toBeEnabled()
  await expect(signOut).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  await expect(page.locator('.account-menu')).toHaveCount(0)
})

test('account password form validates confirmation, recovers from errors, and changes the real password', async ({
  page,
  playwright,
  baseURL,
}) => {
  const errors: string[] = []
  page.on('pageerror', (issue) => errors.push(issue.message))
  await page.goto('/#/account')
  const current = page.getByLabel('Current password', { exact: true })
  const next = page.getByLabel('New password', { exact: true })
  const confirm = page.getByLabel('Confirm new password', { exact: true })
  const save = page.getByRole('button', { name: 'Change password', exact: true })
  await current.fill('incorrect current password')
  await next.fill('a replacement browser password')
  await confirm.fill('a mismatching browser password')
  await save.click()
  await expect(confirm).toHaveAttribute('aria-invalid', 'true')
  await confirm.fill('a replacement browser password')
  await save.click()
  await expect(current).toHaveAttribute('aria-invalid', 'true')
  await expect(page.locator('.field-error')).toHaveText('Current password is incorrect.')
  await expect(next).toHaveValue('a replacement browser password')
  await current.fill('browser-owner-password')
  await page.route('**/api/auth/password', (route) => route.abort('failed'), { times: 1 })
  await save.click()
  await expect(page.getByRole('alert')).toContainText('Cannot reach the server')
  await expect(next).toHaveValue('a replacement browser password')
  await save.click()
  await expect(page.getByRole('status')).toHaveText('Password changed. Other sessions signed out.')
  await expect(current).toHaveValue('')
  await expect(next).toHaveValue('')
  await expect(confirm).toHaveValue('')
  await expect(
    page.locator('[aria-invalid="true"], .field-error, .validation-summary'),
  ).toHaveCount(0)
  const fresh = await playwright.request.newContext({ baseURL })
  expect(
    (
      await fresh.post('/api/auth/login', {
        data: { username: 'owner', password: 'browser-owner-password' },
      })
    ).status(),
  ).toBe(401)
  expect(
    (
      await fresh.post('/api/auth/login', {
        data: { username: 'owner', password: 'a replacement browser password' },
      })
    ).ok(),
  ).toBe(true)
  await fresh.dispose()
  await page.screenshot({
    path: 'test-results/account-settings-desktop.png',
    fullPage: true,
    animations: 'disabled',
  })
  expect(errors).toEqual([])
})
