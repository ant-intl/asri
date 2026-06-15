import React, { useState, useMemo } from 'react';
import { Card, Switch, Button, Modal, Form, Input, Select, message, Typography, Space, Divider } from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getTools, createTool, updateTool, deleteTool, enableTool, disableTool, toggleBuiltInTool } from '@/api/tool';
import type { Tool, ToolType } from '@/types/tool';
import { parseJsonOrThrow } from '@/utils/safeJsonParse';
import styles from './ToolCardGrid.module.css';

const { TextArea } = Input;
const { Text } = Typography;

const toolTypeColors: Record<ToolType, string> = {
  tool: '#1890ff',
  rag: '#722ed1',
};

const toolTypeLabels: Record<ToolType, string> = {
  tool: 'Built-in Tool',
  rag: 'RAG',
};

// Built-in tool type color
const builtinColor = '#888888';

const ToolCardGrid: React.FC = () => {
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

  // Enable tool mutation (user-created tools)
  const enableMutation = useMutation({
    mutationFn: enableTool,
    onSuccess: (data) => {
      message.success(data.message);
      queryClient.invalidateQueries({ queryKey: ['tools'] });
    },
    onError: () => {
      message.error('Enable tool failed');
    },
  });

  // Disable tool mutation (user-created tools)
  const disableMutation = useMutation({
    mutationFn: disableTool,
    onSuccess: (data) => {
      message.success(data.message);
      queryClient.invalidateQueries({ queryKey: ['tools'] });
    },
    onError: () => {
      message.error('Disable tool failed');
    },
  });

  // Toggle built-in tool mutation
  const toggleBuiltInMutation = useMutation({
    mutationFn: ({ name, enable }: { name: string; enable: boolean }) =>
      toggleBuiltInTool(name, enable),
    onSuccess: (data) => {
      message.success(data.message);
      queryClient.invalidateQueries({ queryKey: ['tools'] });
    },
    onError: () => {
      message.error('Toggle tool status failed');
    },
  });

  const handleAdd = () => {
    setEditingTool(null);
    form.resetFields();
    setIsModalOpen(true);
  };

  const handleEdit = (tool: Tool, e?: React.MouseEvent) => {
    e?.stopPropagation();
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

  const handleDelete = (tool: Tool, e: React.MouseEvent) => {
    e.stopPropagation();
    Modal.confirm({
      title: 'Confirm Delete',
      content: `Are you sure you want to delete tool "${tool.name}"?`,
      onOk: () => tool.id && deleteMutation.mutate(tool.id),
    });
  };

  const handleToggleActive = (tool: Tool, checked: boolean) => {
    if (tool.is_builtin) {
      // Built-in tool: use toggleBuiltInTool
      toggleBuiltInMutation.mutate({ name: tool.name, enable: checked });
    } else {
      // User-created tool: use enable/disable
      if (checked) {
        tool.id && enableMutation.mutate(tool.id);
      } else {
        tool.id && disableMutation.mutate(tool.id);
      }
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
      updateMutation.mutate({ id: editingTool.id!, data });
    } else {
      createMutation.mutate(data);
    }
  };

  // Group tools by tool_type
  const groupedTools = useMemo(() => {
    const tools = toolsData?.tools || [];
    const groups: Record<ToolType, Tool[]> = {
      tool: [],
      rag: [],
    };

    tools.forEach((tool) => {
      if (groups[tool.tool_type]) {
        groups[tool.tool_type].push(tool);
      }
    });

    return groups;
  }, [toolsData]);

  const renderToolCard = (tool: Tool) => {
    const cardKey = tool.id ? `db-${tool.id}` : `builtin-${tool.name}`;

    return (
      <Card
        key={cardKey}
        className={styles.card}
        loading={isLoading}
        hoverable
        onClick={() => handleEdit(tool)}
        actions={[
          <div className={styles.cardFooter} key="footer">
            {!tool.is_builtin && (
              <Space>
                <Button
                  type="text"
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={(e) => handleDelete(tool, e)}
                  className={styles.actionBtn}
                />
              </Space>
            )}
            <div className={styles.enableSection} onClick={(e) => e.stopPropagation()}>
              <span className={styles.enableLabel}>Enable</span>
              <Switch
                checked={tool.is_active}
                onChange={(checked) => handleToggleActive(tool, checked)}
                size="small"
                loading={toggleBuiltInMutation.isPending}
              />
            </div>
          </div>,
        ]}
      >
        <div className={styles.cardHeader}>
          <div className={styles.cardTitleRow}>
            <span className={styles.cardTitle}>{tool.name}</span>
            {tool.is_builtin && (
              <span
                className={styles.builtinTag}
                style={{ backgroundColor: `${builtinColor}20`, color: builtinColor }}
              >
                Built-in
              </span>
            )}
          </div>
          <span
            className={styles.typeTag}
            style={{ backgroundColor: `${toolTypeColors[tool.tool_type]}20`, color: toolTypeColors[tool.tool_type] }}
          >
            {toolTypeLabels[tool.tool_type]}
          </span>
        </div>
        <div className={styles.cardDescription}>{tool.description || 'No description'}</div>
      </Card>
    );
  };

  const renderToolGroup = (toolType: ToolType) => {
    const tools = groupedTools[toolType];
    if (tools.length === 0) {
      return null;
    }

    return (
      <div key={toolType} className={styles.toolGroup}>
        <div className={styles.groupHeader}>
          <Text strong className={styles.groupTitle}>
            {toolTypeLabels[toolType]}
          </Text>
          <Text type="secondary" className={styles.groupCount}>
            ({tools.length})
          </Text>
        </div>
        <div className={styles.grid}>
          {tools.map(renderToolCard)}
        </div>
      </div>
    );
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <Text className={styles.title}>Tool Management</Text>
        <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd} className={styles.addBtn}>
          Create Tool
        </Button>
      </div>

      <div className={styles.groupsContainer}>
        {/* Built-in tools first */}
        {renderToolGroup('tool')}

        {/* Then user-created tools */}
        {renderToolGroup('rag')}
      </div>

      <Modal
        title={editingTool ? 'Edit Tool' : 'Create Tool'}
        open={isModalOpen}
        onCancel={() => {
          setIsModalOpen(false);
          setEditingTool(null);
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
            tool_type: 'tool',
            is_active: true,
          }}
        >
          <Form.Item label="Tool Name" name="name" rules={[{ required: true, message: 'Please enter tool name' }]}>
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

          <Form.Item label="Parameters Schema (JSON)" name="parameters_schema">
            <TextArea rows={4} placeholder='{"type": "object", "properties": {}}' />
          </Form.Item>

          <Form.Item label="Config (JSON)" name="config_json">
            <TextArea rows={4} placeholder='{"key": "value"}' />
          </Form.Item>

          <Form.Item label="Enable" name="is_active" valuePropName="checked">
            <Switch />
          </Form.Item>

          <Form.Item>
            <div className={styles.modalFooter}>
              <Button
                onClick={() => {
                  setIsModalOpen(false);
                  setEditingTool(null);
                  form.resetFields();
                }}
              >
                Cancel
              </Button>
              <Button type="primary" htmlType="submit" loading={createMutation.isPending || updateMutation.isPending}>
                {editingTool ? 'Update' : 'Create'}
              </Button>
            </div>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default ToolCardGrid;
