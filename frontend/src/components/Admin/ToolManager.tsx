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
import { getTools, createTool, updateTool, deleteTool, enableTool, disableTool } from '@/api/tool';
import type { Tool, ToolType } from '@/types/tool';
import { parseJsonOrThrow } from '@/utils/safeJsonParse';

const { TextArea } = Input;
const { Text } = Typography;

const toolTypeColors: Record<ToolType, string> = {
  tool: 'blue',
  rag: 'purple',
};

const toolTypeLabels: Record<ToolType, string> = {
  tool: 'Tool',
  rag: 'RAG',
};

const ToolManager: React.FC = () => {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingTool, setEditingTool] = useState<Tool | null>(null);
  const [form] = Form.useForm();
  const queryClient = useQueryClient();

  // Fetch tools
  const { data: toolsData, isLoading } = useQuery({
    queryKey: ['tools'],
    queryFn: getTools,
  });

  // Create tool mutation
  const createMutation = useMutation({
    mutationFn: createTool,
    onSuccess: () => {
      message.success('Tool created successfully');
      queryClient.invalidateQueries({ queryKey: ['tools'] });
      setIsModalOpen(false);
      form.resetFields();
    },
    onError: () => {
      message.error('Tool creation failed');
    },
  });

  // Update tool mutation
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof updateTool>[1] }) =>
      updateTool(id, data),
    onSuccess: () => {
      message.success('Tool updated successfully');
      queryClient.invalidateQueries({ queryKey: ['tools'] });
      setIsModalOpen(false);
      setEditingTool(null);
      form.resetFields();
    },
    onError: () => {
      message.error('Tool update failed');
    },
  });

  // Delete tool mutation
  const deleteMutation = useMutation({
    mutationFn: deleteTool,
    onSuccess: () => {
      message.success('Tool deleted successfully');
      queryClient.invalidateQueries({ queryKey: ['tools'] });
    },
    onError: () => {
      message.error('Tool deletion failed');
    },
  });

  // Enable tool mutation
  const enableMutation = useMutation({
    mutationFn: enableTool,
    onSuccess: (data) => {
      message.success(data.message);
      queryClient.invalidateQueries({ queryKey: ['tools'] });
    },
    onError: () => {
      message.error('Failed to enable tool');
    },
  });

  // Disable tool mutation
  const disableMutation = useMutation({
    mutationFn: disableTool,
    onSuccess: (data) => {
      message.success(data.message);
      queryClient.invalidateQueries({ queryKey: ['tools'] });
    },
    onError: () => {
      message.error('Failed to disable tool');
    },
  });

  const handleAdd = () => {
    setEditingTool(null);
    form.resetFields();
    setIsModalOpen(true);
  };

  const handleEdit = (tool: Tool) => {
    setEditingTool(tool);
    form.setFieldsValue({
      name: tool.name,
      tool_type: tool.tool_type,
      description: tool.description,
      parameters_schema: tool.parameters_schema ? JSON.stringify(tool.parameters_schema, null, 2) : '',
      config_json: tool.config_json ? JSON.stringify(tool.config_json, null, 2) : '',
      is_active: tool.is_active,
    });
    setIsModalOpen(true);
  };

  const handleDelete = (tool: Tool) => {
    Modal.confirm({
      title: 'Confirm Delete',
      content: `Are you sure you want to delete tool "${tool.name}"?`,
      onOk: () => deleteMutation.mutate(tool.id),
    });
  };

  const handleToggleActive = (tool: Tool, checked: boolean) => {
    if (checked) {
      enableMutation.mutate(tool.id);
    } else {
      disableMutation.mutate(tool.id);
    }
  };

  const handleSubmit = (values: {
    name: string;
    tool_type: ToolType;
    description?: string;
    parameters_schema?: string;
    config_json?: string;
    is_active?: boolean;
  }) => {
    let parametersSchema: Record<string, unknown> | undefined;
    let configJson: Record<string, unknown> | undefined;

    try {
      parametersSchema = values.parameters_schema
        ? parseJsonOrThrow(values.parameters_schema, '参数 Schema')
        : undefined;
    } catch (error) {
      message.error(error instanceof Error ? error.message : '参数 Schema 格式无效');
      return;
    }

    try {
      configJson = values.config_json
        ? parseJsonOrThrow(values.config_json, '配置')
        : undefined;
    } catch (error) {
      message.error(error instanceof Error ? error.message : '配置格式无效');
      return;
    }

    const data = {
      name: values.name,
      tool_type: values.tool_type,
      description: values.description,
      is_active: values.is_active ?? true,
      parameters_schema: parametersSchema,
      config_json: configJson,
    };

    if (editingTool) {
      updateMutation.mutate({ id: editingTool.id, data });
    } else {
      createMutation.mutate(data);
    }
  };

  const columns = [
    {
      title: 'Name',
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: Tool) => (
        <Space direction="vertical" size={0}>
          <Text strong style={{ color: 'rgba(255, 255, 255, 0.9)' }}>{text}</Text>
          {record.description && (
            <Text style={{ fontSize: 12, color: 'rgba(255, 255, 255, 0.4)' }}>
              {record.description}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: 'Type',
      dataIndex: 'tool_type',
      key: 'tool_type',
      width: 70,
      render: (type: ToolType) => (
        <Tag
          color={toolTypeColors[type]}
          style={{ border: 'none', fontSize: 11, padding: '0 6px' }}
        >
          {toolTypeLabels[type]}
        </Tag>
      ),
    },
    {
      title: 'Status',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 50,
      render: (isActive: boolean, record: Tool) => (
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
      render: (_: unknown, record: Tool) => (
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

  const tools = toolsData?.tools || [];

  return (
    <div style={{ padding: '0 4px' }}>
      <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Text style={{ fontSize: 13, fontWeight: 600, color: 'rgba(255, 255, 255, 0.9)' }}>
          Tool List
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
        dataSource={tools}
        columns={columns}
        rowKey="id"
        size="small"
        loading={isLoading}
        pagination={false}
        scroll={{ y: 'calc(100vh - 260px)' }}
        style={{
          background: 'transparent',
        }}
      />

      <Modal
        title={editingTool ? 'Edit Tool' : 'New Tool'}
        open={isModalOpen}
        onCancel={() => {
          setIsModalOpen(false);
          setEditingTool(null);
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
            tool_type: 'tool',
            is_active: true,
          }}
        >
          <Form.Item
            label="Tool Name"
            name="name"
            rules={[{ required: true, message: 'Please enter tool name' }]}
          >
            <Input placeholder="e.g.: rag_search" />
          </Form.Item>

          <Form.Item label="Tool Type" name="tool_type">
            <Select>
              <Select.Option value="tool">Tool</Select.Option>
              <Select.Option value="rag">RAG</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item label="Description" name="description">
            <Input placeholder="Tool description" />
          </Form.Item>

          <Form.Item label="Parameter Schema (JSON)" name="parameters_schema">
            <TextArea
              rows={4}
              placeholder='{"type": "object", "properties": {}}'
            />
          </Form.Item>

          <Form.Item label="Configuration (JSON)" name="config_json">
            <TextArea
              rows={4}
              placeholder='{"key": "value"}'
            />
          </Form.Item>

          <Form.Item label="Enabled" name="is_active" valuePropName="checked">
            <Switch />
          </Form.Item>

          <Form.Item>
            <Space>
              <Button
                type="primary"
                htmlType="submit"
                loading={createMutation.isPending || updateMutation.isPending}
              >
                {editingTool ? 'Update' : 'Create'}
              </Button>
              <Button
                onClick={() => {
                  setIsModalOpen(false);
                  setEditingTool(null);
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

export default ToolManager;
