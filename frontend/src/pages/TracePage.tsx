import React from 'react';
import { useParams } from 'react-router-dom';
import { Spin } from 'antd';
import TodoList from '@/components/Chat/TodoList';
import { useTracePolling } from '@/hooks/useTracePolling';
import styles from './TracePage.module.css';

const TracePage: React.FC = () => {
  const { sessionId } = useParams<{ sessionId: string }>();

  const { todoItems, isLoading } = useTracePolling(sessionId || '');

  if (!sessionId) {
    return <div style={{ padding: 24 }}>Session ID is required</div>;
  }

  if (isLoading && todoItems.length === 0) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <div style={{ height: '100vh', overflow: 'auto', background: '#f5f7fa' }}>
      <TodoList
        items={todoItems}
        isLoading={isLoading}
        isExpanded={true}
        title="Execution Details"
        className={styles.todoListFullScreen}
      />
    </div>
  );
};

export default TracePage;
