import { expect, test } from '@playwright/test'

test('工作台加载并显示核心操作和图片列', async ({ context, page }) => {
  await context.addCookies([
    {
      name: 'spw_csrf',
      value: 'e2e-csrf-token',
      domain: '127.0.0.1',
      path: '/',
    },
  ])

  await page.route('**/api/v1/auth/me', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ data: { username: 'admin' } }),
  }))
  await page.route('**/api/v1/rows', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ data: [] }),
  }))
  await page.route('**/api/v1/events', route => route.fulfill({
    status: 200,
    contentType: 'text/event-stream',
    body: '',
  }))

  await page.goto('/')

  await expect(page.getByText('沙发场景提示词工作台')).toBeVisible()
  await expect(page.getByRole('button', { name: '新建任务' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: '场景参考图' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: '沙发白底图' })).toBeVisible()
})
