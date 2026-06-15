/**
 * PromptLayerEditor — local‑state editor for PromptTemplate.layers.
 *
 * No longer talks to a dedicated API; the parent holds the layers array
 * and persists it together with the rest of the PromptTemplate payload.
 */
import React, { useState } from 'react';
import {
  Table,
  Button,
  Modal,
  Form,
  Input,
  Select,
  InputNumber,
  Tag,
  Space,
  Typography,
  Popconfirm,
} from 'antd';
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  OrderedListOutlined,
} from '@ant-design/icons';
import type {
  PromptLayer,
  LayerTarget,
  LayerStrategy,
} from '@/types/promptTemplate';

const { Text } = Typography;
const { TextArea } = Input;

const TARGET_COLOR: Record<LayerTarget, string> = {
  system: 'blue',
  user: 'green',
};

const STRATEGY_COLOR: Record<LayerStrategy, string> = {
  always: 'purple',
  first_turn: 'orange',
};

interface PromptLayerEditorProps {
  layers: PromptLayer[];
  onChange: (layers: PromptLayer[]) => void;
}

let _idCounter = 0;
function nextId(): string {
  _idCounter += 1;
  return `local_${Date.now()}_${_idCounter}`;
}

const PromptLayerEditor: React.FC<PromptLayerEditorProps> = ({ layers, onChange }) => {
  const [modalOpen, setModalOpen] = useState(false);
  const [editingLayer, setEditingLayer] = useState<PromptLayer | null>(null);
  const [form] = Form.useForm();

  // ── handlers ─────────────────────────────────────────

  const handleAdd = () => {
    setEditingLayer(null);
    form.resetFields();
    form.setFieldsValue({
      target: 'system',
      strategy: 'always',
      order: layers.length * 10,
      is_active: true,
    });
    setModalOpen(true);
  };

  const handleEdit = (layer: PromptLayer) => {
    setEditingLayer(layer);
    form.setFieldsValue({
      name: layer.name,
      description: layer.description || '',
      target: layer.target,
      strategy: layer.strategy,
      template: layer.template,
      order: layer.order,
      is_active: layer.is_active,
    });
    setModalOpen(true);
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      if (editingLayer) {
        // Update existing
        onChange(
          layers.map((l) =>
            l.id === editingLayer.id ? { ...l, ...values } : l
          )
        );
      } else {
        // Add new
        onChange([...layers, { id: nextId(), ...values }]);
      }
      setModalOpen(false);
      setEditingLayer(null);
      form.resetFields();
    } catch {
      // validation failed
    }
  };

  const handleDelete = (id: string) => {
    onChange(layers.filter((l) => l.id !== id));
  };

  const handleReorder = () => {
    const updated = layers.map((l, i) => ({ ...l, order: (i + 1) * 10 }));
    onChange(updated);
  };

  // ── table columns ────────────────────────────────────

  const columns = [
    {
      title: 'Order',
      dataIndex: 'order',
      key: 'order',
      width: 72,
      render: (order: number) => <Text code>{order}</Text>,
    },
    {
      title: 'Name',
      dataIndex: 'name',
      key: 'name',
      render: (name: string) => <Text strong>{name}</Text>,
    },
    {
      title: 'Target',
      dataIndex: 'target',
      key: 'target',
      width: 96,
      render: (target: LayerTarget) => (
        <Tag color={TARGET_COLOR[target]}>{target.toUpperCase()}</Tag>
      ),
    },
    {
      title: 'Strategy',
      dataIndex: 'strategy',
      key: 'strategy',
      width: 120,
      render: (strategy: LayerStrategy) => (
        <Tag color={STRATEGY_COLOR[strategy]}>
          {strategy === 'always' ? 'ALWAYS' : 'FIRST_TURN'}
        </Tag>
      ),
    },
    {
      title: 'Template Preview',
      dataIndex: 'template',
      key: 'template',
      ellipsis: true,
      render: (tpl: string) => (
        <Text
          style={{ fontFamily: 'monospace', fontSize: 12 }}
          ellipsis={{ tooltip: tpl }}
        >
          {tpl.slice(0, 80)}{tpl.length > 80 ? '...' : ''}
        </Text>
      ),
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 120,
      render: (_: unknown, record: PromptLayer) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          >
            Edit
          </Button>
          <Popconfirm
            title="Delete this layer?"
            onConfirm={() => handleDelete(record.id)}
            okText="Delete"
            cancelText="Cancel"
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              Delete
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // ── render ───────────────────────────────────────────

  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 12,
        }}
      >
        <Space>
          <OrderedListOutlined />
          <Text strong>Prompt Layers</Text>
          <Tag>{layers.length} layers</Tag>
        </Space>
        <Space>
          {layers.length > 1 && (
            <Button size="small" onClick={handleReorder}>
              Normalize Order
            </Button>
          )}
          <Button
            type="primary"
            size="small"
            icon={<PlusOutlined />}
            onClick={handleAdd}
          >
            Add Layer
          </Button>
        </Space>
      </div>

      <Table
        dataSource={layers}
        columns={columns}
        rowKey="id"
        pagination={false}
        size="small"
        locale={{ emptyText: 'No layers configured. Add a layer to customize prompts.' }}
      />

      {/* Add / Edit Modal */}
      <Modal
        title={editingLayer ? 'Edit Layer' : 'Add Layer'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => {
          setModalOpen(false);
          setEditingLayer(null);
          form.resetFields();
        }}
        destroyOnClose
        width={640}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="name"
            label="Name"
            rules={[{ required: true, message: 'Please enter a layer name' }]}
          >
            <Input placeholder="e.g. system_core_rules, user_context" />
          </Form.Item>

          <Form.Item name="description" label="Description">
            <Input.TextArea rows={2} placeholder="Optional description" />
          </Form.Item>

          <Space style={{ width: '100%' }} size={16}>
            <Form.Item
              name="target"
              label="Target"
              rules={[{ required: true }]}
              style={{ width: 180 }}
            >
              <Select>
                <Select.Option value="system">System Message</Select.Option>
                <Select.Option value="user">User Message</Select.Option>
              </Select>
            </Form.Item>

            <Form.Item
              name="strategy"
              label="Strategy"
              rules={[{ required: true }]}
              style={{ width: 180 }}
            >
              <Select>
                <Select.Option value="always">
                  Always — every turn
                </Select.Option>
                <Select.Option value="first_turn">
                  First Turn — conversation start only
                </Select.Option>
              </Select>
            </Form.Item>

            <Form.Item name="order" label="Order" style={{ width: 100 }}>
              <InputNumber min={0} max={999} style={{ width: '100%' }} />
            </Form.Item>
          </Space>

          <Form.Item
            name="template"
            label="Template (Jinja2)"
            rules={[{ required: true, message: 'Please enter the template content' }]}
            extra="Supports Jinja2 variables: {{ query }}, {{ history }}, {{ skills }}, {{ tool_schemas }}, {{ tool_ans }}, and user-defined variables."
          >
            <TextArea rows={6} style={{ fontFamily: 'monospace', fontSize: 13 }} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default PromptLayerEditor;
