import { test, expect } from './fixtures'
import type { Page } from '@playwright/test'

// Simulate only the vendor handshake; use the real worker, API, and database.
async function mockSubscription(page: Page, permission = 'granted') {
  await page.addInitScript((permission) => {
    Object.defineProperty(Notification, 'requestPermission', {
      value: async () => {
        if (!navigator.userActivation.isActive)
          throw new Error('Permission requires a user gesture')
        return permission
      },
    })
    function wrap(value: { endpoint: string; keys: { p256dh: string; auth: string } }) {
      return {
        endpoint: value.endpoint,
        toJSON: () => value,
        unsubscribe: async () => {
          sessionStorage.removeItem('test-push')
          return true
        },
      }
    }
    PushManager.prototype.getSubscription = async function () {
      const value = sessionStorage.getItem('test-push')
      return value ? (wrap(JSON.parse(value)) as unknown as PushSubscription) : null
    }
    PushManager.prototype.subscribe = async function (options) {
      if (!options?.userVisibleOnly || !options.applicationServerKey)
        throw new Error('Missing VAPID options')
      const key = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, true, [
        'deriveBits',
      ])
      const raw = await crypto.subtle.exportKey('raw', key.publicKey)
      const encode = (data: Uint8Array) =>
        btoa(String.fromCharCode(...data))
          .replace(/\+/g, '-')
          .replace(/\//g, '_')
          .replace(/=/g, '')
      const value = {
        endpoint: 'https://fcm.googleapis.com/fcm/send/' + crypto.randomUUID(),
        keys: {
          p256dh: encode(new Uint8Array(raw)),
          auth: encode(crypto.getRandomValues(new Uint8Array(16))),
        },
      }
      sessionStorage.setItem('test-push', JSON.stringify(value))
      return wrap(value) as unknown as PushSubscription
    }
  }, permission)
}

test('enable, scope, test, remove, and sign out revoke this installation', async ({
  page,
  request,
}) => {
  await mockSubscription(page)
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/#/account')
  const push = page.getByRole('region', { name: 'Push notifications', exact: true })
  await push.getByLabel('Device name', { exact: true }).fill('My phone')
  await push.getByRole('button', { name: 'Enable notifications', exact: true }).click()
  await expect(push.getByRole('status')).toHaveText('Notifications enabled.')
  const prefs = push.getByRole('button', { name: 'Notification preferences', exact: true })
  await prefs.click()
  await push.getByRole('checkbox', { name: 'My printed labels', exact: true }).check()
  await push.getByRole('checkbox', { name: 'All printers I can moderate', exact: true }).check()
  await push.getByRole('checkbox', { name: 'Empty cartridges', exact: true }).check()
  await push.getByRole('checkbox', { name: 'Finished batches', exact: true }).check()
  await prefs.click()
  await expect(push.getByRole('checkbox', { name: 'Empty cartridges', exact: true })).toBeHidden()
  await prefs.click()
  await push.getByRole('button', { name: 'Save notification preferences', exact: true }).click()
  await expect(push.getByRole('status')).toHaveText('Notification preferences saved.')
  await expect(prefs).toBeFocused()
  await page.reload()
  await prefs.click()
  await expect(push.getByRole('checkbox', { name: 'Empty cartridges', exact: true })).toBeChecked()
  await expect(push.getByRole('checkbox', { name: 'My printed labels', exact: true })).toBeChecked()
  await expect(push.getByRole('checkbox', { name: 'Finished batches', exact: true })).toBeChecked()
  for (const width of [390, 820]) {
    await page.setViewportSize({ width, height: 1000 })
    await push.scrollIntoViewIfNeeded()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
    await page.screenshot({
      path: `test-results/push-settings-${width}.png`,
      fullPage: true,
      animations: 'disabled',
    })
  }
  await push.getByRole('button', { name: 'Send test notification', exact: true }).click()
  await expect(push.getByRole('status')).toHaveText('Test notification sent.')
  expect((await (await request.get('/api/test/pushes')).json())[0]).toMatchObject({
    path: '/#/account',
    body: 'Push notifications are working.',
  })
  await push.getByRole('button', { name: 'Remove My phone', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(push.getByRole('button', { name: 'Remove My phone', exact: true })).toBeVisible()
  await push.getByRole('button', { name: 'Remove My phone', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Remove device', exact: true }).click()
  await expect(push.getByRole('status')).toHaveText('Device removed.')
  await expect(
    push.getByRole('button', { name: 'Enable notifications', exact: true }),
  ).toBeFocused()
  expect((await (await request.get('/api/auth/push')).json()).devices).toEqual([])
  await push.getByRole('button', { name: 'Enable notifications', exact: true }).click()
  await expect(push.getByRole('status')).toHaveText('Notifications enabled.')
  await page.locator('.account-menu > summary').click()
  await page
    .locator('.account-flyout')
    .getByRole('button', { name: 'Sign out', exact: true })
    .click()
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  const login = await request.post('/api/auth/login', {
    data: { username: 'owner', password: 'browser-owner-password' },
  })
  const session = await login.json()
  expect(
    (
      await (
        await request.get('/api/auth/push', { headers: { 'X-CSRF-Token': session.csrf_token } })
      ).json()
    ).devices,
  ).toEqual([])
  expect(errors).toEqual([])
})

test('denied permission stays recoverable without creating a device', async ({ page, request }) => {
  await mockSubscription(page, 'denied')
  await page.goto('/#/account')
  const push = page.getByRole('region', { name: 'Push notifications', exact: true })
  await push.getByRole('button', { name: 'Enable notifications', exact: true }).click()
  await expect(push.getByRole('alert')).toContainText('The browser denied notification permission.')
  await expect(
    push.getByRole('button', { name: 'Enable notifications', exact: true }),
  ).toBeEnabled()
  expect((await (await request.get('/api/auth/push')).json()).devices).toEqual([])
})

test('an unanswered permission prompt is not reported as a browser block', async ({
  page,
  request,
}) => {
  await mockSubscription(page, 'default')
  await page.goto('/#/account')
  const push = page.getByRole('region', { name: 'Push notifications', exact: true })
  await push.getByRole('button', { name: 'Enable notifications', exact: true }).click()
  await expect(push.getByRole('alert')).toContainText('Notification permission was not granted.')
  await expect(push.getByRole('alert')).not.toContainText('denied')
  expect((await (await request.get('/api/auth/push')).json()).devices).toEqual([])
})

test('existing notification permission does not request permission again', async ({
  page,
  context,
}) => {
  await context.grantPermissions(['notifications'])
  // If a redundant permission request is made, the simulated prompt denies it.
  await mockSubscription(page, 'denied')
  await page.goto('/#/account')
  const push = page.getByRole('region', { name: 'Push notifications', exact: true })
  await push.getByRole('button', { name: 'Enable notifications', exact: true }).click()
  await expect(push.getByRole('status')).toHaveText('Notifications enabled.')
})

test('iPhone browser explains the Home Screen requirement', async ({ page }) => {
  await page.addInitScript(() =>
    Object.defineProperty(navigator, 'userAgent', {
      value: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)',
    }),
  )
  await page.goto('/#/account')
  const push = page.getByRole('region', { name: 'Push notifications', exact: true })
  await expect(push.getByText(/Share → Add to Home Screen/)).toBeVisible()
  await expect(push.getByRole('button', { name: 'Enable notifications', exact: true })).toHaveCount(
    0,
  )
})

test('real worker displays a push offline and restricts notification links to the app', async ({
  page,
  context,
  baseURL,
}) => {
  await context.grantPermissions(['notifications'])
  const cdp = await context.newCDPSession(page)
  let registrationId = ''
  cdp.on('ServiceWorker.workerRegistrationUpdated', ({ registrations }) => {
    registrationId =
      registrations.find((registration) => registration.scopeURL === `${baseURL}/`)
        ?.registrationId || registrationId
  })
  await cdp.send('ServiceWorker.enable')
  await page.goto('/#/account')
  await page.evaluate(() => navigator.serviceWorker.ready.then(() => true))
  await expect.poll(() => registrationId).not.toBe('')
  await context.setOffline(true)
  await cdp.send('ServiceWorker.deliverPushMessage', {
    origin: baseURL!,
    registrationId,
    data: JSON.stringify({
      title: 'Tape empty',
      body: 'Desk printer needs tape',
      path: 'https://attacker.invalid/',
      tag: 'offline-push',
    }),
  })
  await expect
    .poll(() =>
      page.evaluate(async () =>
        (await (await navigator.serviceWorker.ready).getNotifications()).map((notification) => ({
          title: notification.title,
          body: notification.body,
          path: notification.data.path,
        })),
      ),
    )
    .toEqual([{ title: 'Tape empty', body: 'Desk printer needs tape', path: '/#/' }])
  const worker = context.serviceWorkers()[0]!
  const target = await worker.evaluate(async () => {
    const scope = globalThis as unknown as ServiceWorkerGlobalScope
    const notification = (await scope.registration.getNotifications())[0]!
    notification.data.path = '/#/printers?printer=main'
    let opened = ''
    const original = scope.clients.openWindow.bind(scope.clients)
    scope.clients.openWindow = async (url) => {
      opened = String(url)
      return null
    }
    const event = new NotificationEvent('notificationclick', { notification })
    let work: Promise<unknown> = Promise.resolve()
    event.waitUntil = (promise) => {
      work = promise
    }
    scope.dispatchEvent(event)
    await work
    scope.clients.openWindow = original
    return opened
  })
  expect(target).toBe(`${baseURL}/#/printers?printer=main`)
  await cdp.detach()
})
