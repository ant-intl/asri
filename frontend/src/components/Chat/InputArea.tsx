import React, { useRef, useEffect, useState, useCallback } from 'react';
import { Input, Button, Tag, Popconfirm } from 'antd';
import { SendOutlined, LoadingOutlined, PaperClipOutlined, BulbOutlined, StopOutlined, ClearOutlined } from '@ant-design/icons';
import { useChatStore } from '@/stores/chatStore';
import styles from './InputArea.module.css';

const { TextArea } = Input;

const MAX_LENGTH = 10000;

interface InputAreaProps {
  onSend: (message: string) => void;
  onClear?: () => void;
  loading?: boolean;
}

const InputArea: React.FC<InputAreaProps> = ({ onSend, onClear, loading }) => {
  const { inputValue, setInputValue, isStreaming, showThinking, setShowThinking, messages } = useChatStore();
  const inputRef = useRef<any>(null);

  // History navigation state
  const [historyIndex, setHistoryIndex] = useState<number>(-1);
  const [savedInput, setSavedInput] = useState<string>('');

  // Get user messages from history (only 'user' role, exclude empty)
  const userMessages = React.useMemo(() => {
    return messages
      .filter(m => m.role === 'user' && m.content.trim())
      .map(m => m.content.trim());
  }, [messages]);

  // Auto-focus after sending message
  useEffect(() => {
    // Only auto-focus when not streaming and not loading
    // Keeping focus during streaming allows user to continue typing interrupt messages
    if (!loading && !isStreaming && inputRef.current) {
      inputRef.current.focus();
    }
  }, [loading, isStreaming]);

  const handleSend = () => {
    if (inputValue.trim()) {
      // Always allow sending messages, interrupt logic handled in ChatWindow
      onSend(inputValue.trim());
      setInputValue('');
    }
  };

  const handleClear = () => {
    onClear?.();
  };

  // Navigate through message history
  const navigateHistory = useCallback((direction: 'up' | 'down') => {
    const history = userMessages;
    if (history.length === 0) return;

    if (direction === 'up') {
      // Save current input if starting navigation
      if (historyIndex === -1) {
        setSavedInput(inputValue);
      }
      // Move up in history (newer to older)
      const newIndex = historyIndex === -1 ? history.length - 1 : Math.max(0, historyIndex - 1);
      setHistoryIndex(newIndex);
      setInputValue(history[newIndex]);
    } else {
      // Move down in history (older to newer)
      if (historyIndex === -1) return;

      const newIndex = historyIndex + 1;
      if (newIndex >= history.length) {
        // Restore saved input when going past newest message
        setHistoryIndex(-1);
        setInputValue(savedInput);
        setSavedInput('');
      } else {
        setHistoryIndex(newIndex);
        setInputValue(history[newIndex]);
      }
    }
  }, [historyIndex, inputValue, savedInput, setInputValue, userMessages]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    } else if (e.key === 'ArrowUp' && !e.shiftKey && !inputValue) {
      // Press Up when input is empty to go to last message
      e.preventDefault();
      navigateHistory('up');
    } else if (e.key === 'ArrowDown' && !e.shiftKey && historyIndex !== -1) {
      // Press Down to go forward in history
      e.preventDefault();
      navigateHistory('down');
    }
  };

  // Reset history index when input changes manually
  const handleInputChange = (value: string) => {
    setInputValue(value.slice(0, MAX_LENGTH));
    // Reset history navigation if user types manually
    if (historyIndex !== -1 && value !== userMessages[historyIndex]) {
      setHistoryIndex(-1);
      setSavedInput('');
    }
  };

  // Display different placeholder based on streaming status
  const placeholder = isStreaming
    ? 'Typing will interrupt current response...'
    : 'Enter message...';

  return (
    <div className={styles.container} role="form" aria-label="Message input">
      <div className={styles.inputWrapper}>
        <TextArea
          ref={inputRef}
          value={inputValue}
          onChange={(e) => handleInputChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          autoSize={{ minRows: 1, maxRows: 8 }}
          className={styles.input}
          aria-label="Message content"
        />
        <div className={styles.inputFooter}>
          <div className={styles.inputActions}>
            <Button
              type="text"
              size="small"
              icon={<PaperClipOutlined />}
              className={styles.actionBtn}
              title="Attachment"
            />
            <Button
              type="text"
              size="small"
              icon={<BulbOutlined />}
              className={`${styles.actionBtn} ${showThinking ? styles.actionBtnActive : ''}`}
              onClick={() => setShowThinking(!showThinking)}
              title={showThinking ? 'Hide thinking process' : 'Show thinking process'}
            />
            <Popconfirm
              title="Clear conversation"
              description="Are you sure you want to clear the current conversation?"
              onConfirm={handleClear}
              okText="OK"
              cancelText="Cancel"
              disabled={messages.length === 0}
            >
              <Button
                type="text"
                size="small"
                icon={<ClearOutlined />}
                className={styles.actionBtn}
                disabled={messages.length === 0 || isStreaming}
                title="Clear conversation"
              />
            </Popconfirm>
          </div>
          <div className={styles.inputRight}>
            {isStreaming && (
              <Tag color="orange" icon={<StopOutlined />}>
                Generating, typing will interrupt
              </Tag>
            )}
            <span className={`${styles.charCount} ${inputValue.length > MAX_LENGTH * 0.9 ? styles.charCountWarn : ''}`}>
              {inputValue.length}/{MAX_LENGTH}
            </span>
            <Button
              type="primary"
              icon={loading ? <LoadingOutlined /> : <SendOutlined />}
              onClick={handleSend}
              disabled={!inputValue.trim()}
              className={styles.sendBtn}
              aria-label={loading ? 'Sending' : 'Send message'}
            />
          </div>
        </div>
      </div>
    </div>
  );
};

export default InputArea;
