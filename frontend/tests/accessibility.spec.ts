import { test, expect } from './fixtures'
import type { Locator } from '@playwright/test'

async function expectFocusOutlineInside(control: Locator, container: Locator) {
  await expect(control).toBeFocused()
  const ring = await control.evaluate((element) => {
    const rect = element.getBoundingClientRect()
    const style = getComputedStyle(element)
    const outset = Math.max(0, parseFloat(style.outlineWidth) + parseFloat(style.outlineOffset))
    return {
      left: rect.left - outset,
      right: rect.right + outset,
      top: rect.top - outset,
      bottom: rect.bottom + outset,
    }
  })
  const clip = await container.boundingBox()
  expect(ring.left).toBeGreaterThanOrEqual(clip!.x - 0.5)
  expect(ring.right).toBeLessThanOrEqual(clip!.x + clip!.width + 0.5)
  expect(ring.top).toBeGreaterThanOrEqual(clip!.y - 0.5)
  expect(ring.bottom).toBeLessThanOrEqual(clip!.y + clip!.height + 0.5)
}

for (const viewport of [
  { width: 1280, height: 600 },
  { width: 390, height: 844 },
]) {
  test(`navigation focus outlines fit inside the scroll area at ${viewport.width}px`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport)
    await page.goto('/#/templates')
    await expect(page.getByRole('link', { name: 'Create template', exact: true })).toBeVisible()
    await expect(page.locator('.route-surface')).not.toHaveClass(/page-enter-active/)
    const navigation = page.getByRole('navigation', { name: 'Main navigation' })
    await expect(navigation).toBeVisible()
    for (const link of [
      navigation.getByRole('link').first(),
      navigation.getByRole('link').last(),
    ]) {
      await page.keyboard.press('Tab')
      await link.focus()
      await page.screenshot({
        path: `test-results/navigation-focus-${viewport.width}-${await link.innerText()}.png`,
      })
      await expectFocusOutlineInside(link, navigation)
    }
  })
}

test('inspector focus outlines fit inside the scrolling settings', async ({ page }) => {
  await page.goto('/#/templates/new')
  await page.getByRole('button', { name: 'Add text', exact: true }).click()
  await page.getByRole('tab', { name: 'Style', exact: true }).click()
  await page.keyboard.press('Tab')
  const toggle = page.getByRole('button', { name: 'Typography', exact: true })
  await expectFocusOutlineInside(toggle, page.locator('.editor-property-sections'))
  await page.screenshot({ path: 'test-results/inspector-focus.png' })
})

test('queue disclosure focus outlines stay visible outside the cell content', async ({
  page,
  request,
}) => {
  const [profile] = await (await request.get('/api/tape-profiles')).json()
  expect(
    (
      await request.post('/api/jobs', {
        data: { tape_profile: profile.id, data: { text: 'Keyboard label' } },
      })
    ).ok(),
  ).toBe(true)
  await page.goto('/#/queue')
  await page.getByLabel('Select Keyboard label', { exact: true }).focus()
  await page.keyboard.press('Tab')
  const summary = page.locator('.queue-label-details > summary')
  await expect(summary).toBeFocused()
  const clipping = await summary.evaluate((element) => {
    const rect = element.getBoundingClientRect()
    const style = getComputedStyle(element)
    const outset = parseFloat(style.outlineWidth) + parseFloat(style.outlineOffset)
    const clipped: string[] = []
    for (let parent = element.parentElement; parent; parent = parent.parentElement) {
      const clip = parent.getBoundingClientRect()
      const parentStyle = getComputedStyle(parent)
      const clips = (value: string) => ['auto', 'scroll', 'hidden', 'clip'].includes(value)
      if (
        (clips(parentStyle.overflowX) &&
          (rect.left - outset < clip.left || rect.right + outset > clip.right)) ||
        (clips(parentStyle.overflowY) &&
          (rect.top - outset < clip.top || rect.bottom + outset > clip.bottom))
      )
        clipped.push(parent.className)
    }
    return clipped
  })
  expect(clipping).toEqual([])
  await page.screenshot({ path: 'test-results/queue-disclosure-focus.png' })
})

test('Tab traverses the navigation and reaches page controls in both directions', async ({
  page,
}) => {
  await page.goto('/#/templates')
  await expect(page.getByRole('link', { name: 'Create template', exact: true })).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to content', exact: true })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.locator('.brand-link')).toBeFocused()
  const links = page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link')
  for (const link of await links.all()) {
    await page.keyboard.press('Tab')
    await expect(link).toBeFocused()
  }
  await page.keyboard.press('Tab')
  await expect(page.locator('.account-menu > summary')).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(links.last()).toBeFocused()
  await page.keyboard.press('Tab')
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'New label', exact: true })).toBeFocused()
  const scopes = page.getByRole('group', { name: 'Template visibility', exact: true })
  const controls = [
    ...['All', 'Personal', 'Groups', 'Global'].map((name) =>
      scopes.getByRole('button', { name, exact: true }),
    ),
    page.getByRole('link', { name: 'Create template', exact: true }),
    page.getByRole('searchbox', { name: 'Search templates', exact: true }),
    page.getByRole('combobox', { name: 'Tape width', exact: true }),
  ]
  for (const control of controls) {
    await page.keyboard.press('Tab')
    await expect(control).toBeFocused()
  }
  for (const control of controls.slice(0, -1).reverse()) {
    await page.keyboard.press('Shift+Tab')
    await expect(control).toBeFocused()
  }
  await page.keyboard.press('Shift+Tab')
  await expect(page.getByRole('link', { name: 'New label', exact: true })).toBeFocused()
})

test('the skip link reaches account fields without entering disabled or hidden controls', async ({
  page,
}) => {
  await page.goto('/#/account')
  await expect(page.getByRole('heading', { name: 'Change password', exact: true })).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to content', exact: true })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('#main-content')).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'New label', exact: true })).toBeFocused()
  for (const control of [
    page.getByLabel('Reduced motion', { exact: true }),
    page.getByLabel('Current password', { exact: true }),
    page.getByLabel('New password', { exact: true }),
    page.getByLabel('Confirm new password', { exact: true }),
    page.getByRole('button', { name: 'Change password', exact: true }),
  ]) {
    await page.keyboard.press('Tab')
    await expect(control).toBeFocused()
  }
  await page.keyboard.press('Shift+Tab')
  await expect(page.getByLabel('Confirm new password', { exact: true })).toBeFocused()
})

test('switching authentication forms clears old validation and focuses the username', async ({
  page,
}) => {
  await page.goto('/#/')
  await page.locator('.account-menu > summary').click()
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await page.route('**/api/auth/login', (route) =>
    route.fulfill({ status: 401, json: { detail: 'Invalid username or password.' } }),
  )
  await page.getByLabel('Username', { exact: true }).fill('tester')
  await page.getByLabel('Password', { exact: true }).fill('test-password-123')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveText('Invalid username or password.')
  await page.getByRole('button', { name: 'Create an account', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Create account', exact: true })).toBeVisible()
  await expect(page.getByLabel('Username', { exact: true })).toBeFocused()
  await expect(page.locator('[aria-invalid="true"], .field-error')).toHaveCount(0)
  await page.getByRole('button', { name: 'Back to sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  await expect(page.getByLabel('Username', { exact: true })).toBeFocused()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('navigation stays reachable in short windows and identifies nested pages on mobile', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1024, height: 600 })
  await page.goto('/#/templates/text/edit')
  const navigation = page.getByRole('navigation', { name: 'Main navigation' })
  const templates = navigation.getByRole('link', { name: 'Templates', exact: true })
  await expect(templates).toHaveAttribute('aria-current', 'location')
  const admin = navigation.getByRole('link', { name: 'Administration', exact: true })
  await admin.focus()
  const bounds = await admin.boundingBox()
  expect(bounds!.y).toBeGreaterThanOrEqual(0)
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(600)
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: 'Administration', exact: true })).toBeVisible()
  await expect(admin).toHaveAttribute('aria-current', 'page')

  await page.setViewportSize({ width: 390, height: 812 })
  await page.goto('/#/templates/text/edit')
  await expect(templates).toHaveAttribute('aria-current', 'location')
  await expect
    .poll(async () => {
      const item = await templates.boundingBox()
      const container = await navigation.boundingBox()
      return item!.x >= container!.x && item!.x + item!.width <= container!.x + container!.width
    })
    .toBe(true)
  await templates.click()
  await expect(page.getByRole('heading', { name: 'Templates', exact: true })).toBeVisible()
  await expect(templates).toHaveAttribute('aria-current', 'page')
})

test('primary buttons keep readable contrast in default and hover states', async ({ page }) => {
  await page.goto('/#/profiles')
  await page.getByRole('button', { name: 'Add tape profile', exact: true }).click()
  const save = page.getByRole('button', { name: 'Save tape profile', exact: true })
  const contrast = () =>
    save.evaluate((button) => {
      const style = getComputedStyle(button)
      const luminance = (color: string) => {
        const values = color
          .match(/[\d.]+/g)!
          .slice(0, 3)
          .map(Number)
          .map((channel) => {
            const value = channel / 255
            return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
          })
        return values[0] * 0.2126 + values[1] * 0.7152 + values[2] * 0.0722
      }
      const values = [luminance(style.color), luminance(style.backgroundColor)].sort(
        (a, b) => a - b,
      )
      return (values[1] + 0.05) / (values[0] + 0.05)
    })
  expect(await contrast()).toBeGreaterThanOrEqual(4.5)
  await save.hover()
  await expect.poll(contrast).toBeGreaterThanOrEqual(4.5)
})

test('mobile queue scrolls locally and compact checkbox targets work at their edges', async ({
  page,
  request,
}) => {
  const profile = (await (await request.get('/api/tape-profiles')).json())[0]
  await request.post('/api/jobs', {
    data: { tape_profile: profile.id, data: { text: 'Mobile selection' } },
  })
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/#/queue')
  const checkbox = page.getByRole('checkbox', { name: 'Select Mobile selection', exact: true })
  await expect(checkbox).toBeVisible()
  const target = checkbox.locator('..')
  const box = await target.boundingBox()
  expect(box!.width).toBeGreaterThanOrEqual(44)
  expect(box!.height).toBeGreaterThanOrEqual(44)
  expect(await checkbox.evaluate((el) => el.getBoundingClientRect().width)).toBeCloseTo(17, 3)
  await target.click({ position: { x: 2, y: 2 } })
  await expect(checkbox).toBeChecked()
  const scroll = page.locator('.table-scroll')
  expect(await scroll.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375)
  await scroll.evaluate((el) => (el.scrollLeft = el.scrollWidth))
  await expect.poll(() => scroll.evaluate((el) => el.scrollLeft)).toBeGreaterThan(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375)
  await scroll.evaluate((el) => (el.scrollLeft = 0))
  await checkbox.focus()
  await page.keyboard.press('Space')
  await expect(checkbox).not.toBeChecked()
})

test('failed forms retain inline errors, focus linked summaries, and recover without submitting invalid data', async ({
  page,
}) => {
  let saves = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/api/tape-profiles')) saves++
  })
  await page.goto('/#/profiles')
  await page.getByRole('button', { name: 'Add tape profile', exact: true }).click()
  const name = page.getByLabel('Profile name', { exact: true })
  const threshold = page.getByLabel('Automatic batch threshold', { exact: true })
  await threshold.fill('')
  const save = page.getByRole('button', { name: 'Save tape profile', exact: true })
  await save.click()
  const summary = page.locator('.validation-summary')
  await expect(summary).toBeFocused()
  await expect(summary.getByRole('link')).toHaveCount(2)
  for (const field of [name, threshold]) {
    await expect(field).toHaveAttribute('aria-invalid', 'true')
    const id = await field.getAttribute('aria-describedby')
    await expect(page.locator(`[id="${id}"]`)).not.toBeEmpty()
  }
  expect(saves).toBe(0)
  // An unrelated Vue update must not replace the focused summary.
  await page.getByLabel('Tape color', { exact: true }).evaluate((input: HTMLInputElement) => {
    input.value = '#aaaaaa'
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await expect(summary).toBeFocused()
  await summary.getByRole('link', { name: /^Profile name:/ }).click()
  await expect(name).toBeFocused()
  await name.fill('Accessible profile')
  await expect(name).not.toHaveAttribute('aria-invalid')
  await expect(summary).toHaveCount(0)
  await expect(threshold).toHaveAttribute('aria-invalid', 'true')
  await save.click()
  await expect(threshold).toBeFocused()
  await threshold.fill('50')
  await expect(threshold).not.toHaveAttribute('aria-invalid')
  await save.click()
  await expect(page.getByRole('heading', { name: 'Accessible profile', exact: true })).toBeVisible()
  expect(saves).toBe(1)
})

test('label submission associates server field errors and clears only the edited error', async ({
  page,
}) => {
  await page.route('**/api/jobs', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    await route.fulfill({
      status: 422,
      json: {
        detail: [
          { loc: ['body', 'data', 'text'], msg: 'Choose different label text.' },
          { loc: ['body', 'copies'], msg: 'Choose a different copy count.' },
        ],
      },
    })
  })
  await page.goto('/#/new')
  const text = page.getByLabel('Label text', { exact: true })
  const copies = page.getByLabel('Copies', { exact: true })
  await text.fill('Invalid server value')
  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  await expect(page.locator('.validation-summary')).toBeFocused()
  await expect(page.getByRole('alert')).toHaveCount(1)
  await expect(text).toHaveAttribute('aria-invalid', 'true')
  await expect(copies).toHaveAttribute('aria-invalid', 'true')
  await expect(text).toHaveAccessibleDescription('Choose different label text.')
  await expect(copies).toHaveAccessibleDescription('Choose a different copy count.')
  await text.fill('Corrected text')
  await expect(text).not.toHaveAttribute('aria-invalid')
  await expect(copies).toHaveAttribute('aria-invalid', 'true')
  await expect(text).toBeFocused()
  await copies.fill('2')
  await expect(copies).not.toHaveAttribute('aria-invalid')
})
