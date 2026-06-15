/**
 * Trace to TodoItem conversion utility.
 *
 * Pure functions for converting trace data into TodoItem structures
 * used by the TodoList component. Shared between ChatWindow and TracePage.
 */

import type { TraceItem } from '@/types/chat';
import type { TodoItem } from '@/components/Chat/TodoList';
import { inferTotalDuration } from '@/types/traceConfig';

/**
 * Truncate text for display (show first ~30 chars).
 */
function truncateText(text: string, maxLength: number = 30): string {
  if (!text) return '';
  const trimmed = text.trim().replace(/\n/g, ' ');
  if (trimmed.length <= maxLength) return trimmed;
  return trimmed.substring(0, maxLength) + '...';
}

export interface ConversationInput {
  userContent: string;
  trace: TraceItem[];
  isComplete: boolean;
  conversationIndex: number;
}

/**
 * Build TodoItem array from a single conversation's trace data.
 *
 * Handles trace grouping:
 * - think/thinking: consecutive items merged into one "Thinking" entry
 * - tool_call + tool_result: paired into one "Tool" entry
 * - answer: consecutive items merged into one "Answer" entry
 * - llm_start/llm_end: skipped (internal markers)
 */
export function buildTodoItemsForConversation(
  conversation: ConversationInput,
): { conversationItem: TodoItem; stepItems: TodoItem[] } {
  const { userContent, trace, isComplete, conversationIndex } = conversation;
  const conversationId = `conversation-${conversationIndex}`;

  const baseTimestamp = trace.length > 0
    ? Math.min(...trace.map(t => t.timestamp))
    : Date.now();

  const totalDuration = inferTotalDuration(trace);

  const conversationTitle = userContent
    ? truncateText(userContent)
    : `Conversation ${conversationIndex}`;

  const hasInterruptedTrace = trace.some(t => t.type === 'interrupted');

  const conversationStatus = hasInterruptedTrace
    ? 'interrupted'
    : (isComplete ? 'completed' : 'running');

  const conversationEndTime = trace.length > 0 ? trace[trace.length - 1].timestamp : undefined;

  const conversationItem: TodoItem = {
    id: conversationId,
    title: conversationTitle,
    type: 'conversation',
    status: conversationStatus,
    relativeTime: 0,
    startTime: baseTimestamp,
    endTime: conversationEndTime,
    conversationId,
    conversationIndex,
    children: [],
    left: 0,
    width: 100,
    totalDuration,
    duration: totalDuration,
  };

  const stepItems: TodoItem[] = [];

  for (let i = 0; i < trace.length; i++) {
    const step = trace[i];
    const stepType = step.type;

    // Skip llm_start and llm_end - internal markers
    if (stepType === 'llm_start' || stepType === 'llm_end') {
      continue;
    }

    // answer consecutive block merge
    if (stepType === 'answer') {
      const lastAnswerItem = stepItems.filter(item => item.type === 'answer').pop();
      if (lastAnswerItem && step.timestamp <= lastAnswerItem.endTime!) {
        continue;
      }

      let blockEndIdx = i;
      for (let j = i + 1; j < trace.length; j++) {
        if (trace[j].type === 'answer') {
          blockEndIdx = j;
        } else {
          break;
        }
      }

      const startTime = step.timestamp;
      const endTime = trace[blockEndIdx].timestamp;
      const relativeTime = (startTime - baseTimestamp) / 1000;
      const timeWidth = endTime - startTime;
      const left = totalDuration > 0 ? (relativeTime / (totalDuration / 1000)) * 100 : 0;
      const width = totalDuration > 0 && timeWidth > 0
        ? Math.max(1, (timeWidth / totalDuration) * 100)
        : 2;

      let answerContent = '';
      for (let j = i; j <= blockEndIdx; j++) {
        if (trace[j].type === 'answer' && trace[j].content) {
          answerContent += trace[j].content;
        }
      }

      const item: TodoItem = {
        id: `${conversationId}-answer-${i}`,
        title: 'Answer',
        type: 'answer',
        status: isComplete ? 'completed' : 'running',
        relativeTime,
        startTime,
        endTime,
        conversationId,
        conversationIndex,
        parentId: conversationId,
        left: Math.max(0, Math.min(98, left)),
        width,
        duration: timeWidth || 1,
        totalDuration,
        traceData: {
          type: step.type,
          timestamp: step.timestamp,
          content: answerContent || step.content,
        },
      };

      stepItems.push(item);
      conversationItem.children = conversationItem.children || [];
      conversationItem.children.push(item);
      continue;
    }

    // think/thinking consecutive block merge
    if (stepType === 'think' || stepType === 'thinking') {
      const lastThinkItem = stepItems.filter(item => item.type === 'thinking').pop();
      if (lastThinkItem && step.timestamp <= lastThinkItem.endTime!) {
        continue;
      }

      let blockEndIdx = i;
      for (let j = i + 1; j < trace.length; j++) {
        if (trace[j].type === 'think' || trace[j].type === 'thinking') {
          blockEndIdx = j;
        } else {
          break;
        }
      }

      const startTime = step.timestamp;
      const endTime = trace[blockEndIdx].timestamp;
      const relativeTime = (startTime - baseTimestamp) / 1000;
      const timeWidth = endTime - startTime;
      const left = totalDuration > 0 ? (relativeTime / (totalDuration / 1000)) * 100 : 0;
      const width = totalDuration > 0 && timeWidth > 0
        ? Math.max(1, (timeWidth / totalDuration) * 100)
        : 2;

      let thinkContent = '';
      for (let j = i; j <= blockEndIdx; j++) {
        if ((trace[j].type === 'think' || trace[j].type === 'thinking') && trace[j].content) {
          thinkContent += trace[j].content;
        }
      }

      const item: TodoItem = {
        id: `${conversationId}-think-${i}`,
        title: 'Thinking',
        type: 'thinking',
        status: isComplete ? 'completed' : 'running',
        relativeTime,
        startTime,
        endTime,
        conversationId,
        conversationIndex,
        parentId: conversationId,
        left: Math.max(0, Math.min(98, left)),
        width,
        duration: timeWidth || 1,
        totalDuration,
        traceData: {
          type: step.type,
          timestamp: step.timestamp,
          content: thinkContent || step.content,
        },
      };

      stepItems.push(item);
      conversationItem.children = conversationItem.children || [];
      conversationItem.children.push(item);
      continue;
    }

    // tool_call + tool_result paired
    if (stepType === 'tool_call') {
      const startTime = step.timestamp;
      let endTime: number | undefined;
      let depth = 1;
      for (let j = i + 1; j < trace.length; j++) {
        if (trace[j].type === 'tool_call') depth++;
        if (trace[j].type === 'tool_result') {
          depth--;
          if (depth === 0) {
            endTime = trace[j].timestamp;
            break;
          }
        }
      }
      const duration = endTime ? endTime - startTime : undefined;
      const nextStep = trace[i + 1];

      const relativeTime = (startTime - baseTimestamp) / 1000;
      const left = totalDuration > 0 ? (relativeTime / (totalDuration / 1000)) * 100 : 0;
      const width = totalDuration > 0 && duration ? (duration / totalDuration) * 100 : 2;

      const item: TodoItem = {
        id: `${conversationId}-tool-${i}`,
        title: 'Tool',
        type: 'tool_call',
        status: isComplete || nextStep?.type === 'tool_result' ? 'completed' : 'running',
        relativeTime,
        startTime,
        endTime,
        conversationId,
        conversationIndex,
        parentId: conversationId,
        left: Math.max(0, Math.min(98, left)),
        width: Math.max(1, width),
        duration: duration || 1,
        totalDuration,
        traceData: {
          type: step.type,
          timestamp: step.timestamp,
          tool_name: step.tool_name,
          parameters: step.parameters,
          status: step.status,
          result: nextStep?.result,
        },
      };

      stepItems.push(item);
      conversationItem.children = conversationItem.children || [];
      conversationItem.children.push(item);
      continue;
    }

    // tool_result skipped (already handled in tool_call)
    if (stepType === 'tool_result') {
      continue;
    }
  }

  return { conversationItem, stepItems };
}

/**
 * Build TodoItem array from multiple conversations.
 *
 * Each conversation produces a conversation root node plus its step children.
 * The flat array structure matches what TodoList expects.
 */
export function buildTodoItemsFromConversations(
  conversations: ConversationInput[],
): TodoItem[] {
  const allItems: TodoItem[] = [];

  for (const conversation of conversations) {
    const { conversationItem, stepItems } = buildTodoItemsForConversation(conversation);
    allItems.push(conversationItem, ...stepItems);
  }

  return allItems;
}
