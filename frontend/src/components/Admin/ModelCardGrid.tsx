import React, { useState } from 'react';
import { Card, Switch, Button, Modal, Form, Input, Select, message, Typography } from 'antd';
import { PlusOutlined, DeleteOutlined, RobotOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getLLMProviders,
  createLLMProvider,
  updateLLMProvider,
  deleteLLMProvider,
  enableLLMProvider,
  disableLLMProvider,
} from '@/api/llmProvider';
import type { LLMProvider, ProviderType, ModelPurpose } from '@/types/llmProvider';
import { parseJsonOrThrow } from '@/utils/safeJsonParse';
import styles from './ModelCardGrid.module.css';

const { TextArea } = Input;
const { Text } = Typography;

const providerTypeColors: Record<ProviderType, string> = {
  openai: '#1890ff',
  ollama: '#52c41a',
  asri_gateway: '#13c2c2',
};

const providerTypeLabels: Record<ProviderType, string> = {
  openai: 'OpenAI',
  ollama: 'Ollama',
  asri_gateway: 'ASRI Gateway',
};

const purposeColors: Record<ModelPurpose, string> = {
  chatbot: '#1677ff',
};

const purposeLabels: Record<ModelPurpose, string> = {
  chatbot: 'Chatbot',
};

const purposeIcons: Record<ModelPurpose, React.ReactNode> = {
  chatbot: <RobotOutlined />,
};

const ModelCardGrid: React.FC = () => {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingProvider, setEditingProvider] = useState<LLMProvider | null>(null);
  const [form] = Form.useForm();
  const queryClient = useQueryClient();

  // Fetch providers
  const { data: providersData, isLoading } = useQuery({
    queryKey: ['llm-providers'],
    queryFn: getLLMProviders,
  });

  // Create provider mutation
  const createMutation = useMutation({
    mutationFn: createLLMProvider,
    onSuccess: () => {
      message.success('Model created successfully');
      queryClient.invalidateQueries({ queryKey: ['llm-providers'] });
      setIsModalOpen(false);
      form.resetFields();
    },
    onError: () => {
      message.error('Model creation failed');
    },
  });

  // Update provider mutation
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof updateLLMProvider>[1] }) =>
      updateLLMProvider(id, data),
    onSuccess: () => {
      message.success('Model updated successfully');
      queryClient.invalidateQueries({ queryKey: ['llm-providers'] });
      setIsModalOpen(false);
      setEditingProvider(null);
      form.resetFields();
    },
    onError: () => {
      message.error('Model update failed');
    },
  });

  // Delete provider mutation
  const deleteMutation = useMutation({
    mutationFn: deleteLLMProvider,
    onSuccess: () => {
      message.success('Model deleted successfully');
      queryClient.invalidateQueries({ queryKey: ['llm-providers'] });
    },
    onError: () => {
      message.error('Model deletion failed');
    },
  });

  // Enable provider mutation
  const enableMutation = useMutation({
    mutationFn: enableLLMProvider,
    onSuccess: (data) => {
      message.success(data.message);
      queryClient.invalidateQueries({ queryKey: ['llm-providers'] });
    },
    onError: () => {
      message.error('Enable model failed');
    },
  });

  // Disable provider mutation
  const disableMutation = useMutation({
    mutationFn: disableLLMProvider,
    onSuccess: (data) => {
      message.success(data.message);
      queryClient.invalidateQueries({ queryKey: ['llm-providers'] });
    },
    onError: () => {
      message.error('Disable model failed');
    },
  });

  const handleAdd = () => {
    setEditingProvider(null);
    form.resetFields();
    setIsModalOpen(true);
  };

  const handleEdit = (provider: LLMProvider, e?: React.MouseEvent) => {
    e?.stopPropagation();
    setEditingProvider(provider);
    form.setFieldsValue({
      name: provider.name,
      provider_type: provider.provider_type,
      api_base: provider.api_base,
      api_key: provider.api_key,
      model_name: provider.model_name,
      purpose: provider.purpose || 'chatbot',
      auto_tools: (provider.config_json as Record<string, unknown>)?.auto_tools === true,
      config_json: provider.config_json ? JSON.stringify(provider.config_json, null, 2) : '',
    });
    setIsModalOpen(true);
  };

  const handleDelete = (provider: LLMProvider, e: React.MouseEvent) => {
    e.stopPropagation();
    Modal.confirm({
      title: 'Confirm Delete',
      content: `Are you sure you want to delete model "${provider.name}"?`,
      onOk: () => deleteMutation.mutate(provider.id),
    });
  };

  const handleToggleActive = (provider: LLMProvider, checked: boolean) => {
    if (checked) {
      enableMutation.mutate(provider.id);
    } else {
      disableMutation.mutate(provider.id);
    }
  };

  const handleSubmit = (values: {
    name: string;
    provider_type: ProviderType;
    api_base?: string;
    api_key?: string;
    model_name: string;
    purpose?: ModelPurpose;
    auto_tools?: boolean;
    config_json?: string;
  }) => {
    let parsedConfig: Record<string, unknown>;
    try {
      parsedConfig = values.config_json
        ? parseJsonOrThrow(values.config_json, '配置')
        : {};
    } catch (error) {
      message.error(error instanceof Error ? error.message : '配置格式无效');
      return;
    }
    parsedConfig.auto_tools = values.auto_tools ?? false;

    const data = {
      name: values.name,
      provider_type: values.provider_type,
      api_base: values.api_base,
      api_key: values.api_key,
      model_name: values.model_name,
      purpose: values.purpose || 'chatbot',
      config_json: parsedConfig,
    };

    if (editingProvider) {
      updateMutation.mutate({ id: editingProvider.id, data });
    } else {
      createMutation.mutate(data);
    }
  };

  const providers = providersData?.providers || [];

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <Text className={styles.title}>Model Management</Text>
        <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd} className={styles.addBtn}>
          Create Model
        </Button>
      </div>

      <div className={styles.grid}>
        {providers.map((provider) => (
          <Card
            key={provider.id}
            className={styles.card}
            loading={isLoading}
            hoverable
            onClick={() => handleEdit(provider)}
            actions={[
              <div className={styles.cardFooter} key="footer" onClick={(e) => e.stopPropagation()}>
                <span className={styles.enableLabel}>Enable</span>
                <Switch
                  checked={provider.is_active}
                  onChange={(checked) => handleToggleActive(provider, checked)}
                  size="small"
                />
              </div>,
            ]}
          >
            <div className={styles.cardHeader}>
              <div className={styles.cardTitleRow}>
                <div className={styles.titleWithTag}>
                  <span className={styles.cardTitle}>{provider.name}</span>
                </div>
                <div className={styles.cardActions} onClick={(e) => e.stopPropagation()}>
                  <Button
                    type="text"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={(e) => handleDelete(provider, e)}
                    className={styles.actionBtn}
                  />
                </div>
              </div>
              <span
                className={styles.typeTag}
                style={{
                  backgroundColor: `${providerTypeColors[provider.provider_type]}20`,
                  color: providerTypeColors[provider.provider_type],
                }}
              >
                {providerTypeLabels[provider.provider_type]}
              </span>
              <span
                className={styles.purposeTag}
                style={{
                  backgroundColor: `${purposeColors[provider.purpose || 'chatbot']}20`,
                  color: purposeColors[provider.purpose || 'chatbot'],
                }}
              >
                {purposeIcons[provider.purpose || 'chatbot']}
                <span className={styles.purposeLabel}>{purposeLabels[provider.purpose || 'chatbot']}</span>
              </span>
            </div>
            <div className={styles.cardMeta}>
              <div className={styles.metaItem}>
                <span className={styles.metaLabel}>Model:</span>
                <span className={styles.metaValue}>{provider.model_name}</span>
              </div>
              {provider.api_base && (
                <div className={styles.metaItem}>
                  <span className={styles.metaLabel}>API:</span>
                  <span className={styles.metaValue} title={provider.api_base}>
                    {provider.api_base}
                  </span>
                </div>
              )}
            </div>
          </Card>
        ))}
      </div>

      <Modal
        title={editingProvider ? 'Edit Model' : 'Create Model'}
        open={isModalOpen}
        onCancel={() => {
          setIsModalOpen(false);
          setEditingProvider(null);
          form.resetFields();
        }}
        footer={null}
        destroyOnClose
        width={560}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSubmit}
          initialValues={{
            provider_type: 'openai',
            purpose: 'chatbot',
          }}
        >
          <Form.Item label="Config Name" name="name" rules={[{ required: true, message: 'Please enter config name' }]}>
            <Input placeholder="e.g.: default-openai" />
          </Form.Item>

          <Form.Item label="Provider Type" name="provider_type" rules={[{ required: true, message: 'Please select Provider type' }]}>
            <Select>
              <Select.Option value="openai">OpenAI</Select.Option>
              <Select.Option value="ollama">Ollama</Select.Option>
              <Select.Option value="asri_gateway">ASRI Gateway</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item label="Model Purpose" name="purpose" rules={[{ required: true, message: 'Please select model purpose' }]}>
            <Select>
              <Select.Option value="chatbot">
                <span className={styles.selectOption}>
                  <RobotOutlined className={styles.optionIcon} style={{ color: purposeColors.chatbot }} />
                  <span>Chatbot - For conversational chat</span>
                </span>
              </Select.Option>
            </Select>
          </Form.Item>

          <Form.Item label="Model Name" name="model_name" rules={[{ required: true, message: 'Please enter model name' }]}>
            <Input placeholder="e.g.: gpt-4, qwen2.5:14b" />
          </Form.Item>

          <Form.Item label="API Base URL" name="api_base">
            <Input placeholder="e.g.: https://api.openai.com/v1" />
          </Form.Item>

          <Form.Item label="API Key" name="api_key">
            <Input.Password placeholder="API Key (encrypted storage)" />
          </Form.Item>

          <Form.Item label="Extra Config (JSON)" name="config_json">
            <TextArea rows={3} placeholder='{"temperature": 0.8}' />
          </Form.Item>

          <Form.Item
            label="Native Function Calling (auto_tools)"
            name="auto_tools"
            valuePropName="checked"
            tooltip="启用后，工具 Schema 将作为原生 tools 参数传递给 LLM API"
          >
            <Switch />
          </Form.Item>

          <Form.Item>
            <div className={styles.modalFooter}>
              <Button
                onClick={() => {
                  setIsModalOpen(false);
                  setEditingProvider(null);
                  form.resetFields();
                }}
              >
                Cancel
              </Button>
              <Button type="primary" htmlType="submit" loading={createMutation.isPending || updateMutation.isPending}>
                {editingProvider ? 'Update' : 'Create'}
              </Button>
            </div>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default ModelCardGrid;
