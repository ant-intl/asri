import { test, expect } from '@playwright/test';
import { SidebarPage, PromptManagerPage } from './pages';

test.describe('Agent Settings - Prompts Tab', () => {
  let sidebar: SidebarPage;
  let promptManager: PromptManagerPage;

  test.beforeEach(async ({ page }) => {
    sidebar = new SidebarPage(page);
    promptManager = new PromptManagerPage(page);

    // Navigate to app
    await sidebar.goto();

    // Navigate to Agent tab under Settings
    await sidebar.navigateToSettingsTab('agent');

    // Wait for Agent Settings to load
    await expect(page.locator('text=Agent Settings')).toBeVisible();

    // Click on Prompts tab (default active)
    await page.locator('.ant-tabs-tab:has-text("Prompts")').click();
    await promptManager.waitForLoad();
  });

  test('should display Prompt Manager page', async ({ page }) => {
    // Title should be visible
    await expect(page.locator('text=Prompt Manager')).toBeVisible();

    // Save button should be visible
    await expect(promptManager.saveButton).toBeVisible();

    // Reset button should be visible
    await expect(promptManager.resetButton).toBeVisible();
  });

  test('should display System Prompt and User Prompt sections', async ({ page }) => {
    // System Prompt section should be visible
    await expect(page.locator('text=System Prompt')).toBeVisible();

    // User Prompt section should be visible
    await expect(page.locator('text=User Prompt')).toBeVisible();
  });

  test('should toggle between Edit and Preview mode', async ({ page }) => {
    // Initially should show Edit button (in preview mode)
    const editBtn = promptManager.systemPromptSection.locator('button:has-text("Edit")');
    await expect(editBtn).toBeVisible();

    // Click to switch to edit mode
    await editBtn.click();
    await page.waitForTimeout(300);

    // Now should show Preview button
    const previewBtn = promptManager.systemPromptSection.locator('button:has-text("Preview")');
    await expect(previewBtn).toBeVisible();

    // Textarea should be visible in edit mode
    const textarea = promptManager.systemPromptSection.locator('textarea');
    await expect(textarea).toBeVisible();
  });

  test('should edit and save system prompt', async ({ page }) => {
    const testContent = `# Test System Prompt ${Date.now()}

This is a test prompt for E2E testing.`;

    // Toggle to edit mode
    await promptManager.toggleEditMode('system');

    // Edit content
    await promptManager.editSystemPrompt(testContent);

    // Save
    await promptManager.save();

    // Verify success message
    await expect(page.locator('.ant-message:has-text("Saved successfully")')).toBeVisible();
  });

  test('should reset prompts to default', async ({ page }) => {
    // Click reset button
    await promptManager.reset();

    // Verify reset message
    await expect(page.locator('.ant-message:has-text("Reset")')).toBeVisible();
  });

  test('should navigate to Skills tab', async ({ page }) => {
    // Click on Skills tab
    await page.locator('.ant-tabs-tab:has-text("Skills")').click();

    // Should show skills content
    await expect(page.locator('text=Skills')).toBeVisible();
  });

  test('should navigate to MCPs tab', async ({ page }) => {
    // Click on MCPs tab
    await page.locator('.ant-tabs-tab:has-text("MCPs")').click();

    // Should show MCP config
    await expect(page.locator('text=MCP')).toBeVisible();
  });

  test('should navigate to Tools tab', async ({ page }) => {
    // Click on Tools tab
    await page.locator('.ant-tabs-tab:has-text("Tools")').click();

    // Should show tools content
    await expect(page.locator('text=Tools')).toBeVisible();
  });

  test('should navigate to Models tab', async ({ page }) => {
    // Click on Models tab
    await page.locator('.ant-tabs-tab:has-text("Models")').click();

    // Should show models content
    await expect(page.locator('text=Models')).toBeVisible();
  });
});