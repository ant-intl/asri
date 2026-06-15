import React, { useState } from 'react';
import {
  Card,
  Button,
  Form,
  Input,
  Select,
  Slider,
  message,
  Typography,
  Space,
  Tooltip,
  Divider,
  Tabs,
} from 'antd';
import {
  SettingOutlined,
  SaveOutlined,
  InfoCircleOutlined,
  RobotOutlined,
  DatabaseOutlined,
} from '@ant-design/icons';
import styles from './AgentConfig.module.css';

const { Title, Text } = Typography;
const { Option } = Select;
const { TabPane } = Tabs;

interface AgentConfig {
  // ReAct Agent
  agentLanguage: string;
  userTimezone: string;
  maxIterations: number;
  // Context Management
  maxInputLength: number;
  contextCompactRatio: number;
  contextCompactThreshold: number;
  contextReserveRatio: number;
  contextReserveThreshold: number;
}

const defaultConfig: AgentConfig = {
  // ReAct Agent
  agentLanguage: 'English',
  userTimezone: 'Asia/Shanghai (UTC+8)',
  maxIterations: 50,
  // Context Management
  maxInputLength: 131072,
  contextCompactRatio: 0.75,
  contextCompactThreshold: 98304,
  contextReserveRatio: 0.1,
  contextReserveThreshold: 13107,
};

const languages = [
  { value: 'English', label: 'English' },
  { value: 'Chinese', label: 'Chinese' },
];

const timezones = [
  { value: 'Asia/Shanghai (UTC+8)', label: 'Asia/Shanghai (UTC+8)' },
  { value: 'UTC', label: 'UTC' },
  { value: 'America/New_York (UTC-5)', label: 'America/New_York (UTC-5)' },
];

const AgentConfig: React.FC = () => {
  const [config, setConfig] = useState<AgentConfig>(defaultConfig);

  const handleSave = () => {
    message.success('Agent configuration saved');
  };

  const FormItemLabel = ({ label, tooltip, required }: { label: string; tooltip?: string; required?: boolean }) => (
    <div>
      <Text strong>
        {label}
        {required && <span style={{ color: '#ff4d4f', marginLeft: 4 }}>*</span>}
      </Text>
      {tooltip && (
        <Tooltip title={tooltip}>
          <InfoCircleOutlined style={{ marginLeft: 4, color: '#999' }} />
        </Tooltip>
      )}
    </div>
  );

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <Title level={5} className={styles.title}>
            <RobotOutlined /> Configuration
          </Title>
          <Text type="secondary" className={styles.subtitle}>
            Configure runtime parameters
          </Text>
        </div>
        <Button
          type="primary"
          icon={<SaveOutlined />}
          onClick={handleSave}
          className={styles.saveBtn}
        >
          Save Config
        </Button>
      </div>

      <div className={styles.content}>
        <Tabs defaultActiveKey="base" className={styles.tabs}>
          <TabPane
            tab={
              <span>
                <RobotOutlined /> Base
              </span>
            }
            key="base"
          >
            <Card className={styles.sectionCard}>
              <div className={styles.sectionHeader}>
                <div>
                  <Title level={5}>Basic Configuration</Title>
                  <Text type="secondary">Configure Agent's basic runtime parameters</Text>
                </div>
              </div>

              <div className={styles.formItem}>
                <div className={styles.formLabel}>
                  <FormItemLabel label="Agent Language" />
                </div>
                <Select
                  value={config.agentLanguage}
                  onChange={(value) => setConfig({ ...config, agentLanguage: value })}
                  style={{ width: '100%' }}
                >
                  {languages.map((lang) => (
                    <Option key={lang.value} value={lang.value}>
                      {lang.label}
                    </Option>
                  ))}
                </Select>
              </div>

              <Divider />

              <div className={styles.formItem}>
                <div className={styles.formLabel}>
                  <FormItemLabel label="User Timezone" />
                </div>
                <Select
                  value={config.userTimezone}
                  onChange={(value) => setConfig({ ...config, userTimezone: value })}
                  style={{ width: '100%' }}
                >
                  {timezones.map((tz) => (
                    <Option key={tz.value} value={tz.value}>
                      {tz.label}
                    </Option>
                  ))}
                </Select>
              </div>

              <Divider />

              <div className={styles.formItem}>
                <div className={styles.formLabel}>
                  <FormItemLabel
                    label="Max Iterations"
                    tooltip="Maximum number of reasoning iterations"
                    required
                  />
                </div>
                <Input
                  type="number"
                  value={config.maxIterations}
                  onChange={(e) => setConfig({ ...config, maxIterations: parseInt(e.target.value) || 0 })}
                />
              </div>
            </Card>
          </TabPane>

          <TabPane
            tab={
              <span>
                <DatabaseOutlined /> Context
              </span>
            }
            key="context"
          >
            <Card className={styles.sectionCard}>
              <div className={styles.sectionHeader}>
                <div>
                  <Title level={5}>Context Management</Title>
                  <Text type="secondary">Configure context compression and retention policies</Text>
                </div>
              </div>

              <div className={styles.formItem}>
                <div className={styles.formLabel}>
                  <FormItemLabel
                    label="Max Input Length"
                    tooltip="Maximum input length in tokens"
                    required
                  />
                </div>
                <Input
                  type="number"
                  value={config.maxInputLength}
                  onChange={(e) => setConfig({ ...config, maxInputLength: parseInt(e.target.value) || 0 })}
                />
              </div>

              <Divider />

              <div className={styles.formItem}>
                <div className={styles.formLabel}>
                  <FormItemLabel
                    label="Context Compact Ratio"
                    tooltip="Ratio of context to compact when exceeding threshold"
                    required
                  />
                </div>
                <Slider
                  min={0.1}
                  max={0.9}
                  step={0.05}
                  value={config.contextCompactRatio}
                  onChange={(value) => setConfig({ ...config, contextCompactRatio: value })}
                  marks={{
                    0.3: '0.3',
                    0.6: '0.6',
                    0.9: '0.9',
                  }}
                />
              </div>

              <Divider />

              <div className={styles.formItem}>
                <div className={styles.formLabel}>
                  <FormItemLabel label="Context Compact Threshold" />
                </div>
                <Input type="number" value={config.contextCompactThreshold} disabled />
                <Text type="secondary" className={styles.formDesc}>Auto-calculated, cannot be modified</Text>
              </div>

              <Divider />

              <div className={styles.formItem}>
                <div className={styles.formLabel}>
                  <FormItemLabel
                    label="Context Reserve Ratio"
                    tooltip="Ratio of context to reserve"
                    required
                  />
                </div>
                <Slider
                  min={0.05}
                  max={0.3}
                  step={0.05}
                  value={config.contextReserveRatio}
                  onChange={(value) => setConfig({ ...config, contextReserveRatio: value })}
                  marks={{
                    0.05: '0.05',
                    0.15: '0.15',
                    0.3: '0.3',
                  }}
                />
              </div>

              <Divider />

              <div className={styles.formItem}>
                <div className={styles.formLabel}>
                  <FormItemLabel label="Context Reserve Threshold" />
                </div>
                <Input type="number" value={config.contextReserveThreshold} disabled />
                <Text type="secondary" className={styles.formDesc}>Auto-calculated, cannot be modified</Text>
              </div>
            </Card>
          </TabPane>
        </Tabs>
      </div>
    </div>
  );
};

export default AgentConfig;
