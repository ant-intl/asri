import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Typography, message, Button, Tooltip, Modal, Input, Space } from 'antd';
import { CheckCircleOutlined, CameraOutlined } from '@ant-design/icons';
import MessageList from './MessageList';
import InputArea from './InputArea';
import TodoList from './TodoList';
import type { TodoItem } from './TodoList';
import { useChatStore } from '@/stores/chatStore';
import { getSessionMessages } from '@/api/session';
import { sendChat, sendChatStream, parseWebSocketMessage, interruptChat } from '@/api/chat';
import { initPollChat, pollChatChunks, cancelPollChat } from '@/api/pollChat';
import { createSnapshot } from '@/api/snapshot';
import type { Message, StreamChunk, WebSocketMessage, TraceItem } from '@/types/chat';
import { getConnectionSettings, getInteractionSettings, getSessionSettings } from '@/components/Admin/SessionSettingsContent';
import { inferTotalDuration, calculateTimelinePosition } from '@/types/traceConfig';
import ToolConfirmModal from './ToolConfirmModal';
import type { ToolConfirmRequest } from '@/types/hook';
import { confirmTool } from '@/api/hook';
import styles from './ChatWindow.module.css';

const { Title, Text } = Typography;

// Accumulated content for streaming
interface StreamingState {
  content: string;
  trace: TraceItem[];
  cards: Record<string, unknown>[];
}

const ChatWindow: React.FC = () => {
  const {
    currentSession,
    sessionToken,
    addMessage,
    setIsStreaming,
    appendStreamingContent,
    clearStreamingContent,
    messages,
    isStreaming,
    abortController,
    setAbortController,
    clearMessages,
    sidebarCollapsed,
    currentPollingMessageId,
    setCurrentPollingMessageId,
    isPolling,
    setIsPolling,
  } = useChatStore();

  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [showTodoList, setShowTodoList] = useState(true);
  const [todoExpanded, setTodoExpanded] = useState(false);
  const [streamingTrace, setStreamingTrace] = useState<TraceItem[]>([]);
  const [todoItems, setTodoItems] = useState<TodoItem[]>([]);
  const [highlightedConversationId, setHighlightedConversationId] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const streamingStateRef = useRef<StreamingState>({ content: '', trace: [], cards: [] });
  const sendStartTimeRef = useRef<number>(0);
  const currentStreamingMessageRef = useRef<string>(''); // Track the message being streamed
  const [confirmData, setConfirmData] = useState<ToolConfirmRequest | null>(null);
  const confirmSentRef = useRef<Set<string>>(new Set());
  const confirmClearTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const messageListRef = useRef<HTMLDivElement>(null);
  const [showSnapshotModal, setShowSnapshotModal] = useState(false);
  const [snapshotName, setSnapshotName] = useState('');
  const [snapshotDesc, setSnapshotDesc] = useState('');
  const [savingSnapshot, setSavingSnapshot] = useState(false);

  // Send tool confirm response - use WebSocket if open, otherwise HTTP
  const sendToolConfirmResponse = useCallback((confirmationId: string, approved: boolean) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'tool_confirm_response',
        confirmation_id: confirmationId,
        approved,
      }));
    } else {
      confirmTool(confirmationId, approved);
    }
  }, []);

  const handleToolConfirm = useCallback((confirmationId: string, approved: boolean) => {
    if (confirmSentRef.current.has(confirmationId)) return;
    confirmSentRef.current.add(confirmationId);
    sendToolConfirmResponse(confirmationId, approved);
    // Clear previous auto-clear timeout to avoid overwriting a newer confirmData
    if (confirmClearTimeoutRef.current) {
      clearTimeout(confirmClearTimeoutRef.current);
    }
    // Auto-clear after 3s so user can see the feedback
    confirmClearTimeoutRef.current = setTimeout(() => {
      setConfirmData(null);
      confirmClearTimeoutRef.current = null;
    }, 3000);
  }, [sendToolConfirmResponse]);

  const handleToolConfirmTimeout = useCallback((confirmationId: string) => {
    if (!confirmationId || confirmSentRef.current.has(confirmationId)) return;
    confirmSentRef.current.add(confirmationId);
    sendToolConfirmResponse(confirmationId, false);
    // Clear previous auto-clear timeout to avoid overwriting a newer confirmData
    if (confirmClearTimeoutRef.current) {
      clearTimeout(confirmClearTimeoutRef.current);
    }
    // Auto-clear after 3s so user can see the timeout feedback
    confirmClearTimeoutRef.current = setTimeout(() => {
      setConfirmData(null);
      confirmClearTimeoutRef.current = null;
    }, 3000);
  }, [sendToolConfirmResponse]);

  // Auto-scroll to bottom when confirmation card appears
  useEffect(() => {
    if (confirmData && messageListRef.current) {
      // Delay to wait for DOM rendering
      setTimeout(() => {
        if (messageListRef.current) {
          messageListRef.current.scrollTop = messageListRef.current.scrollHeight;
        }
      }, 100);
    }
  }, [confirmData]);

  // Handler for message click - highlight corresponding conversation in TodoList
  const handleMessageClick = useCallback((conversationId: string) => {
    if (!showTodoList) return;
    setHighlightedConversationId(conversationId);
    // Clear highlight after 3 seconds
    setTimeout(() => setHighlightedConversationId(null), 3000);
  }, [showTodoList]);

  // Get current trace - prioritize streaming trace for real-time display
  // When streaming, use streamingTrace; otherwise use the last message's trace
  // Filter out 'answer' type traces (these are shown in chat content, not thinking panel)
  const lastMessageTrace = messages.length > 0 ? messages[messages.length - 1].trace : undefined;
  // Use streamingTrace if available (during or right after streaming), otherwise use message trace
  const rawTrace = streamingTrace.length > 0 ? streamingTrace : lastMessageTrace;


  // Load session messages when session changes
  useEffect(() => {
    if (currentSession) {
      loadMessages();
      // Clear TodoList (since clearMessages is called when creating a new session, but TodoList is not automatically cleared)
      setTodoItems([]);
      conversationIndexRef.current = 0;
    }
  }, [currentSession?.session_id]);

  const loadMessages = async () => {
    if (!currentSession) return;

    setHistoryLoading(true);
    try {
      const response = await getSessionMessages(currentSession.session_id, undefined, sessionToken || undefined);
      const messages: Message[] = response.messages.map((msg, index) => ({
        id: msg.message_id || `msg-${index}`,
        role: msg.role as 'user' | 'assistant' | 'system',
        content: msg.content,
        message_type: msg.message_type as 'text' | 'thought' | 'action' | 'observation',
        timestamp: msg.gmt_create,
        metadata: msg.metadata,
        trace: msg.metadata?.trace as TraceItem[],
      }));
      useChatStore.getState().setMessages(messages);

      // Extract trace from history messages and update todoItems
      // Group by session, each assistant message corresponds to a conversation
      const assistantMessages = messages.filter(m => m.role === 'assistant' && m.trace && m.trace.length > 0);
      if (assistantMessages.length > 0) {
        // Reset conversation index
        conversationIndexRef.current = 0;
        // Clear existing todoItems
        setTodoItems([]);

        // Create conversation for each assistant message
        const userMessages = messages.filter(m => m.role === 'user');
        assistantMessages.forEach((msg, idx) => {
          // Get corresponding user message as title
          const userMsg = userMessages[idx] || userMessages[userMessages.length - 1];
          currentConversationInputRef.current = userMsg?.content || '';

          // New conversation marker
          updateTodoItemsFromTrace(msg.trace || [], true, true);
        });
      }
    } catch (error) {
      console.error('Failed to load messages:', error);
    } finally {
      setHistoryLoading(false);
    }
  };

  // Cleanup WebSocket on unmount
  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  // Handle clear chat
  const handleClear = useCallback(() => {
    // Clear messages
    clearMessages();
    // Clear todo items
    setTodoItems([]);
    // Reset conversation index
    conversationIndexRef.current = 0;
    // Clear streaming state if any
    setStreamingTrace([]);
    streamingStateRef.current = { content: '', trace: [], cards: [] };
    setIsStreaming(false);
    clearStreamingContent();
  }, [clearMessages, setStreamingTrace, setIsStreaming, clearStreamingContent]);

  // Current conversation index for grouping
  const conversationIndexRef = useRef<number>(0);
  // Store current conversation user input for display
  const currentConversationInputRef = useRef<string>('');

  // Helper to truncate text for display (show first ~30 chars of user question)
  const truncateText = (text: string, maxLength: number = 30): string => {
    if (!text) return '';
    // Trim whitespace and newlines
    const trimmed = text.trim().replace(/\n/g, ' ');
    if (trimmed.length <= maxLength) return trimmed;
    return trimmed.substring(0, maxLength) + '...';
  };

  // Convert trace to todo items for visualization with conversation grouping
  // Message type grouping:
  // - Paired messages: tool_call+tool_result (merged into one entry), llm_start+llm_end (merged into one entry)
  // - Independent messages: thinking, answer (consecutive ones merged into one)
  const updateTodoItemsFromTrace = useCallback((trace: TraceItem[], isNewConversation: boolean = false, isComplete: boolean = false) => {
    setTodoItems((prevItems) => {
      // If new conversation, increment index
      if (isNewConversation) {
        // First abort all running items in previous conversations (including children/steps)
        const markAllRunningAsInterrupted = (items: TodoItem[]) => {
          items.forEach(item => {
            if (item.status === 'running') {
              item.status = 'interrupted';
            }
            // Recursively mark children
            if (item.children) {
              markAllRunningAsInterrupted(item.children);
            }
          });
        };
        markAllRunningAsInterrupted(prevItems);
        conversationIndexRef.current += 1;
      }
      const currentConversationIndex = conversationIndexRef.current;

      const newItems: TodoItem[] = [];
      const conversationId = `conversation-${currentConversationIndex}`;

      // Get base timestamp (minimum timestamp from all trace items) for relative time calculation
      // Use the minimum timestamp to ensure relativeTime is never negative
      const baseTimestamp = trace.length > 0
        ? Math.min(...trace.map(t => t.timestamp))
        : Date.now();

      // Calculate total duration for Gantt-style positioning
      const totalDuration = inferTotalDuration(trace);

      // Create conversation root node with user input as title
      const conversationTitle = currentConversationInputRef.current
        ? truncateText(currentConversationInputRef.current)
        : `Conversation ${currentConversationIndex}`;

      // Check if any step in previous items was interrupted (for current conversation)
      const hasInterruptedStep = prevItems.some(
        item => item.conversationId === conversationId && item.status === 'interrupted'
      );

      // Check if trace contains interrupted signal
      const hasInterruptedTrace = trace.some(t => t.type === 'interrupted');

      // Conversation status: interrupted if any step was interrupted, otherwise completed/running
      const conversationStatus = hasInterruptedStep || hasInterruptedTrace
        ? 'interrupted'
        : (isComplete ? 'completed' : 'running');

      // Calculate conversation end time
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
        conversationIndex: currentConversationIndex,
        children: [],
        // Gantt-style positioning
        left: 0,
        width: 100,
        totalDuration,
        duration: totalDuration,
      };

      // Process trace items: group paired and consecutive items
      // Correct grouping logic:
      // 1. think/thinking displayed as "Thinking"
      // 2. tool_call + tool_result paired → display as "Tool"
      // 3. answer displayed as "Answer"

      // Iterate through trace, create entries
      for (let i = 0; i < trace.length; i++) {
        const step = trace[i];
        const stepType = step.type;

        // llm_start + llm_end paired → display as "LLM Call"
        if (stepType === 'llm_start') {
          const startTime = step.timestamp;
          // Find matching llm_end
          let endTime: number | undefined;
          let endData: TraceItem | undefined;
          for (let j = i + 1; j < trace.length; j++) {
            if (trace[j].type === 'llm_end') {
              endTime = trace[j].timestamp;
              endData = trace[j];
              break;
            }
            // If we hit another llm_start, stop looking (no matching llm_end found)
            if (trace[j].type === 'llm_start') {
              break;
            }
          }
          const duration = endTime ? endTime - startTime : undefined;
          const relativeTime = (startTime - baseTimestamp) / 1000;
          const left = totalDuration > 0 ? (relativeTime / (totalDuration / 1000)) * 100 : 0;
          const width = totalDuration > 0 && duration ? (duration / totalDuration) * 100 : 2;

          const item: TodoItem = {
            id: `${conversationId}-llm-${i}`,
            title: step.model || 'LLM Call',
            type: 'llm_call',
            status: endData ? 'completed' : 'running',
            relativeTime,
            startTime,
            endTime,
            conversationId,
            conversationIndex: currentConversationIndex,
            parentId: conversationId,
            left: Math.max(0, Math.min(98, left)),
            width: Math.max(1, width),
            duration: duration || 1,
            totalDuration,
            traceData: {
              type: 'llm_call',
              timestamp: startTime,
              model: step.model,
              provider: step.provider,
              duration_ms: endData?.duration_ms || duration,
              prompt_tokens: endData?.prompt_tokens,
              completion_tokens: endData?.completion_tokens,
              total_tokens: endData?.total_tokens,
              cached_tokens: endData?.cached_tokens,
              finish_reason: endData?.finish_reason,
              status: endData ? 'success' : 'calling',
            },
          };

          newItems.push(item);
          conversationItem.children = conversationItem.children || [];
          conversationItem.children.push(item);
          continue;
        }

        // llm_end skipped (already handled in llm_start)
        if (stepType === 'llm_end') {
          continue;
        }

        // answer consecutive message block merge - find range of consecutive answer messages
        if (stepType === 'answer') {
          // Check if already covered by previous consecutive block (skip subsequent messages of consecutive block)
          const lastAnswerItem = newItems.filter(item => item.type === 'answer').pop();
          if (lastAnswerItem && step.timestamp <= lastAnswerItem.endTime!) {
            continue;
          }

          // Find end position of consecutive answer message block
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

          // Collect all content from consecutive answer blocks
          let answerContent = '';
          for (let j = i; j <= blockEndIdx; j++) {
            if (trace[j].type === 'answer' && trace[j].content) {
              answerContent += trace[j].content;
            }
          }

          // Answer type always shows "Answer" as title, content is only visible in expanded detail panel
          const answerTitle = 'Answer';

          const item: TodoItem = {
            id: `${conversationId}-answer-${i}`,
            title: answerTitle,
            type: 'answer',
            status: isComplete ? 'completed' : 'running',
            relativeTime,
            startTime,
            endTime,
            conversationId,
            conversationIndex: currentConversationIndex,
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

          newItems.push(item);
          conversationItem.children = conversationItem.children || [];
          conversationItem.children.push(item);
          continue;
        }
        
        // think/thinking consecutive message block merge
        if (stepType === 'think' || stepType === 'thinking') {
          // Check if already covered by previous consecutive block
          const lastThinkItem = newItems.filter(item => item.type === 'thinking').pop();
          if (lastThinkItem && step.timestamp <= lastThinkItem.endTime!) {
            continue;
          }
          
          // Find end position of consecutive think message block
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

          const item: TodoItem = {
            id: `${conversationId}-think-${i}`,
            title: 'Thinking',
            type: 'thinking',
            status: isComplete ? 'completed' : 'running',
            relativeTime,
            startTime,
            endTime,
            conversationId,
            conversationIndex: currentConversationIndex,
            parentId: conversationId,
            left: Math.max(0, Math.min(98, left)),
            width,
            duration: timeWidth || 1,
            totalDuration,
            traceData: {
              type: step.type,
              timestamp: step.timestamp,
              content: step.content,
            },
          };

          newItems.push(item);
          conversationItem.children = conversationItem.children || [];
          conversationItem.children.push(item);
          continue;
        }
        
        // tool_call + tool_result paired - use corresponding tool_result timestamp as end time
        if (stepType === 'tool_call') {
          const startTime = step.timestamp;
          // Find matching tool_result
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
          // Width calculated based on actual time range
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
            conversationIndex: currentConversationIndex,
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

          newItems.push(item);
          conversationItem.children = conversationItem.children || [];
          conversationItem.children.push(item);
          continue;
        }
        
        // tool_result skipped (already handled in tool_call)
        if (stepType === 'tool_result') {
          continue;
        }
      }

      // Remove old items from the same conversation (if updating)
      const filteredPrevItems = prevItems.filter(
        item => item.conversationIndex !== currentConversationIndex
      );

      // Return filtered items plus new conversation
      return [...filteredPrevItems, conversationItem, ...newItems];
    });
  }, []);

  // Helper to get trace label
  const getTraceLabel = (step: TraceItem): string => {
    switch (step.type) {
      case 'thinking':
      case 'think':
        return 'Thinking';
      case 'tool_call':
        return step.tool_name || 'Call Tool';
      case 'tool_result':
        return step.tool_name ? `${step.tool_name} Result` : 'Tool Result';
      default:
        return step.type;
    }
  };

  // Update todo items when trace changes during streaming
  useEffect(() => {
    if (streamingTrace.length > 0 && isStreaming) {
      // Update with running status during streaming
      updateTodoItemsFromTrace(streamingTrace, false, false);
    }
  }, [streamingTrace, isStreaming, updateTodoItemsFromTrace]);

  const handleSend = useCallback(async (content: string) => {
    // Check if session exists
    const sessionId = currentSession?.session_id;
    if (!sessionId) {
      message.warning('Please create a session first');
      return;
    }

    // Record send start time for latency calculation
    sendStartTimeRef.current = Date.now();

    // Get connection settings from SessionSettings
    const { connectionType, isStream, httpStreamingMode } = getConnectionSettings();

    // Store user input for conversation title
    currentConversationInputRef.current = content;

    // Check if currently streaming or loading - if so, trigger interrupt
    if (isStreaming || loading) {
      // User is interrupting an ongoing request
      message.info('Interrupting current response, merging your new message...');

      // Get current trace from both state and ref (use whichever has data)
      const currentTrace = streamingTrace.length > 0 ? streamingTrace : streamingStateRef.current.trace;
      const currentContent = streamingStateRef.current.content || streamingContent;

      // Create an interrupted assistant message with complete trace
      // Add interrupted assistant message FIRST to maintain proper conversation order
      if (currentContent || currentTrace.length > 0) {
        const interruptedMessage: Message = {
          id: `interrupted-${Date.now()}`,
          role: 'assistant',
          content: currentContent || '',
          message_type: 'text',
          timestamp: new Date().toISOString(),
          trace: currentTrace.length > 0 ? currentTrace : undefined,
          metadata: { interrupted: true },
        };
        addMessage(interruptedMessage);
      }

      // Add the interrupt user message AFTER the interrupted assistant message
      // This ensures proper user-reply-user-reply alternating display
      const interruptUserMessage: Message = {
        id: `user-interrupt-${Date.now()}`,
        role: 'user',
        content,
        message_type: 'text',
        timestamp: new Date().toISOString(),
      };
      addMessage(interruptUserMessage);

      // Abort ongoing HTTP request if exists
      if (abortController) {
        abortController.abort();
        setAbortController(null);
      }

      // Cancel ongoing polling task if exists
      if (currentPollingMessageId) {
        try {
          await cancelPollChat(currentPollingMessageId, sessionToken || undefined);
        } catch (error) {
          console.error('Failed to cancel polling:', error);
        }
        setCurrentPollingMessageId(null);
        setIsPolling(false);
      }

      // Reset streaming state first
      setIsStreaming(false);
      clearStreamingContent();
      setStreamingTrace([]);
      streamingStateRef.current = { content: '', trace: [], cards: [] };

      // Close WebSocket if exists
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }

      // Mark current running tasks as interrupted
      // Recursively update all items including nested children
      const markAllInterrupted = (items: TodoItem[]): TodoItem[] => {
        return items.map((item) => {
          const updatedItem: TodoItem = {
            ...item,
            status: item.status === 'running' ? 'interrupted' : item.status,
          };
          if (item.children && item.children.length > 0) {
            updatedItem.children = markAllInterrupted(item.children);
          }
          return updatedItem;
        });
      };
      setTodoItems((prevItems) => markAllInterrupted(prevItems));

      // Send interrupt signal to backend
      try {
        await interruptChat(sessionId, content, sessionToken || undefined);
      } catch (error) {
        console.error('Failed to send interrupt signal:', error);
      }

      // Send new message directly (no merging)
      // The backend will load context from previous messages automatically
      console.log('[Interrupt] Sending new message:', content);

      // Reset loading state since we're starting a new request
      setLoading(false);

      // Increment conversation index for the new conversation
      conversationIndexRef.current += 1;

      // Send new message directly without merging
      if (connectionType === 'websocket') {
        handleWebSocketChat(sessionId, content);
      } else if (isStream && httpStreamingMode === 'polling') {
        handleHttpPollingChat(sessionId, content);
      } else {
        handleHttpChat(sessionId, content);
      }
      return;
    }

    // Increment conversation index for new conversation (non-interrupt case)
    conversationIndexRef.current += 1;

    // Add user message
    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content,
      message_type: 'text',
      timestamp: new Date().toISOString(),
    };
    addMessage(userMessage);

    if (connectionType === 'websocket') {
      // WebSocket mode
      handleWebSocketChat(sessionId, content);
    } else if (isStream && httpStreamingMode === 'polling') {
      // HTTP Long Polling mode
      handleHttpPollingChat(sessionId, content);
    } else {
      // HTTP/SSE mode
      handleHttpChat(sessionId, content);
    }
  }, [currentSession, isStreaming, loading, sessionToken, abortController]);

  // Listen for card button click events to send messages
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      // Only handle global events without sourceId (Playground window has its own handler)
      if (detail?.content && !detail?.sourceId) {
        handleSend(detail.content);
      }
    };
    window.addEventListener('asri:send-message', handler);
    return () => window.removeEventListener('asri:send-message', handler);
  }, [handleSend]);

  // Process SSE chunk
  const processStreamChunk = (chunk: StreamChunk, state: StreamingState): string => {
    switch (chunk.type) {
      case 'thinking':
      case 'think': {
        // Accumulate think content into a single trace item
        const lastTrace = state.trace[state.trace.length - 1];
        if (lastTrace && (lastTrace.type === 'thinking' || lastTrace.type === 'think')) {
          // Append to existing think trace item
          lastTrace.content = (lastTrace.content || '') + (chunk.content || '');
          lastTrace.timestamp = chunk.timestamp || Date.now();
        } else {
          // Create new think trace item (first chunk or after non-think step)
          state.trace.push({
            type: chunk.type === 'think' ? 'think' : 'thinking',
            content: chunk.content || '',
            timestamp: chunk.timestamp || Date.now(),
          });
        }
        setStreamingTrace([...state.trace]);
        return '';
      }
      case 'tool_call':
        state.trace.push({
          type: 'tool_call',
          status: 'calling',
          tool_name: chunk.tool_name,
          parameters: chunk.parameters,
          tool_call_id: chunk.tool_call_id,
          timestamp: chunk.timestamp || Date.now(),
        });
        // Update streaming trace state for real-time display
        setStreamingTrace([...state.trace]);
        return '';
      case 'tool_result':
        state.trace.push({
          type: 'tool_result',
          status: chunk.status || 'success',
          tool_name: chunk.tool_name,
          result: chunk.result,
          tool_call_id: chunk.tool_call_id,
          timestamp: chunk.timestamp || Date.now(),
        });
        // Update streaming trace state for real-time display
        setStreamingTrace([...state.trace]);
        return '';
      case 'llm_start':
        state.trace.push({
          type: 'llm_start',
          llm_id: chunk.llm_id,
          model: chunk.model,
          provider: chunk.provider,
          timestamp: chunk.timestamp || Date.now(),
        });
        setStreamingTrace([...state.trace]);
        return '';
      case 'llm_end':
        state.trace.push({
          type: 'llm_end',
          duration_ms: chunk.duration_ms,
          prompt_tokens: chunk.prompt_tokens,
          completion_tokens: chunk.completion_tokens,
          total_tokens: chunk.total_tokens,
          cached_tokens: chunk.cached_tokens,
          finish_reason: chunk.finish_reason,
          timestamp: chunk.timestamp || Date.now(),
        });
        setStreamingTrace([...state.trace]);
        return '';
      case 'tool_confirm_request':
        confirmSentRef.current.clear();
        // Clear auto-clear timeout so it doesn't overwrite this new confirmation
        if (confirmClearTimeoutRef.current) {
          clearTimeout(confirmClearTimeoutRef.current);
          confirmClearTimeoutRef.current = null;
        }
        setConfirmData(chunk as unknown as ToolConfirmRequest);
        return '';
      case 'answer': {
        const content = chunk.content || '';
        // Accumulate answer content into trace for timeline display
        const lastTrace = state.trace[state.trace.length - 1];
        if (lastTrace && lastTrace.type === 'answer') {
          // Append to existing answer trace item
          lastTrace.content = (lastTrace.content || '') + content;
          lastTrace.timestamp = chunk.timestamp || Date.now();
        } else {
          // Create new answer trace item (first chunk or after non-answer step)
          state.trace.push({
            type: 'answer',
            content: content,
            timestamp: chunk.timestamp || Date.now(),
          });
        }
        setStreamingTrace([...state.trace]);
        return content;
      }
      case 'card': {
        if (chunk.card_data) {
          state.cards.push(chunk.card_data);
        }
        return '';
      }
      default:
        return '';
    }
  };

  const handleHttpChat = async (sessionId: string, content: string) => {
    setLoading(true);
    const { isStream } = getConnectionSettings();
    const { toolInterruptStrategy, maxInteractionRounds } = getInteractionSettings();
    const config = { interrupt_strategy: toolInterruptStrategy, max_iterations: maxInteractionRounds };

    if (isStream) {
      // Use SSE streaming for HTTP mode
      setIsStreaming(true);
      clearStreamingContent();
      setStreamingTrace([]);
      streamingStateRef.current = { content: '', trace: [], cards: [] };
      currentStreamingMessageRef.current = content;

      try {
        const streamResult = sendChatStream(
          {
            session_id: sessionId,
            message: content,
            stream: true,
            config,
          },
          sessionToken || undefined,
          (chunk) => {
            // On message chunk received
            const textChunk = processStreamChunk(chunk, streamingStateRef.current);
            if (textChunk) {
              streamingStateRef.current.content += textChunk;
              appendStreamingContent(textChunk);
            }
          },
          () => {
            // On done - add the complete message
            const finalContent = streamingStateRef.current.content || useChatStore.getState().streamingContent;
            const finalTrace = streamingStateRef.current.trace;
            const assistantMessage: Message = {
              id: `sse-${Date.now()}`,
              role: 'assistant',
              content: finalContent,
              message_type: 'text',
              timestamp: new Date().toISOString(),
              trace: finalTrace.length > 0 ? finalTrace : undefined,
              metadata: streamingStateRef.current.cards.length > 0
                ? { cards: streamingStateRef.current.cards }
                : undefined,
            };
            addMessage(assistantMessage);

            // Update todo items with completed status before clearing
            if (finalTrace.length > 0) {
              updateTodoItemsFromTrace(finalTrace, false, true);
            }

            // Reset all states
            setLoading(false);
            setIsStreaming(false);
            clearStreamingContent();
            setStreamingTrace([]);
            streamingStateRef.current = { content: '', trace: [], cards: [] };
          },
          (error) => {
            // On error - check if it's an abort (interrupt)
            if (error.name === 'AbortError') {
              console.log('Stream aborted for interrupt');
              return;
            }
            console.error('Chat error:', error);
            message.error(error.message || 'Failed to send message');
            setLoading(false);
            setIsStreaming(false);
            clearStreamingContent();
            setStreamingTrace([]);
            streamingStateRef.current = { content: '', trace: [], cards: [] };
          }
        );

        // Store abort controller for potential interrupt
        setAbortController({ abort: streamResult.abort });
      } catch (error: unknown) {
        console.error('Chat error:', error);
        const errorMessage = error instanceof Error ? error.message : 'Failed to send message';
        message.error(errorMessage);
        setLoading(false);
        setIsStreaming(false);
        clearStreamingContent();
        setStreamingTrace([]);
        streamingStateRef.current = { content: '', trace: [], cards: [] };
      }
    } else {
      // Use non-streaming HTTP request
      try {
        const response = await sendChat({
          session_id: sessionId,
          message: content,
          stream: false,
          config,
        }, sessionToken || undefined);

        // Add assistant message
        const assistantMessage: Message = {
          id: response.message_id,
          role: 'assistant',
          content: response.content,
          message_type: 'text',
          timestamp: new Date().toISOString(),
          trace: response.trace,
          usage: response.usage,
        };
        addMessage(assistantMessage);
      } catch (error: unknown) {
        console.error('Chat error:', error);
        const errorMessage = error instanceof Error ? error.message : 'Failed to send message';
        message.error(errorMessage);
      } finally {
        setLoading(false);
      }
    }
  };

  // HTTP Long Polling chat - simulates streaming via multiple HTTP requests
  const handleHttpPollingChat = async (sessionId: string, content: string) => {
    setLoading(true);
    setIsStreaming(true);
    clearStreamingContent();
    setStreamingTrace([]);
    streamingStateRef.current = { content: '', trace: [], cards: [] };
    currentStreamingMessageRef.current = content;

    const { toolInterruptStrategy, maxInteractionRounds } = getInteractionSettings();
    const config = { interrupt_strategy: toolInterruptStrategy, max_iterations: maxInteractionRounds };

    let pollingRef = { current: true }; // Track polling state locally

    try {
      // Step 1: Init polling task
      const initResponse = await initPollChat(
        {
          session_id: sessionId,
          message: content,
          config,
        },
        sessionToken || undefined,
      );

      const userMessageId = initResponse.user_message_id;
      setCurrentPollingMessageId(userMessageId);
      setIsPolling(true);

      // Step 2: Poll for chunks in a loop
      let lastOffset = 0;
      let isDone = false;

      while (pollingRef.current && !isDone) {
        const pollResponse = await pollChatChunks(
          userMessageId,
          { last_offset: lastOffset, timeout: 30 },
          sessionToken || undefined,
        );

        // Process each chunk
        for (const chunk of pollResponse.chunks) {
          const streamChunk: StreamChunk = {
            ...chunk,
            timestamp: chunk.timestamp || Date.now(),
          };

          const textChunk = processStreamChunk(streamChunk, streamingStateRef.current);
          if (textChunk) {
            streamingStateRef.current.content += textChunk;
            appendStreamingContent(textChunk);
          }
        }

        lastOffset = pollResponse.offset;

        // Check if done
        if (pollResponse.status === 'done') {
          isDone = true;

          // Build final message
          const finalContent = streamingStateRef.current.content;
          const finalTrace = streamingStateRef.current.trace;

          const assistantMessage: Message = {
            id: pollResponse.assistant_message_id || `poll-${Date.now()}`,
            role: 'assistant',
            content: finalContent,
            message_type: 'text',
            timestamp: new Date().toISOString(),
            trace: finalTrace.length > 0 ? finalTrace : undefined,
            usage: pollResponse.usage,
            metadata: streamingStateRef.current.cards.length > 0
              ? { cards: streamingStateRef.current.cards }
              : undefined,
          };
          addMessage(assistantMessage);

          // Update todo items
          if (finalTrace.length > 0) {
            updateTodoItemsFromTrace(finalTrace, false, true);
          }

          // Reset state
          setLoading(false);
          setIsStreaming(false);
          setIsPolling(false);
          setCurrentPollingMessageId(null);
          clearStreamingContent();
          setStreamingTrace([]);
          streamingStateRef.current = { content: '', trace: [], cards: [] };
        } else if (pollResponse.status === 'error') {
          // Error case
          message.error(pollResponse.error || 'Polling error');
          setLoading(false);
          setIsStreaming(false);
          setIsPolling(false);
          setCurrentPollingMessageId(null);
          clearStreamingContent();
          setStreamingTrace([]);
          streamingStateRef.current = { content: '', trace: [], cards: [] };
          isDone = true;
        } else if (pollResponse.status === 'cancelled') {
          // Cancelled case
          setLoading(false);
          setIsStreaming(false);
          setIsPolling(false);
          setCurrentPollingMessageId(null);
          isDone = true;
        }
        // If status is 'running' and no chunks, loop continues (timeout case)
      }
    } catch (error: unknown) {
      console.error('Polling chat error:', error);
      const errorMessage = error instanceof Error ? error.message : 'Failed to send message';
      message.error(errorMessage);
      setLoading(false);
      setIsStreaming(false);
      setIsPolling(false);
      setCurrentPollingMessageId(null);
      clearStreamingContent();
      setStreamingTrace([]);
      streamingStateRef.current = { content: '', trace: [], cards: [] };
    }
  };

  // Process WebSocket message
  const processWebSocketMessage = (data: WebSocketMessage, state: StreamingState): string => {
    switch (data.type) {
      case 'thinking':
      case 'think': {
        // Accumulate think content into a single trace item
        const lastTrace = state.trace[state.trace.length - 1];
        if (lastTrace && (lastTrace.type === 'thinking' || lastTrace.type === 'think')) {
          // Append to existing think trace item
          lastTrace.content = (lastTrace.content || '') + (data.content || '');
          lastTrace.timestamp = data.timestamp || Date.now();
        } else {
          // Create new think trace item (first chunk or after non-think step)
          state.trace.push({
            type: data.type === 'think' ? 'think' : 'thinking',
            content: data.content || '',
            timestamp: data.timestamp || Date.now(),
          });
        }
        setStreamingTrace([...state.trace]);
        return '';
      }
      case 'tool_call':
        state.trace.push({
          type: 'tool_call',
          status: 'calling',
          tool_name: data.tool_name,
          parameters: data.parameters,
          tool_call_id: data.tool_call_id,
          timestamp: data.timestamp || Date.now(),
        });
        // Update streaming trace state for real-time display
        setStreamingTrace([...state.trace]);
        return '';
      case 'tool_result':
        state.trace.push({
          type: 'tool_result',
          status: data.status || 'success',
          tool_name: data.tool_name,
          result: data.result,
          tool_call_id: data.tool_call_id,
          timestamp: data.timestamp || Date.now(),
        });
        // Update streaming trace state for real-time display
        setStreamingTrace([...state.trace]);
        return '';
      case 'answer':
        return data.content || '';
      default:
        return '';
    }
  };

  const handleWebSocketChat = (sessionId: string, content: string) => {
    // Close existing connection
    if (wsRef.current) {
      wsRef.current.close();
    }

    const baseUrl = import.meta.env.VITE_API_BASE || window.location.origin;
    const wsBaseUrl = baseUrl.replace('http', 'ws');
    const wsUrl = new URL(`/ws/chat/${sessionId}/`, wsBaseUrl);
    if (sessionToken) {
      wsUrl.searchParams.set('token', sessionToken);
    }

    const ws = new WebSocket(wsUrl.toString());
    wsRef.current = ws;

    setIsStreaming(true);
    clearStreamingContent();
    setStreamingTrace([]);
    streamingStateRef.current = { content: '', trace: [], cards: [] };
    currentStreamingMessageRef.current = content;

    const { toolInterruptStrategy, maxInteractionRounds } = getInteractionSettings();
    const config = { interrupt_strategy: toolInterruptStrategy, max_iterations: maxInteractionRounds };

    ws.onopen = () => {
      // Send chat message with config
      ws.send(JSON.stringify({ type: 'chat', message: content, config }));
    };

    ws.onmessage = (event) => {
      const data = parseWebSocketMessage(event.data);
      if (!data) {
        console.error('Failed to parse WebSocket message');
        return;
      }

      switch (data.type) {
        case 'connected':
          // Connection established, do nothing
          break;
        case 'thinking':
        case 'think':
        case 'tool_call':
        case 'tool_result':
          processWebSocketMessage(data, streamingStateRef.current);
          break;
        case 'llm_start':
          streamingStateRef.current.trace.push({
            type: 'llm_start',
            llm_id: data.llm_id,
            model: data.model,
            provider: data.provider,
            timestamp: data.timestamp || Date.now(),
          });
          setStreamingTrace([...streamingStateRef.current.trace]);
          break;
        case 'llm_end':
          streamingStateRef.current.trace.push({
            type: 'llm_end',
            duration_ms: data.duration_ms,
            prompt_tokens: data.prompt_tokens,
            completion_tokens: data.completion_tokens,
            total_tokens: data.total_tokens,
            cached_tokens: data.cached_tokens,
            finish_reason: data.finish_reason,
            timestamp: data.timestamp || Date.now(),
          });
          setStreamingTrace([...streamingStateRef.current.trace]);
          break;
        case 'answer':
          const textChunk = data.content || '';
          streamingStateRef.current.content += textChunk;
          appendStreamingContent(textChunk);
          // Accumulate answer content into trace for timeline display
          const lastWsTrace = streamingStateRef.current.trace[streamingStateRef.current.trace.length - 1];
          if (lastWsTrace && lastWsTrace.type === 'answer') {
            // Append to existing answer trace item
            lastWsTrace.content = (lastWsTrace.content || '') + textChunk;
            lastWsTrace.timestamp = data.timestamp || Date.now();
          } else {
            // Create new answer trace item (first chunk or after non-answer step)
            streamingStateRef.current.trace.push({
              type: 'answer',
              content: textChunk,
              timestamp: data.timestamp || Date.now(),
            });
          }
          setStreamingTrace([...streamingStateRef.current.trace]);
          break;
        case 'card':
          if (data.card_data) {
            streamingStateRef.current.cards.push(data.card_data);
          }
          break;
        case 'done':
          // Convert streaming content to message
          const wsFinalContent = streamingStateRef.current.content || useChatStore.getState().streamingContent;
          const wsFinalTrace = streamingStateRef.current.trace;
          const wsAssistantMessage: Message = {
            id: `ws-${Date.now()}`,
            role: 'assistant',
            content: wsFinalContent,
            message_type: 'text',
            timestamp: new Date().toISOString(),
            trace: wsFinalTrace.length > 0 ? wsFinalTrace : undefined,
            metadata: streamingStateRef.current.cards.length > 0
              ? { cards: streamingStateRef.current.cards }
              : undefined,
          };
          addMessage(wsAssistantMessage);

          // Update todo items with completed status before clearing
          if (wsFinalTrace.length > 0) {
            updateTodoItemsFromTrace(wsFinalTrace, false, true);
          }

          // Reset all states
          setIsStreaming(false);
          clearStreamingContent();
          setStreamingTrace([]);
          streamingStateRef.current = { content: '', trace: [], cards: [] };

          ws.close();
          break;
        case 'interrupted':
          // Backend acknowledged the interrupt - prepare to receive merged response
          console.log('Stream interrupted by backend');
          break;
        case 'tool_confirm_request':
          confirmSentRef.current.clear();
          // Clear auto-clear timeout so it doesn't overwrite this new confirmation
          if (confirmClearTimeoutRef.current) {
            clearTimeout(confirmClearTimeoutRef.current);
            confirmClearTimeoutRef.current = null;
          }
          setConfirmData(data as unknown as ToolConfirmRequest);
          break;
        case 'error':
          console.error('WebSocket error:', data.content);
          message.error(data.content || 'Chat error');
          setIsStreaming(false);
          clearStreamingContent();
          setStreamingTrace([]);
          streamingStateRef.current = { content: '', trace: [], cards: [] };
          ws.close();
          break;
      }
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      message.error('WebSocket connection error');
      setIsStreaming(false);
      setStreamingTrace([]);
      streamingStateRef.current = { content: '', trace: [], cards: [] };
    };

    ws.onclose = () => {
      setIsStreaming(false);
    };
  };

  if (!currentSession) {
    return (
      <div className={styles.container} role="main" aria-label="Chat area">
        <div className={styles.welcome}>
          <Title level={2}>Welcome to ASRI</Title>
          <p>Create a new session from the left sidebar to start chatting</p>
        </div>
      </div>
    );
  }

  // ── Save Snapshot ─────────────────────────────────────────────────
  const handleSaveSnapshot = async () => {
    if (!currentSession || !snapshotName.trim()) return;
    setSavingSnapshot(true);
    try {
      const sessionSettings = getSessionSettings();
      await createSnapshot({
        session_id: currentSession.session_id,
        name: snapshotName.trim(),
        description: snapshotDesc.trim(),
        settings: {
          toolInterruptStrategy: sessionSettings.toolInterruptStrategy,
          connectionType: sessionSettings.connectionType,
          httpStreamingMode: sessionSettings.httpStreamingMode,
          execution_mode: sessionSettings.executionMode,
        },
      });
      message.success('Snapshot saved successfully');
      setShowSnapshotModal(false);
      setSnapshotName('');
      setSnapshotDesc('');
    } catch (e: any) {
      message.error(e?.response?.data?.error || 'Failed to save snapshot');
    } finally {
      setSavingSnapshot(false);
    }
  };

  return (
    <div className={styles.container} role="main" aria-label="Chat area">
      <div className={styles.main}>
        <section className={styles.chatArea} aria-label="Conversation area">
          <header className={styles.header}>
            <Title level={5} className={styles.title} id="chat-title">
              {currentSession.title || 'Current Conversation'}
            </Title>
            <div className={styles.headerActions}>
              <Tooltip title={showTodoList ? 'Hide task list' : 'Show task list'}>
                <Button
                  type="text"
                  size="small"
                  icon={<CheckCircleOutlined />}
                  onClick={() => setShowTodoList(!showTodoList)}
                  aria-label={showTodoList ? 'Hide task list' : 'Show task list'}
                  aria-pressed={showTodoList}
                />
              </Tooltip>
              <Tooltip title="Save as Snapshot">
                <Button
                  type="text"
                  size="small"
                  icon={<CameraOutlined />}
                  onClick={() => setShowSnapshotModal(true)}
                  aria-label="Save as Snapshot"
                />
              </Tooltip>
            </div>
          </header>
          <div className={styles.messageListWrapper} ref={messageListRef}>
            <MessageList
              loading={historyLoading}
              streamingTrace={isStreaming ? streamingTrace : undefined}
              sendStartTime={sendStartTimeRef.current}
              hideTraceDetails={showTodoList}
              onMessageClick={handleMessageClick}
            />
            {/* Inline tool confirmation card - inside scrollable area above input */}
            <ToolConfirmModal
              key={confirmData?.confirmation_id || 'empty'}
              confirmData={confirmData}
              onConfirm={handleToolConfirm}
              onTimeout={handleToolConfirmTimeout}
            />
          </div>
          {/* Input area - fixed at screen bottom, centered in chatArea */}
          <div className={`
            ${styles.inputAreaWrapper}
            ${sidebarCollapsed ? styles.inputAreaWrapperCollapsed : ''}
            ${!showTodoList ? styles.inputAreaWrapperFull : ''}
            ${showTodoList && !todoExpanded ? styles.inputAreaWrapperWithTodo : ''}
            ${showTodoList && todoExpanded ? styles.inputAreaWrapperWithTodoExpanded : ''}
          `.trim().replace(/\s+/g, ' ')}>
            <InputArea onSend={handleSend} onClear={handleClear} loading={loading} />
          </div>
        </section>
        {/* TodoPanel - same layout style as chatArea */}
        <div className={`${styles.todoPanel} ${!showTodoList ? styles.todoPanelHidden : ''} ${todoExpanded ? styles.todoPanelExpanded : ''}`}>
          <TodoList
            items={todoItems}
            isLoading={isStreaming && todoItems.length === 0}
            title="Execution Details"
            isExpanded={todoExpanded}
            onToggleExpand={() => setTodoExpanded(!todoExpanded)}
            highlightedConversationId={highlightedConversationId}
          />
        </div>
      </div>
      <Modal
        title="Save as Snapshot"
        open={showSnapshotModal}
        onOk={handleSaveSnapshot}
        onCancel={() => setShowSnapshotModal(false)}
        okText="Save"
        cancelText="Cancel"
        confirmLoading={savingSnapshot}
        okButtonProps={{ disabled: !snapshotName.trim() }}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <Text strong>Name</Text>
            <Input
              placeholder="Enter snapshot name"
              value={snapshotName}
              onChange={(e) => setSnapshotName(e.target.value)}
              status={!snapshotName.trim() && snapshotName !== '' ? 'error' : undefined}
            />
          </div>
          <div>
            <Text strong>Description</Text>
            <Input.TextArea
              placeholder="Optional description"
              value={snapshotDesc}
              onChange={(e) => setSnapshotDesc(e.target.value)}
              rows={3}
            />
          </div>
        </Space>
      </Modal>
    </div>
  );
};

export default ChatWindow;
