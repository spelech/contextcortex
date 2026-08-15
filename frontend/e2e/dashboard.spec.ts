import { test, expect } from '@playwright/test';

test('has title and basic UI elements', async ({ page }) => {
  // We mock a successful load of the app, we can just check if it renders locally
  // However, we don't necessarily have the backend running for this basic test,
  // so let's just make a very basic test that can pass even if the app fails to fetch stats.
  await page.goto('/');

  // Expect the main header title to be visible
  await expect(page.locator('h1', { hasText: 'Code & Docs RAG Server' })).toBeVisible();

  // Expect the navigation tabs to be present
  await expect(page.locator('button.nav-tab', { hasText: 'Overview' })).toBeVisible();
  await expect(page.locator('button.nav-tab', { hasText: 'Git Repositories' })).toBeVisible();
  await expect(page.locator('button.nav-tab', { hasText: 'Settings' })).toBeVisible();
});
