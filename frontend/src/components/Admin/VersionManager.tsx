import React, { useState } from 'react';
import {
  Card,
  Button,
  Typography,
  Space,
  Tag,
  Modal,
  Form,
  Input,
  List,
  Empty,
  message,
  Popconfirm,
  Alert,
} from 'antd';
import {
  HistoryOutlined,
  PlusOutlined,
  RollbackOutlined,
  DeleteOutlined,
  ClockCircleOutlined,
  TagOutlined,
} from '@ant-design/icons';
import styles from './VersionManager.module.css';

const { Title, Text } = Typography;
const { TextArea } = Input;

interface VersionSnapshot {
  id: string;
  name: string;
  description?: string;
  createdAt: string;
  tags: string[];
  // Configuration snapshot
  configSnapshot: {
    memory?: Record<string, unknown>;
    security?: Record<string, unknown>;
    context?: Record<string, unknown>;
    skills?: string[];
    tools?: string[];
  };
}

// Mock data
const mockVersions: VersionSnapshot[] = [
  {
    id: '1',
    name: 'Initial Configuration',
    description: 'Default system configuration',
    createdAt: '2024-01-15 10:00:00',
    tags: ['default', 'baseline'],
    configSnapshot: {
      memory: { scope: 'session' },
      security: { contentFiltering: true },
    },
  },
  {
    id: '2',
    name: 'Production Config',
    description: 'Optimized configuration for production environment',
    createdAt: '2024-03-20 14:30:00',
    tags: ['production', 'optimized'],
    configSnapshot: {
      memory: { scope: 'multiday', days: 30 },
      security: { contentFiltering: true, rateLimit: 100 },
    },
  },
];

const VersionManager: React.FC = () => {
  const [versions, setVersions] = useState<VersionSnapshot[]>(mockVersions);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [form] = Form.useForm();

  const handleCreateVersion = (values: { name: string; description: string; tags: string }) => {
    const newVersion: VersionSnapshot = {
      id: Date.now().toString(),
      name: values.name,
      description: values.description,
      createdAt: new Date().toLocaleString(),
      tags: values.tags ? values.tags.split(',').map((t) => t.trim()) : [],
      configSnapshot: {
        // In real usage, this would capture all current configurations
        memory: { scope: 'session', compression: true },
        security: { contentFiltering: true },
      },
    };
    setVersions([newVersion, ...versions]);
    message.success('Configuration version created');
    setIsModalOpen(false);
    form.resetFields();
  };

  const handleRestore = (version: VersionSnapshot) => {
    Modal.confirm({
      title: 'Confirm Rollback',
      content: `Are you sure you want to rollback to "${version.name}"? Current configuration will be overwritten.`,
      okText: 'Confirm',
      okType: 'primary',
      cancelText: 'Cancel',
      onOk: () => {
        // In real usage, this would restore the configuration
        message.success(`Rolled back to "${version.name}"`);
      },
    });
  };

  const handleDelete = (versionId: string) => {
    setVersions(versions.filter((v) => v.id !== versionId));
    message.success('Version deleted');
  };

  const handleCaptureCurrent = () => {
    setIsModalOpen(true);
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <Text className={styles.title}>Version Manager</Text>
          <Text type="secondary" className={styles.subtitle}>
            Create and manage configuration snapshots, rollback to historical states anytime
          </Text>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={handleCaptureCurrent}
          className={styles.createBtn}
        >
          Create Version
        </Button>
      </div>

      <div className={styles.content}>
        {versions.length === 0 ? (
          <Empty
            description="No configuration versions"
            className={styles.empty}
          >
            <Button type="primary" icon={<PlusOutlined />} onClick={handleCaptureCurrent}>
              Create first version
            </Button>
          </Empty>
        ) : (
          <List
            className={styles.snapshotList}
            dataSource={versions}
            renderItem={(item) => (
              <List.Item
                className={styles.snapshotItem}
                actions={[
                  <Button
                    key="restore"
                    type="primary"
                    icon={<RollbackOutlined />}
                    onClick={() => handleRestore(item)}
                  >
                    Rollback
                  </Button>,
                  <Popconfirm
                    key="delete"
                    title="Confirm Delete"
                    description="This cannot be undone. Continue?"
                    onConfirm={() => handleDelete(item.id)}
                    okText="Delete"
                    cancelText="Cancel"
                  >
                    <Button danger icon={<DeleteOutlined />}>
                      Delete
                    </Button>
                  </Popconfirm>,
                ]}
              >
                <List.Item.Meta
                  avatar={<HistoryOutlined className={styles.snapshotIcon} />}
                  title={
                    <Space>
                      <span className={styles.snapshotName}>{item.name}</span>
                      {item.tags.map((tag) => (
                        <Tag key={tag}>
                          {tag}
                        </Tag>
                      ))}
                    </Space>
                  }
                  description={
                    <div className={styles.snapshotMeta}>
                      {item.description && (
                        <Text className={styles.description}>{item.description}</Text>
                      )}
                      <div className={styles.metaRow}>
                        <ClockCircleOutlined />
                        <Text type="secondary">{item.createdAt}</Text>
                      </div>
                    </div>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </div>

      <Modal
        title="Create Configuration Version"
        open={isModalOpen}
        onCancel={() => {
          setIsModalOpen(false);
          form.resetFields();
        }}
        footer={null}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleCreateVersion}
        >
          <Form.Item
            label="Name"
            name="name"
            rules={[{ required: true, message: 'Please enter version name' }]}
          >
            <Input placeholder="e.g., Production Config" />
          </Form.Item>

          <Form.Item label="Description" name="description">
            <TextArea rows={3} placeholder="Describe the features or purpose of this config..." />
          </Form.Item>

          <Form.Item label="Tags" name="tags">
            <Input placeholder="Comma separated, e.g., production, v1.0" />
          </Form.Item>

          <Alert
            message="Note"
            description="Creating a version will capture snapshots of all current configurations (Memory, Security, Context, etc.)."
            type="info"
            showIcon
            className={styles.alert}
          />

          <Form.Item className={styles.modalFooter}>
            <Space>
              <Button onClick={() => setIsModalOpen(false)}>Cancel</Button>
              <Button type="primary" htmlType="submit">
                Create
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default VersionManager;