import React from 'react';
import { Typography } from 'antd';
import styles from './SystemSettings.module.css';

const { Title } = Typography;

const SystemSettings: React.FC = () => {
  return (
    <div className={styles.container}>
      <Title level={4} className={styles.title}>System Settings</Title>
    </div>
  );
};

export default SystemSettings;
