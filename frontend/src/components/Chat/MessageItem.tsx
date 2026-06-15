import React, { useState, useRef, useEffect, useCallback } from 'react';
import { message as antMessage, Image } from 'antd';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  BulbOutlined,
  ToolOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  DownOutlined,
  RobotOutlined,
  UserOutlined,
  CopyOutlined,
} from '@ant-design/icons';
import type { Message, TraceItem } from '@/types/chat';
import { useChatStore } from '@/stores/chatStore';
import CardRenderer from './CardRenderer';
import styles from './MessageItem.module.css';

// Shared Markdown renderer
const MarkdownContent: React.FC<{ content: string; className?: string }> = ({ content, className }) => (
  <div className={`${styles.markdownBody} ${className || ''}`}>
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        img: ({ src, alt }) => (
          <Image
            src={src}
            alt={alt || ''}
            className={styles.markdownImage}
            preview={{ mask: '点击查看原图' }}
          />
        ),
      }}
    >
      {content}
    </ReactMarkdown>
  </div>
);

interface MessageItemProps {
  message: Message;
  streamingTrace?: TraceItem[];
  sendStartTime?: number;
  isStreaming?: boolean;
  hideTraceDetails?: boolean; // When Execution Details panel is open, hide thinking/tool
  cardSourceId?: string;  // Card event scope, used for Playground card click isolation
}

// Get icon for trace type
const getTraceIcon = (step: TraceItem) => {
  switch (step.type) {
    case 'thinking':
    case 'think':
      return <BulbOutlined />;
    case 'tool_call':
      return <ToolOutlined />;
    case 'tool_result':
      return step.status === 'error'
        ? <CloseCircleOutlined />
        : <CheckCircleOutlined />;
    default:
      return <ToolOutlined />;
  }
};

// Get label text
const getTraceLabel = (step: TraceItem): string => {
  switch (step.type) {
    case 'thinking':
    case 'think':
      return 'Thinking';
    case 'tool_call':
      return step.tool_name || 'Tool Call';
    case 'tool_result':
      return step.tool_name || 'Result';
    case 'answer':
      return 'Answer';
    default:
      return step.type;
  }
};

// Syntax-highlight JSON string: keys blue, string values red
const highlightJson = (json: string): React.ReactNode => {
  const lines = json.split('\n');
  return lines.map((line, li) => {
    const tokens: React.ReactNode[] = [];
    let last = 0;
    const re = /("[^"]*")(\s*:)?/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(line)) !== null) {
      if (m.index > last) tokens.push(line.slice(last, m.index));
      if (m[2]) {
        // key
        tokens.push(<span key={`k-${li}-${m.index}`} className={styles.jsonKey}>{m[1]}</span>);
        tokens.push(m[2]);
      } else {
        // string value
        tokens.push(<span key={`v-${li}-${m.index}`} className={styles.jsonString}>{m[1]}</span>);
      }
      last = m.index + m[0].length;
    }
    if (last < line.length) tokens.push(line.slice(last));
    return <div key={li}>{tokens}</div>;
  });
};

// Copy to clipboard button
const CopyButton: React.FC<{ text: string }> = ({ text }) => (
  <button
    className={styles.copyBtn}
    onClick={() => {
      navigator.clipboard.writeText(text).then(() => antMessage.success('已复制'));
    }}
    title="复制"
    type="button"
  >
    <CopyOutlined />
  </button>
);

// Code card with title + copy + highlighted content
const CodeCard: React.FC<{ title: string; content: string }> = ({ title, content }) => (
  <div className={styles.codeCard}>
    <div className={styles.codeCardHeader}>
      <span className={styles.codeCardTitle}>{title}</span>
      <CopyButton text={content} />
    </div>
    <pre className={styles.codeBlock}>
      {highlightJson(content)}
    </pre>
  </div>
);

// Helper: try to parse and format JSON string, fallback to raw string
const formatToolResult = (result: unknown): string => {
  if (result == null) {
    return '{}';
  }
  if (typeof result === 'string') {
    // Try to parse as JSON to pretty-print it
    try {
      const parsed = JSON.parse(result);
      return JSON.stringify(parsed, null, 2);
    } catch {
      // Not valid JSON, return as-is
      return result;
    }
  }
  // Already an object, serialize with indentation
  return JSON.stringify(result, null, 2);
};

// Render trace content
const renderTraceContent = (step: TraceItem): React.ReactNode => {
  switch (step.type) {
    case 'thinking':
    case 'think':
      return (
        <div className={styles.thinkingContent}>
          {(step.content || '').split('\n\n').filter(Boolean).map((para, i) => (
            <p key={i} className={styles.thinkingPara}>{para}</p>
          ))}
        </div>
      );
    case 'tool_call': {
      const inputStr = step.parameters && Object.keys(step.parameters).length > 0
        ? JSON.stringify(step.parameters, null, 2)
        : '{}';
      return (
        <div className={styles.toolContent}>
          <CodeCard title="Input" content={inputStr} />
        </div>
      );
    }
    case 'tool_result': {
      const outputStr = formatToolResult(step.result);
      return (
        <div className={styles.toolContent}>
          <CodeCard title="Output" content={outputStr} />
        </div>
      );
    }
    case 'answer': {
      // answer type only uses content field, should not fallback to result
      // result field is only for tool_result type
      return (
        <div className={styles.traceText}>
          <MarkdownContent content={step.content || ''} />
        </div>
      );
    }
    default:
      // Unknown trace step type - not rendered (usually an internal marker)
      return null;
  }
};

// Format latency for display
const formatLatency = (ms: number): string => {
  if (ms < 1000) {
    return `+${Math.round(ms)}ms`;
  }
  return `+${(ms / 1000).toFixed(2)}s`;
};

// Get latency color class based on duration
const getLatencyClass = (ms: number): string => {
  if (ms < 300) return styles.latencyFast;
  if (ms < 1000) return styles.latencyMedium;
  return styles.latencySlow;
};

// Individual trace step - card row style (like reference image)
const TraceStep: React.FC<{
  step: MergedTraceItem;
  defaultExpanded?: boolean;
  isLast?: boolean;
  previousTimestamp?: number;
  baseTimestamp: number;
  isIntermediateAnswer?: boolean;
}> = ({ step, defaultExpanded = false, previousTimestamp, baseTimestamp, isIntermediateAnswer }) => {
  const isAnswer = step.type === 'answer';
  const [expanded, setExpanded] = useState(defaultExpanded);
  const contentRef = useRef<HTMLDivElement>(null);
  const [contentHeight, setContentHeight] = useState(0);

  useEffect(() => {
    if (contentRef.current) {
      setContentHeight(contentRef.current.scrollHeight);
    }
  }, [expanded, step]);

  const toggle = useCallback(() => {
    if (contentRef.current) {
      setContentHeight(contentRef.current.scrollHeight);
    }
    setExpanded(prev => !prev);
  }, []);

  // Answer steps render as markdown, not a card row
  if (isAnswer) {
    return (
      <div className={`${styles.answerBlock} ${isIntermediateAnswer ? styles.intermediateAnswer : ''}`}>
        {isIntermediateAnswer && (
          <div className={styles.intermediateAnswerLabel}>💬 中间回答</div>
        )}
        <MarkdownContent content={step.content || ''} />
      </div>
    );
  }

  // For merged tool_call+tool_result: latency = toolResult.timestamp - step.timestamp
  const latency = step.toolResult
    ? step.toolResult.timestamp - step.timestamp
    : step.timestamp - (previousTimestamp || baseTimestamp);

  // Render combined tool content when tool_call has toolResult paired
  const renderContent = () => {
    if (step.type === 'tool_call' && step.toolResult) {
      const inputStr = step.parameters && Object.keys(step.parameters).length > 0
        ? JSON.stringify(step.parameters, null, 2)
        : '{}';
      const outputStr = formatToolResult(step.toolResult.result);
      return (
        <div className={styles.toolContent}>
          <CodeCard title="Input" content={inputStr} />
          <CodeCard title="Output" content={outputStr} />
        </div>
      );
    }
    return renderTraceContent(step);
  };

  return (
    <div className={styles.traceRow} role="listitem">
      <button
        className={`${styles.traceRowHeader} ${expanded ? styles.traceRowHeaderActive : ''}`}
        onClick={toggle}
        aria-expanded={expanded}
        type="button"
      >
        <span className={styles.traceRowIcon}>
          {getTraceIcon(step)}
        </span>
        <span className={styles.traceRowLabel}>
          {getTraceLabel(step)}
        </span>
        {latency > 0 && (
          <span className={`${styles.traceRowLatency} ${getLatencyClass(latency)}`}>
            {formatLatency(latency)}
          </span>
        )}
        <DownOutlined
          className={`${styles.traceRowChevron} ${expanded ? styles.traceRowChevronOpen : ''}`}
        />
      </button>
      <div
        className={styles.traceRowContent}
        style={{
          maxHeight: expanded ? `${contentHeight}px` : '0px',
          opacity: expanded ? 1 : 0,
        }}
      >
        <div ref={contentRef} className={styles.traceRowContentInner}>
          {renderContent()}
        </div>
      </div>
    </div>
  );
};

// Mock trace data for testing latency display
const createMockTrace = (baseTime: number): TraceItem[] => [
  {
    type: 'thinking',
    content: '用户要求计算，我需要分析这个数学表达式。',
    timestamp: baseTime + 150,
  },
  {
    type: 'tool_call',
    tool_name: 'calculator',
    parameters: { expression: '789 + 321' },
    timestamp: baseTime + 320,
  },
  {
    type: 'tool_result',
    tool_name: 'calculator',
    result: '1110',
    timestamp: baseTime + 580,
  },
  {
    type: 'thinking',
    content: '计算器返回结果是 1110，我现在可以将这个结果呈现给用户了。',
    timestamp: baseTime + 850,
  },
];

// Merge tool_call + tool_result pairs into single nodes
interface MergedTraceItem extends TraceItem {
  toolResult?: TraceItem;
}

const mergeToolPairs = (trace: TraceItem[]): MergedTraceItem[] => {
  const result: MergedTraceItem[] = [];
  let i = 0;
  console.log('[mergeToolPairs] Input trace:', trace.map(t => ({ type: t.type, tool_name: t.tool_name })));
  while (i < trace.length) {
    const step = trace[i];
    if (step.type === 'tool_call') {
      // Look ahead for matching tool_result
      const next = trace[i + 1];
      if (next && next.type === 'tool_result' && next.tool_name === step.tool_name) {
        console.log(`[mergeToolPairs] Merging tool_call ${step.tool_name} with tool_result`);
        result.push({ ...step, toolResult: next });
        i += 2;
        continue;
      } else {
        console.log(`[mergeToolPairs] No match for tool_call ${step.tool_name}`, { next });
      }
    }
    result.push(step);
    i++;
  }
  console.log('[mergeToolPairs] Output:', result.map(t => ({ type: t.type, tool_name: t.tool_name, hasToolResult: !!t.toolResult })));
  return result;
};

// Merge consecutive answer steps into one
const mergeConsecutiveAnswers = (trace: TraceItem[]): TraceItem[] => {
  const result: TraceItem[] = [];
  let currentAnswer: TraceItem | null = null;

  for (const step of trace) {
    if (step.type === 'answer') {
      if (currentAnswer) {
        // Merge with current answer
        currentAnswer.content = (currentAnswer.content || '') + (step.content || '');
        currentAnswer.timestamp = step.timestamp; // Use last timestamp
      } else {
        currentAnswer = { ...step };
      }
    } else {
      if (currentAnswer) {
        result.push(currentAnswer);
        currentAnswer = null;
      }
      result.push(step);
    }
  }

  if (currentAnswer) {
    result.push(currentAnswer);
  }

  return result;
};

// Merge consecutive thinking/think steps into one
const mergeConsecutiveThinks = (trace: TraceItem[]): TraceItem[] => {
  const result: TraceItem[] = [];
  let currentThink: TraceItem | null = null;

  for (const step of trace) {
    if (step.type === 'thinking' || step.type === 'think') {
      if (currentThink) {
        // Merge with current think (add space between segments)
        currentThink.content = (currentThink.content || '') + (step.content || '');
        currentThink.timestamp = step.timestamp; // Use last timestamp
      } else {
        currentThink = { ...step };
      }
    } else {
      if (currentThink) {
        result.push(currentThink);
        currentThink = null;
      }
      result.push(step);
    }
  }

  if (currentThink) {
    result.push(currentThink);
  }

  return result;
};

const MessageItem: React.FC<MessageItemProps> = ({ message, streamingTrace, sendStartTime, hideTraceDetails, cardSourceId }) => {
  const isUser = message.role === 'user';
  const { showThinking } = useChatStore();

  // Use streamingTrace if provided (for streaming mode), otherwise use message.trace
  const trace = streamingTrace || message.trace;
  // Filter out internal markers (llm_start/llm_end) - not displayed to users
  // Use whitelist filtering, only keep user-visible types
  const VISIBLE_TRACE_TYPES = new Set(['thinking', 'think', 'tool_call', 'tool_result', 'answer']);
  const filteredTrace = (trace || []).filter(
    step => VISIBLE_TRACE_TYPES.has(step.type)
      && !(step.type === 'answer' && !step.content?.trim())  // filter empty answers
  );
  // Merge: consecutive thinks -> consecutive answers -> tool_call+tool_result pairs
  const allTrace = mergeToolPairs(mergeConsecutiveAnswers(mergeConsecutiveThinks(filteredTrace)));

  // Filter trace based on settings
  // 1. If Execution Details panel is open (hideTraceDetails=true), only show answer
  // 2. If showThinking is false, only show answer
  const visibleTrace = (hideTraceDetails || !showThinking)
    ? allTrace.filter(step => step.type === 'answer')
    : allTrace;

  // Determine which answers are intermediate (not the last answer in the trace)
  const answerIndices: number[] = [];
  visibleTrace.forEach((step, idx) => {
    if (step.type === 'answer') answerIndices.push(idx);
  });
  const lastAnswerIndex = answerIndices.length > 0 ? answerIndices[answerIndices.length - 1] : -1;

  // For demo: add mock trace to assistant messages containing calculation results
  if (!isUser && allTrace.length === 0 && message.content?.match(/\d+\s*[=＝]\s*\d+/)) {
    const baseTime = sendStartTime || Date.now() - 1000;
    allTrace.push(...createMockTrace(baseTime));
  }

  // User message - right-aligned bubble with avatar
  if (isUser) {
    return (
      <div className={styles.userRow}>
        <div className={styles.userBubble}>
          <p className={styles.userText}>{message.content}</p>
        </div>
        <div className={styles.userAvatar}>
          <UserOutlined />
        </div>
      </div>
    );
  }

  // Assistant message with trace
  // Use allTrace.length instead of visibleTrace.length to prevent raw message.content
  // from leaking tool_result JSON during Tool Call phase.
  if (allTrace.length > 0) {
    const baseTimestamp = (sendStartTime && sendStartTime > 0) ? sendStartTime : (allTrace[0]?.timestamp || Date.now());

    return (
      <div className={styles.assistantRow}>
        <div className={styles.assistantAvatar}>
          <RobotOutlined />
        </div>
        <div className={styles.assistantBody}>
          {visibleTrace.length > 0 ? (
            <div className={styles.traceList} role="list" aria-label="Trace steps">
              {visibleTrace.map((step, index) => (
                <TraceStep
                  key={index}
                  step={step}
                  defaultExpanded={false}
                  isLast={index === visibleTrace.length - 1}
                  previousTimestamp={index > 0 ? visibleTrace[index - 1].timestamp : undefined}
                  baseTimestamp={baseTimestamp}
                  isIntermediateAnswer={step.type === 'answer' && index !== lastAnswerIndex}
                />
              ))}
            </div>
          ) : (
            // All trace items are filtered out (e.g. only tool_call/tool_result visible
            // but user has hideTraceDetails or showThinking=false).
            // Show a minimal loading indicator instead of raw message.content.
            <div className={styles.traceLoading}>Processing...</div>
          )}
          {message.metadata?.cards && (message.metadata.cards as any[]).length > 0 && (
            <div className={styles.cardsList}>
              {(message.metadata.cards as any[]).map((card, idx) => (
                <CardRenderer key={idx} card={card} sourceId={cardSourceId} />
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  // Regular assistant message without trace
  return (
    <div className={styles.assistantRow}>
      <div className={styles.assistantAvatar}>
        <RobotOutlined />
      </div>
      <div className={styles.assistantBody}>
        {message.metadata?.cards && (message.metadata.cards as any[]).length > 0 && (
          <div className={styles.cardsList}>
            {(message.metadata.cards as any[]).map((card, idx) => (
              <CardRenderer key={idx} card={card} sourceId={cardSourceId} />
            ))}
          </div>
        )}
        <MarkdownContent content={message.content || ''} />
      </div>
    </div>
  );
};

export default MessageItem;
