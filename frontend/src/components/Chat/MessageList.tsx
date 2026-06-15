import React, { useEffect, useRef } from 'react';
import { Spin, Empty } from 'antd';
import MessageItem from './MessageItem';
import { useChatStore } from '@/stores/chatStore';
import type { TraceItem } from '@/types/chat';
import styles from './MessageList.module.css';

interface MessageListProps {
  loading?: boolean;
  streamingTrace?: TraceItem[];
  sendStartTime?: number;
  hideTraceDetails?: boolean; // When Task Execution Details panel is open
  onMessageClick?: (conversationId: string) => void; // Callback when a message is clicked
}

const MessageList: React.FC<MessageListProps> = ({ loading, streamingTrace, sendStartTime, hideTraceDetails, onMessageClick }) => {
  const { messages, isStreaming, streamingContent } = useChatStore();
  const bottomRef = useRef<HTMLDivElement>(null);

  // Scroll to bottom when messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  if (loading) {
    return (
      <div className={styles.container}>
        <div className={styles.loading}>
          <Spin size="large" />
        </div>
      </div>
    );
  }

  if (messages.length === 0 && !isStreaming) {
    return (
      <div className={styles.container}>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="Start a new conversation"
          className={styles.empty}
        />
      </div>
    );
  }

  // Calculate sendStartTime for each assistant message based on the preceding user message
  const getSendStartTime = (messageIndex: number): number => {
    // Find the preceding user message
    for (let i = messageIndex - 1; i >= 0; i--) {
      if (messages[i].role === 'user') {
        // Convert ISO timestamp to Unix timestamp (milliseconds)
        // Use Date.parse for consistent UTC-based conversion
        const userTimestamp = Date.parse(messages[i].timestamp);
        return isNaN(userTimestamp) ? 0 : userTimestamp;
      }
    }
    return 0;
  };

  return (
    <div className={styles.container}>
      <div className={styles.list}>
        {messages.map((message, index) => (
          <MessageItem
            key={message.id}
            message={message}
            sendStartTime={message.role === 'assistant' ? getSendStartTime(index) : undefined}
            hideTraceDetails={hideTraceDetails}
            onClick={onMessageClick ? () => onMessageClick(`conversation-${Math.floor(index / 2) + 1}`) : undefined}
          />
        ))}
        {isStreaming && (streamingContent || (streamingTrace && streamingTrace.length > 0)) && (
          <MessageItem
            key={`streaming-${streamingTrace?.length || 0}`}
            message={{
              id: 'streaming',
              role: 'assistant',
              content: streamingContent,
              message_type: 'text',
              timestamp: new Date().toISOString(),
            }}
            streamingTrace={streamingTrace}
            sendStartTime={sendStartTime}
            isStreaming={true}
            hideTraceDetails={hideTraceDetails}
          />
        )}
      </div>
      <div ref={bottomRef} />
    </div>
  );
};

export default MessageList;
