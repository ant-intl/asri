import React from 'react';
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  LoadingOutlined,
  SyncOutlined,
  CheckOutlined,
  BulbOutlined,
  ToolOutlined,
  ThunderboltOutlined,
  SearchOutlined,
  ExpandAltOutlined,
  CompressOutlined,
  ExclamationOutlined,
  UpOutlined,
  DownOutlined,
  ApiOutlined,
} from '@ant-design/icons';
import styles from './TodoList.module.css';
import { TRACE_TYPE_CONFIG } from '@/types/traceConfig';

// Extended TodoItem type with Gantt positioning
// 5 states: pending, running, completed, failed, interrupted
// 4 types: thinking, tool_call(tool call), llm_call(LLM call), answer
export interface TodoItem {
  id: string;
  title: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'interrupted';
  type: 'conversation' | 'thinking' | 'tool_call' | 'llm_call' | 'answer';
  progress?: number;
  startTime?: number;
  endTime?: number;
  relativeTime?: number;
  dependencies?: string[];
  level?: number;
  children?: TodoItem[];
  parentId?: string;
  expanded?: boolean;
  conversationId?: string;
  conversationIndex?: number;
  duration?: number;
  left?: number;
  width?: number;
  totalDuration?: number;
  // Raw trace data, used to show details when expanded
  traceData?: TraceItemData;
}

// Simplified trace data type
export interface TraceItemData {
  type: string;
  timestamp?: number;
  content?: string;
  model?: string;
  provider?: string;
  duration_ms?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  cached_tokens?: number;
  finish_reason?: string;
  tool_name?: string;
  parameters?: Record<string, unknown>;
  result?: unknown;
  status?: string;
}

interface TodoListProps {
  items: TodoItem[];
  isLoading?: boolean;
  title?: string;
  isExpanded?: boolean;
  onToggleExpand?: () => void;
  highlightedConversationId?: string; // ID of conversation to highlight and scroll to
  className?: string;
}

// ============================================================
// Helper functions
// ============================================================

const getStatusLabel = (status: string): string => {
  switch (status) {
    case 'pending': return 'Pending';
    case 'running': return 'Running';
    case 'completed': return 'Completed';
    case 'failed': return 'Failed';
    case 'interrupted': return 'Interrupted';
    default: return '';
  }
};

const getStatusClass = (status: string): string => {
  switch (status) {
    case 'pending': return styles.statusPending;
    case 'running': return styles.statusRunning;
    case 'completed': return styles.statusCompleted;
    case 'failed': return styles.statusFailed;
    case 'interrupted': return styles.statusInterrupted;
    default: return styles.statusCompleted;
  }
};

// Status icon: completed=checkmark, interrupted=exclamation, pending=hollow circle, running=hollow circle
const getStatusIcon = (status: string) => {
  switch (status) {
    case 'completed':
      return <CheckOutlined className={styles.statusIconCheck} />;
    case 'interrupted':
      return <ExclamationOutlined className={styles.statusIconExclamation} />;
    case 'pending':
      return <span className={styles.statusIconCircle} />;
    case 'running':
      return <span className={`${styles.statusIconCircle} ${styles.statusIconCircleRunning}`} />;
    case 'failed':
      return <ExclamationOutlined className={styles.statusIconFailed} />;
    default:
      return null;
  }
};

// Status icon container styles - returns different background colors based on status
const getStatusIconWrapperClass = (status: string): string => {
  const baseClass = styles.stepStatus;
  switch (status) {
    case 'running':
      return `${baseClass} ${styles.statusIconRunning}`;
    case 'completed':
      return `${baseClass} ${styles.statusIconCompleted}`;
    case 'failed':
      return `${baseClass} ${styles.statusIconFailedBg}`;
    case 'interrupted':
      return `${baseClass} ${styles.statusIconInterrupted}`;
    default:
      return baseClass; // pending uses the default light yellow
  }
};

const getTypeLabel = (type: string): string => {
  const config = TRACE_TYPE_CONFIG[type] || TRACE_TYPE_CONFIG['thinking'];
  return config?.label || type;
};

const getStepIcon = (type: string, status?: string) => {
  // Interrupted status always shows lightning bolt
  if (status === 'interrupted') {
    return <ThunderboltOutlined />;
  }
  switch (type) {
    case 'thinking': return <BulbOutlined />;
    case 'tool_call': return <ToolOutlined />;
    case 'llm_call': return <ApiOutlined />;
    case 'answer': return <CheckCircleOutlined />;
    default: return <ClockCircleOutlined />;
  }
};

const getStepIconClass = (type: string, status?: string): string => {
  // Interrupted status always shows gray icon
  if (status === 'interrupted') {
    return `${styles.stepIcon} ${styles.stepIconInterrupted}`.trim();
  }
  const typeClass = {
    thinking: styles.stepIconThinking,
    tool_call: styles.stepIconToolCall,
    llm_call: styles.stepIconThinking,
    answer: styles.stepIconAnswer,
  }[type] || styles.stepIconThinking;
  return `${styles.stepIcon} ${typeClass}`.trim();
};

const getTimelineBarClass = (type: string): string => {
  const typeMap: Record<string, string> = {
    thinking: styles.timelineBarThinking,
    tool_call: styles.timelineBarToolCall,
    llm_call: styles.timelineBarThinking,
    answer: styles.timelineBarAnswer,
  };
  return typeMap[type] || styles.timelineBarThinking;
};

// Background fill color - unified gray tones
const getProgressBgColor = (type: string): string => {
  return '#b8b8b8';
};

const formatRelativeTime = (relativeTime?: number): string => {
  if (relativeTime === undefined || relativeTime === null) return '0.0';
  // Ensure time is not negative
  const safeTime = Math.max(0, relativeTime);
  return safeTime.toFixed(1);
};

const formatDuration = (ms?: number): string => {
  if (!ms) return '0.0';
  return (ms / 1000).toFixed(1);
};

// Format trace data for display
const formatTraceData = (traceData?: TraceItemData): React.ReactNode => {
  if (!traceData) return null;

  const rows: React.ReactNode[] = [];

  // Basic information
  if (traceData.type) {
    rows.push(<div key="type"><span className={styles.detailLabel}>Type:</span> <span>{traceData.type}</span></div>);
  }
  if (traceData.model) {
    rows.push(<div key="model"><span className={styles.detailLabel}>Model:</span> <span>{traceData.model}</span></div>);
  }
  if (traceData.provider) {
    rows.push(<div key="provider"><span className={styles.detailLabel}>Provider:</span> <span>{traceData.provider}</span></div>);
  }
  if (traceData.tool_name) {
    rows.push(<div key="tool_name"><span className={styles.detailLabel}>Tool:</span> <span>{traceData.tool_name}</span></div>);
  }
  if (traceData.status) {
    rows.push(<div key="status"><span className={styles.detailLabel}>Status:</span> <span>{traceData.status}</span></div>);
  }
  if (traceData.duration_ms) {
    rows.push(<div key="duration"><span className={styles.detailLabel}>Duration:</span> <span>{traceData.duration_ms.toFixed(2)}ms</span></div>);
  }
  if (traceData.prompt_tokens) {
    rows.push(<div key="prompt"><span className={styles.detailLabel}>Prompt Tokens:</span> <span>{traceData.prompt_tokens}</span></div>);
  }
  if (traceData.completion_tokens) {
    rows.push(<div key="completion"><span className={styles.detailLabel}>Completion Tokens:</span> <span>{traceData.completion_tokens}</span></div>);
  }
  if (traceData.total_tokens) {
    rows.push(<div key="total"><span className={styles.detailLabel}>Total Tokens:</span> <span>{traceData.total_tokens}</span></div>);
  }
  if (traceData.cached_tokens !== undefined && traceData.cached_tokens > 0) {
    rows.push(<div key="cached"><span className={styles.detailLabel}>Cached Tokens:</span> <span>{traceData.cached_tokens}</span></div>);
    // Show cache hit rate
    const promptTokens = traceData.prompt_tokens || 0;
    if (promptTokens > 0) {
      const hitRate = ((traceData.cached_tokens / promptTokens) * 100).toFixed(1);
      rows.push(<div key="cache_rate"><span className={styles.detailLabel}>Cache Hit Rate:</span> <span style={{ color: '#16a34a', fontWeight: 600 }}>{hitRate}%</span></div>);
    }
  }
  if (traceData.finish_reason) {
    rows.push(<div key="finish_reason"><span className={styles.detailLabel}>Finish Reason:</span> <span>{traceData.finish_reason}</span></div>);
  }

  // Content - show for all types including answer
  if (traceData.content) {
    rows.push(
      <div key="content" className={styles.detailContent}>
        <span className={styles.detailLabel}>Content:</span>
        <pre className={styles.detailPre}>{traceData.content}</pre>
      </div>
    );
  }

  // Parameters
  if (traceData.parameters && Object.keys(traceData.parameters).length > 0) {
    rows.push(
      <div key="params" className={styles.detailContent}>
        <span className={styles.detailLabel}>Parameters:</span>
        <pre className={styles.detailPre}>{JSON.stringify(traceData.parameters, null, 2)}</pre>
      </div>
    );
  }

  // Result
  if (traceData.result !== undefined && traceData.result !== null) {
    const resultStr = typeof traceData.result === 'string'
      ? traceData.result
      : JSON.stringify(traceData.result, null, 2);
    rows.push(
      <div key="result" className={styles.detailContent}>
        <span className={styles.detailLabel}>Result:</span>
        <pre className={styles.detailPre}>{resultStr}</pre>
      </div>
    );
  }

  return <div className={styles.detailGrid}>{rows}</div>;
};

// ============================================================
// Components
// ============================================================

const TimelineBar: React.FC<{ item: TodoItem }> = ({ item }) => {
  const left = item.left ?? 0;
  // Width should already have minimum from calculateTimelinePosition
  // but we ensure a minimum here as well
  const calculatedWidth = item.width ?? 2;
  const width = Math.max(calculatedWidth, 2);

  return (
    <div
      className={`${styles.timelineBar} ${getTimelineBarClass(item.type)} ${item.status === 'running' ? styles.timelineBarRunning : ''}`}
      style={{ left: `${Math.max(left, 0)}%`, width: `${width}%` }}
      title={`${getTypeLabel(item.type)}: ${formatDuration(item.duration)}s | Position: ${left.toFixed(1)}%`}
    />
  );
};

const StepRow: React.FC<{ item: TodoItem; isExpanded: boolean; onToggle: () => void }> = ({
  item,
  isExpanded,
  onToggle
}) => {
  const progressColor = getProgressBgColor(item.type);

  return (
    <div className={styles.stepRowWrapper}>
      <div
        className={`${styles.stepRowBg} ${isExpanded ? styles.stepRowExpanded : ''}`}
        onClick={onToggle}
      >
        {/* Background progress bar - fills from left to right */}
        <div
          className={`${styles.progressBg} ${item.status === 'running' ? styles.progressBgRunning : ''}`}
          style={{
            width: '100%',
            backgroundColor: progressColor,
            opacity: item.status === 'pending' ? 0.05 : 0.15,
          }}
        />
        {/* Info layer */}
        <div className={styles.stepContent}>
          <div className={getStepIconClass(item.type, item.status)}>
            {getStepIcon(item.type, item.status)}
          </div>
          <span className={styles.stepLabel}>{item.title}</span>
          <span className={styles.stepTime}>
            {formatRelativeTime(item.relativeTime)}s
          </span>
          <div className={getStatusIconWrapperClass(item.status)}>
            {getStatusIcon(item.status)}
          </div>
        </div>
      </div>
      {/* Expanded detail panel */}
      {isExpanded && (
        <div className={styles.stepDetailPanel}>
          {formatTraceData(item.traceData)}
        </div>
      )}
    </div>
  );
};

const ConversationBlock: React.FC<{
  conversation: TodoItem;
  steps: TodoItem[];
  isLastConversation?: boolean;
  isHighlighted?: boolean;
  expandAll?: boolean; // Global expand state from parent
}> = ({
  conversation,
  steps,
  isLastConversation = false,
  isHighlighted = false,
  expandAll = true,
}) => {
  // Interrupted conversations should be collapsed by default, others expanded
  const [localExpandedIds, setLocalExpandedIds] = React.useState<Set<string>>(() => {
    // Interrupted conversations should remain collapsed by default
    if (conversation.status === 'interrupted') {
      return new Set();
    }
    return new Set(steps.map(s => s.id));
  });
  const totalDuration = conversation.totalDuration || 1;
  const blockRef = React.useRef<HTMLDivElement>(null);

  // Sync with expandAll prop (but interrupted conversations stay collapsed unless highlighted)
  React.useEffect(() => {
    // Interrupted conversations stay collapsed unless highlighted
    if (conversation.status === 'interrupted' && !isHighlighted) {
      return;
    }
    if (expandAll) {
      setLocalExpandedIds(new Set(steps.map(s => s.id)));
    } else {
      setLocalExpandedIds(new Set());
    }
  }, [expandAll, steps, conversation.status, isHighlighted]);

  // Scroll into view and expand when highlighted
  React.useEffect(() => {
    if (isHighlighted && blockRef.current) {
      blockRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
      // Expand all steps when highlighted
      setLocalExpandedIds(new Set(steps.map(s => s.id)));
    }
  }, [isHighlighted, steps]);

  const handleToggle = (id: string) => {
    setLocalExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  return (
    <div
      ref={blockRef}
      className={`${styles.conversationBlock} ${isHighlighted ? styles.conversationBlockHighlighted : ''}`}
    >
      <div className={styles.conversationHeader}>
        <div className={styles.conversationTitle}>
          <span className={styles.conversationQuestion}>
            {conversation.title}
          </span>
        </div>
        <div className={styles.conversationMeta}>
          <span className={`${styles.statusBadge} ${getStatusClass(conversation.status)}`}>
            {conversation.status === 'running' && (
              <SyncOutlined spin style={{ fontSize: 10 }} />
            )}
            {getStatusLabel(conversation.status)}
          </span>
        </div>
      </div>

      <div className={styles.stepDetails}>
        {/* Filter out thinking steps for interrupted conversations */}
        {steps
          .filter(step => conversation.status !== 'interrupted' || step.type !== 'thinking')
          .map((step) => (
            <StepRow
              key={step.id}
              item={step}
              isExpanded={localExpandedIds.has(step.id)}
              onToggle={() => handleToggle(step.id)}
            />
        ))}
      </div>
    </div>
  );
};

// ============================================================
// Main Component
// ============================================================

const TodoList: React.FC<TodoListProps> = ({
  items,
  isLoading,
  title = 'Task Execution Details',
  isExpanded = false,
  onToggleExpand,
  highlightedConversationId,
  className,
}) => {
  const stepItems = items.filter((i) => i.type !== 'conversation');
  // Completed includes both 'completed' and 'interrupted' states
  const completedCount = stepItems.filter((i) => i.status === 'completed' || i.status === 'interrupted').length;
  const runningCount = stepItems.filter((i) => i.status === 'running').length;

  // Global expand/collapse state
  const [expandAll, setExpandAll] = React.useState(true);

  // Ref for auto-scroll to bottom
  const bottomRef = React.useRef<HTMLDivElement>(null);

  const conversations = React.useMemo(() => {
    const grouped = new Map<string, { conversation: TodoItem; steps: TodoItem[] }>();

    // First pass: collect all conversation items
    items.forEach((item) => {
      if (item.type === 'conversation') {
        grouped.set(item.id, { conversation: item, steps: [] });
      }
    });

    // Second pass: assign steps to conversations
    let defaultConversationCreated = false;
    items.forEach((item) => {
      if (item.type === 'conversation') return;

      const convId = item.conversationId || 'default';
      let group = grouped.get(convId);

      // If conversation doesn't exist, create a synthetic one
      if (!group) {
        // Find the first step to get conversation metadata
        const firstStep = items.find(i => i.conversationId === convId && i.type !== 'conversation');
        const conversationIndex = firstStep?.conversationIndex || grouped.size + 1;

        const syntheticConversation: TodoItem = {
          id: convId,
          type: 'conversation',
          title: firstStep?.title || `Conversation ${conversationIndex}`,
          status: 'completed',
          relativeTime: 0,
          conversationId: convId,
          conversationIndex,
          left: 0,
          width: 100,
          totalDuration: firstStep?.totalDuration || 1000,
          duration: firstStep?.totalDuration,
        };
        group = { conversation: syntheticConversation, steps: [] };
        grouped.set(convId, group);
        defaultConversationCreated = true;
      }

      group.steps.push(item);
    });

    // Sort steps by relativeTime
    grouped.forEach((group) => {
      group.steps.sort((a, b) => (a.relativeTime ?? 0) - (b.relativeTime ?? 0));
    });

    return Array.from(grouped.values()).sort(
      (a, b) => (a.conversation.conversationIndex ?? 0) - (b.conversation.conversationIndex ?? 0)
    );
  }, [items]);

  // Auto-scroll to bottom when new items arrive
  React.useEffect(() => {
    if (items.length > 0) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [items]);

  // Check for empty state - use conversations length instead of items length
  const hasNoConversations = conversations.length === 0;
  const hasNoSteps = conversations.every(c => c.steps.length === 0);

  if ((hasNoConversations || hasNoSteps) && !isLoading) {
    return (
      <aside className={`${styles.container}${className ? ` ${className}` : ''}`} aria-label="Todo list panel">
        <div className={styles.header}>
          <h4 className={styles.title}>{title}</h4>
        </div>
        <div className={styles.empty}>
          <CheckOutlined className={styles.emptyIcon} />
          <div className={styles.emptyText}>No tasks yet</div>
          <div className={styles.emptySubText}>Task execution progress will be shown after sending a message</div>
        </div>
      </aside>
    );
  }

  return (
    <aside className={`${styles.container} ${!title ? styles.containerCompact : ''}${className ? ` ${className}` : ''}`} aria-label="Todo list panel">
      {title && (
        <div className={styles.header}>
          <div className={styles.headerLeft}>
            <h4 className={styles.title}>{title}</h4>
            {stepItems.length > 0 && (
              <span className={styles.summary}>{completedCount}/{stepItems.length}</span>
            )}
          </div>
          <div className={styles.headerRight}>
            <button
              className={styles.expandBtn}
              onClick={() => setExpandAll(!expandAll)}
              title={expandAll ? 'Collapse all items' : 'Expand all items'}
              aria-label={expandAll ? 'Collapse all items' : 'Expand all items'}
            >
              {expandAll ? <UpOutlined /> : <DownOutlined />}
            </button>
            {onToggleExpand && (
              <button
                className={styles.expandBtn}
                onClick={onToggleExpand}
                title={isExpanded ? 'Collapse panel' : 'Expand panel to 50%'}
                aria-label={isExpanded ? 'Collapse panel' : 'Expand panel to 50%'}
              >
                {isExpanded ? <CompressOutlined /> : <ExpandAltOutlined />}
              </button>
            )}
          </div>
        </div>
      )}

      {isLoading && items.length === 0 && (
        <div className={styles.loading}>
          <LoadingOutlined className={styles.loadingIcon} />
          <span>Preparing...</span>
        </div>
      )}

      <div
        className={`${styles.conversationList} ${!title ? styles.ganttCompact : ''}`}
        role="list"
      >
        {conversations.map(({ conversation, steps }, index) => (
          <ConversationBlock
            key={conversation.id}
            conversation={conversation}
            steps={steps}
            isLastConversation={index === conversations.length - 1}
            isHighlighted={conversation.id === highlightedConversationId}
            expandAll={expandAll}
          />
        ))}
        <div ref={bottomRef} />
      </div>

      {runningCount > 0 && title && (
        <div className={styles.footer}>
          <SyncOutlined spin />
          <span>{runningCount} tasks running</span>
        </div>
      )}
    </aside>
  );
};

export default TodoList;
