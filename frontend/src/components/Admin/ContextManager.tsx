import React, { useState } from 'react';
import {
  Card,
  Button,
  Form,
  Input,
  message,
  Typography,
  Space,
  Tag,
  Modal,
  Tree,
  Empty,
  Dropdown,
} from 'antd';
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  FolderOutlined,
  FileOutlined,
  MoreOutlined,
  GlobalOutlined,
} from '@ant-design/icons';
import type { DataNode } from 'antd/es/tree';
import styles from './ContextManager.module.css';

const { TextArea } = Input;
const { Text, Title } = Typography;

interface ContextItem {
  id: string;
  key: string;
  title: string;
  content?: string;
  type: 'folder' | 'file';
  children?: ContextItem[];
  isActive: boolean;
}

// Mock data
const mockContextData: ContextItem[] = [
  {
    id: '1',
    key: 'projects',
    title: 'Project Documents',
    type: 'folder',
    isActive: true,
    children: [
      {
        id: '1-1',
        key: 'asri',
        title: 'ASRI Project',
        type: 'folder',
        isActive: true,
        children: [
          {
            id: '1-1-1',
            key: 'architecture',
            title: 'Architecture Design',
            content: 'ASRI uses a frontend-backend separated architecture. Frontend uses React + TypeScript + Vite, backend uses Python FastAPI.',
            type: 'file',
            isActive: true,
          },
          {
            id: '1-1-2',
            key: 'api',
            title: 'API Documentation',
            content: 'RESTful API design specification. All interfaces return unified format: {code, message, data}',
            type: 'file',
            isActive: true,
          },
        ],
      },
    ],
  },
  {
    id: '2',
    key: 'knowledge',
    title: 'Knowledge Base',
    type: 'folder',
    isActive: true,
    children: [
      {
        id: '2-1',
        key: 'tech-stack',
        title: 'Tech Stack',
        content: 'Frontend: React, TypeScript, Vite, Ant Design\nBackend: Python, FastAPI, SQLAlchemy',
        type: 'file',
        isActive: true,
      },
      {
        id: '2-2',
        key: 'best-practices',
        title: 'Best Practices',
        content: '1. Code reviews must include unit tests\n2. API changes require documentation updates\n3. Commit messages follow Conventional Commits',
        type: 'file',
        isActive: true,
      },
    ],
  },
];

const ContextManager: React.FC = () => {
  const [contextData, setContextData] = useState<ContextItem[]>(mockContextData);
  const [selectedNode, setSelectedNode] = useState<ContextItem | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [parentId, setParentId] = useState<string | null>(null);
  const [form] = Form.useForm();

  // Convert to tree data
  const convertToTreeData = (items: ContextItem[]): DataNode[] => {
    return items.map((item) => ({
      key: item.id,
      title: (
        <div className={styles.treeNode}>
          {item.type === 'folder' ? (
            <FolderOutlined className={styles.folderIcon} />
          ) : (
            <FileOutlined className={styles.fileIcon} />
          )}
          <span className={item.isActive ? '' : styles.inactiveText}>
            {item.title}
          </span>
          {!item.isActive && <Tag className={styles.disabledTag}>Disabled</Tag>}
        </div>
      ),
      children: item.children ? convertToTreeData(item.children) : undefined,
      isLeaf: item.type === 'file',
    }));
  };

  const findNodeById = (
    items: ContextItem[],
    id: string
  ): ContextItem | null => {
    for (const item of items) {
      if (item.id === id) return item;
      if (item.children) {
        const found = findNodeById(item.children, id);
        if (found) return found;
      }
    }
    return null;
  };

  const handleSelect = (selectedKeys: React.Key[]) => {
    if (selectedKeys.length > 0) {
      const node = findNodeById(contextData, selectedKeys[0] as string);
      setSelectedNode(node);
    } else {
      setSelectedNode(null);
    }
  };

  const handleAdd = (type: 'folder' | 'file', parentId?: string) => {
    setIsEditing(false);
    setParentId(parentId || null);
    form.resetFields();
    form.setFieldsValue({ type, isActive: true });
    setIsModalOpen(true);
  };

  const handleEdit = () => {
    if (!selectedNode) return;
    setIsEditing(true);
    form.setFieldsValue({
      title: selectedNode.title,
      key: selectedNode.key,
      content: selectedNode.content,
      type: selectedNode.type,
      isActive: selectedNode.isActive,
    });
    setIsModalOpen(true);
  };

  const handleDelete = () => {
    if (!selectedNode) return;
    Modal.confirm({
      title: 'Confirm Delete',
      content: `Are you sure you want to delete "${selectedNode.title}"?${
        selectedNode.type === 'folder' ? ' All sub-items will also be deleted.' : ''
      }`,
      onOk: () => {
        const deleteNode = (items: ContextItem[]): ContextItem[] => {
          return items
            .filter((item) => item.id !== selectedNode.id)
            .map((item) => ({
              ...item,
              children: item.children ? deleteNode(item.children) : undefined,
            }));
        };
        setContextData(deleteNode(contextData));
        setSelectedNode(null);
        message.success('Deleted successfully');
      },
    });
  };

  const handleSubmit = (values: {
    title: string;
    key: string;
    content?: string;
    type: 'folder' | 'file';
    isActive: boolean;
  }) => {
    const newItem: ContextItem = {
      id: isEditing
        ? selectedNode!.id
        : `${Date.now()}`,
      key: values.key,
      title: values.title,
      content: values.content,
      type: values.type,
      isActive: values.isActive,
      children: values.type === 'folder' ? [] : undefined,
    };

    if (isEditing && selectedNode) {
      const updateNode = (items: ContextItem[]): ContextItem[] => {
        return items.map((item) => {
          if (item.id === selectedNode.id) {
            return { ...newItem, children: item.children };
          }
          if (item.children) {
            return { ...item, children: updateNode(item.children) };
          }
          return item;
        });
      };
      setContextData(updateNode(contextData));
      setSelectedNode({ ...newItem, children: selectedNode.children });
      message.success('Updated successfully');
    } else {
      if (parentId) {
        const addToParent = (items: ContextItem[]): ContextItem[] => {
          return items.map((item) => {
            if (item.id === parentId) {
              return {
                ...item,
                children: [...(item.children || []), newItem],
              };
            }
            if (item.children) {
              return { ...item, children: addToParent(item.children) };
            }
            return item;
          });
        };
        setContextData(addToParent(contextData));
      } else {
        setContextData([...contextData, newItem]);
      }
      message.success('Created successfully');
    }
    setIsModalOpen(false);
    form.resetFields();
  };

  const toggleActive = () => {
    if (!selectedNode) return;
    const toggleNode = (items: ContextItem[]): ContextItem[] => {
      return items.map((item) => {
        if (item.id === selectedNode.id) {
          return { ...item, isActive: !item.isActive };
        }
        if (item.children) {
          return { ...item, children: toggleNode(item.children) };
        }
        return item;
      });
    };
    setContextData(toggleNode(contextData));
    setSelectedNode({ ...selectedNode, isActive: !selectedNode.isActive });
  };

  const treeData = convertToTreeData(contextData);

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <Text className={styles.title}>Context Management</Text>
          <Text type="secondary" className={styles.subtitle}>
            Manage AI assistant context knowledge base
          </Text>
        </div>
        <Space>
          <Button
            icon={<PlusOutlined />}
            onClick={() => handleAdd('folder')}
          >
            New Folder
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => handleAdd('file')}
            className={styles.addBtn}
          >
            New Document
          </Button>
        </Space>
      </div>

      <div className={styles.content}>
        <div className={styles.treePanel}>
          <div className={styles.treeHeader}>
            <GlobalOutlined />
            <span>Knowledge Base Structure</span>
          </div>
          {contextData.length === 0 ? (
            <Empty description="No data" className={styles.empty} />
          ) : (
            <Tree
              treeData={treeData}
              onSelect={handleSelect}
              className={styles.tree}
              showLine
              defaultExpandAll
            />
          )}
        </div>

        <div className={styles.detailPanel}>
          {selectedNode ? (
            <Card
              className={styles.detailCard}
              title={
                <div className={styles.detailHeader}>
                  <div className={styles.detailTitle}>
                    {selectedNode.type === 'folder' ? (
                      <FolderOutlined className={styles.folderIcon} />
                    ) : (
                      <FileOutlined className={styles.fileIcon} />
                    )}
                    <span>{selectedNode.title}</span>
                    <Tag color={selectedNode.isActive ? 'success' : 'default'}>
                      {selectedNode.isActive ? 'Enabled' : 'Disabled'}
                    </Tag>
                  </div>
                  <Space>
                    <Button
                      size="small"
                      onClick={toggleActive}
                    >
                      {selectedNode.isActive ? 'Disable' : 'Enable'}
                    </Button>
                    <Button
                      size="small"
                      icon={<EditOutlined />}
                      onClick={handleEdit}
                    >
                      Edit
                    </Button>
                    <Button
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={handleDelete}
                    >
                      Delete
                    </Button>
                    {selectedNode.type === 'folder' && (
                      <Dropdown
                        menu={{
                          items: [
                            {
                              key: 'folder',
                              label: 'New Folder',
                              icon: <FolderOutlined />,
                              onClick: () => handleAdd('folder', selectedNode.id),
                            },
                            {
                              key: 'file',
                              label: 'New Document',
                              icon: <FileOutlined />,
                              onClick: () => handleAdd('file', selectedNode.id),
                            },
                          ],
                        }}
                      >
                        <Button size="small" icon={<MoreOutlined />} />
                      </Dropdown>
                    )}
                  </Space>
                </div>
              }
            >
              <div className={styles.detailContent}>
                <div className={styles.metaRow}>
                  <Text type="secondary">Key: {selectedNode.key}</Text>
                  <Text type="secondary">
                    Type: {selectedNode.type === 'folder' ? 'Folder' : 'Document'}
                  </Text>
                </div>
                {selectedNode.content && (
                  <div className={styles.contentBox}>
                    <pre>{selectedNode.content}</pre>
                  </div>
                )}
                {selectedNode.type === 'folder' &&
                  selectedNode.children &&
                  selectedNode.children.length > 0 && (
                    <div className={styles.childrenInfo}>
                      <Text type="secondary">
                        Contains {selectedNode.children.length} sub-items
                      </Text>
                    </div>
                  )}
              </div>
            </Card>
          ) : (
            <Empty
              description="Select an item on the left to view details"
              className={styles.emptyDetail}
            />
          )}
        </div>
      </div>

      <Modal
        title={isEditing ? 'Edit' : 'New'}
        open={isModalOpen}
        onCancel={() => {
          setIsModalOpen(false);
          form.resetFields();
        }}
        footer={null}
        width={600}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSubmit}
          initialValues={{ type: 'file', isActive: true }}
        >
          <Form.Item
            label="Name"
            name="title"
            rules={[{ required: true, message: 'Please enter name' }]}
          >
            <Input placeholder="e.g.: Project Documents" />
          </Form.Item>

          <Form.Item
            label="Key"
            name="key"
            rules={[{ required: true, message: 'Please enter Key' }]}
          >
            <Input placeholder="e.g.: project_docs" />
          </Form.Item>

          <Form.Item label="Type" name="type">
            <Input disabled />
          </Form.Item>

          {form.getFieldValue('type') === 'file' && (
            <Form.Item label="Content" name="content">
              <TextArea rows={8} placeholder="Enter document content..." />
            </Form.Item>
          )}

          <Form.Item label="Enabled" name="isActive" valuePropName="checked">
            <Input disabled />
          </Form.Item>

          <Form.Item>
            <Space className={styles.modalFooter}>
              <Button
                onClick={() => {
                  setIsModalOpen(false);
                  form.resetFields();
                }}
              >
                Cancel
              </Button>
              <Button type="primary" htmlType="submit">
                {isEditing ? 'Update' : 'Create'}
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default ContextManager;
