import { test, expect } from './fixtures'

for (const width of [1280, 390]) {
  test(`group accounts and funding controls at ${width}px`, async ({
    page,
    request,
    browser,
    baseURL,
  }) => {
    await page.setViewportSize({ width, height: 900 })
    const [cartridge] = await (await request.get('/api/cartridges')).json()
    expect(
      (
        await request.put(`/api/cartridges/${cartridge.id}/price`, {
          data: { price_minor: 2000, currency: 'EUR' },
        })
      ).ok(),
    ).toBeTruthy()
    await page.goto('/#/group-accounts')
    await page.getByText('Create group account', { exact: true }).click()
    const createDialog = page.getByRole('dialog', { name: 'Create group account', exact: true })
    await createDialog.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(createDialog).toBeHidden()
    await expect(
      page.getByRole('button', { name: 'Create group account', exact: true }),
    ).toBeFocused()
    await page.getByRole('button', { name: 'Create group account', exact: true }).click()
    await createDialog.getByLabel('Name', { exact: true }).fill('Vereinskasse')
    await page.getByRole('button', { name: 'Create account', exact: true }).click()
    await expect(createDialog).toBeHidden()
    const { accounts } = await (await request.get('/api/accounts/groups')).json()
    const account = accounts[0]
    async function navigate(id: string, name: string) {
      if (width < 700)
        await page.getByRole('combobox', { name: 'Group funding section' }).selectOption(id)
      else
        await page
          .getByRole('navigation', { name: 'Group funding sections' })
          .getByRole('button', { name, exact: true })
          .click()
    }
    await navigate('permissions', 'Permissions')
    await expect(page.getByRole('combobox', { name: 'Permission', exact: true })).toBeVisible()
    await page.getByRole('combobox', { name: 'Rule', exact: true }).selectOption('deny')
    await navigate('balances', 'Balances & charges')
    await expect(page.getByRole('combobox', { name: 'Permission', exact: true })).not.toBeVisible()
    await navigate('permissions', 'Permissions')
    await expect(page.getByRole('combobox', { name: 'Rule', exact: true })).toHaveValue('deny')
    if (width === 1280) {
      await page.getByRole('button', { name: 'Create group account', exact: true }).click()
      await createDialog.getByLabel('Name', { exact: true }).fill('Second account')
      await createDialog.getByRole('button', { name: 'Create account', exact: true }).click()
      await expect(createDialog).toBeHidden()
      await expect(page.getByRole('heading', { name: 'Requests', exact: true })).toBeVisible()
      await page
        .getByRole('combobox', { name: 'Group account', exact: true })
        .selectOption(account.id)
    }
    await navigate('requests', 'Requests')
    await navigate('settings', 'Account settings')
    const archived = page.getByRole('checkbox', { name: 'Archived', exact: true })
    await expect(archived.locator('..')).toHaveCSS('flex-direction', 'row')
    await navigate('requests', 'Requests')
    await page.screenshot({
      path: `test-results/group-navigation-${width}.png`,
      fullPage: true,
      animations: 'disabled',
    })
    await page.goto(`/#/new?template=text&profile=${cartridge.profile_id}`)
    await page
      .getByRole('combobox', { name: 'Paying account', exact: true })
      .selectOption(account.id)
    await expect(page.getByRole('combobox', { name: 'Funding', exact: true })).toHaveValue('wait')
    const preview = page.waitForResponse(
      (response) =>
        response.url().endsWith('/api/preview') &&
        response.ok() &&
        response.request().postDataJSON()?.data?.text === 'Group print',
    )
    await page.getByLabel('Label text', { exact: true }).fill('Group print')
    await preview
    await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
    await expect(page).toHaveURL(/#\/queue/)
    await expect(page.locator('.status-badge')).toContainText('waiting for group approval')
    const status = page.locator('.queue-table .status-badge').first()
    await status.scrollIntoViewIfNeeded()
    const badgeBox = (await status.boundingBox())!
    const statusCell = (await status.locator('xpath=ancestor::td').boundingBox())!
    expect(badgeBox.x + badgeBox.width).toBeLessThanOrEqual(statusCell.x + statusCell.width)
    const removeBox = (await page
      .getByRole('button', { name: 'Remove', exact: true })
      .boundingBox())!
    expect(badgeBox.x + badgeBox.width + 8).toBeLessThanOrEqual(removeBox.x)
    await page.getByRole('link', { name: 'Group funding', exact: true }).click()
    const decisionDialog = page.getByRole('dialog', { name: 'Print funding', exact: true })
    await expect(decisionDialog).toBeVisible()
    await expect(
      decisionDialog.getByRole('img', { name: 'Label preview: Group print', exact: true }),
    ).toBeVisible()
    await expect
      .poll(() =>
        decisionDialog
          .locator('.history-thumbnail img')
          .evaluate((image) => (image as HTMLImageElement).naturalWidth),
      )
      .toBeGreaterThan(0)
    await decisionDialog.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(decisionDialog).toBeHidden()
    const viewRequest = page.getByRole('button', {
      name: 'View Print funding from owner',
      exact: true,
    })
    await viewRequest.focus()
    const focusBox = (await viewRequest.boundingBox())!
    const contentBox = (await page.locator('.administration-content').boundingBox())!
    expect(focusBox.x + focusBox.width + 6).toBeLessThanOrEqual(contentBox.x + contentBox.width + 1)
    await page.getByRole('button', { name: 'View Print funding from owner', exact: true }).click()
    await expect(decisionDialog).toBeVisible()
    await expect(page.getByRole('button', { name: 'Pay personally', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Approve', exact: true })).toHaveCount(0)
    if (width === 1280) {
      const payload = {
        username: 'funding-reviewer',
        password: 'browser-reviewer-password',
        role_ids: ['member'],
      }
      const permissionPreview = await request.post('/api/admin/access-preview', {
        data: { resource: 'users', method: 'POST', payload },
      })
      const created = await request.post('/api/admin/users', {
        data: payload,
        headers: { 'X-Access-Confirmation': (await permissionPreview.json()).confirmation_token },
      })
      expect(created.ok(), await created.text()).toBeTruthy()
      const reviewerUser = await created.json()
      expect(
        (
          await request.put(`/api/accounts/groups/${account.id}/access`, {
            data: {
              principal_kind: 'user',
              principal_id: reviewerUser.id,
              permission: 'approve',
              effect: 'allow',
            },
          })
        ).ok(),
      ).toBeTruthy()
      const funding = (await (await request.get(`/api/accounts/groups/${account.id}`)).json())
        .requests[0]
      const context = await browser.newContext({
        baseURL,
        storageState: { cookies: [], origins: [] },
        extraHTTPHeaders: {},
      })
      try {
        expect(
          (
            await context.request.post('/api/auth/login', {
              data: { username: payload.username, password: payload.password },
            })
          ).ok(),
        ).toBeTruthy()
        const reviewer = await context.newPage()
        await reviewer.goto(`/#/group-accounts?account=${account.id}&request=${funding.id}`)
        const modal = reviewer.getByRole('dialog', { name: 'Print funding', exact: true })
        await expect(modal).toBeVisible()
        await expect
          .poll(() =>
            modal
              .locator('.history-thumbnail img')
              .evaluate((image) => (image as HTMLImageElement).naturalWidth),
          )
          .toBeGreaterThan(0)
        await modal.getByLabel('Decision note').fill('Please use personal funding for this label.')
        await reviewer.screenshot({
          path: 'test-results/group-approval-dialog.png',
          animations: 'disabled',
        })
        await modal.getByRole('button', { name: 'Reject', exact: true }).click()
        await expect(modal).toBeHidden()
        await expect(reviewer.locator('.group-accounts').getByRole('status')).toContainText(
          'Request rejected.',
        )
      } finally {
        await context.close()
      }
    }
    await page.evaluate(async () => {
      await Promise.all(
        document
          .getAnimations()
          .filter((animation) => animation.effect?.getComputedTiming().iterations !== Infinity)
          .map((animation) => animation.finished.catch(() => {})),
      )
    })
    await page.screenshot({ path: `test-results/group-accounts-${width}.png`, fullPage: true })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const first = await page
      .getByRole('button', { name: 'Pay personally', exact: true })
      .boundingBox()
    const second = await page
      .getByRole('button', { name: 'Cancel queued labels', exact: true })
      .boundingBox()
    expect(
      first &&
        second &&
        (second.x >= first.x + first.width + 8 || second.y >= first.y + first.height + 8),
    ).toBeTruthy()
    await page.getByRole('button', { name: 'Pay personally', exact: true }).click()
    await expect(decisionDialog).toBeHidden()
    await expect(page.getByRole('button', { name: 'Pay personally', exact: true })).toHaveCount(0)
    await expect(page.locator('.group-accounts').getByRole('status')).toContainText(
      'Personal payment selected.',
    )
  })
}
