import React, { useState, useEffect, useMemo } from 'react';
import {
  BulbOutlined,
  ToolOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  CloseOutlined,
  RobotOutlined,
  UserOutlined,
  SendOutlined,
  LoadingOutlined,
  PlayCircleOutlined,
  ClockCircleOutlined,
  DownOutlined,
  RightOutlined,
} from '@ant-design/icons';
import { Collapse } from 'antd';
import type { TraceItem } from '@/types/chat';
import styles from './ThinkingPanel.module.css';

// ============================================
// Types
// ============================================
export type TraceType = 'thinking' | 'think' | 'llm_start' | 'llm_end' | 'tool_call' | 'tool_result' | 'answer';

export type TimelineMessageType = 'user' | 'llm_start' | 'llm_end' | 'think' | 'tool_call' | 'tool_result' | 'answer';

export interface TimelineMessage {
  id: string;
  type: TimelineMessageType;
  timestamp: number;
  content?: string;
  // LLM fields
  llm_id?: string;
  model?: string;
  provider?: string;
  duration_ms?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  cached_tokens?: number;
  // Tool fields
  toolName?: string;
  parameters?: Record<string, unknown>;
  result?: unknown;
  duration?: number;
  status?: 'calling' | 'success' | 'error';
}

export interface TimelineState {
  messages: TimelineMessage[];
  startTime: number;
  totalDuration?: number;
}

// ============================================
// Helper Functions
// ============================================
const formatTime = (ms: number): string => {
  if (ms < 1000) return `+${ms}ms`;
  return `+${(ms / 1000).toFixed(2)}s`;
};

// Merge consecutive think/thinking/answer steps (merge same types)
const mergeConsecutiveTrace = (trace: TraceItem[]): TraceItem[] => {
  const result: TraceItem[] = [];
  let currentItem: TraceItem | null = null;

  for (const step of trace) {
    // For think/thinking/answer, merge consecutive items of the same type
    if (step.type === 'think' || step.type === 'thinking' || step.type === 'answer') {
      if (currentItem && currentItem.type === step.type) {
        // Merge with current item of the same type
        currentItem.content = (currentItem.content || '') + (step.content || '');
        currentItem.timestamp = step.timestamp;
      } else {
        // Flush previous item and start new one
        if (currentItem) {
          result.push(currentItem);
        }
        currentItem = { ...step };
      }
    } else {
      // Non-mergeable items (tool_call, tool_result, llm_start, llm_end, etc.)
      if (currentItem) {
        result.push(currentItem);
        currentItem = null;
      }
      result.push(step);
    }
  }

  if (currentItem) {
    result.push(currentItem);
  }

  return result;
};

// Convert TraceItem[] to TimelineMessage[]
const convertTraceToMessages = (trace: TraceItem[], userMessage?: string): TimelineMessage[] => {
  const messages: TimelineMessage[] = [];

  // Add user message
  if (userMessage) {
    messages.push({
      id: 'msg_user',
      type: 'user',
      timestamp: 0,
      content: userMessage,
    });
  }

  // Merge consecutive think/answer messages
  const mergedTrace = mergeConsecutiveTrace(trace);

  // Iterate through trace, add messages in time order
  for (const item of mergedTrace) {
    // Skip llm_start - internal marker, not displayed
    if (item.type === 'llm_start') {
      continue;
    }

    switch (item.type) {
      case 'think':
      case 'thinking':
        // Thinking message
        messages.push({
          id: `msg_think_${item.timestamp || Date.now()}`,
          type: 'think',
          timestamp: item.timestamp || Date.now(),
          content: item.content,
        });
        break;

      case 'llm_end':
        // LLM call end message (shows token usage and cache hit rate)
        messages.push({
          id: `msg_llm_end_${item.timestamp || Date.now()}`,
          type: 'llm_end',
          timestamp: item.timestamp || Date.now(),
          llm_id: item.llm_id,
          duration_ms: item.duration_ms,
          prompt_tokens: item.prompt_tokens,
          completion_tokens: item.completion_tokens,
          total_tokens: item.total_tokens,
          cached_tokens: item.cached_tokens,
        });
        break;

      case 'tool_call':
        // Tool call
        messages.push({
          id: `msg_call_${item.tool_call_id || item.timestamp || Date.now()}`,
          type: 'tool_call',
          timestamp: item.timestamp || Date.now(),
          toolName: item.tool_name,
          parameters: item.parameters,
          status: item.status,
        });
        break;

      case 'tool_result':
        // Tool result
        messages.push({
          id: `msg_result_${item.tool_call_id || item.timestamp || Date.now()}`,
          type: 'tool_result',
          timestamp: item.timestamp || Date.now(),
          toolName: item.tool_name,
          result: item.result,
          duration: item.duration_ms,
          status: item.status,
        });
        break;

      case 'answer':
        // Final answer
        messages.push({
          id: `msg_answer_${item.timestamp || Date.now()}`,
          type: 'answer',
          timestamp: item.timestamp || Date.now(),
          content: item.content,
        });
        break;
    }
  }

  return messages;
};

// ============================================
// Mock Data
// ============================================
const createStaticMockData = (): TimelineState => {
  const startTime = Date.now();
  return {
    startTime,
    messages: [
      {
        id: 'msg_user',
        type: 'user',
        timestamp: startTime,
        content: '查询我的订单状态和物流信息',
      },
      {
        id: 'msg_llm_start_1',
        type: 'llm_start',
        timestamp: startTime + 50,
        llm_id: 'llm_001',
        model: 'gpt-4',
        provider: 'openai',
      },
      {
        id: 'msg_think_1',
        type: 'think',
        timestamp: startTime + 80,
        content: '用户想要查询订单状态和物流信息，我需要同时调用订单查询和物流查询接口',
      },
      {
        id: 'msg_call_1',
        type: 'tool_call',
        timestamp: startTime + 100,
        toolName: 'get_order_info',
        parameters: { order_id: 'ORD20240330001' },
        status: 'calling',
      },
      {
        id: 'msg_call_2',
        type: 'tool_call',
        timestamp: startTime + 100,
        toolName: 'get_delivery_status',
        parameters: { order_id: 'ORD20240330001' },
        status: 'calling',
      },
      {
        id: 'msg_result_1',
        type: 'tool_result',
        timestamp: startTime + 956,
        toolName: 'get_order_info',
        result: { order_id: 'ORD20240330001', status: '已发货', amount: 299.0 },
        duration: 856,
        status: 'success',
      },
      {
        id: 'msg_result_2',
        type: 'tool_result',
        timestamp: startTime + 1334,
        toolName: 'get_delivery_status',
        result: { tracking_no: 'SF1234567890', status: '运输中' },
        duration: 1234,
        status: 'success',
      },
      {
        id: 'msg_llm_start_2',
        type: 'llm_start',
        timestamp: startTime + 1400,
        llm_id: 'llm_002',
        model: 'gpt-4',
        provider: 'openai',
      },
      {
        id: 'msg_llm_end_1',
        type: 'llm_end',
        timestamp: startTime + 1500,
        llm_id: 'llm_001',
        duration_ms: 450,
        prompt_tokens: 120,
        completion_tokens: 80,
        total_tokens: 200,
      },
      {
        id: 'msg_think_2',
        type: 'think',
        timestamp: startTime + 1450,
        content: '已获取订单和物流信息，整合回复用户',
      },
      {
        id: 'msg_answer',
        type: 'answer',
        timestamp: startTime + 1700,
        content: '您的订单 ORD20240330001 已发货，金额 299.00 元。物流单号 SF1234567890 正在运输中。',
      },
    ],
    totalDuration: 1700,
  };
};

// ============================================
// Components
// ============================================

// User Message
const UserMessage: React.FC<{ msg: TimelineMessage; baseTime: number }> = ({ msg, baseTime }) => (
  <div className={styles.item}>
    <div className={styles.timelineTrack}>
      <div className={`${styles.dot} ${styles.dot_gray}`}>
        <UserOutlined />
      </div>
    </div>
    <div className={styles.itemContent}>
      <span className={styles.itemTime}>{formatTime(msg.timestamp - baseTime)}</span>
      <div className={`${styles.itemBody} ${styles.userBody}`}>
        <span className={styles.userText}>{msg.content}</span>
      </div>
    </div>
  </div>
);

// LLM Start Message (collapsible)
const LLMStartMessage: React.FC<{ msg: TimelineMessage; baseTime: number }> = ({ msg, baseTime }) => {
  const [expanded, setExpanded] = useState(false);
  const header = (
    <div className={styles.collapseHeader}>
      <span className={styles.itemTime}>{formatTime(msg.timestamp - baseTime)}</span>
      <span className={`${styles.llmLabel}`}>llm_start</span>
      <span className={styles.llmModel}>{msg.model || 'Unknown'}</span>
      {msg.provider && <span className={styles.llmProvider}>via {msg.provider}</span>}
    </div>
  );
  return (
    <div className={styles.item}>
      <div className={styles.timelineTrack}>
        <div className={`${styles.dot} ${styles.dot_purple}`}>
          <PlayCircleOutlined />
        </div>
      </div>
      <div className={styles.itemContent}>
        <Collapse
          ghost
          expandIcon={({ isActive }) => isActive ? <DownOutlined /> : <RightOutlined />}
          expandIconPosition="end"
          items={[{
            key: '1',
            label: header,
            children: (
              <div className={`${styles.itemBody} ${styles.llmStartBody}`}>
                <div>Model: {msg.model || 'Unknown'}</div>
                <div>Provider: {msg.provider || 'Unknown'}</div>
                <div>LLM ID: {msg.llm_id}</div>
              </div>
            ),
          }]}
        />
      </div>
    </div>
  );
};

// LLM End Message (collapsible)
const LLMEndMessage: React.FC<{ msg: TimelineMessage; baseTime: number }> = ({ msg, baseTime }) => {
  const [expanded, setExpanded] = useState(false);
  const cacheHitRate = msg.cached_tokens !== undefined && msg.prompt_tokens && msg.prompt_tokens > 0
    ? ((msg.cached_tokens / msg.prompt_tokens) * 100).toFixed(1)
    : null;
  const header = (
    <div className={styles.collapseHeader}>
      <span className={styles.itemTime}>{formatTime(msg.timestamp - baseTime)}</span>
      <span className={`${styles.llmLabel}`}>llm_end</span>
      {msg.duration_ms && <span className={styles.llmDuration}>Duration {formatTime(msg.duration_ms)}</span>}
      {(msg.prompt_tokens !== undefined || msg.completion_tokens !== undefined) && (
        <span className={styles.llmTokens}>
          {msg.total_tokens || (msg.prompt_tokens || 0) + (msg.completion_tokens || 0)} tokens
        </span>
      )}
      {cacheHitRate && (
        <span className={styles.llmCacheHit}>
          KV Cache {cacheHitRate}%
        </span>
      )}
    </div>
  );
  return (
    <div className={styles.item}>
      <div className={styles.timelineTrack}>
        <div className={`${styles.dot} ${styles.dot_purple}`}>
          <ClockCircleOutlined />
        </div>
      </div>
      <div className={styles.itemContent}>
        <Collapse
          ghost
          expandIcon={({ isActive }) => isActive ? <DownOutlined /> : <RightOutlined />}
          expandIconPosition="end"
          items={[{
            key: '1',
            label: header,
            children: (
              <div className={`${styles.itemBody} ${styles.llmEndBody}`}>
                <div>Duration: {msg.duration_ms?.toFixed(2) || 0} ms</div>
                <div>Prompt Tokens: {msg.prompt_tokens ?? 0}</div>
                <div>Completion Tokens: {msg.completion_tokens ?? 0}</div>
                <div>Total Tokens: {msg.total_tokens || (msg.prompt_tokens || 0) + (msg.completion_tokens || 0)}</div>
                <div>Cached Tokens: {msg.cached_tokens ?? 0}</div>
                <div>Cache Hit Rate: {cacheHitRate ? `${cacheHitRate}%` : 'N/A'}</div>
              </div>
            ),
          }]}
        />
      </div>
    </div>
  );
};

// Think Message (collapsible)
const ThinkMessage: React.FC<{ msg: TimelineMessage; baseTime: number }> = ({ msg, baseTime }) => {
  const header = (
    <div className={styles.collapseHeader}>
      <span className={styles.itemTime}>{formatTime(msg.timestamp - baseTime)}</span>
      <span className={styles.thinkLabel}>Thinking</span>
      <span className={styles.thinkText}>{msg.content?.substring(0, 50)}{msg.content && msg.content.length > 50 ? '...' : ''}</span>
    </div>
  );
  return (
    <div className={styles.item}>
      <div className={styles.timelineTrack}>
        <div className={`${styles.dot} ${styles.dot_yellow}`}>
          <BulbOutlined />
        </div>
      </div>
      <div className={styles.itemContent}>
        <Collapse
          ghost
          expandIcon={({ isActive }) => isActive ? <DownOutlined /> : <RightOutlined />}
          expandIconPosition="end"
          items={[{
            key: '1',
            label: header,
            children: (
              <div className={`${styles.itemBody} ${styles.thinkBody}`}>
                <span className={styles.thinkText}>{msg.content}</span>
              </div>
            ),
          }]}
        />
      </div>
    </div>
  );
};

// Tool Call Message (collapsible)
const ToolCallMessage: React.FC<{ msg: TimelineMessage; baseTime: number }> = ({ msg, baseTime }) => {
  const header = (
    <div className={styles.collapseHeader}>
      <span className={styles.itemTime}>{formatTime(msg.timestamp - baseTime)}</span>
      <span className={styles.toolLabel}>tool_call</span>
      <span className={styles.toolName}>{msg.toolName}</span>
      {msg.status === 'calling' && <span className={styles.toolStatus}><LoadingOutlined spin /> Calling</span>}
    </div>
  );
  return (
    <div className={styles.item}>
      <div className={styles.timelineTrack}>
        <div className={`${styles.dot} ${styles.dot_orange}`}>
          <ToolOutlined />
        </div>
      </div>
      <div className={styles.itemContent}>
        <Collapse
          ghost
          expandIcon={({ isActive }) => isActive ? <DownOutlined /> : <RightOutlined />}
          expandIconPosition="end"
          items={[{
            key: '1',
            label: header,
            children: (
              <div className={`${styles.itemBody} ${styles.toolCallBody}`}>
                <div>Parameters: {JSON.stringify(msg.parameters || {}, null, 2)}</div>
              </div>
            ),
          }]}
        />
      </div>
    </div>
  );
};

// Tool Result Message (collapsible)
const ToolResultMessage: React.FC<{ msg: TimelineMessage; baseTime: number }> = ({ msg, baseTime }) => {
  const isError = msg.status === 'error';
  const header = (
    <div className={styles.collapseHeader}>
      <span className={styles.itemTime}>{formatTime(msg.timestamp - baseTime)}</span>
      <span className={styles.toolLabel}>{isError ? 'tool_error' : 'tool_result'}</span>
      <span className={styles.toolName}>{msg.toolName}</span>
      {msg.duration && <span className={styles.toolDuration}>Duration {formatTime(msg.duration)}</span>}
    </div>
  );
  return (
    <div className={styles.item}>
      <div className={styles.timelineTrack}>
        <div className={`${styles.dot} ${isError ? styles.dot_red : styles.dot_green}`}>
          {isError ? <CloseCircleOutlined /> : <CheckCircleOutlined />}
        </div>
      </div>
      <div className={styles.itemContent}>
        <Collapse
          ghost
          expandIcon={({ isActive }) => isActive ? <DownOutlined /> : <RightOutlined />}
          expandIconPosition="end"
          items={[{
            key: '1',
            label: header,
            children: (
              <div className={`${styles.itemBody} ${isError ? styles.toolResultErrorBody : styles.toolResultBody}`}>
                <div className={styles.toolResult}>{typeof msg.result === 'string' ? msg.result : JSON.stringify(msg.result, null, 2)}</div>
              </div>
            ),
          }]}
        />
      </div>
    </div>
  );
};

// Answer Message
const AnswerMessage: React.FC<{ msg: TimelineMessage; baseTime: number }> = ({ msg, baseTime }) => (
  <div className={styles.item}>
    <div className={styles.timelineTrack}>
      <div className={`${styles.dot} ${styles.dot_green}`}>
        <SendOutlined />
      </div>
    </div>
    <div className={styles.itemContent}>
      <span className={styles.itemTime}>{formatTime(msg.timestamp - baseTime)}</span>
      <div className={`${styles.itemBody} ${styles.answerBody}`}>
        {msg.content}
      </div>
    </div>
  </div>
);

// Main Timeline
const SimpleTimeline: React.FC<{
  state: TimelineState;
  isStreaming?: boolean;
}> = ({ state, isStreaming }) => {
  const { messages, startTime } = state;
  const baseTime = startTime;

  return (
    <div className={styles.timeline}>
      {messages.map((msg) => {
        switch (msg.type) {
          case 'user':
            return <UserMessage key={msg.id} msg={msg} baseTime={baseTime} />;
          case 'llm_start':
            return <LLMStartMessage key={msg.id} msg={msg} baseTime={baseTime} />;
          case 'llm_end':
            return <LLMEndMessage key={msg.id} msg={msg} baseTime={baseTime} />;
          case 'think':
            return <ThinkMessage key={msg.id} msg={msg} baseTime={baseTime} />;
          case 'tool_call':
            return <ToolCallMessage key={msg.id} msg={msg} baseTime={baseTime} />;
          case 'tool_result':
            return <ToolResultMessage key={msg.id} msg={msg} baseTime={baseTime} />;
          case 'answer':
            return <AnswerMessage key={msg.id} msg={msg} baseTime={baseTime} />;
          default:
            return null;
        }
      })}

      {isStreaming && (
        <div className={styles.streaming}>
          <LoadingOutlined spin /> Waiting for response...
        </div>
      )}
    </div>
  );
};

// ============================================
// Main ThinkingPanel Component
// ============================================
interface ThinkingPanelProps {
  trace?: TraceItem[];
  userMessage?: string;
  isLoading?: boolean;
  onClose?: () => void;
}

const ThinkingPanel: React.FC<ThinkingPanelProps> = ({
  trace,
  userMessage,
  isLoading,
  onClose,
}) => {
  const [timelineState, setTimelineState] = useState<TimelineState | null>(null);
  const mockEnabled = new URLSearchParams(window.location.search).get('mock') === 'true';
  const streamingMode = new URLSearchParams(window.location.search).get('stream') === 'true';

  // Handle real trace data
  useEffect(() => {
    if (trace && trace.length > 0 && !mockEnabled) {
      const messages = convertTraceToMessages(trace, userMessage);
      const startTime = messages.length > 0 ? messages[0].timestamp : Date.now();
      setTimelineState({
        messages,
        startTime,
        totalDuration: messages.length > 0
          ? messages[messages.length - 1].timestamp - startTime
          : 0,
      });
    }
  }, [trace, userMessage, mockEnabled]);

  // Initialize mock data
  useEffect(() => {
    if (mockEnabled && !timelineState) {
      setTimelineState(createStaticMockData());
    }
  }, [mockEnabled, timelineState]);

  // Simulate streaming updates
  useEffect(() => {
    if (mockEnabled && streamingMode) {
      const state = createStaticMockData();
      state.messages = [
        { id: 'msg_user', type: 'user', timestamp: Date.now(), content: '查询我的订单状态和物流信息' },
      ];
      state.totalDuration = 0;
      setTimelineState(state);

      const steps = [
        { delay: 100, update: (s: TimelineState) => ({
          ...s,
          messages: [...s.messages, { id: 'msg_llm_start_1', type: 'llm_start', timestamp: Date.now(), llm_id: 'llm_001', model: 'gpt-4', provider: 'openai' }]
        })},
        { delay: 150, update: (s: TimelineState) => ({
          ...s,
          messages: [...s.messages, { id: 'msg_think_1', type: 'think', timestamp: Date.now(), content: '用户想要查询订单...' }]
        })},
        { delay: 200, update: (s: TimelineState) => ({
          ...s,
          messages: [...s.messages, { id: 'msg_call_1', type: 'tool_call', timestamp: Date.now(), toolName: 'get_order_info', parameters: { order_id: '123' }, status: 'calling' }]
        })},
        { delay: 250, update: (s: TimelineState) => ({
          ...s,
          messages: [...s.messages, { id: 'msg_call_2', type: 'tool_call', timestamp: Date.now(), toolName: 'get_delivery_status', parameters: { order_id: '123' }, status: 'calling' }]
        })},
        { delay: 1000, update: (s: TimelineState) => ({
          ...s,
          messages: [...s.messages, { id: 'msg_result_1', type: 'tool_result', timestamp: Date.now(), toolName: 'get_order_info', result: { status: '已发货' }, duration: 800, status: 'success' }]
        })},
        { delay: 1200, update: (s: TimelineState) => ({
          ...s,
          messages: [...s.messages, { id: 'msg_result_2', type: 'tool_result', timestamp: Date.now(), toolName: 'get_delivery_status', result: { status: '运输中' }, duration: 1000, status: 'success' }]
        })},
        { delay: 1300, update: (s: TimelineState) => ({
          ...s,
          messages: [...s.messages, { id: 'msg_llm_end_1', type: 'llm_end', timestamp: Date.now(), llm_id: 'llm_001', duration_ms: 1200, prompt_tokens: 120, completion_tokens: 35, total_tokens: 155 }]
        })},
        { delay: 1350, update: (s: TimelineState) => ({
          ...s,
          messages: [...s.messages, { id: 'msg_llm_start_2', type: 'llm_start', timestamp: Date.now(), llm_id: 'llm_002', model: 'gpt-4', provider: 'openai' }]
        })},
        { delay: 1400, update: (s: TimelineState) => ({
          ...s,
          messages: [...s.messages, { id: 'msg_think_2', type: 'think', timestamp: Date.now(), content: '已获取数据，整合回复' }]
        })},
        { delay: 1500, update: (s: TimelineState) => ({
          ...s,
          messages: [...s.messages, { id: 'msg_llm_end_2', type: 'llm_end', timestamp: Date.now(), llm_id: 'llm_002', duration_ms: 150, prompt_tokens: 180, completion_tokens: 80, total_tokens: 260 }]
        })},
        { delay: 1600, update: (s: TimelineState) => ({
          ...s,
          messages: [...s.messages, { id: 'msg_answer', type: 'answer', timestamp: Date.now(), content: '您的订单已发货...' }]
        })},
      ];

      const timers = steps.map(step =>
        setTimeout(() => setTimelineState(prev => step.update(prev!)), step.delay)
      );

      return () => timers.forEach(clearTimeout);
    }
  }, [mockEnabled, streamingMode]);

  const renderHeader = () => (
    <div className={styles.header}>
      <h4 className={styles.title}>Execution Process</h4>
      {mockEnabled && <span className={styles.mockBadge}>Mock</span>}
      {onClose && (
        <button className={styles.closeBtn} onClick={onClose} aria-label="Close" type="button">
          <CloseOutlined />
        </button>
      )}
    </div>
  );

  if (isLoading && !timelineState) {
    return (
      <aside className={styles.container} aria-label="Thinking process panel" aria-busy="true">
        {renderHeader()}
        <div className={styles.loading}>
          <LoadingOutlined className={styles.loadingIcon} />
          <span>Processing...</span>
        </div>
      </aside>
    );
  }

  if (!timelineState) {
    return (
      <aside className={styles.container} aria-label="Thinking process panel">
        {renderHeader()}
        <div className={styles.empty}>
          <BulbOutlined className={styles.emptyIcon} />
          <p className={styles.emptyText}>No execution process yet</p>
          <p className={styles.emptyHint}>Add ?mock=true to see demo</p>
        </div>
      </aside>
    );
  }

  return (
    <aside className={styles.container} aria-label="Thinking process panel">
      {renderHeader()}
      <div className={styles.content}>
        <SimpleTimeline state={timelineState} isStreaming={isLoading} />
      </div>
    </aside>
  );
};

export default ThinkingPanel;
