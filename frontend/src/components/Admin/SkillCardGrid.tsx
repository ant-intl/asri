import React, { useState } from 'react';
import {
  Card,
  Switch,
  Button,
  Modal,
  Form,
  Input,
  message,
  Typography,
  Tag,
  Space,
  Tooltip,
  Tabs,
  Upload,
  Divider,
} from 'antd';
import {
  PlusOutlined,
  DeleteOutlined,
  ReloadOutlined,
  CloudOutlined,
  SettingOutlined,
  SyncOutlined,
  EyeOutlined,
  HistoryOutlined,
  CloudUploadOutlined,
} from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getSkills,
  createSkill,
  updateSkill,
  deleteSkill,
  refreshSkill,
  enableSkill,
  disableSkill,
  uploadSkillZip,
} from '@/api/skill';
import type { Skill, RegistrySkillDetail } from '@/types/skill';
import VersionHistoryPanel from './VersionHistoryPanel';

import styles from './SkillCardGrid.module.css';

const { TextArea } = Input;
const { Text } = Typography;
const { TabPane } = Tabs;

// Markdown preview component
const MarkdownPreview: React.FC<{ content: string }> = ({ content }) => (
  <div className={styles.markdownPreview}>
    <ReactMarkdown remarkPlugins={[remarkGfm]}>{content || 'No content'}</ReactMarkdown>
  </div>
);


const SkillCardGrid: React.FC = () => {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingSkill, setEditingSkill] = useState<Skill | null>(null);
  const [form] = Form.useForm();
  const queryClient = useQueryClient();

  // Version history panel states
  const [versionPanelOpen, setVersionPanelOpen] = useState(false);

  // KB Config modal states
  const [kbConfigModalOpen, setKbConfigModalOpen] = useState(false);
  const [kbConfigForm] = Form.useForm();

  // Registry Skill Detail modal states
  const [registryDetailOpen, setRegistryDetailOpen] = useState(false);
  const [registryDetailSkill, setRegistryDetailSkill] = useState<RegistrySkillDetail | null>(null);
  const [registryDetailLoading, setRegistryDetailLoading] = useState(false);

  // Watch content field for markdown preview
  const contentValue = Form.useWatch('content', form);

  // Fetch skills
  const { data: skillsData, isLoading } = useQuery({
    queryKey: ['skills'],
    queryFn: () => getSkills(1, 100),
  });

  // Create skill mutation
  const createMutation = useMutation({
    mutationFn: createSkill,
    onSuccess: () => {
      message.success('Skill created successfully');
      queryClient.invalidateQueries({ queryKey: ['skills'] });
      setIsModalOpen(false);
      form.resetFields();
    },
    onError: (error: Error) => {
      message.error(error.message || 'Skill creation failed');
    },
  });

  // Update skill mutation
  const updateMutation = useMutation({
    mutationFn: ({ skillId, data }: { skillId: string; data: Parameters<typeof updateSkill>[1] }) =>
      updateSkill(skillId, data),
    onSuccess: () => {
      message.success('Skill updated successfully');
      queryClient.invalidateQueries({ queryKey: ['skills'] });
      setIsModalOpen(false);
      setEditingSkill(null);
      form.resetFields();
    },
    onError: (error: Error) => {
      message.error(error.message || 'Skill update failed');
    },
  });

  // Delete skill mutation
  const deleteMutation = useMutation({
    mutationFn: deleteSkill,
    onSuccess: () => {
      message.success('Skill deleted successfully');
      queryClient.invalidateQueries({ queryKey: ['skills'] });
    },
    onError: (error: Error) => {
      message.error(error.message || 'Skill deletion failed');
    },
  });

  // Refresh skill mutation
  const refreshMutation = useMutation({
    mutationFn: refreshSkill,
    onSuccess: () => {
      message.success('Skill cache refreshed successfully');
    },
    onError: (error: Error) => {
      message.error(error.message || 'Cache refresh failed');
    },
  });

  // Enable skill mutation
  const enableMutation = useMutation({
    mutationFn: enableSkill,
    onSuccess: (data) => {
      message.success(data.message);
      queryClient.invalidateQueries({ queryKey: ['skills'] });
    },
    onError: (error: Error) => {
      message.error(error.message || 'Enable Skill failed');
    },
  });

  // Disable skill mutation
  const disableMutation = useMutation({
    mutationFn: disableSkill,
    onSuccess: (data) => {
      message.success(data.message);
      queryClient.invalidateQueries({ queryKey: ['skills'] });
    },
    onError: (error: Error) => {
      message.error(error.message || 'Disable Skill failed');
    },
  });

  // Import ZIP mutation
  const [importModalOpen, setImportModalOpen] = useState(false);
  const importMutation = useMutation({
    mutationFn: uploadSkillZip,
    onSuccess: (data) => {
      message.success(data.message);
      queryClient.invalidateQueries({ queryKey: ['skills'] });
      setImportModalOpen(false);
    },
    onError: (error: Error) => {
      message.error(error.message || 'Import failed');
    },
  });

  // Save KB config mutation
  const saveKBConfigMutation = useMutation({
    mutationFn: async () => {
      // KB config save - to be implemented
    },
    onSuccess: () => {
      message.success('Knowledge Base configuration saved');
      setKbConfigModalOpen(false);
      kbConfigForm.resetFields();
    },
    onError: (error: Error) => {
      message.error(error.message || 'Failed to save KB config');
    },
  });

  const handleSaveKBConfig = async () => {
    try {
      const values = await kbConfigForm.validateFields();
      saveKBConfigMutation.mutate(values);
    } catch {
      // validation failed
    }
  };

  const handleAdd = () => {
    setEditingSkill(null);
    form.resetFields();
    setIsModalOpen(true);
  };

  const handleEdit = (skill: Skill, e?: React.MouseEvent) => {
    e?.stopPropagation();
    setEditingSkill(skill);
    form.setFieldsValue({
      name: skill.name,
      description: skill.description,
      content: skill.content,
      is_active: skill.is_active,
    });
    setIsModalOpen(true);
  };

  const handleDelete = (skill: Skill, e: React.MouseEvent) => {
    e.stopPropagation();
    Modal.confirm({
      title: 'Confirm Delete',
      content: `Are you sure you want to delete Skill "${skill.name}"?`,
      onOk: () => deleteMutation.mutate(skill.skill_id),
    });
  };

  const handleRefresh = (skill: Skill, e: React.MouseEvent) => {
    e.stopPropagation();
    refreshMutation.mutate(skill.skill_id);
  };

  const handleToggleActive = (skill: Skill, checked: boolean) => {
    if (checked) {
      enableMutation.mutate(skill.skill_id);
    } else {
      disableMutation.mutate(skill.skill_id);
    }
  };

  const handleSubmit = (values: {
    name: string;
    description?: string;
    content: string;
    is_active?: boolean;
  }) => {
    const data: Record<string, unknown> = {
      name: values.name,
      description: values.description,
      content: values.content,
      is_active: values.is_active ?? true,
    };

    if (editingSkill) {
      updateMutation.mutate({ skillId: editingSkill.skill_id, data } as any);
    } else {
      createMutation.mutate(data as any);
    }
  };

  const skills = skillsData?.skills || [];

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <Text className={styles.title}>Skill Management</Text>
        <Space>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd} className={styles.addBtn}>
            Manual Add
          </Button>
          <Button type="primary" icon={<CloudUploadOutlined />} onClick={() => setImportModalOpen(true)} className={styles.addBtn}>
            Import ZIP
          </Button>
        </Space>
      </div>

      <div className={styles.scrollArea}>
        <div className={styles.sectionTitle}>Database Skills ({skills.length})</div>
        <div className={styles.grid}>
          {skills.map((skill) => (
            <Card
              key={skill.skill_id}
              className={styles.card}
              loading={isLoading}
              hoverable
              onClick={() => handleEdit(skill)}
              actions={[
                <div className={styles.cardFooter} key="footer">
                  <Space>
                    <Tooltip title="Refresh Cache">
                      <Button
                        type="text"
                        size="small"
                        icon={<ReloadOutlined />}
                        onClick={(e) => handleRefresh(skill, e)}
                        loading={refreshMutation.isPending}
                        className={styles.actionBtn}
                      />
                    </Tooltip>
                    <Button
                      type="text"
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={(e) => handleDelete(skill, e)}
                      className={styles.actionBtn}
                    />
                  </Space>
                  <div className={styles.enableSection} onClick={(e) => e.stopPropagation()}>
                    <span className={styles.enableLabel}>Enable</span>
                    <Switch
                      checked={skill.is_active}
                      onChange={(checked) => handleToggleActive(skill, checked)}
                      size="small"
                    />
                  </div>
                </div>,
              ]}
            >
              <div className={styles.cardHeader}>
                <div className={styles.cardTitleRow}>
                  <span className={styles.cardTitle}>{skill.name}</span>
                </div>
                <div className={styles.cardMeta}>
                  <Tag color={skill.is_active ? 'success' : 'default'} className={styles.statusTag}>
                    {skill.is_active ? 'Enabled' : 'Disabled'}
                  </Tag>
                  <Text type="secondary" className={styles.timeText}>
                    {new Date(skill.gmt_create).toLocaleDateString()}
                  </Text>
                </div>
              </div>
              <div className={styles.cardDescription}>{skill.description || 'No description'}</div>
            </Card>
          ))}
        </div>
      </div>

      <Modal
        title={editingSkill ? 'Edit Skill' : 'Create Skill'}
        open={isModalOpen}
        onCancel={() => {
          setIsModalOpen(false);
          setEditingSkill(null);
          form.resetFields();
        }}
        footer={null}
        destroyOnClose
        width={720}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSubmit}
          initialValues={{
            is_active: true,
          }}
        >
          <Form.Item
            label="Skill Name"
            name="name"
            rules={[
              { required: true, message: 'Please enter Skill name' },
            ]}
          >
            <Input placeholder="e.g.: refund_process" disabled={!!editingSkill} />
          </Form.Item>

          <Form.Item label="Description" name="description">
            <Input placeholder="Skill description" />
          </Form.Item>

          <Form.Item label="SKILL.md Content" required>
            <Tabs defaultActiveKey="preview" className={styles.contentTabs} destroyInactiveTabPane={false}>
              <TabPane tab="Preview" key="preview">
                <MarkdownPreview content={contentValue || ''} />
              </TabPane>
              <TabPane tab="Edit" key="edit">
                <Form.Item
                  name="content"
                  rules={[{ required: true, message: 'Please enter SKILL.md content' }]}
                  noStyle
                >
                  <TextArea
                    rows={14}
                    placeholder={`# Skill Name

## Description
Skill description, explaining the purpose of this skill

## Instructions
Detailed execution steps or guidelines
1. Step One
2. Step Two
3. Step Three`}
                    className={styles.contentTextArea}
                  />
                </Form.Item>
              </TabPane>

            </Tabs>
          </Form.Item>

          <Divider plain style={{ margin: '8px 0' }}>设置</Divider>

          <Form.Item label="Enable" name="is_active" valuePropName="checked">
            <Switch />
          </Form.Item>

          <Form.Item>
            <div className={styles.modalFooter}>
              <div>
                {editingSkill && (
                  <Button
                    icon={<HistoryOutlined />}
                    onClick={() => setVersionPanelOpen(true)}
                  >
                    History
                  </Button>
                )}
              </div>
              <Space>
                <Button
                  onClick={() => {
                    setIsModalOpen(false);
                    setEditingSkill(null);
                    form.resetFields();
                  }}
                >
                  Cancel
                </Button>
                <Button
                  type="primary"
                  htmlType="submit"
                  loading={createMutation.isPending || updateMutation.isPending}
                >
                  {editingSkill ? 'Update' : 'Create'}
                </Button>
              </Space>
            </div>
          </Form.Item>
        </Form>
      </Modal>

      {/* KB Config Modal */}
      <Modal
        title="Knowledge Base Configuration"
        open={kbConfigModalOpen}
        onCancel={() => {
          setKbConfigModalOpen(false);
          kbConfigForm.resetFields();
        }}
        footer={null}
        destroyOnClose
        width={520}
      >
        <Form
          form={kbConfigForm}
          layout="vertical"
          onFinish={handleSaveKBConfig}
        >
          <Form.Item
            label="API URL"
            name="api_url"
            rules={[{ required: true, message: 'Please enter API URL' }]}
          >
            <Input placeholder="https://example.com/api/knowledge/list" />
          </Form.Item>

          <Form.Item
            label="Doc ID"
            name="doc_id"
            rules={[{ required: true, message: 'Please enter Doc ID' }]}
          >
            <Input placeholder="e.g.: 8610893650304010371" />
          </Form.Item>

          <Form.Item>
            <div className={styles.modalFooter}>
              <Button onClick={() => {
                setKbConfigModalOpen(false);
                kbConfigForm.resetFields();
              }}>
                Cancel
              </Button>
              <Button
                type="primary"
                htmlType="submit"
                loading={saveKBConfigMutation.isPending}
              >
                Save
              </Button>
            </div>
          </Form.Item>
        </Form>
      </Modal>

      {/* Import ZIP Modal */}
      <Modal
        title="Import Skill from ZIP"
        open={importModalOpen}
        onCancel={() => {
          setImportModalOpen(false);
        }}
        footer={null}
        destroyOnClose
        width={480}
      >
        <div style={{ padding: '24px 0', textAlign: 'center' }}>
          <Upload
            accept=".zip"
            showUploadList={false}
            beforeUpload={(file) => {
              importMutation.mutate(file);
              return false;
            }}
          >
            <Button
              type="primary"
              icon={<CloudUploadOutlined />}
              loading={importMutation.isPending}
              size="large"
            >
              Select ZIP File
            </Button>
          </Upload>
          <div style={{ marginTop: 16 }}>
            <Text type="secondary">
              The ZIP must contain a <Text code>SKILL.md</Text> at its root
              with a <Text code>name</Text> field in YAML frontmatter.
            </Text>
          </div>
        </div>
      </Modal>

      {/* Registry Skill Detail Modal (read-only) */}
      <Modal
        title={registryDetailSkill?.name || 'Skill Detail'}
        open={registryDetailOpen}
        onCancel={() => {
          setRegistryDetailOpen(false);
          setRegistryDetailSkill(null);
        }}
        footer={[
          <Button key="close" onClick={() => {
            setRegistryDetailOpen(false);
            setRegistryDetailSkill(null);
          }}>
            Close
          </Button>,
        ]}
        width={720}
        loading={registryDetailLoading}
      >
        {registryDetailSkill && (
          <div className={styles.registryDetail}>
            <div className={styles.registryDetailMeta}>
              <Tag color="blue">Knowledge Base</Tag>
              {registryDetailSkill.labels.map((label) => (
                <Tag key={label.key || label.value} color="default">{label.value || label.key}</Tag>
              ))}
            </div>
            {registryDetailSkill.description && (
              <div className={styles.registryDetailDesc}>
                {registryDetailSkill.description}
              </div>
            )}
            <Divider style={{ margin: '12px 0' }} />
            <div className={styles.registryDetailContent}>
              <Text strong style={{ marginBottom: 8, display: 'block' }}>Content</Text>
              <MarkdownPreview content={registryDetailSkill.content} />
            </div>
          </div>
        )}
      </Modal>

      {/* Version History Panel */}
      {editingSkill && (
        <VersionHistoryPanel
          entityType="skill"
          entityId={editingSkill.skill_id}
          open={versionPanelOpen}
          onClose={() => setVersionPanelOpen(false)}
          onVersionActivated={() => {
            queryClient.invalidateQueries({ queryKey: ['skills'] });
          }}
        />
      )}
    </div>
  );
};

export default SkillCardGrid;