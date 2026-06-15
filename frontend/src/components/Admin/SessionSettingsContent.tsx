import React, { useState } from 'react';
import {
  Card,
  Form,
  Select,
  InputNumber,
  Switch,
  Typography,
  Divider,
  message,
} from 'antd';
import { safeJsonParse } from '@/utils/safeJsonParse';
import {
  ClockCircleOutlined,
  ThunderboltOutlined,
  ApiOutlined,
  ToolOutlined,
} from '@ant-design/icons';
import styles from './SettingsContent.module.css';

const { Title, Text } = Typography;

const STORAGE_KEY = 'asri_session_settings';

interface SessionSettingsData {
  maxInteractionRounds: number;
  thinkingAndActing: boolean;
  multitasking: boolean;
  executionMode: 'interleaved' | 'standard';
  connectionType: 'http' | 'websocket';
  isStream: boolean;
  httpStreamingMode: 'sse' | 'polling' | 'none';
  toolInterruptStrategy: 'immediate' | 'semantic_complete' | 'none';
}

const defaultSettings: SessionSettingsData = {
  maxInteractionRounds: 10,
  thinkingAndActing: true,
  multitasking: true,
  executionMode: 'interleaved',
  connectionType: 'http',
  isStream: true,
  httpStreamingMode: 'sse',
  toolInterruptStrategy: 'none',
};

/**
 * Read connection settings from localStorage.
 * Used by ChatWindow to determine connection type and stream mode.
 */
export function getConnectionSettings(): { connectionType: 'http' | 'websocket'; isStream: boolean; httpStreamingMode: 'sse' | 'polling' | 'none' } {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) {
    try {
      const settings = JSON.parse(saved);
      const connType = settings.connectionType || 'http';
      return {
        connectionType: connType,
        isStream: connType === 'websocket' ? true : (settings.isStream ?? true),
        httpStreamingMode: settings.httpStreamingMode ?? 'sse',
      };
    } catch {
      return { connectionType: 'http', isStream: true, httpStreamingMode: 'sse' };
    }
  }
  return { connectionType: 'http', isStream: true, httpStreamingMode: 'sse' };
}

/**
 * Read full interaction settings from localStorage.
 * Used by ChatWindow to pass interaction config to backend.
 */
export function getInteractionSettings(): { toolInterruptStrategy: 'immediate' | 'semantic_complete' | 'none'; maxInteractionRounds: number } {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) {
    try {
      const settings = JSON.parse(saved);
      return {
        toolInterruptStrategy: settings.toolInterruptStrategy ?? 'none',
        maxInteractionRounds: settings.maxInteractionRounds ?? 10,
      };
    } catch {
      return { toolInterruptStrategy: 'none', maxInteractionRounds: 10 };
    }
  }
  return { toolInterruptStrategy: 'none', maxInteractionRounds: 10 };
}

/**
 * Read full session settings from localStorage.
 * Used by ChatWindow to pass settings when creating snapshots.
 */
export function getSessionSettings(): SessionSettingsData {
  const saved = localStorage.getItem(STORAGE_KEY);
  return saved ? safeJsonParse<SessionSettingsData>(saved) ?? defaultSettings : defaultSettings;
}

const SessionSettingsContent: React.FC = () => {
  const [form] = Form.useForm();
  const [settings, setSettings] = useState<SessionSettingsData>(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved ? safeJsonParse<SessionSettingsData>(saved) ?? defaultSettings : defaultSettings;
  });

  const handleValuesChange = (changedValues: Partial<SessionSettingsData>) => {
    const newSettings = { ...settings, ...changedValues };
    // WebSocket forces stream mode
    if (changedValues.connectionType === 'websocket') {
      newSettings.isStream = true;
      form.setFieldsValue({ isStream: true });
    }
    // Sync thinkingAndActing and multitasking with executionMode
    if (changedValues.executionMode) {
      const isInterleaved = changedValues.executionMode === 'interleaved';
      newSettings.thinkingAndActing = isInterleaved;
      newSettings.multitasking = isInterleaved;
      form.setFieldsValue({
        thinkingAndActing: isInterleaved,
        multitasking: isInterleaved,
      });
    }
    setSettings(newSettings);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(newSettings));
    message.success('Settings saved');
  };

  return (
    <Card className={styles.card}>
      <Form
        form={form}
        layout="vertical"
        initialValues={settings}
        onValuesChange={handleValuesChange}
      >
        {/* Connection Settings */}
        <Title level={5} className={styles.sectionTitle}>
          <ApiOutlined className={styles.icon} />
          Connection Settings
        </Title>

        <Form.Item
          label="Connection Type"
          name="connectionType"
          help="HTTP supports both streaming and non-streaming; WebSocket always uses streaming"
        >
          <Select
            options={[
              { label: 'HTTP', value: 'http' },
              { label: 'WebSocket', value: 'websocket' },
            ]}
          />
        </Form.Item>

        {settings.connectionType === 'http' && (
          <>
            <Form.Item
              label="Stream Mode"
              name="isStream"
              help="Enable streaming mode for real-time responses"
            >
              <Select
                options={[
                  { label: 'Stream', value: true },
                  { label: 'Non-stream', value: false },
                ]}
              />
            </Form.Item>

            {settings.isStream && (
              <Form.Item
                label="HTTP Streaming Method"
                name="httpStreamingMode"
                help="SSE: Server-Sent Events (recommended). Polling: HTTP Long Polling (for environments without SSE support). None: Disable streaming."
              >
                <Select
                  options={[
                    { label: 'SSE (Server-Sent Events)', value: 'sse' },
                    { label: 'HTTP Long Polling', value: 'polling' },
                    { label: 'None (Wait for complete response)', value: 'none' },
                  ]}
                />
              </Form.Item>
            )}
          </>
        )}

        <Divider />

        {/* Interaction Limits */}
        <Title level={5} className={styles.sectionTitle}>
          <ClockCircleOutlined className={styles.icon} />
          Interaction Limits
        </Title>

        <Form.Item
          label="Max Interaction Rounds"
          name="maxInteractionRounds"
          help="Maximum think-act cycles per conversation, prevents infinite loops (default: 10)"
        >
          <InputNumber min={1} max={50} style={{ width: '100%' }} />
        </Form.Item>

        <Divider />

        {/* Agent Behavior Mode */}
        <Title level={5} className={styles.sectionTitle}>
          <ThunderboltOutlined className={styles.icon} />
          Agent Behavior Mode
        </Title>

        <Form.Item
          label="Execution Mode"
          name="executionMode"
          help="Interleaved: emit intermediate answers and execute tools concurrently. Standard: silent reasoning, sequential tools, final answer only."
        >
          <Select
            options={[
              { label: 'Interleaved (边想边答 / 并发工具 / 随机应变)', value: 'interleaved' },
              { label: 'Standard (完整推理 / 顺序工具 / 固定计划)', value: 'standard' },
            ]}
          />
        </Form.Item>

        <div className={styles.switchItem}>
          <div className={styles.switchLabel}>
            <Text strong>Think and Act Simultaneously</Text>
            <Text type="secondary">Agent will execute parallel operations during thinking process when enabled</Text>
          </div>
          <Switch
            checked={settings.thinkingAndActing}
            onChange={(checked) => handleValuesChange({ thinkingAndActing: checked })}
          />
        </div>

        <div className={styles.switchItem}>
          <div className={styles.switchLabel}>
            <Text strong>Multitasking</Text>
            <Text type="secondary">Allow Agent to handle multiple independent tasks simultaneously</Text>
          </div>
          <Switch
            checked={settings.multitasking}
            onChange={(checked) => handleValuesChange({ multitasking: checked })}
          />
        </div>

        <Divider />

        {/* Tool Interrupt Strategy */}
        <Title level={5} className={styles.sectionTitle}>
          <ToolOutlined className={styles.icon} />
          Tool Interrupt Strategy
        </Title>

        <Form.Item
          label="Tool Interrupt Behavior"
          name="toolInterruptStrategy"
          help="Controls how LLM streaming is interrupted when tool results arrive"
        >
          <Select
            options={[
              {
                label: 'Wait for current token then interrupt - Fast response with token integrity',
                value: 'immediate'
              },
              {
                label: 'Wait for all tools to complete then interrupt - Ensure tool context completeness',
                value: 'semantic_complete'
              },
              {
                label: 'No interrupt - LLM runs to completion naturally',
                value: 'none'
              },
            ]}
          />
        </Form.Item>
      </Form>
    </Card>
  );
};

export default SessionSettingsContent;
