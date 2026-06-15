import { Page, Locator, expect } from '@playwright/test';

/**
 * Page Object Model for Chat Window
 * Handles chat interactions
 */
export class ChatWindowPage {
  readonly page: Page;

  // Locators
  readonly chatWindow: Locator;
  readonly messageInput: Locator;
  readonly sendButton: Locator;
  readonly messageList: Locator;
  readonly userMessages: Locator;
  readonly assistantMessages: Locator;
  readonly thinkingPanel: Locator;
  readonly welcomePage: Locator;

  constructor(page: Page) {
    this.page = page;

    // Chat window container
    this.chatWindow = page.locator('[role="main"]').first();

    // Input area - placeholder is "Enter message..."
    this.messageInput = page.locator('textarea[placeholder*="Enter"], textarea[placeholder*="message"]').first();
    this.sendButton = page.locator('.sendBtn, button[type="primary"]').first();

    // Messages
    this.messageList = page.locator('.messageListWrapper').first();
    this.userMessages = page.locator('.messageItem:has(.userMessage), [data-testid="user-message"]');
    this.assistantMessages = page.locator('.messageItem:has(.assistantMessage), [data-testid="assistant-message"]');

    // Thinking panel
    this.thinkingPanel = page.locator('.todoPanel, [data-testid="thinking-panel"]');

    // Welcome page - use text content for better reliability
    this.welcomePage = page.locator('h4:has-text("Welcome to ASRI"), h2:has-text("Welcome to ASRI")');
  }

  /**
   * Check if chat window is visible
   */
  async isVisible(): Promise<boolean> {
    return await this.chatWindow.isVisible();
  }

  /**
   * Check if welcome page is shown
   */
  async isWelcomePageVisible(): Promise<boolean> {
    return await this.welcomePage.isVisible();
  }

  /**
   * Send a message
   */
  async sendMessage(message: string) {
    // Fill the input
    await this.messageInput.fill(message);

    // Press Enter to send
    await this.messageInput.press('Enter');

    // Wait for the message to be sent
    await this.page.waitForTimeout(500);
  }

  /**
   * Send message with send button
   */
  async sendMessageWithButton(message: string) {
    await this.messageInput.fill(message);
    await this.sendButton.click();
    await this.page.waitForTimeout(500);
  }

  /**
   * Get the last message text
   */
  async getLastMessageText(): Promise<string> {
    const lastMessage = this.messageList.locator('.messageItem').last();
    return await lastMessage.textContent() || '';
  }

  /**
   * Get message count
   */
  async getMessageCount(): Promise<number> {
    return await this.messageList.locator('.messageItem').count();
  }

  /**
   * Wait for assistant response
   */
  async waitForResponse(timeout: number = 60000) {
    // Wait for the assistant message to appear
    await this.assistantMessages.last().waitFor({ state: 'visible', timeout });
  }

  /**
   * Wait for thinking panel to appear and disappear
   */
  async waitForThinking() {
    try {
      // Wait for thinking to start
      await this.thinkingPanel.waitFor({ state: 'visible', timeout: 5000 });
      // Wait for thinking to complete
      await this.thinkingPanel.waitFor({ state: 'hidden', timeout: 60000 });
    } catch {
      // Thinking panel might not always be visible
    }
  }

  /**
   * Verify message appears in chat
   */
  async verifyMessageAppears(text: string) {
    await expect(this.messageList.locator(`text="${text}"`)).toBeVisible();
  }

  /**
   * Clear chat input
   */
  async clearInput() {
    await this.messageInput.clear();
  }
}