/**
 * Trace Type Configuration
 *
 * Centralized configuration for trace item display and behavior.
 * This allows easy extension when backend adds new trace types.
 */

import type { TraceType } from './chat';

// ============================================================
// Category definitions
// ============================================================

export type TraceCategory = 'thinking' | 'action' | 'result' | 'control';

// ============================================================
// Trace type configuration
// ============================================================

export interface TraceTypeConfig {
  /** Display label */
  label: string;
  /** Display icon (emoji or text) */
  icon: string;
  /** Primary color for UI */
  color: string;
  /** Category for grouping */
  category: TraceCategory;
  /** Whether to show in timeline */
  visible?: boolean;
  /** Whether to show content preview */
  showContent?: boolean;
}

/**
 * Configuration for all supported trace types.
 * To add a new type from backend, simply add an entry here.
 *
 * Three core types: Thinking, Tool (tool call), Answer
 */
export const TRACE_TYPE_CONFIG: Record<string, TraceTypeConfig> = {
  thinking: {
    label: 'Thinking',
    icon: '💡',
    color: '#60a5fa',
    category: 'thinking',
    visible: true,
    showContent: true,
  },
  think: {
    label: 'Thinking',
    icon: '💡',
    color: '#60a5fa',
    category: 'thinking',
    visible: true,
    showContent: true,
  },
  tool_call: {
    label: 'Tool',
    icon: '🔧',
    color: '#f59e0b',
    category: 'action',
    visible: true,
    showContent: true,
  },
  tool_result: {
    label: 'Result',
    icon: '✓',
    color: '#10b981',
    category: 'result',
    visible: false, // merged into tool_call display
    showContent: true,
  },
  answer: {
    label: 'Answer',
    icon: '✎',
    color: '#8b5cf6',
    category: 'result',
    visible: true,
    showContent: true,
  },
  llm_start: {
    label: 'LLM Start',
    icon: '▶',
    color: '#3b82f6',
    category: 'action',
    visible: false,
    showContent: false,
  },
  llm_end: {
    label: 'LLM End',
    icon: '◼',
    color: '#3b82f6',
    category: 'action',
    visible: false,
    showContent: false,
  },
  llm_call: {
    label: 'LLM Call',
    icon: '⚡',
    color: '#3b82f6',
    category: 'action',
    visible: true,
    showContent: true,
  },
};

// ============================================================
// Status configuration
// ============================================================

export type TraceStatus = 'pending' | 'running' | 'success' | 'error' | 'interrupted';

export interface StatusConfig {
  label: string;
  color: string;
  icon: string;
}

export const STATUS_CONFIG: Record<TraceStatus, StatusConfig> = {
  pending: {
    label: '等待中',
    color: '#9ca3af',
    icon: '○',
  },
  running: {
    label: '执行中',
    color: '#3b82f6',
    icon: '◐',
  },
  success: {
    label: '成功',
    color: '#10b981',
    icon: '✓',
  },
  error: {
    label: '错误',
    color: '#ef4444',
    icon: '✗',
  },
  interrupted: {
    label: '已中断',
    color: '#f59e0b',
    icon: '⊘',
  },
};

// ============================================================
// Helper functions
// ============================================================

/**
 * Get display config for a trace type
 */
export function getTraceConfig(type: string): TraceTypeConfig | undefined {
  return TRACE_TYPE_CONFIG[type];
}

/**
 * Get display config for a status
 */
export function getStatusConfig(status: TraceStatus): StatusConfig {
  return STATUS_CONFIG[status];
}

/**
 * Check if a trace type should be visible in timeline
 */
export function isTraceVisible(type: string): boolean {
  return TRACE_TYPE_CONFIG[type]?.visible ?? true;
}

/**
 * Get all visible trace types
 */
export function getVisibleTraceTypes(): string[] {
  return Object.entries(TRACE_TYPE_CONFIG)
    .filter(([, config]) => config.visible)
    .map(([type]) => type);
}

/**
 * Get category color
 */
export function getCategoryColor(category: TraceCategory): string {
  const categoryColors: Record<TraceCategory, string> = {
    thinking: '#60a5fa',
    action: '#f59e0b',
    result: '#10b981',
    control: '#8b5cf6',
  };
  return categoryColors[category] || '#9ca3af';
}

/**
 * Infer status from trace item fields
 */
export function inferTraceStatus(
  type: string,
  status?: 'calling' | 'success' | 'error'
): TraceStatus {
  if (type === 'tool_call') {
    return status === 'error' ? 'error' : 'running';
  }
  if (type === 'tool_result' || type === 'answer') {
    return status === 'error' ? 'error' : 'success';
  }
  if (type === 'thinking' || type === 'think') {
    return status === 'error' ? 'error' : 'running';
  }
  return 'pending';
}

// ============================================================
// Gantt-style Timeline types
// ============================================================

/**
 * Extended trace item with Gantt timeline positioning
 * These fields are calculated from the raw trace data
 */
export interface TraceTimelineItem {
  /** Unique identifier */
  id: string;
  /** Trace type (from TraceType) */
  type: string;
  /** Display label */
  label: string;
  /** Display icon */
  icon: string;
  /** Primary color */
  color: string;
  /** Category for grouping */
  category: TraceCategory;

  /** Start timestamp (ms) */
  startTime: number;
  /** End timestamp (ms) - optional for running items */
  endTime?: number;
  /** Duration in ms */
  duration?: number;

  /** Relative position: left = (stepTime / totalTime) × 100% */
  left: number;
  /** Progress bar width: (duration / totalTime) × 100% */
  width: number;

  /** Total duration of the parent conversation */
  totalDuration: number;

  /** Current status */
  status: TraceStatus;

  /** Content preview (if applicable) */
  content?: string;

  /** Conversation grouping */
  conversationId: string;
  conversationIndex: number;

  /** Tool-specific fields */
  toolName?: string;
  toolCallId?: string;
  result?: unknown;

  /** LLM-specific fields */
  llmId?: string;
  model?: string;
  provider?: string;
  durationMs?: number;
  promptTokens?: number;
  completionTokens?: number;
  totalTokens?: number;
}

/**
 * Conversation timeline summary
 */
export interface ConversationTimeline {
  /** Conversation ID */
  id: string;
  /** Conversation index */
  index: number;
  /** User input (truncated for display) */
  title: string;
  /** Start timestamp */
  startTime: number;
  /** End timestamp */
  endTime?: number;
  /** Total duration in ms */
  totalDuration?: number;

  /** Overall progress: (currentTime - startTime) / totalDuration × 100% */
  progress: number;
  /** Left position is always 0 for conversation root */
  left: number;
  /** Width is always 100% for conversation root */
  width: number;

  /** Child trace items */
  children: TraceTimelineItem[];

  /** Status */
  status: TraceStatus;
}

/**
 * Calculate timeline positioning for trace items
 * Ensures minimum visibility for instantaneous operations
 */
export function calculateTimelinePosition(
  items: Array<{
    timestamp: number;
    duration_ms?: number;
    type: string;
  }>,
  startTimestamp: number,
  totalDuration: number
): Array<{ left: number; width: number; duration: number }> {
  if (totalDuration <= 0 || items.length === 0) {
    return items.map(() => ({ left: 0, width: 0, duration: 0 }));
  }

  // Calculate average spacing between items for instantaneous operations
  const timeSpan = (items[items.length - 1].timestamp - startTimestamp) || 1;
  const avgSpacing = items.length > 1 ? Math.max(timeSpan / items.length, 50) : 50;

  // Minimum width for visibility (as percentage)
  const MIN_WIDTH_PERCENT = 2;

  return items.map((item) => {
    const stepTime = item.timestamp - startTimestamp;
    const duration = item.duration_ms || 0;
    const left = (stepTime / totalDuration) * 100;

    let width: number;
    let effectiveDuration = duration;

    if (duration > 0) {
      // Has actual duration, calculate width
      width = (duration / totalDuration) * 100;
    } else {
      // No duration - assign a representative duration and width based on item spacing
      // Use a minimum duration for instantaneous operations so they still show in timeline
      effectiveDuration = Math.min(avgSpacing, 500); // Cap at 500ms for visibility
      width = (effectiveDuration / totalDuration) * 100;
    }

    // Ensure minimum width for visibility
    width = Math.max(width, MIN_WIDTH_PERCENT);

    return {
      left: Math.max(0, Math.min(99, left)),
      width: Math.max(MIN_WIDTH_PERCENT, Math.min(100 - left, width)),
      duration: effectiveDuration,
    };
  });
}

/**
 * Infer total duration from trace items
 * Handles both long-running operations and instantaneous operations
 */
export function inferTotalDuration(
  items: Array<{ timestamp: number; duration_ms?: number }>
): number {
  if (items.length === 0) return 0;

  const firstItem = items[0];
  const lastItem = items[items.length - 1];

  // Calculate end time:
  // 1. If last item has duration, use it
  // 2. Otherwise, find the maximum duration from all items
  // 3. If no items have duration, use a reasonable minimum based on item count
  let endTime = lastItem.timestamp;
  let maxDuration = 0;
  let hasAnyDuration = false;

  for (const item of items) {
    if (item.duration_ms && item.duration_ms > 0) {
      hasAnyDuration = true;
      maxDuration = Math.max(maxDuration, item.duration_ms);
    }
  }

  if (lastItem.duration_ms && lastItem.duration_ms > 0) {
    endTime = lastItem.timestamp + lastItem.duration_ms;
  } else if (hasAnyDuration) {
    // Use the maximum duration found as a representative value
    endTime = lastItem.timestamp + maxDuration;
  }
  // If no duration data, endTime stays as lastItem.timestamp

  const startTime = firstItem.timestamp;
  const timeSpan = endTime - startTime;

  // Ensure minimum duration for visualization:
  // - If we have multiple items but no duration data, use minimum 500ms
  // - This ensures the Gantt bars are visible even for instantaneous operations
  const MIN_DURATION = items.length > 1 ? 500 : 100;

  return Math.max(timeSpan, MIN_DURATION);
}

// ============================================================
// Re-export trace types for convenience
// ============================================================

export type { TraceType } from './chat';
