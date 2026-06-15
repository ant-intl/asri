import React from 'react';
import { Typography } from 'antd';
import { AgentConfig } from '.';
import styles from './AdvancedSettings.module.css';

const { Title } = Typography;

const AdvancedSettings: React.FC = () => {
  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <Title level={4} className={styles.title}>Advanced Settings</Title>
      </div>
      <AgentConfig />
    </div>
  );
};

export default AdvancedSettings;
