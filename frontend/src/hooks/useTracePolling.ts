/**
 * Hook for polling session trace data.
 *
 * Uses TanStack Query with dynamic refetchInterval:
 * - Polls every 2s while the session is streaming
 * - Polls every 5s when idle (to detect new conversations)
 *
 * Always fetches full data (no incremental after_id) to ensure
 * correctness — streaming messages keep receiving new trace items
 * but their gmt_modified is not updated by QuerySet.update().
 */

import { useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getSessionTrace, type ConversationTrace } from '@/api/trace';
import { buildTodoItemsFromConversations, type ConversationInput } from '@/utils/traceTransform';
import type { TodoItem } from '@/components/Chat/TodoList';

/** Fast polling interval during active streaming. */
const POLL_INTERVAL_MS = 100;
/** Slow polling interval when idle – keeps checking for new activity. */
const IDLE_POLL_INTERVAL_MS = 1000;

interface UseTracePollingResult {
  todoItems: TodoItem[];
  isStreaming: boolean;
  sessionTitle: string;
  isLoading: boolean;
  error: Error | null;
}

export function useTracePolling(sessionId: string): UseTracePollingResult {
  const [isStreaming, setIsStreaming] = useState(false);
  const [sessionTitle, setSessionTitle] = useState('');
  /** Version counter to trigger useMemo recomputation on each poll. */
  const [dataVersion, setDataVersion] = useState(0);

  /** Accumulated conversations map: assistant_message_id → ConversationTrace. */
  const conversationsRef = useRef<Map<string, ConversationTrace>>(new Map());

  const { isLoading, error } = useQuery({
    queryKey: ['trace', sessionId],
    queryFn: async () => {
      const data = await getSessionTrace(sessionId);

      // Update session metadata
      setSessionTitle(data.session_title);
      setIsStreaming(data.is_streaming);

      // Replace conversations with latest full snapshot
      conversationsRef.current.clear();
      for (const conv of data.conversations) {
        conversationsRef.current.set(conv.assistant_message_id, conv);
      }

      // Bump version to trigger useMemo recomputation
      setDataVersion(v => v + 1);
      return data;
    },
    refetchInterval: isStreaming ? POLL_INTERVAL_MS : IDLE_POLL_INTERVAL_MS,
    enabled: !!sessionId,
  });

  // Derive TodoItem[] from accumulated conversations
  const todoItems = useMemo(() => {
    const conversations: ConversationInput[] = [];
    let index = 1;

    // Sort by gmt_create to maintain order
    const sorted = Array.from(conversationsRef.current.values()).sort(
      (a, b) => new Date(a.gmt_create).getTime() - new Date(b.gmt_create).getTime(),
    );

    for (const conv of sorted) {
      conversations.push({
        userContent: conv.user_content,
        trace: conv.trace || [],
        isComplete: conv.stream_status !== 'streaming',
        conversationIndex: index++,
      });
    }

    return buildTodoItemsFromConversations(conversations);
  }, [dataVersion]);

  return {
    todoItems,
    isStreaming,
    sessionTitle,
    isLoading,
    error: error as Error | null,
  };
}
