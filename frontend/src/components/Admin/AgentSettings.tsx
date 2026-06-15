import React from 'react';
import { Tabs, Typography } from 'antd';
import {
  FileTextOutlined,
  DeploymentUnitOutlined,
  ApiOutlined,
  ToolOutlined,
  RobotOutlined,
} from '@ant-design/icons';
import { PromptManager, SkillCardGrid, McpConfig, ToolCardGrid, ModelCardGrid } from '@/components/Admin';
import styles from './Settings.module.css';

const { Title, Text } = Typography;

const AgentSettings: React.FC = () => {
  const tabsItems = [
    {
      key: 'prompts',
      label: (
        <span className={styles.tabLabel}>
          <FileTextOutlined className={styles.tabIcon} />
          Prompts
        </span>
      ),
      children: <PromptManager />,
    },
    {
      key: 'skills',
      label: (
        <span className={styles.tabLabel}>
          <DeploymentUnitOutlined className={styles.tabIcon} />
          Skills
        </span>
      ),
      children: <SkillCardGrid />,
    },
    {
      key: 'mcp',
      label: (
        <span className={styles.tabLabel}>
          <ApiOutlined className={styles.tabIcon} />
          MCPs
        </span>
      ),
      children: <McpConfig />,
    },
    {
      key: 'tools',
      label: (
        <span className={styles.tabLabel}>
          <ToolOutlined className={styles.tabIcon} />
          Tools
        </span>
      ),
      children: <ToolCardGrid />,
    },
    {
      key: 'models',
      label: (
        <span className={styles.tabLabel}>
          <RobotOutlined className={styles.tabIcon} />
          Models
        </span>
      ),
      children: <ModelCardGrid />,
    },
  ];

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <Title level={4} className={styles.title}>Agent Settings</Title>
          <Text type="secondary" className={styles.subtitle}>
            Manage Prompts, Skills, MCPs, Tools, Models
          </Text>
        </div>
      </div>

      <Tabs
        defaultActiveKey="prompts"
        className={styles.tabs}
        items={tabsItems}
      />
    </div>
  );
};

export default AgentSettings;
