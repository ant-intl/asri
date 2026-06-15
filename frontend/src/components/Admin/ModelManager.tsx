import React, { useState } from 'react';
import {
  Table,
  Button,
  Modal,
  Form,
  Input,
  Select,
  Switch,
  Space,
  Tag,
  message,
  Typography,
} from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getLLMProviders,
  createLLMProvider,
  updateLLMProvider,
  deleteLLMProvider,
  enableLLMProvider,
  disableLLMProvider,
} from '@/api/llmProvider';
import type { LLMProvider, ProviderType } from '@/types/llmProvider';
import { parseJsonOrThrow } from '@/utils/safeJsonParse';

const { TextArea } = Input;
const { Text } = Typography;

const providerTypeColors: Record<ProviderType, string> = {
  openai: 'blue',
  ollama: 'green',
  asri_gateway: 'cyan',
};

const providerTypeLabels: Record<ProviderType, string> = {
  openai: 'OpenAI',
  ollama: 'Ollama',
  asri_gateway: 'ASRI Gateway',
};

const ModelManager: React.FC = () => {
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
      message.error('Failed to enable model');
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
      message.error('Failed to disable model');
    },
  });

  const handleAdd = () => {
    setEditingProvider(null);
    form.resetFields();
    setIsModalOpen(true);
  };

  const handleEdit = (provider: LLMProvider) => {
    setEditingProvider(provider);
    form.setFieldsValue({
      name: provider.name,
      provider_type: provider.provider_type,
      api_base: provider.api_base,
      api_key: provider.api_key,
      model_name: provider.model_name,
      auto_tools: (provider.config_json as Record<string, unknown>)?.auto_tools === true,
      config_json: provider.config_json ? JSON.stringify(provider.config_json, null, 2) : '',
    });
    setIsModalOpen(true);
  };

  const handleDelete = (provider: LLMProvider) => {
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
      config_json: parsedConfig,
    };

    if (editingProvider) {
      updateMutation.mutate({ id: editingProvider.id, data });
    } else {
      createMutation.mutate(data);
    }
  };

  const columns = [
    {
      title: 'Name',
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: LLMProvider) => (
        <Space direction="vertical" size={0}>
          <Text strong style={{ color: 'rgba(255, 255, 255, 0.9)' }}>{text}</Text>
          <Text style={{ fontSize: 12, color: 'rgba(255, 255, 255, 0.4)' }}>
            {record.model_name}
          </Text>
        </Space>
      ),
    },
    {
      title: 'Type',
      dataIndex: 'provider_type',
      key: 'provider_type',
      width: 80,
      render: (type: ProviderType) => (
        <Tag
          color={providerTypeColors[type]}
          style={{ border: 'none', fontSize: 11, padding: '0 6px' }}
        >
          {providerTypeLabels[type]}
        </Tag>
      ),
    },
    {
      title: 'Status',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 50,
      render: (isActive: boolean, record: LLMProvider) => (
        <Switch
          checked={isActive}
          onChange={(checked) => handleToggleActive(record, checked)}
          size="small"
        />
      ),
    },
    {
      title: 'Actions',
      key: 'action',
      width: 80,
      render: (_: unknown, record: LLMProvider) => (
        <Space size={4}>
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
            style={{ color: 'rgba(255, 255, 255, 0.5)' }}
          />
          <Button
            type="text"
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() => handleDelete(record)}
          />
        </Space>
      ),
    },
  ];

  const providers = providersData?.providers || [];

  return (
    <div style={{ padding: '0 4px' }}>
      <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Text style={{ fontSize: 13, fontWeight: 600, color: 'rgba(255, 255, 255, 0.9)' }}>
          Model List
        </Text>
        <Button
          type="primary"
          size="small"
          icon={<PlusOutlined />}
          onClick={handleAdd}
          style={{ background: 'rgba(255, 255, 255, 0.1)', border: 'none' }}
        >
          New
        </Button>
      </div>

      <Table
        dataSource={providers}
        columns={columns}
        rowKey="id"
        size="small"
        loading={isLoading}
        pagination={false}
        scroll={{ y: 'calc(100vh - 260px)' }}
        style={{ background: 'transparent' }}
      />

      <Modal
        title={editingProvider ? 'Edit Model' : 'New Model'}
        open={isModalOpen}
        onCancel={() => {
          setIsModalOpen(false);
          setEditingProvider(null);
          form.resetFields();
        }}
        footer={null}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSubmit}
          initialValues={{
            provider_type: 'openai',
          }}
        >
          <Form.Item
            label="Configuration Name"
            name="name"
            rules={[{ required: true, message: 'Please enter configuration name' }]}
          >
            <Input placeholder="e.g.: default-openai" />
          </Form.Item>

          <Form.Item
            label="Provider Type"
            name="provider_type"
            rules={[{ required: true, message: 'Please select Provider type' }]}
          >
            <Select>
              <Select.Option value="openai">OpenAI</Select.Option>
              <Select.Option value="ollama">Ollama</Select.Option>
              <Select.Option value="asri_gateway">ASRI Gateway</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item
            label="Model Name"
            name="model_name"
            rules={[{ required: true, message: 'Please enter model name' }]}
          >
            <Input placeholder="e.g.: gpt-4, qwen2.5:14b" />
          </Form.Item>

          <Form.Item label="API Base URL" name="api_base">
            <Input placeholder="e.g.: https://api.openai.com/v1" />
          </Form.Item>

          <Form.Item label="API Key" name="api_key">
            <Input.Password placeholder="API Key (encrypted storage)" />
          </Form.Item>

          <Form.Item label="Extra Configuration (JSON)" name="config_json">
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
            <Space>
              <Button
                type="primary"
                htmlType="submit"
                loading={createMutation.isPending || updateMutation.isPending}
              >
                {editingProvider ? 'Update' : 'Create'}
              </Button>
              <Button
                onClick={() => {
                  setIsModalOpen(false);
                  setEditingProvider(null);
                  form.resetFields();
                }}
              >
                Cancel
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default ModelManager;
