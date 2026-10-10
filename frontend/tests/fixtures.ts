import { test as base, expect } from '@playwright/test'
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { createServer } from 'node:net'
import { delimiter, resolve } from 'node:path'

export { expect }
export const test = base.extend<{ seed: void }>({
  request: async ({ playwright, baseURL }, use) => {
    const login = await playwright.request.newContext({ baseURL })
    const response = await login.post('/api/auth/login', {
      data: { username: 'owner', password: 'browser-owner-password' },
    })
    expect(response.ok()).toBeTruthy()
    const session = await response.json()
    const request = await playwright.request.newContext({
      baseURL,
      storageState: await login.storageState(),
      extraHTTPHeaders: { 'X-CSRF-Token': session.csrf_token },
    })
    await login.dispose()
    await use(request)
    await request.dispose()
  },
  storageState: async ({ request }, use) => {
    await use(await request.storageState())
  },
  extraHTTPHeaders: async ({ request }, use) => {
    const session = await (await request.get('/api/auth/session')).json()
    await use({ 'X-CSRF-Token': session.csrf_token })
  },
  baseURL: async ({}, use) => {
    const listener = createServer()
    listener.listen(0, '127.0.0.1')
    await once(listener, 'listening')
    const address = listener.address()
    if (!address || typeof address === 'string') throw new Error('No test port')
    const port = address.port
    await new Promise<void>((done) => listener.close(() => done()))
    const server = spawn(resolve('../.venv/bin/python'), [resolve('../tests/ui_server.py')], {
      cwd: resolve('..'),
      env: {
        ...process.env,
        LABEL_UI_PORT: String(port),
        // Exercise this checkout even if the virtualenv contains an older installed package.
        PYTHONPATH: [resolve('..'), process.env.PYTHONPATH].filter(Boolean).join(delimiter),
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    let output = ''
    server.stdout.on('data', (data) => {
      output += data
    })
    server.stderr.on('data', (data) => {
      output += data
    })
    const url = `http://127.0.0.1:${port}`
    try {
      await expect
        .poll(
          async () => {
            if (server.exitCode !== null) throw new Error(output)
            return fetch(url)
              .then((r) => r.ok)
              .catch(() => false)
          },
          { timeout: 30000 },
        )
        .toBe(true)
      await use(url)
    } finally {
      if (server.exitCode === null) {
        const exited = once(server, 'exit')
        server.kill('SIGTERM')
        await exited
      }
    }
  },
  seed: [
    async ({ request }, use, info) => {
      if (!info.tags.includes('@empty-fleet')) {
        const printer = await request.post('/api/printers', {
          data: { name: 'Desk printer', usb_serial: 'UI-DESK' },
        })
        expect(printer.ok()).toBeTruthy()
        const profile = await (
          await request.post('/api/tape-profiles', {
            data: { name: 'Black on Yellow 24 mm', width_mm: 24, auto_print_threshold: 1000 },
          })
        ).json()
        const cartridge = await (
          await request.post('/api/cartridges', {
            data: { profile_id: profile.id, name: 'Yellow cassette 1', nominal_length_mm: 8000 },
          })
        ).json()
        expect(
          (
            await request.put('/api/printer/active-tape', { data: { cartridge_id: cartridge.id } })
          ).ok(),
        ).toBeTruthy()
      }
      await use()
    },
    { auto: true },
  ],
})
