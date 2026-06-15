import React from 'react';
import { Tabs, Typography } from 'antd';
import {
  SettingOutlined,
  ApiOutlined,
} from '@ant-design/icons';
import SessionSettingsContent from './SessionSettingsContent';
import HookConfigSection from './HookConfigSection';
import styles from './Settings.module.css';

const { Title, Text } = Typography;

const Settings: React.FC = () => {
  const tabsItems = [
    {
      key: 'session',
      label: (
        <span className={styles.tabLabel}>
          <SettingOutlined className={styles.tabIcon} />
          Session
        </span>
      ),
      children: <SessionSettingsContent />,
    },
    {
      key: 'hooks',
      label: (
        <span className={styles.tabLabel}>
          <ApiOutlined className={styles.tabIcon} />
          Hooks
        </span>
      ),
      children: <HookConfigSection />,
    },
  ];

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <Title level={4} className={styles.title}>Session</Title>
          <Text type="secondary" className={styles.subtitle}>
            Configure session parameters and hook policies
          </Text>
        </div>
      </div>

      <Tabs
        defaultActiveKey="session"
        className={styles.tabs}
        items={tabsItems}
      />
    </div>
  );
};

export default Settings;
