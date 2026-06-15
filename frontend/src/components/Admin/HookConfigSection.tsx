import React, { useState, useCallback } from 'react';
import {
  Card,
  Button,
  Switch,
  Modal,
  Form,
  Input,
  Select,
  message,
  Tag,
  Spin,
  Popconfirm,
} from 'antd';
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getHookConfigs,
  createHookConfig,
  updateHookConfig,
  deleteHookConfig,
  toggleHookConfig,
} from '../../api/hook';
import type { HookConfig, CreateHookConfigRequest } from '../../types/hook';
import styles from './HookConfigSection.module.css';

const { TextArea } = Input;

const HOOK_TYPE_OPTIONS = [
  { value: 'tool_confirmation', label: '工具确认 (tool_confirmation)' },
  { value: 'tool_rule_deny', label: '工具规则拒绝 (tool_rule_deny)' },
  { value: 'coevoloop_data_feed', label: 'CoEvoLoop 数据回传 (coevoloop_data_feed)' },
];

interface HookFormValues {
  hook_type: string;
  hook_name: string;
  description: string;
  is_active: boolean;
  config_json: string;
}

const parseJsonOrThrow = (jsonStr: string): Record<string, unknown> => {
  if (!jsonStr?.trim()) return {};
  try {
    return JSON.parse(jsonStr);
  } catch {
    throw new Error('config_json 格式错误，请输入有效的 JSON');
  }
};

const formatJsonSafe = (value: unknown): string => {
  if (!value) return '';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
};

const HookConfigSection: React.FC = () => {
  const queryClient = useQueryClient();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingHook, setEditingHook] = useState<HookConfig | null>(null);
  const [form] = Form.useForm<HookFormValues>();

  // ── Data Fetching ──────────────────────────────────────────────

  const { data: hooksData, isLoading } = useQuery({
    queryKey: ['hooks'],
    queryFn: getHookConfigs,
  });

  const hooks = hooksData?.hooks || [];

  // ── Mutations ──────────────────────────────────────────────────

  const createMutation = useMutation({
    mutationFn: createHookConfig,
    onSuccess: () => {
      message.success('Hook 创建成功');
      queryClient.invalidateQueries({ queryKey: ['hooks'] });
      setIsModalOpen(false);
      form.resetFields();
    },
    onError: (error: Error) => {
      message.error(error.message || '创建失败');
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, ...req }: Partial<CreateHookConfigRequest> & { id: number }) =>
      updateHookConfig(id, req),
    onSuccess: () => {
      message.success('Hook 更新成功');
      queryClient.invalidateQueries({ queryKey: ['hooks'] });
      setIsModalOpen(false);
      setEditingHook(null);
      form.resetFields();
    },
    onError: (error: Error) => {
      message.error(error.message || '更新失败');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteHookConfig,
    onSuccess: () => {
      message.success('Hook 已删除');
      queryClient.invalidateQueries({ queryKey: ['hooks'] });
    },
    onError: (error: Error) => {
      message.error(error.message || '删除失败');
    },
  });

  const toggleMutation = useMutation({
    mutationFn: toggleHookConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hooks'] });
    },
    onError: (error: Error) => {
      message.error(error.message || '操作失败');
    },
  });

  // ── Handlers ───────────────────────────────────────────────────

  const handleAdd = useCallback(() => {
    setEditingHook(null);
    form.resetFields();
    form.setFieldsValue({
      hook_type: 'tool_confirmation',
      is_active: true,
      config_json: '{}',
    });
    setIsModalOpen(true);
  }, [form]);

  const handleEdit = useCallback(
    (hook: HookConfig) => {
      setEditingHook(hook);
      form.setFieldsValue({
        hook_type: hook.hook_type,
        hook_name: hook.hook_name,
        description: hook.description,
        is_active: hook.is_active,
        config_json: formatJsonSafe(hook.config_json),
      });
      setIsModalOpen(true);
    },
    [form]
  );

  const handleDelete = useCallback(
    (id: number) => {
      deleteMutation.mutate(id);
    },
    [deleteMutation]
  );

  const handleToggle = useCallback(
    (id: number) => {
      toggleMutation.mutate(id);
    },
    [toggleMutation]
  );

  const handleSubmit = useCallback(
    async (values: HookFormValues) => {
      let configJson: Record<string, unknown>;
      try {
        configJson = parseJsonOrThrow(values.config_json);
      } catch (e: unknown) {
        message.error((e as Error).message);
        return;
      }

      const payload: CreateHookConfigRequest = {
        hook_type: values.hook_type,
        hook_name: values.hook_name,
        description: values.description,
        is_active: values.is_active,
        config_json: configJson,
      };

      if (editingHook) {
        updateMutation.mutate({ id: editingHook.id, ...payload });
      } else {
        createMutation.mutate(payload);
      }
    },
    [editingHook, createMutation, updateMutation]
  );

  const isPending = createMutation.isPending || updateMutation.isPending;

  // ── Render helpers ─────────────────────────────────────────────

  const renderConfigSummary = (configJson: Record<string, unknown>) => {
    if (!configJson || Object.keys(configJson).length === 0) return null;
    const entries = Object.entries(configJson).slice(0, 3);
    return (
      <div className={styles.configSummary}>
        {entries.map(([key, value]) => (
          <span key={key} className={styles.configItem}>
            {key}: {typeof value === 'object' ? JSON.stringify(value) : String(value)}
          </span>
        ))}
      </div>
    );
  };

  const getHookTypeLabel = (hookType: string) => {
    const opt = HOOK_TYPE_OPTIONS.find((o) => o.value === hookType);
    return opt?.label || hookType;
  };

  // ── Render ─────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className={styles.loadingContainer}>
        <Spin tip="加载中..." />
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.title}>Hook 配置</div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={handleAdd}
        >
          新增 Hook
        </Button>
      </div>

      {hooks.length === 0 ? (
        <div className={styles.empty}>
          暂无 Hook 配置，点击「新增 Hook」开始配置
        </div>
      ) : (
        <div className={styles.grid}>
          {hooks.map((hook) => (
            <Card
              key={hook.id}
              className={styles.card}
              actions={[
                <Button
                  key="edit"
                  type="link"
                  icon={<EditOutlined />}
                  onClick={() => handleEdit(hook)}
                >
                  编辑
                </Button>,
                <Popconfirm
                  key="delete"
                  title="确定删除此 Hook？"
                  onConfirm={() => handleDelete(hook.id)}
                  okText="确定"
                  cancelText="取消"
                >
                  <Button type="link" danger icon={<DeleteOutlined />}>
                    删除
                  </Button>
                </Popconfirm>,
              ]}
            >
              <div className={styles.cardHeader}>
                <span className={styles.hookName}>{hook.hook_name}</span>
                <Switch
                  checked={hook.is_active}
                  onChange={() => handleToggle(hook.id)}
                  size="small"
                />
              </div>

              <Tag className={styles.typeTag}>
                {getHookTypeLabel(hook.hook_type)}
              </Tag>

              {hook.description && (
                <div className={styles.description}>{hook.description}</div>
              )}

              {renderConfigSummary(hook.config_json)}
            </Card>
          ))}
        </div>
      )}

      {/* ── Modal Form ────────────────────────────────────────── */}
      <Modal
        title={editingHook ? '编辑 Hook' : '新增 Hook'}
        open={isModalOpen}
        onCancel={() => {
          setIsModalOpen(false);
          setEditingHook(null);
          form.resetFields();
        }}
        footer={null}
        width={560}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSubmit}
        >
          <Form.Item
            label="Hook 类型"
            name="hook_type"
            rules={[{ required: true, message: '请选择 Hook 类型' }]}
          >
            <Select options={HOOK_TYPE_OPTIONS} />
          </Form.Item>

          <Form.Item
            label="Hook 名称"
            name="hook_name"
            rules={[
              { required: true, message: '请输入 Hook 名称' },
              { max: 128, message: '名称不能超过 128 个字符' },
            ]}
          >
            <Input placeholder="例如：confirm_sensitive_ops" />
          </Form.Item>

          <Form.Item label="描述" name="description">
            <TextArea rows={2} placeholder="Hook 描述（可选）" />
          </Form.Item>

          <Form.Item label="启用" name="is_active" valuePropName="checked">
            <Switch />
          </Form.Item>

          <Form.Item
            label="配置参数 (JSON)"
            name="config_json"
            rules={[
              {
                validator: (_, value) => {
                  if (!value?.trim()) return Promise.resolve();
                  try {
                    parseJsonOrThrow(value);
                    return Promise.resolve();
                  } catch (e: unknown) {
                    return Promise.reject((e as Error).message);
                  }
                },
              },
            ]}
            dependencies={['hook_type']}
          >
            <TextArea
              rows={6}
              placeholder={JSON.stringify(
                {
                  rules: [
                    {
                      name: '示例规则',
                      tool_name: 'some_tool',
                      deny_message: '已拒绝 {tool}: {value}',
                      conditions: [
                        { path: 'args.field', op: 'not_in', value: ['allowed_val'] },
                      ],
                    },
                  ],
                },
                null,
                2
              )}
            />
          </Form.Item>

          <Form.Item className={styles.formActions}>
            <Button
              type="primary"
              htmlType="submit"
              loading={isPending}
            >
              {editingHook ? '更新' : '创建'}
            </Button>
            <Button
              style={{ marginLeft: 8 }}
              onClick={() => {
                setIsModalOpen(false);
                setEditingHook(null);
                form.resetFields();
              }}
            >
              取消
            </Button>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default HookConfigSection;
