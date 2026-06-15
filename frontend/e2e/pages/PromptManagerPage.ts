import { Page, Locator, expect } from '@playwright/test';

/**
 * Page Object Model for Prompt Manager
 * Handles prompt editing (System Prompt and User Prompt)
 */
export class PromptManagerPage {
  readonly page: Page;

  // Locators
  readonly container: Locator;
  readonly saveButton: Locator;
  readonly resetButton: Locator;
  readonly title: Locator;

  // Prompt sections
  readonly systemPromptSection: Locator;
  readonly userPromptSection: Locator;

  constructor(page: Page) {
    this.page = page;

    // Container
    this.container = page.locator('.container:has(.title:has-text("Prompt Manager"))').first();
    this.title = page.locator('text=Prompt Manager');
    this.saveButton = page.locator('button:has-text("Save")');
    this.resetButton = page.locator('button:has-text("Reset")');

    // Prompt sections
    this.systemPromptSection = page.locator('.promptSection:has-text("System Prompt")');
    this.userPromptSection = page.locator('.promptSection:has-text("User Prompt")');
  }

  /**
   * Wait for page to load
   */
  async waitForLoad() {
    await this.title.waitFor({ state: 'visible', timeout: 10000 });
  }

  /**
   * Check if prompt manager is visible
   */
  async isVisible(): Promise<boolean> {
    return await this.title.isVisible();
  }

  /**
   * Click save button
   */
  async save() {
    await this.saveButton.click();
    // Wait for success message
    await this.page.waitForTimeout(500);
  }

  /**
   * Click reset button
   */
  async reset() {
    await this.resetButton.click();
    await this.page.waitForTimeout(300);
  }

  /**
   * Toggle edit mode for a section
   */
  async toggleEditMode(section: 'system' | 'user') {
    const sectionLocator = section === 'system' ? this.systemPromptSection : this.userPromptSection;
    const editBtn = sectionLocator.locator('button:has-text("Edit"), button:has-text("Preview")');
    await editBtn.click();
    await this.page.waitForTimeout(300);
  }

  /**
   * Edit system prompt content
   */
  async editSystemPrompt(content: string) {
    // First, ensure we're in edit mode
    const editBtn = this.systemPromptSection.locator('button:has-text("Edit")');
    if (await editBtn.isVisible()) {
      await editBtn.click();
      await this.page.waitForTimeout(300);
    }

    // Find the textarea and update content
    const textarea = this.systemPromptSection.locator('textarea');
    await textarea.fill(content);
  }

  /**
   * Edit user prompt content
   */
  async editUserPrompt(content: string) {
    // First, ensure we're in edit mode
    const editBtn = this.userPromptSection.locator('button:has-text("Edit")');
    if (await editBtn.isVisible()) {
      await editBtn.click();
      await this.page.waitForTimeout(300);
    }

    // Find the textarea and update content
    const textarea = this.userPromptSection.locator('textarea');
    await textarea.fill(content);
  }

  /**
   * Get system prompt content from preview
   */
  async getSystemPromptPreview(): Promise<string> {
    const preview = this.systemPromptSection.locator('.markdownPreview');
    return await preview.textContent() || '';
  }

  /**
   * Get user prompt content from preview
   */
  async getUserPromptPreview(): Promise<string> {
    const preview = this.userPromptSection.locator('.markdownPreview');
    return await preview.textContent() || '';
  }
}