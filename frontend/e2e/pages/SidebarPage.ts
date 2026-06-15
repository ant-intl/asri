import { Page, Locator, expect } from '@playwright/test';

/**
 * Page Object Model for Sidebar component
 * Handles navigation and session management
 */
export class SidebarPage {
  readonly page: Page;

  // Locators
  readonly sidebar: Locator;
  readonly newSessionBtn: Locator;

  // Session list
  readonly sessionList: Locator;
  readonly sessionItems: Locator;
  readonly collapseBtn: Locator;

  constructor(page: Page) {
    this.page = page;

    // Main sidebar elements
    this.sidebar = page.locator('aside, [role="complementary"]').first();
    this.newSessionBtn = page.getByRole('button', { name: 'plus' }).first();

    // Session list
    this.sessionList = page.locator('.chatSessionList');
    this.sessionItems = page.locator('.sessionItem');
    this.collapseBtn = page.getByRole('button', { name: 'menu-fold' });
  }

  /**
   * Navigate to the application
   */
  async goto() {
    await this.page.goto('/');
    await this.waitForSidebar();
  }

  /**
   * Wait for sidebar to be visible
   */
  async waitForSidebar() {
    await this.sidebar.waitFor({ state: 'visible', timeout: 10000 });
  }

  /**
   * Get menu locator by name
   */
  private getMenuLocator(menuText: string): Locator {
    // Find the menu item container and click on it
    return this.page.locator(`xpath=//aside//*[text()='${menuText}']/ancestor::div[contains(@class, 'menuItem')][1]`).first();
  }

  /**
   * Expand a menu section by clicking on it
   */
  async expandMenu(menu: 'chat' | 'settings' | 'lab') {
    const menuText = menu === 'chat' ? 'Chat' :
                     menu === 'settings' ? 'Settings' : 'AI Lab';

    // Click on the menu item container
    // The menu structure: div.menuItem > div.menuHeader (clickable)
    const menuItem = this.page.locator(`xpath=//*[text()='${menuText}']/ancestor::div[position() <= 5][@cursor='pointer' or contains(@class, 'menuItem') or contains(@class, 'menuHeader')][1]`).first();
    await menuItem.click();
    await this.page.waitForTimeout(300);
  }

  /**
   * Collapse sidebar
   */
  async collapseSidebar() {
    await this.collapseBtn.click();
    await this.page.waitForTimeout(300);
  }

  /**
   * Check if sidebar is collapsed
   */
  async isCollapsed(): Promise<boolean> {
    const width = await this.sidebar.evaluate(el => el.getBoundingClientRect().width);
    return width < 50;
  }

  /**
   * Create a new chat session
   */
  async createNewSession(title?: string) {
    // Click the inline add button on Chat menu
    await this.newSessionBtn.click();

    // Wait for modal
    const modal = this.page.locator('.ant-modal:visible');
    await modal.waitFor({ state: 'visible' });

    // Fill title if provided
    if (title) {
      await modal.locator('input').first().fill(title);
    }

    // Click create button
    await modal.locator('button:has-text("Create")').click();

    // Wait for modal to close
    await modal.waitFor({ state: 'hidden' });
  }

  /**
   * Select a session by title
   */
  async selectSession(title: string) {
    const session = this.sessionItems.filter({ hasText: title });
    await session.click();
  }

  /**
   * Delete a session by title
   */
  async deleteSession(title: string) {
    const session = this.sessionItems.filter({ hasText: title });
    const deleteBtn = session.locator('.deleteBtn, button:has(.DeleteOutlined)');

    // Hover to reveal delete button
    await session.hover();
    await deleteBtn.click();

    // Confirm deletion in modal
    await this.page.locator('.ant-modal-confirm button:has-text("OK"), .ant-modal-confirm button:has-text("确定")').click();
    await this.page.waitForTimeout(500);
  }

  /**
   * Get session count
   */
  async getSessionCount(): Promise<number> {
    return await this.sessionItems.count();
  }

  /**
   * Navigate to a specific tab under Settings
   */
  async navigateToSettingsTab(tab: 'session' | 'agent' | 'snapshot') {
    // Expand settings menu first
    await this.expandMenu('settings');
    await this.page.waitForTimeout(300);

    // Click on the tab using exact text
    const tabText = tab === 'session' ? 'Session' :
                    tab === 'agent' ? 'Agent' : 'Snapshot';
    await this.page.getByText(tabText, { exact: true }).first().click();
  }

  /**
   * Navigate to a specific tab under AI Lab
   */
  async navigateToAILabTab(tab: 'playground' | 'batch-runner' | 'conversations') {
    // Expand AI Lab menu first
    await this.expandMenu('lab');
    await this.page.waitForTimeout(300);

    // Click on the tab using text
    const tabText = tab === 'playground' ? 'Playground' :
                    tab === 'batch-runner' ? 'Batch Runner' : 'Conversations';
    await this.page.getByText(tabText, { exact: true }).first().click();
  }
}