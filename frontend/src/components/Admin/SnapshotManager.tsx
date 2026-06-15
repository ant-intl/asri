import React, { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Button,
  Typography,
  Space,
  Tag,
  Modal,
  Input,
  List,
  Empty,
  message,
  Popconfirm,
  Spin,
  Descriptions,
} from 'antd';
import {
  HistoryOutlined,
  DeleteOutlined,
  CameraOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import styles from './VersionManager.module.css';
import { getSnapshots, deleteSnapshot, updateSnapshot, getSnapshotConfigPreview } from '@/api/snapshot';
import type { SessionSnapshot, SnapshotConfigPreview } from '@/types/snapshot';

const { Title, Text } = Typography;
const { TextArea } = Input;

const SnapshotManager: React.FC = () => {
  const [snapshots, setSnapshots] = useState<SessionSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [deleteLoading, setDeleteLoading] = useState<string | null>(null);
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [editingSnapshot, setEditingSnapshot] = useState<SessionSnapshot | null>(null);
  const [editName, setEditName] = useState('');
  const [editDesc, setEditDesc] = useState('');
  const [previewVisible, setPreviewVisible] = useState(false);
  const [previewData, setPreviewData] = useState<SnapshotConfigPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const loadSnapshots = useCallback(async (p: number = 1) => {
    setLoading(true);
    try {
      const res = await getSnapshots(p, 20);
      setSnapshots(res.items);
      setTotal(res.total);
      setPage(p);
    } catch {
      message.error('Failed to load snapshots');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSnapshots();
  }, [loadSnapshots]);

  const handleDelete = async (id: string) => {
    setDeleteLoading(id);
    try {
      await deleteSnapshot(id);
      message.success('Snapshot deleted');
      loadSnapshots(page);
    } catch {
      message.error('Failed to delete snapshot');
    } finally {
      setDeleteLoading(null);
    }
  };

  const handleEdit = (snap: SessionSnapshot) => {
    setEditingSnapshot(snap);
    setEditName(snap.name);
    setEditDesc(snap.description || '');
    setEditModalVisible(true);
  };

  const handleEditSave = async () => {
    if (!editingSnapshot || !editName.trim()) return;
    try {
      await updateSnapshot(editingSnapshot.id, {
        name: editName.trim(),
        description: editDesc.trim(),
      });
      message.success('Snapshot updated');
      setEditModalVisible(false);
      loadSnapshots(page);
    } catch {
      message.error('Failed to update snapshot');
    }
  };

  const handlePreview = async (snap: SessionSnapshot) => {
    setPreviewLoading(true);
    setPreviewVisible(true);
    try {
      const data = await getSnapshotConfigPreview(snap.id);
      setPreviewData(data);
    } catch {
      message.error('Failed to load snapshot config preview');
    } finally {
      setPreviewLoading(false);
    }
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return 'N/A';
    return new Date(dateStr).toLocaleString();
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <Title level={5} className={styles.title}>Snapshot Manager</Title>
          <Text type="secondary">
            Manage saved session snapshots — {total} total
          </Text>
        </div>
        <Space>
          <Button icon={<SearchOutlined />} onClick={() => loadSnapshots()}>
            Refresh
          </Button>
        </Space>
      </div>

      <div className={styles.content}>
        {loading ? (
          <div style={{ textAlign: 'center', padding: 80 }}>
            <Spin size="large" />
          </div>
        ) : snapshots.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="No snapshots yet. Save a session as a snapshot first."
            style={{ marginTop: 80 }}
          />
        ) : (
          <List
            dataSource={snapshots}
            pagination={{
              current: page,
              pageSize: 20,
              total,
              onChange: loadSnapshots,
              showTotal: (t) => `Total ${t} snapshots`,
            }}
            renderItem={(snap) => {
              const data = snap.snapshot_data || {};
              const llmName = data.llm_provider_ref?.name || data.llm_provider_ref?.model_name || 'N/A';
              const promptMode = data.prompt?.mode || 'N/A';

              return (
                <List.Item
                  actions={[
                    <Button key="preview" type="link" size="small" onClick={() => handlePreview(snap)}>
                      Preview
                    </Button>,
                    <Button key="edit" type="link" size="small" onClick={() => handleEdit(snap)}>
                      Edit
                    </Button>,
                    <Popconfirm
                      key="delete"
                      title="Delete this snapshot?"
                      onConfirm={() => handleDelete(snap.id)}
                    >
                      <Button
                        type="link"
                        size="small"
                        danger
                        loading={deleteLoading === snap.id}
                      >
                        Delete
                      </Button>
                    </Popconfirm>,
                  ]}
                >
                  <List.Item.Meta
                    avatar={<CameraOutlined style={{ fontSize: 24, color: '#1677ff' }} />}
                    title={
                      <Space>
                        <Text strong>{snap.name}</Text>
                        <Tag>{promptMode}</Tag>
                        <Tag>{llmName}</Tag>
                      </Space>
                    }
                    description={
                      <div>
                        <Text type="secondary">
                          {snap.description || <span style={{ opacity: 0.5 }}>No description</span>}
                        </Text>
                        <br />
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          <HistoryOutlined /> {formatDate(snap.gmt_create)}
                          {snap.created_by ? ` · by ${snap.created_by}` : ''}
                        </Text>
                      </div>
                    }
                  />
                </List.Item>
              );
            }}
          />
        )}
      </div>

      {/* Edit Modal */}
      <Modal
        title="Edit Snapshot"
        open={editModalVisible}
        onOk={handleEditSave}
        onCancel={() => setEditModalVisible(false)}
        okText="Save"
        cancelText="Cancel"
        okButtonProps={{ disabled: !editName.trim() }}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <Text strong>Name</Text>
            <Input value={editName} onChange={(e) => setEditName(e.target.value)} />
          </div>
          <div>
            <Text strong>Description</Text>
            <TextArea value={editDesc} onChange={(e) => setEditDesc(e.target.value)} rows={3} />
          </div>
        </Space>
      </Modal>

      {/* Preview Modal */}
      <Modal
        title="Snapshot Config Preview"
        open={previewVisible}
        onCancel={() => { setPreviewVisible(false); setPreviewData(null); }}
        footer={null}
        width={640}
      >
        {previewLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin />
          </div>
        ) : previewData ? (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            {/* Snapshot Info */}
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="ID">
                <Typography.Text copyable style={{ fontSize: 12 }}>{previewData.id}</Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label="Name">{previewData.name}</Descriptions.Item>
              <Descriptions.Item label="Description">{previewData.description || '-'}</Descriptions.Item>
              <Descriptions.Item label="Agent Type">
                <Tag>{previewData.snapshot_data?.agent_type || 'react'}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Source Session">{previewData.source_session_id || 'Manual'}</Descriptions.Item>
              <Descriptions.Item label="Created">{formatDate(previewData.gmt_create)}</Descriptions.Item>
            </Descriptions>

            {/* LLM Provider */}
            <Card size="small" title="LLM Provider">
              {previewData.resolved_llm ? (
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="Model">{previewData.resolved_llm.model_name || '-'}</Descriptions.Item>
                  {previewData.resolved_llm.error && (
                    <Descriptions.Item label="Error">
                      <Text type="danger">{previewData.resolved_llm.error}</Text>
                    </Descriptions.Item>
                  )}
                </Descriptions>
              ) : previewData.snapshot_data?.llm_provider_ref ? (
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="Model">{previewData.snapshot_data.llm_provider_ref.model_name || '-'}</Descriptions.Item>
                </Descriptions>
              ) : (
                <Text type="secondary">No LLM provider configured</Text>
              )}
            </Card>

            {/* Prompt */}
            <Card size="small" title="Prompt">
              {previewData.snapshot_data?.prompt ? (
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="Mode">{previewData.snapshot_data.prompt.mode}</Descriptions.Item>
                  <Descriptions.Item label="Name">{previewData.snapshot_data.prompt.name}</Descriptions.Item>
                  <Descriptions.Item label="User Template Mode">{previewData.snapshot_data.prompt.user_template_mode}</Descriptions.Item>
                  <Descriptions.Item label="System Template">
                    <pre style={{ margin: 0, maxHeight: 200, overflow: 'auto', fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                      {previewData.snapshot_data.prompt.system_template || '(空)'}
                    </pre>
                  </Descriptions.Item>
                  {previewData.snapshot_data.prompt.user_template && (
                    <Descriptions.Item label="User Template">
                      <pre style={{ margin: 0, maxHeight: 200, overflow: 'auto', fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                        {previewData.snapshot_data.prompt.user_template}
                      </pre>
                    </Descriptions.Item>
                  )}
                  <Descriptions.Item label="Layers">
                    {previewData.snapshot_data.prompt.layers?.length ? (
                      <Space direction="vertical" style={{ width: '100%' }}>
                        {previewData.snapshot_data.prompt.layers.map((layer: any, idx: number) => (
                          <Card key={idx} size="small" type="inner" title={`#${idx + 1} ${layer.name || ''}`}>
                            <Descriptions column={1} size="small">
                              <Descriptions.Item label="Target">{layer.target}</Descriptions.Item>
                              <Descriptions.Item label="Strategy">{layer.strategy}</Descriptions.Item>
                              <Descriptions.Item label="Order">{layer.order}</Descriptions.Item>
                              <Descriptions.Item label="Active">
                                <Tag color={layer.is_active ? 'green' : 'default'}>{layer.is_active ? 'Yes' : 'No'}</Tag>
                              </Descriptions.Item>
                              <Descriptions.Item label="Template">
                                <pre style={{ margin: 0, maxHeight: 150, overflow: 'auto', fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                                  {layer.template}
                                </pre>
                              </Descriptions.Item>
                            </Descriptions>
                          </Card>
                        ))}
                      </Space>
                    ) : (
                      <Text type="secondary">None</Text>
                    )}
                  </Descriptions.Item>
                  {previewData.snapshot_data.prompt.extractor_config && Object.keys(previewData.snapshot_data.prompt.extractor_config).length > 0 && (
                    <Descriptions.Item label="Extractor Config">
                      <pre style={{ margin: 0, maxHeight: 150, overflow: 'auto', fontSize: 12 }}>
                        {JSON.stringify(previewData.snapshot_data.prompt.extractor_config, null, 2)}
                      </pre>
                    </Descriptions.Item>
                  )}
                </Descriptions>
              ) : (
                <Text type="secondary">No prompt configuration</Text>
              )}
            </Card>

            {/* Skills & Tools & RAG */}
            <Card size="small" title="Skills & Tools">
              <Space direction="vertical" style={{ width: '100%' }}>
                <div>
                  <Text strong>Skills: </Text>
                  {previewData.snapshot_data?.skills?.length
                    ? previewData.snapshot_data.skills.map((s) => <Tag key={s.skill_id}>{s.name}</Tag>)
                    : <Text type="secondary">None</Text>}
                </div>
                <div>
                  <Text strong>Tools: </Text>
                  {previewData.snapshot_data?.tools?.length
                    ? previewData.snapshot_data.tools.map((t) => <Tag key={t.id}>{t.name}</Tag>)
                    : <Text type="secondary">None</Text>}
                </div>
                <div>
                  <Text strong>RAG Providers: </Text>
                  {previewData.snapshot_data?.rag_providers?.length
                    ? previewData.snapshot_data.rag_providers.map((r) => <Tag key={r.id}>{r.name}</Tag>)
                    : <Text type="secondary">None</Text>}
                </div>
              </Space>
            </Card>
          </Space>
        ) : null}
      </Modal>
    </div>
  );
};

export default SnapshotManager;
