import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  Card,
  Button,
  Typography,
  Space,
  Select,
  Empty,
  Badge,
  Tag,
  Modal,
  Input,
  message as antMessage,
  Spin,
} from 'antd';
import {
  PlusOutlined,
  DeleteOutlined,
  HistoryOutlined,
  SendOutlined,
  LoadingOutlined,
  ExclamationCircleOutlined,
  BulbOutlined,
  ThunderboltOutlined,
  SyncOutlined,
  LockOutlined,
  OrderedListOutlined,
  FileTextOutlined,
} from '@ant-design/icons';
import styles from './ChatCompare.module.css';
import { getSnapshots } from '@/api/snapshot';
import { createWebSocketChat, parseWebSocketMessage } from '@/api/chat';
import { createSession } from '@/api/session';
import type { SessionSnapshot } from '@/types/snapshot';
import type { TraceItem } from '@/types/chat';
import type { ToolConfirmRequest } from '@/types/hook';
import { confirmTool } from '@/api/hook';
import MessageItem from '@/components/Chat/MessageItem';
import ToolConfirmInline from '@/components/Chat/ToolConfirmModal';

const { Text } = Typography;
const { Option } = Select;
const { TextArea } = Input;

const MAX_LENGTH = 10000;

/* ------------------------------------------------------------------ */
/*  CompareMessageList — independent message list per card + auto-scroll  */
/*  inlined in this file instead of a separate file to prevent Vite   */
/*  production build tree-shaking                                      */
/* ------------------------------------------------------------------ */
interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  trace?: TraceItem[];
  timestamp?: string;
  metadata?: { cards: any[] };
}

interface CompareStats {
  firstResponseTime?: number;  // ms
  firstAnswerTime?: number;  // ms - time to first <answer> output
  intermediateAnswerCount: number;
  toolCallCount: number;
  maxConcurrentTools?: number;  // max concurrent tools at any point
  totalTime?: number;  // ms
}

interface CompareItem {
  id: string;
  snapshot: SessionSnapshot;
  messages: Message[];
  loading?: boolean;
  error?: string;
  sessionId?: string;
  streamingContent?: string;
  streamingTrace?: TraceItem[];
  confirmData?: ToolConfirmRequest | null;
  stats?: CompareStats;
}

/* ------------------------------------------------------------------ */
/*  CompareMessageList — independent message list per card + auto-scroll  */
/* ------------------------------------------------------------------ */
interface CompareMessageListProps {
  itemId: string;
  messages: Message[];
  loading?: boolean;
  error?: string;
  streamingContent?: string;
  streamingTrace?: TraceItem[];
  confirmData?: ToolConfirmRequest | null;
  onConfirm: (confirmationId: string, approved: boolean) => void;
  onTimeout: (confirmationId: string) => void;
  onSendMessage: (content: string) => void;  // internal message send callback
}

const CompareMessageList: React.FC<CompareMessageListProps> = ({
  itemId,
  messages,
  loading,
  error,
  streamingContent,
  streamingTrace,
  confirmData,
  onConfirm,
  onTimeout,
  onSendMessage,
}) => {
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const userScrolledUpRef = useRef(false);

  // Listen for asri:send-message events belonging to this window
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail?.content && detail?.sourceId === itemId) {
        onSendMessage(detail.content);
      }
    };
    window.addEventListener('asri:send-message', handler);
    return () => window.removeEventListener('asri:send-message', handler);
  }, [itemId, onSendMessage]);

  // Track user scroll behavior: check if user manually scrolled up
  const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const container = e.currentTarget;
    const threshold = 100;
    const isNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < threshold;
    userScrolledUpRef.current = !isNearBottom;
  }, []);

  // Auto-scroll to bottom — only trigger when user has not manually scrolled up
  useEffect(() => {
    const el = messagesEndRef.current;
    if (!el || userScrolledUpRef.current) return;
    const container = el.parentElement;
    if (container) {
      container.scrollTop = container.scrollHeight;
    }
  }, [messages, streamingContent, streamingTrace]);

  return (
    <div className={styles.messagesContainer} onScroll={handleScroll}>
      {messages.map((msg) => (
        <MessageItem
          key={msg.id}
          message={{
            id: msg.id,
            role: msg.role,
            content: msg.content,
            trace: msg.trace,
            message_type: 'text',
            timestamp: msg.timestamp || new Date().toISOString(),
            metadata: msg.metadata,
          }}
          cardSourceId={itemId}
        />
      ))}
      {/* Streaming message (visible during WebSocket streaming) */}
      {loading && (streamingContent || (streamingTrace && streamingTrace.length > 0)) && (
        <MessageItem
          key={`streaming-${itemId}`}
          message={{
            id: `streaming-${itemId}`,
            role: 'assistant',
            content: streamingContent || '',
            trace: streamingTrace,
            message_type: 'text',
            timestamp: new Date().toISOString(),
          }}
          cardSourceId={itemId}
        />
      )}
      {/* Loading spinner (before any streaming data arrives) */}
      {loading && !streamingContent && (!streamingTrace || streamingTrace.length === 0) && (
        <div className={styles.loadingIndicator}>
          <LoadingOutlined className={styles.loadingIcon} />
          <Text type="secondary">Thinking...</Text>
        </div>
      )}
      {error && (
        <div className={styles.loadingIndicator} style={{ color: '#ff4d4f' }}>
          <ExclamationCircleOutlined />
          <Text type="danger">{error}</Text>
        </div>
      )}
      {confirmData && (
        <div className={styles.confirmCardContainer}>
          <ToolConfirmInline
            key={confirmData.confirmation_id}
            confirmData={confirmData}
            onConfirm={(cid, approved) => onConfirm(cid, approved)}
            onTimeout={(cid) => onTimeout(cid)}
          />
        </div>
      )}
      <div ref={(el) => { messagesEndRef.current = el; }} />
    </div>
  );
};

const ChatCompare: React.FC = () => {
  const [compareItems, setCompareItems] = useState<CompareItem[]>([]);
  const compareItemsRef = useRef<CompareItem[]>([]);  // always points to the latest compareItems, avoids stale closure
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedSnapshotId, setSelectedSnapshotId] = useState<string | null>(null);
  const [inputValue, setInputValue] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [snapshots, setSnapshots] = useState<SessionSnapshot[]>([]);
  const [loadingSnapshots, setLoadingSnapshots] = useState(true);
  const inputRef = useRef<any>(null);
  const wsRefs = useRef<{ [key: string]: WebSocket }>({});
  const confirmSentRef = useRef<Set<string>>(new Set());
  const confirmClearTimeoutRef = useRef<{ [key: string]: ReturnType<typeof setTimeout> | null }>({});

  // Load snapshots on mount
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        setLoadingSnapshots(true);
        const res = await getSnapshots(1, 50);
        if (!cancelled) {
          setSnapshots(res.items);
          // Auto-select the 2 most recent snapshots
          if (res.items.length > 0) {
            const recent = res.items.slice(0, Math.min(2, res.items.length));
            setCompareItems(recent.map((s) => ({
              id: `init-${s.id}`,
              snapshot: s,
              messages: [],
            })));
          }
        }
      } catch (e) {
        if (!cancelled) {
          antMessage.error('Failed to load snapshots');
        }
      } finally {
        if (!cancelled) {
          setLoadingSnapshots(false);
        }
      }
    };
    load();
    return () => { cancelled = true; };
  }, []);

  // Auto-focus input
  useEffect(() => {
    if (!isStreaming && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isStreaming]);

  // Cleanup WebSocket connections on unmount
  useEffect(() => {
    return () => {
      Object.values(wsRefs.current).forEach((ws) => ws.close());
      wsRefs.current = {};
    };
  }, []);

  const handleAddCompare = () => {
    if (compareItems.length >= 3) {
      antMessage.warning('Maximum 3 Snapshots for comparison');
      return;
    }
    setIsModalOpen(true);
  };

  const handleRemoveCompare = (id: string) => {
    // Close WebSocket for removed item
    if (wsRefs.current[id]) {
      wsRefs.current[id].close();
      delete wsRefs.current[id];
    }
    setCompareItems(compareItems.filter((item) => item.id !== id));
  };

  const handleModalOk = () => {
    if (!selectedSnapshotId) {
      antMessage.warning('Please select a Snapshot');
      return;
    }
    if (compareItems.some((item) => item.snapshot.id === selectedSnapshotId)) {
      antMessage.warning('Snapshot already added');
      return;
    }
    const snapshot = snapshots.find((s) => s.id === selectedSnapshotId);
    if (!snapshot) return;

    setCompareItems([...compareItems, {
      id: `cmp-${snapshot.id}-${Date.now()}`,
      snapshot,
      messages: [],
    }]);
    setIsModalOpen(false);
    setSelectedSnapshotId(null);
  };

  const handleModalCancel = () => {
    setIsModalOpen(false);
    setSelectedSnapshotId(null);
  };

  // Connect WebSocket for a single compare item and stream response
  const connectWebSocketForItem = useCallback((item: CompareItem, sessionId: string, userMessage: string) => {
    // Close existing WS for this item if any
    if (wsRefs.current[item.id]) {
      // Send stop signal before closing so backend can save context faster
      try {
        wsRefs.current[item.id].send(JSON.stringify({ type: 'stop' }));
      } catch (e) { /* ignore if already closed */ }
      wsRefs.current[item.id].close();
    }

    const baseUrl = import.meta.env.VITE_API_BASE || window.location.origin;
    const wsBaseUrl = baseUrl.replace('http', 'ws');
    const wsUrl = new URL(`/ws/chat/${sessionId}/`, wsBaseUrl);

    const ws = new WebSocket(wsUrl.toString());
    wsRefs.current[item.id] = ws;

    // Per-item streaming state (mutable closures for performance)
    let accumulatedContent = '';
    let accumulatedTrace: TraceItem[] = [];
    let accumulatedCards: any[] = [];
    let firstResponseTime: number | undefined;
    const sendStartTime = Date.now();

    ws.onopen = () => {
      const snapSettings = item.snapshot.snapshot_data?.settings;
      const interruptStrategy = snapSettings?.toolInterruptStrategy || 'none';

      ws.send(JSON.stringify({
        type: 'chat',
        message: userMessage,
        snapshot_id: item.snapshot.id,
        config: {
          interrupt_strategy: interruptStrategy,
        },
      }));
    };

    ws.onmessage = (event) => {
      const data = parseWebSocketMessage(event.data);
      if (!data) return;

      switch (data.type) {
        case 'connected':
        case 'ack':
          break;

        case 'thinking':
        case 'think': {
          if (firstResponseTime === undefined) {
            firstResponseTime = Date.now() - sendStartTime;
          }
          const lastTrace = accumulatedTrace[accumulatedTrace.length - 1];
          if (lastTrace && (lastTrace.type === 'thinking' || lastTrace.type === 'think')) {
            lastTrace.content = (lastTrace.content || '') + (data.content || '');
            lastTrace.timestamp = data.timestamp || Date.now();
          } else {
            accumulatedTrace.push({
              type: data.type === 'think' ? 'think' : 'thinking',
              content: data.content || '',
              timestamp: data.timestamp || Date.now(),
            });
          }
          break;
        }

        case 'tool_call':
          accumulatedTrace.push({
            type: 'tool_call',
            status: 'calling',
            tool_name: data.tool_name,
            parameters: data.parameters,
            tool_call_id: data.tool_call_id,
            timestamp: data.timestamp || Date.now(),
          });
          break;

        case 'tool_result':
          accumulatedTrace.push({
            type: 'tool_result',
            status: data.status || 'success',
            tool_name: data.tool_name,
            result: data.result,
            tool_call_id: data.tool_call_id,
            timestamp: data.timestamp || Date.now(),
          });
          break;

        case 'answer': {
          const text = data.content || '';
          accumulatedContent += text;
          // Accumulate into trace for MessageItem display
          const lastAnsTrace = accumulatedTrace[accumulatedTrace.length - 1];
          if (lastAnsTrace && lastAnsTrace.type === 'answer') {
            lastAnsTrace.content = (lastAnsTrace.content || '') + text;
            lastAnsTrace.timestamp = data.timestamp || Date.now();
          } else {
            accumulatedTrace.push({
              type: 'answer',
              content: text,
              timestamp: data.timestamp || Date.now(),
            });
          }
          break;
        }

        case 'card':
          if (data.card_data) {
            accumulatedCards.push(data.card_data);
          }
          break;

        case 'tool_confirm_request':
          if (wsRefs.current[item.id] !== ws) return;
          confirmSentRef.current.clear();
          // Clear auto-clear timeout so it doesn't overwrite this new confirmation
          if (confirmClearTimeoutRef.current[item.id]) {
            clearTimeout(confirmClearTimeoutRef.current[item.id]!);
            delete confirmClearTimeoutRef.current[item.id];
          }
          setCompareItems((prev) => prev.map((i) =>
            i.id === item.id ? { ...i, confirmData: data as unknown as ToolConfirmRequest } : i
          ));
          break;

        case 'done': {
          // Ignore if a newer WS has been created for this item
          if (wsRefs.current[item.id] !== ws) return;
          // Calculate stats
          const totalTime = Date.now() - sendStartTime;
          const intermediateAnswerCount = accumulatedTrace.filter(
            (t, idx) => t.type === 'answer' &&
              accumulatedTrace.findIndex((tt) => tt.type === 'answer' &&
                accumulatedTrace.indexOf(tt) > idx) !== -1
          ).length;
          const toolCallCount = accumulatedTrace.filter(t => t.type === 'tool_call').length;

          // Calculate first answer time
          const firstAnswerItem = accumulatedTrace.find(t => t.type === 'answer');
          const firstAnswerTime = firstAnswerItem
            ? firstAnswerItem.timestamp - sendStartTime
            : undefined;

          // Calculate max concurrent tools
          let concurrentCount = 0;
          let maxConcurrentTools = 0;
          for (const t of accumulatedTrace) {
            if (t.type === 'tool_call') {
              concurrentCount++;
              maxConcurrentTools = Math.max(maxConcurrentTools, concurrentCount);
            } else if (t.type === 'tool_result') {
              concurrentCount = Math.max(0, concurrentCount - 1);
            }
          }

          // Finalize: add assistant message and clear streaming state
          setCompareItems((prev) => {
            const next = prev.map((i) => {
              if (i.id !== item.id) return i;
              return {
                ...i,
                messages: [...i.messages, {
                  id: `ai-${Date.now()}-${Math.random()}`,
                  role: 'assistant',
                  content: accumulatedContent,
                  trace: accumulatedTrace.length > 0 ? [...accumulatedTrace] : undefined,
                  timestamp: new Date().toISOString(),
                  metadata: accumulatedCards.length > 0 ? { cards: [...accumulatedCards] } : undefined,
                }],
                loading: false,
                error: undefined,
                confirmData: null,
                streamingContent: undefined,
                streamingTrace: undefined,
                stats: {
                  firstResponseTime,
                  firstAnswerTime,
                  intermediateAnswerCount,
                  toolCallCount,
                  maxConcurrentTools: maxConcurrentTools > 0 ? maxConcurrentTools : undefined,
                  totalTime,
                },
              };
            });
            compareItemsRef.current = next;
            return next;
          });
          ws.close();
          delete wsRefs.current[item.id];
          // Check if all connections are done
          if (Object.keys(wsRefs.current).length === 0) {
            setIsStreaming(false);
          }
          return;
        }

        case 'error':
          // Ignore if a newer WS has been created for this item
          if (wsRefs.current[item.id] !== ws) return;
          setCompareItems((prev) => prev.map((i) =>
            i.id === item.id
              ? { ...i, loading: false, error: data.content || 'Chat error', confirmData: null, streamingContent: undefined, streamingTrace: undefined }
              : i
          ));
          ws.close();
          delete wsRefs.current[item.id];
          if (Object.keys(wsRefs.current).length === 0) {
            setIsStreaming(false);
          }
          return;
      }

      // Update streaming state for UI (accumulated content + trace)
      setCompareItems((prev) => prev.map((i) =>
        i.id === item.id
          ? { ...i, streamingContent: accumulatedContent, streamingTrace: [...accumulatedTrace] }
          : i
      ));
    };

    ws.onerror = () => {
      // Ignore if a newer WS has been created for this item
      if (wsRefs.current[item.id] !== ws) return;
      setCompareItems((prev) => prev.map((i) =>
        i.id === item.id
          ? { ...i, loading: false, error: 'WebSocket connection error', streamingContent: undefined, streamingTrace: undefined }
          : i
      ));
      delete wsRefs.current[item.id];
      if (Object.keys(wsRefs.current).length === 0) {
        setIsStreaming(false);
      }
    };  
  }, []);

  const handleSend = useCallback(async (overrideContent?: string) => {
    const userMessage = (overrideContent ?? inputValue).trim();
    if (!userMessage || compareItems.length === 0) return;

    if (!overrideContent) setInputValue('');
    setIsStreaming(true);

    // Add user message to all columns and set streaming state
    setCompareItems((prev) => prev.map((item) => ({
      ...item,
      messages: [...item.messages, {
        id: `user-${Date.now()}-${Math.random()}`,
        role: 'user',
        content: userMessage,
        timestamp: new Date().toISOString(),
      }],
      loading: true,
      error: undefined,
      streamingContent: '',
      streamingTrace: [],
    })));

    // Snapshot items at send time (before async session creation changes state)
    const itemsSnapshot = compareItems;

    // Ensure each item has its own session
    const sessionResults = await Promise.allSettled(
      itemsSnapshot.map(async (item) => {
        let sessionId = item.sessionId;
        if (!sessionId) {
          const data = await createSession({
            user_id: 'playground',
            title: 'Playground',
          });
          sessionId = data.session_id;
        }
        return { itemId: item.id, sessionId: sessionId! };
      }),
    );

    // Build session map
    const sessionMap = new Map<string, string>();
    for (const result of sessionResults) {
      if (result.status === 'fulfilled') {
        sessionMap.set(result.value.itemId, result.value.sessionId);
      }
    }

    if (sessionMap.size === 0) {
      antMessage.error('Failed to create sessions');
      setCompareItems((prev) => prev.map((item) => ({
        ...item,
        loading: false,
        error: 'Session creation failed',
        streamingContent: undefined,
        streamingTrace: undefined,
      })));
      setIsStreaming(false);
      return;
    }

    // Store session IDs back to items
    setCompareItems((prev) => prev.map((item) => {
      const sid = sessionMap.get(item.id);
      if (sid) {
        return { ...item, sessionId: sid };
      }
      return { ...item, loading: false, error: 'Session creation failed', streamingContent: undefined, streamingTrace: undefined };
    }));

    // Connect WebSocket for each item (sequential to avoid race on wsRefs)
    for (const item of itemsSnapshot) {
      const sessionId = sessionMap.get(item.id);
      if (sessionId) {
        connectWebSocketForItem(item, sessionId, userMessage);
      }
    }
  }, [inputValue, isStreaming, compareItems, connectWebSocketForItem]);

  /** Send message to a specific window only (card click callback) */
  const handleSendToItem = useCallback(async (targetItemId: string, content: string) => {
    const userMessage = content.trim();
    if (!userMessage) return;

    // Use ref to get the latest state, avoiding stale closure
    const currentItems = compareItemsRef.current;
    const targetItem = currentItems.find((i) => i.id === targetItemId);
    if (!targetItem) return;

    setCompareItems((prev) => {
      const next = prev.map((item) =>
        item.id !== targetItemId ? item : {
          ...item,
          messages: [...item.messages, {
            id: `user-${Date.now()}-${Math.random()}`,
            role: 'user',
            content: userMessage,
            timestamp: new Date().toISOString(),
          }],
          loading: true,
          error: undefined,
          streamingContent: '',
          streamingTrace: [],
        }
      );
      compareItemsRef.current = next;
      return next;
    });

    let sessionId = targetItem.sessionId;
    if (!sessionId) {
      const data = await createSession({ user_id: 'playground', title: 'Playground' });
      sessionId = data.session_id;
      setCompareItems((prev) => {
        const next = prev.map((i) => i.id === targetItemId ? { ...i, sessionId } : i);
        compareItemsRef.current = next;
        return next;
      });
    }
    connectWebSocketForItem(targetItem, sessionId!, userMessage);
  }, [connectWebSocketForItem]);

  // Listen for card button click events (e.g. confirm submit) to send messages
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      // Only respond to events without sourceId (global) or with sourceId matching this Playground
      // Each CompareItem has its own itemId, but all windows are handled uniformly here
      // Actual dispatch broadcasts to all windows via handleSend, sourceId filtering is done inside each CompareMessageList
      if (detail?.content && !detail?.sourceId) {
        // Global message (Chat page)
        handleSend(detail.content);
      }
    };
    window.addEventListener('asri:send-message', handler);
    return () => window.removeEventListener('asri:send-message', handler);
  }, [handleSend]);

  // ── Tool Confirmation ─────────────────────────────────────────
  /**
   * Send tool confirmation response via HTTP POST.
   *
   * IMPORTANT: Do NOT use WebSocket for this. Django Channels'
   * AsyncWebsocketConsumer processes messages serially — while the
   * streaming async for loop is running inside _handle_chat_message,
   * any tool_confirm_response sent via WebSocket is QUEUED and only
   * processed after streaming finishes, which creates a deadlock
   * because the agent blocks on _store.wait() awaiting this response.
   * HTTP POST uses a separate connection, bypassing the deadlock.
   */
  const sendToolConfirmResponse = useCallback((_itemId: string, confirmationId: string, approved: boolean) => {
    confirmTool(confirmationId, approved);
  }, []);

  const handleToolConfirmForItem = useCallback((itemId: string, confirmationId: string, approved: boolean) => {
    if (confirmSentRef.current.has(confirmationId)) return;
    confirmSentRef.current.add(confirmationId);
    sendToolConfirmResponse(itemId, confirmationId, approved);
    // Clear previous auto-clear timeout to avoid overwriting a newer confirmData
    if (confirmClearTimeoutRef.current[itemId]) {
      clearTimeout(confirmClearTimeoutRef.current[itemId]!);
      delete confirmClearTimeoutRef.current[itemId];
    }
    confirmClearTimeoutRef.current[itemId] = setTimeout(() => {
      setCompareItems((prev) => prev.map((i) =>
        i.id === itemId ? { ...i, confirmData: null } : i
      ));
      delete confirmClearTimeoutRef.current[itemId];
    }, 3000);
  }, [sendToolConfirmResponse]);

  const handleToolConfirmTimeoutForItem = useCallback((itemId: string, confirmationId: string) => {
    if (!confirmationId || confirmSentRef.current.has(confirmationId)) return;
    confirmSentRef.current.add(confirmationId);
    sendToolConfirmResponse(itemId, confirmationId, false);
    // Clear previous auto-clear timeout to avoid overwriting a newer confirmData
    if (confirmClearTimeoutRef.current[itemId]) {
      clearTimeout(confirmClearTimeoutRef.current[itemId]!);
      delete confirmClearTimeoutRef.current[itemId];
    }
    confirmClearTimeoutRef.current[itemId] = setTimeout(() => {
      setCompareItems((prev) => prev.map((i) =>
        i.id === itemId ? { ...i, confirmData: null } : i
      ));
      delete confirmClearTimeoutRef.current[itemId];
    }, 3000);
  }, [sendToolConfirmResponse]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const charCount = inputValue.length;
  const isDisabled = compareItems.length === 0 || loadingSnapshots;

  if (loadingSnapshots) {
    return (
      <div className={styles.container}>
        <div className={styles.content} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Spin size="large" tip="Loading snapshots..." />
        </div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <Text className={styles.title}>Playground</Text>
          <Text type="secondary" className={styles.subtitle}>
            Compare 2-3 Snapshots for configuration differences and conversation effects
          </Text>
        </div>
        <Space>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={handleAddCompare}
            disabled={compareItems.length >= 3}
          >
            Add Comparison
          </Button>
        </Space>
      </div>

      <div className={styles.content}>
        {compareItems.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="No snapshots available. Create a snapshot first from a session."
            className={styles.empty}
          />
        ) : (
          <div className={styles.compareGrid}>
            {compareItems.map((item, index) => (
              <Card
                key={item.id}
                className={styles.compareCard}
                title={
                  <div className={styles.cardTitle}>
                    <Badge count={index + 1} className={styles.badge} />
                    <span className={styles.cardTitleText}>{item.snapshot.name}</span>
                    <Button
                      type="text"
                      danger
                      size="small"
                      icon={<DeleteOutlined />}
                      onClick={() => handleRemoveCompare(item.id)}
                      className={styles.removeBtn}
                    />
                  </div>
                }
              >
                <div className={styles.messageList}>
                  {/* Mode Tags */}
                  <div className={styles.modeTags}>
                    {(() => {
                      const mode = item.snapshot.snapshot_data?.settings?.execution_mode || 'interleaved';
                      const isInterleaved = mode === 'interleaved';
                      return isInterleaved ? (
                        <Space size={[0, 4]} wrap>
                          <Tag icon={<BulbOutlined />} color="blue" className={styles.modeTag}>边想边答</Tag>
                          <Tag icon={<ThunderboltOutlined />} color="orange" className={styles.modeTag}>并发工具</Tag>
                          <Tag icon={<SyncOutlined />} color="green" className={styles.modeTag}>随机应变</Tag>
                        </Space>
                      ) : (
                        <Space size={[0, 4]} wrap>
                          <Tag icon={<LockOutlined />} className={styles.modeTag}>完整推理</Tag>
                          <Tag icon={<OrderedListOutlined />} className={styles.modeTag}>顺序工具</Tag>
                          <Tag icon={<FileTextOutlined />} className={styles.modeTag}>固定计划</Tag>
                        </Space>
                      );
                    })()}
                  </div>

                  {/* Snapshot Info + Interrupt Strategy - merged into one row */}
                  <div className={styles.snapshotInfo}>
                    <div className={styles.infoRowCompact}>
                      <Text type="secondary" className={styles.infoText}>
                        <HistoryOutlined />{' '}
                        {item.snapshot.gmt_create
                          ? new Date(item.snapshot.gmt_create).toLocaleDateString()
                          : 'Unknown'}
                        {' · '}
                        {item.snapshot.snapshot_data?.llm_provider_ref?.model_name || 'N/A'}
                      </Text>
                      <Space size={[8, 4]} wrap className={styles.compactTags}>
                        {(() => {
                          const sd = item.snapshot.snapshot_data;
                          const toolCount = sd?.tools?.length || 0;
                          const skillCount = sd?.skills?.length || 0;
                          const ragCount = sd?.rag_providers?.length || 0;
                          const promptName = sd?.prompt?.name;
                          const promptMode = sd?.prompt?.mode;
                          const tags: React.ReactNode[] = [];
                          if (promptName && promptName !== promptMode) {
                            tags.push(<Tag key="pn" size="small" color="cyan">{promptName}</Tag>);
                          }
                          if (toolCount > 0) {
                            tags.push(<Tag key="tc" size="small" color="purple">{toolCount} tools</Tag>);
                          }
                          if (skillCount > 0) {
                            tags.push(<Tag key="sc" size="small" color="geekblue">{skillCount} skills</Tag>);
                          }
                          if (ragCount > 0) {
                            tags.push(<Tag key="rg" size="small" color="lime">RAG</Tag>);
                          }
                          return tags;
                        })()}
                      </Space>
                    </div>
                  </div>

                  {/* Messages */}
                    <CompareMessageList
                    itemId={item.id}
                    messages={item.messages}
                    loading={item.loading}
                    error={item.error}
                    streamingContent={item.streamingContent}
                    streamingTrace={item.streamingTrace}
                    confirmData={item.confirmData}
                    onConfirm={(cid, approved) => handleToolConfirmForItem(item.id, cid, approved)}
                    onTimeout={(cid) => handleToolConfirmTimeoutForItem(item.id, cid)}
                    onSendMessage={(content) => handleSendToItem(item.id, content)}
                  />

                  {/* Stats Panel */}
                  {item.stats && !item.loading && (
                    <div className={styles.statsPanel}>
                      <div className={styles.statItem}>
                        <span className={styles.statLabel}>First Response</span>
                        <span className={styles.statValue}>
                          {item.stats.firstResponseTime !== undefined
                            ? `${(item.stats.firstResponseTime / 1000).toFixed(1)}s`
                            : '-'}
                        </span>
                      </div>
                      <div className={styles.statItem}>
                        <span className={styles.statLabel}>First Answer</span>
                        <span className={styles.statValue}>
                          {item.stats.firstAnswerTime !== undefined
                            ? `${(item.stats.firstAnswerTime / 1000).toFixed(1)}s`
                            : '-'}
                        </span>
                      </div>
                      <div className={styles.statItem}>
                        <span className={styles.statLabel}>Intermediate Answers</span>
                        <span className={styles.statValue}>{item.stats.intermediateAnswerCount}</span>
                      </div>
                      <div className={styles.statItem}>
                        <span className={styles.statLabel}>Max Concurrent Tools</span>
                        <span className={styles.statValue}>
                          {item.stats.maxConcurrentTools !== undefined
                            ? item.stats.maxConcurrentTools
                            : '-'}
                        </span>
                      </div>
                      <div className={styles.statItem}>
                        <span className={styles.statLabel}>Tool Calls</span>
                        <span className={styles.statValue}>{item.stats.toolCallCount}</span>
                      </div>
                      <div className={styles.statItem}>
                        <span className={styles.statLabel}>Total Time</span>
                        <span className={styles.statValue}>
                          {item.stats.totalTime !== undefined
                            ? `${(item.stats.totalTime / 1000).toFixed(1)}s`
                            : '-'}
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>

      {/* Shared Input */}
      {compareItems.length > 0 && (
        <div className={styles.inputContainer}>
          <div className={`${styles.inputWrapper} ${isDisabled ? styles.inputWrapperDisabled : ''}`}>
            <TextArea
              ref={inputRef}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value.slice(0, MAX_LENGTH))}
              onKeyDown={handleKeyDown}
              placeholder="Enter message, send to all Snapshots simultaneously..."
              autoSize={{ minRows: 1, maxRows: 8 }}
              disabled={isDisabled}
              className={styles.input}
            />
            <div className={styles.inputFooter}>
              <span className={`${styles.charCount} ${charCount > MAX_LENGTH * 0.9 ? styles.charCountWarn : ''}`}>
                {charCount}/{MAX_LENGTH}
              </span>
              <Button
                type="primary"
                icon={isStreaming ? <LoadingOutlined /> : <SendOutlined />}
                onClick={handleSend}
                disabled={!inputValue.trim() || isDisabled}
                className={styles.sendBtn}
              />
            </div>
          </div>
        </div>
      )}

      {/* Select Snapshot Modal */}
      <Modal
        title="Select Snapshot"
        open={isModalOpen}
        onOk={handleModalOk}
        onCancel={handleModalCancel}
        okText="Confirm"
        cancelText="Cancel"
      >
        <Select
          placeholder="Please select a Snapshot to compare"
          value={selectedSnapshotId}
          onChange={setSelectedSnapshotId}
          className={styles.snapshotSelect}
          dropdownMatchSelectWidth={false}
        >
          {snapshots.map((snap) => (
            <Option key={snap.id} value={snap.id}>
              <div className={styles.optionContent}>
                <Text strong>{snap.name}</Text>
                <Text type="secondary" className={styles.optionMeta}>
                  {snap.gmt_create ? new Date(snap.gmt_create).toLocaleString() : ''}
                </Text>
              </div>
            </Option>
          ))}
        </Select>
      </Modal>
    </div>
  );
};

export default ChatCompare;
