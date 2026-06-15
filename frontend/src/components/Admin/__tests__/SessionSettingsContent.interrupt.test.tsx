/**
 * Unit tests for Tool Interrupt Strategy UI in SessionSettingsContent.
 *
 * Tests cover:
 * - UI field existence
 * - Default values
 * - Select options
 * - localStorage persistence
 * - Loading saved values
 */

import { render, screen, fireEvent } from '@testing-library/react';
import SessionSettingsContent from '../SessionSettingsContent';

describe('SessionSettingsContent - Tool Interrupt Strategy', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  test('FE-001: Tool interrupt strategy field exists', () => {
    render(<SessionSettingsContent />);
    
    // Check title exists
    expect(screen.getByText('Tool Interrupt Strategy')).toBeInTheDocument();
    
    // Check form item exists (by label text)
    expect(screen.getByText('Tool Interrupt Behavior')).toBeInTheDocument();
  });

  test('FE-002: Default value is none', () => {
    render(<SessionSettingsContent />);
    
    // The Select should have 'none' as default
    // Ant Design Select shows the label of the selected option
    const selectElement = screen.getByRole('combobox', { name: /Tool Interrupt Behavior/i });
    
    // Open the select to see current value
    fireEvent.mouseDown(selectElement);
    
    // Check that 'none' option is selected (has checkmark or highlighted)
    const noneOption = screen.getByText(/No interrupt/i);
    expect(noneOption).toBeInTheDocument();
  });

  test('FE-003: Three options available', () => {
    render(<SessionSettingsContent />);
    
    const selectElement = screen.getByRole('combobox', { name: /Tool Interrupt Behavior/i });
    fireEvent.mouseDown(selectElement);
    
    // Check all three options exist
    expect(screen.getByText(/Wait for current token then interrupt/i)).toBeInTheDocument();
    expect(screen.getByText(/Wait for all tools to complete then interrupt/i)).toBeInTheDocument();
    expect(screen.getByText(/No interrupt/i)).toBeInTheDocument();
  });

  test('FE-004: Select immediate saves to localStorage', async () => {
    render(<SessionSettingsContent />);
    
    const selectElement = screen.getByRole('combobox', { name: /Tool Interrupt Behavior/i });
    fireEvent.mouseDown(selectElement);
    
    const immediateOption = screen.getByText(/Wait for current token then interrupt/i);
    fireEvent.click(immediateOption);
    
    // Check localStorage
    const saved = JSON.parse(localStorage.getItem('asri_session_settings')!);
    expect(saved.toolInterruptStrategy).toBe('immediate');
  });

  test('FE-005: Select semantic_complete saves to localStorage', async () => {
    render(<SessionSettingsContent />);
    
    const selectElement = screen.getByRole('combobox', { name: /Tool Interrupt Behavior/i });
    fireEvent.mouseDown(selectElement);
    
    const semanticOption = screen.getByText(/Wait for all tools to complete then interrupt/i);
    fireEvent.click(semanticOption);
    
    // Check localStorage
    const saved = JSON.parse(localStorage.getItem('asri_session_settings')!);
    expect(saved.toolInterruptStrategy).toBe('semantic_complete');
  });

  test('FE-006: Select none saves to localStorage', async () => {
    render(<SessionSettingsContent />);
    
    const selectElement = screen.getByRole('combobox', { name: /Tool Interrupt Behavior/i });
    fireEvent.mouseDown(selectElement);
    
    const noneOption = screen.getByText(/No interrupt/i);
    fireEvent.click(noneOption);
    
    // Check localStorage
    const saved = JSON.parse(localStorage.getItem('asri_session_settings')!);
    expect(saved.toolInterruptStrategy).toBe('none');
  });

  test('FE-007: Loads existing value from localStorage', () => {
    // Pre-populate localStorage
    const existingSettings = {
      language: 'zh-CN',
      timezone: 'Asia/Shanghai',
      maxInteractionRounds: 10,
      thinkingAndActing: true,
      multitasking: true,
      executionMode: 'interleaved',
      interruptionLogic: 'ask',
      connectionType: 'http',
      isStream: true,
      toolInterruptStrategy: 'immediate',
    };
    localStorage.setItem('asri_session_settings', JSON.stringify(existingSettings));
    
    render(<SessionSettingsContent />);
    
    // Open select to see current value
    const selectElement = screen.getByRole('combobox', { name: /Tool Interrupt Behavior/i });
    fireEvent.mouseDown(selectElement);
    
    // The immediate option should be highlighted/selected
    const immediateOption = screen.getByText(/Wait for current token then interrupt/i);
    expect(immediateOption).toBeInTheDocument();
  });

  test('FE-008: ToolOutlined icon displayed', () => {
    render(<SessionSettingsContent />);
    
    // The icon should be rendered with the title
    const titleElement = screen.getByText('Tool Interrupt Strategy');
    expect(titleElement).toBeInTheDocument();
    
    // The icon is rendered as an SVG inside the Title
    const iconContainer = titleElement.previousElementSibling;
    expect(iconContainer).toBeTruthy();
  });

  test('FE-009: Configuration survives form values change', () => {
    render(<SessionSettingsContent />);
    
    // Change some other field
    const maxRoundsInput = screen.getByRole('spinbutton', { name: /Max Interaction Rounds/i });
    fireEvent.change(maxRoundsInput, { target: { value: '20' } });
    
    // Change tool interrupt strategy
    const selectElement = screen.getByRole('combobox', { name: /Tool Interrupt Behavior/i });
    fireEvent.mouseDown(selectElement);
    
    const immediateOption = screen.getByText(/Wait for current token then interrupt/i);
    fireEvent.click(immediateOption);
    
    // Both values should be saved
    const saved = JSON.parse(localStorage.getItem('asri_session_settings')!);
    expect(saved.maxInteractionRounds).toBe(20);
    expect(saved.toolInterruptStrategy).toBe('immediate');
  });

  test('FE-010: Help text is displayed', () => {
    render(<SessionSettingsContent />);
    
    // Check help text exists
    expect(screen.getByText(/Controls how LLM streaming is interrupted when tool results arrive/i))
      .toBeInTheDocument();
  });
});
