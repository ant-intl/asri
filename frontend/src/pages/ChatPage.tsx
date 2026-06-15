import React from 'react';
import { Typography } from 'antd';
import { MessageOutlined } from '@ant-design/icons';
import ChatWindow from '@/components/Chat/ChatWindow';
import { ToolCardGrid, ModelCardGrid, SkillCardGrid, McpConfig, PromptManager, AdvancedSettings, VersionManager, ChatCompare, Settings, AgentSettings, CacheMonitor, SnapshotManager } from '@/components/Admin';
import { useChatStore } from '@/stores/chatStore';
import styles from './ChatPage.module.css';

const { Title, Text } = Typography;

const WelcomePage: React.FC = () => (
  <div className={styles.welcome}>
    <div className={styles.welcomeIcon}>
      <MessageOutlined />
    </div>
    <Title level={4} className={styles.welcomeTitle}>
      Welcome to ASRI
    </Title>
    <Text className={styles.welcomeText}>Select a session from the left to start chatting, or manage tools/models</Text>
  </div>
);

const ChatPage: React.FC = () => {
  const { activeTab, currentSession } = useChatStore();

  // Render content based on active tab
  const renderContent = () => {
    switch (activeTab) {
      case 'chat':
        return currentSession ? <ChatWindow /> : <WelcomePage />;
      case 'agent-settings':
        return <AgentSettings />;
      case 'tools':
        return <ToolCardGrid />;
      case 'models':
        return <ModelCardGrid />;
      case 'skills':
        return <SkillCardGrid />;
      case 'mcp':
        return <McpConfig />;
      case 'prompt':
        return <PromptManager />;
      case 'advanced':
        return <AdvancedSettings />;
      case 'mcp-mock':
        return <div style={{ padding: 24 }}><h2>MCP Mock</h2><p>MCP Mock configuration page (coming soon)</p></div>;
      case 'user-simulator':
        return <div style={{ padding: 24 }}><h2>User Simulator</h2><p>User Simulator page (coming soon)</p></div>;
      case 'version-manager':
        return <VersionManager />;
      case 'cache-monitor':
        return <CacheMonitor />;
      case 'chat-compare':
        return <ChatCompare />;
      case 'snapshots':
        return <SnapshotManager />;
      case 'setting':
        return <Settings />;
      default:
        return <WelcomePage />;
    }
  };

  return <div className={styles.container}>{renderContent()}</div>;
};

export default ChatPage;
