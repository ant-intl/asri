import { test, expect } from '@playwright/test';
import { SidebarPage, ChatWindowPage } from './pages';

test.describe('Chat Session Flow', () => {
  let sidebar: SidebarPage;
  let chatWindow: ChatWindowPage;

  test.beforeEach(async ({ page }) => {
    sidebar = new SidebarPage(page);
    chatWindow = new ChatWindowPage(page);

    // Navigate to app
    await sidebar.goto();
  });

  test('should display welcome page when no session selected', async ({ page }) => {
    // Welcome page should be visible
    await expect(chatWindow.welcomePage).toBeVisible();

    // Should show welcome text
    await expect(page.locator('text=Welcome to ASRI')).toBeVisible();
  });

  test('should create new chat session', async ({ page }) => {
    // Ensure Chat menu is expanded
    await sidebar.expandMenu('chat');

    // Create new session
    await sidebar.createNewSession('Test Session E2E');

    // Wait for session to be created
    await page.waitForTimeout(1000);

    // Verify session appears in list
    const sessionCount = await sidebar.getSessionCount();
    expect(sessionCount).toBeGreaterThan(0);

    // Chat window should be visible now (input area)
    await expect(chatWindow.messageInput).toBeVisible();
  });

  test('should send message and receive response', async ({ page }) => {
    // Create session first
    await sidebar.expandMenu('chat');
    await sidebar.createNewSession('Chat Test Session');

    // Wait for chat to load
    await chatWindow.messageInput.waitFor({ state: 'visible' });

    // Send a message
    await chatWindow.sendMessage('Hello, please introduce yourself');

    // Wait for response (longer timeout for LLM response)
    await chatWindow.waitForResponse(60000);

    // Verify we got a response
    const messageCount = await chatWindow.getMessageCount();
    expect(messageCount).toBeGreaterThanOrEqual(2); // User message + assistant response
  });

  test('should switch between sessions', async ({ page }) => {
    // Create two sessions
    await sidebar.expandMenu('chat');
    await sidebar.createNewSession('Session 1');
    await page.waitForTimeout(500);

    await sidebar.createNewSession('Session 2');
    await page.waitForTimeout(500);

    // Select first session
    await sidebar.selectSession('Session 1');
    await page.waitForTimeout(300);

    // Chat window should be visible
    await expect(chatWindow.messageInput).toBeVisible();

    // Select second session
    await sidebar.selectSession('Session 2');
    await page.waitForTimeout(300);

    // Chat window should still be visible
    await expect(chatWindow.messageInput).toBeVisible();
  });

  test('should delete session with confirmation', async ({ page }) => {
    // Create a session to delete
    await sidebar.expandMenu('chat');
    await sidebar.createNewSession('Session to Delete');
    await page.waitForTimeout(500);

    const initialCount = await sidebar.getSessionCount();

    // Delete the session
    await sidebar.deleteSession('Session to Delete');
    await page.waitForTimeout(500);

    const finalCount = await sidebar.getSessionCount();
    expect(finalCount).toBeLessThan(initialCount);
  });
});

test.describe('Sidebar Navigation', () => {
  let sidebar: SidebarPage;

  test.beforeEach(async ({ page }) => {
    sidebar = new SidebarPage(page);
    await sidebar.goto();
  });

  test('should expand and collapse Chat menu', async ({ page }) => {
    // Expand chat menu
    await sidebar.expandMenu('chat');

    // Session list should be visible
    await expect(sidebar.sessionList).toBeVisible();

    // Collapse chat menu
    await sidebar.expandMenu('chat');

    // Session list should be hidden
    await expect(sidebar.sessionList).not.toBeVisible();
  });

  test('should expand Settings menu and show sub-items', async ({ page }) => {
    // Expand settings menu
    await sidebar.expandMenu('settings');

    // Sub-menu items should be visible
    await expect(sidebar.sessionTab).toBeVisible();
    await expect(sidebar.agentTab).toBeVisible();
    await expect(sidebar.snapshotTab).toBeVisible();
  });

  test('should expand AI Lab menu and show sub-items', async ({ page }) => {
    // Expand AI Lab menu
    await sidebar.expandMenu('lab');

    // Sub-menu items should be visible
    await expect(sidebar.playgroundTab).toBeVisible();
    await expect(sidebar.batchRunnerTab).toBeVisible();
    await expect(sidebar.conversationsTab).toBeVisible();
  });

  test('should navigate to Agent tab under Settings', async ({ page }) => {
    await sidebar.navigateToSettingsTab('agent');

    // Should show agent settings content
    await expect(page.locator('text=Agent Settings, text=Agent')).toBeVisible();
  });

  test('should navigate to Snapshot tab under Settings', async ({ page }) => {
    await sidebar.navigateToSettingsTab('snapshot');

    // Should show snapshot/version manager content
    await expect(page.locator('text=Snapshot, text=Version')).toBeVisible();
  });

  test('should navigate to Playground tab under AI Lab', async ({ page }) => {
    await sidebar.navigateToAILabTab('playground');

    // Should show playground content
    await expect(page.locator('text=Playground, text=Compare')).toBeVisible();
  });

  test('should collapse and expand sidebar', async ({ page }) => {
    // Sidebar should be expanded initially
    const isInitiallyCollapsed = await sidebar.isCollapsed();
    expect(isInitiallyCollapsed).toBe(false);

    // Collapse sidebar
    await sidebar.collapseSidebar();
    await page.waitForTimeout(500);

    // Check collapsed state
    const collapsed = await sidebar.isCollapsed();
    expect(collapsed).toBe(true);

    // Expand again
    await sidebar.collapseSidebar();
    await page.waitForTimeout(500);

    const expanded = await sidebar.isCollapsed();
    expect(expanded).toBe(false);
  });
});