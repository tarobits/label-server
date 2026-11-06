import { createHash } from 'node:crypto'
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { test as base, expect } from './fixtures'
import type { Page } from '@playwright/test'

// Each test serves its own copy of the production build. Updating the shell and
// its precache revision exercises a real waiting worker, without mocking the
// service-worker APIs or overwriting the developer's build.
const test = base.extend({
  frontendDist: async ({}, use) => {
    const directory = mkdtempSync(join(tmpdir(), 'label-room-pwa-update-'))
    cpSync(resolve('dist'), directory, { recursive: true })
    try {
      await use(directory)
    } finally {
      rmSync(directory, { recursive: true, force: true })
    }
  },
})

async function publishUpdate(page: Page, directory: string, version: string) {
  const indexPath = join(directory, 'index.html')
  const html = readFileSync(indexPath, 'utf8')
    .replace(/(<meta name="app-build" content=")[^"]+/, `$1test-${version}`)
    .replace(/<html[^>]*>/, `<html lang="en" data-test-build="${version}">`)
  const revision = createHash('md5').update(html).digest('hex')
  writeFileSync(indexPath, html)
  const workerPath = join(directory, 'sw.js')
  const previous = readFileSync(workerPath, 'utf8')
  const next = previous.replace(
    /\{"revision":"[^"]+","url":"index.html"\}/,
    JSON.stringify({ revision, url: 'index.html' }),
  )
  expect(next).not.toBe(previous)
  writeFileSync(workerPath, next)
  await page.evaluate(async () => {
    const registration = await navigator.serviceWorker.ready
    await registration.update()
  })
  await expect(page.getByRole('status', { name: 'App update', exact: true })).toBeVisible()
}

test('updates can be deferred and a newer build is offered again', async ({
  page,
  request,
  frontendDist,
}) => {
  await page.goto('/')
  await page.evaluate(() => navigator.serviceWorker.ready.then(() => undefined))
  await page.reload()
  await publishUpdate(page, frontendDist, 'second')
  const notice = page.getByRole('status', { name: 'App update', exact: true })
  await expect(notice).toHaveCSS('animation-name', 'feedback-arrive')
  await notice.getByRole('button', { name: 'Later' }).click()
  await expect(notice).not.toBeVisible()
  expect(await page.evaluate(() => document.documentElement.dataset.testBuild)).toBeUndefined()
  expect(await page.evaluate(async () => !!(await navigator.serviceWorker.ready).waiting)).toBe(
    true,
  )
  await publishUpdate(page, frontendDist, 'third')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: 'test-results/pwa-update-phone.png', animations: 'disabled' })
  expect((await request.post('/api/test/outage', { data: { status: 502 } })).ok()).toBe(true)
  await notice.getByRole('button', { name: 'Reload', exact: true }).click()
  const unavailable = page.getByRole('dialog', { name: 'Server unavailable' })
  await expect(unavailable).toBeVisible()
  expect(await page.evaluate(async () => !!(await navigator.serviceWorker.ready).waiting)).toBe(
    true,
  )
  expect((await request.post('/api/test/outage', { data: { status: null } })).ok()).toBe(true)
  await unavailable.getByRole('button', { name: 'Retry' }).click()
  await expect(unavailable).not.toBeVisible()
  await notice.getByRole('button', { name: 'Reload', exact: true }).click()
  await expect(page.locator('html')).toHaveAttribute('data-test-build', 'third')
  await expect(notice).not.toBeVisible()
})

test('worker-only changes do not announce an update to the already loaded app', async ({
  page,
  frontendDist,
}) => {
  await page.goto('/')
  await page.evaluate(() => navigator.serviceWorker.ready.then(() => undefined))
  await page.reload()
  const path = join(frontendDist, 'sw.js')
  writeFileSync(path, readFileSync(path, 'utf8') + '\n// worker-only change\n')
  await page.evaluate(async () => {
    await (await navigator.serviceWorker.ready).update()
  })
  await expect
    .poll(() => page.evaluate(async () => !!(await navigator.serviceWorker.ready).waiting))
    .toBe(true)
  // Wait beyond the build handshake timeout, including any legacy fallback.
  await page.waitForTimeout(2300)
  await expect(page.getByRole('status', { name: 'App update', exact: true })).not.toBeVisible()
  await page.evaluate(async () => {
    const changed = new Promise<void>((resolve) =>
      navigator.serviceWorker.addEventListener('controllerchange', () => resolve(), { once: true }),
    )
    ;(await navigator.serviceWorker.ready).waiting!.postMessage({ type: 'SKIP_WAITING' })
    await changed
  })
  await page.waitForTimeout(2300)
  await expect(page.getByRole('status', { name: 'App update', exact: true })).not.toBeVisible()
})

test('deferring a build survives replacement by another worker for the same build', async ({
  page,
  frontendDist,
}) => {
  await page.goto('/')
  await page.evaluate(() => navigator.serviceWorker.ready.then(() => undefined))
  await page.reload()
  await publishUpdate(page, frontendDist, 'second')
  const notice = page.getByRole('status', { name: 'App update', exact: true })
  await notice.getByRole('button', { name: 'Later' }).click()
  const path = join(frontendDist, 'sw.js')
  writeFileSync(path, readFileSync(path, 'utf8') + '\n// same app build\n')
  await page.evaluate(async () => {
    await (await navigator.serviceWorker.ready).update()
  })
  await page.waitForTimeout(2300)
  await expect(notice).not.toBeVisible()
  await publishUpdate(page, frontendDist, 'third')
})

test('updating another window never reloads an editor, and its reload guard can cancel', async ({
  page,
  context,
  frontendDist,
}) => {
  await page.goto('/#/templates/new')
  await page.evaluate(() => navigator.serviceWorker.ready.then(() => undefined))
  await page.reload()
  const name = page.getByLabel('Template name', { exact: true })
  await name.fill('Draft across updates')
  const other = await context.newPage()
  await other.goto('/')
  await publishUpdate(other, frontendDist, 'second')
  const notice = page.getByRole('status', { name: 'App update', exact: true })
  await expect(notice).toBeVisible()
  await other
    .getByRole('status', { name: 'App update', exact: true })
    .getByRole('button', { name: 'Reload', exact: true })
    .click()
  await expect(other.locator('html')).toHaveAttribute('data-test-build', 'second')
  await expect(name).toHaveValue('Draft across updates')
  expect(await page.evaluate(() => document.documentElement.dataset.testBuild)).toBeUndefined()

  const cancelled = page.waitForEvent('dialog').then(async (dialog) => {
    expect(dialog.type()).toBe('beforeunload')
    await dialog.dismiss()
  })
  await notice.getByRole('button', { name: 'Reload', exact: true }).click()
  await cancelled
  await expect(name).toHaveValue('Draft across updates')
  await expect(notice).toBeVisible()

  const accepted = page.waitForEvent('dialog').then((dialog) => dialog.accept())
  await notice.getByRole('button', { name: 'Reload', exact: true }).click()
  await accepted
  await expect(page.locator('html')).toHaveAttribute('data-test-build', 'second')
  await expect(notice).not.toBeVisible()
  await other.close()
})
