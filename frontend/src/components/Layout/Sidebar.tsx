import React, { useState } from 'react';
import { Layout, Button, Modal, Form, Input, Space, Typography, Empty, Select, message } from 'antd';
import {
  PlusOutlined,
  CommentOutlined,
  DeleteOutlined,
  AppstoreOutlined,
  RightOutlined,
  ToolOutlined,
  DeploymentUnitOutlined,
  MenuFoldOutlined,
  ThunderboltOutlined,
  ApiOutlined,
  FileTextOutlined,
  DatabaseOutlined,
  GlobalOutlined,
  SafetyOutlined,
  SettingOutlined,
  ExperimentOutlined,
  UserOutlined,
  HistoryOutlined,
  SplitCellsOutlined,
  BugOutlined,
  CloudOutlined,
  RobotOutlined,
  ControlOutlined,
  CameraOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getSessions, createSession, deleteSession } from '@/api/session';
import { useChatStore } from '@/stores/chatStore';
import type { Session } from '@/types/session';
import styles from './Sidebar.module.css';

const { Sider } = Layout;
const { Title, Text } = Typography;
const { Option } = Select;

interface SidebarProps {
  collapsed?: boolean;
  onCollapse?: (collapsed: boolean) => void;
}

type MenuKey = 'chat' | 'agent-settings' | 'setting' | 'tools' | 'models' | 'skills' | 'mcp' | 'prompt' | 'advanced' | 'mcp-mock' | 'user-simulator' | 'version-manager' | 'chat-compare' | 'cache-monitor' | 'snapshots';

type SubMenuKey = 'chat' | 'tools' | 'advanced';

const Sidebar: React.FC<SidebarProps> = ({ collapsed: propsCollapsed, onCollapse }) => {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [form] = Form.useForm();
  const [expandedMenus, setExpandedMenus] = useState<Set<SubMenuKey>>(new Set(['chat', 'tools', 'advanced']));
  const [internalCollapsed, setInternalCollapsed] = useState(false);
  const [showUserContext, setShowUserContext] = useState(false);

  // Mock snapshots data - TODO: replace with actual API call
  const snapshots = [
    { id: 'current', name: 'Current Config', description: 'Use current system configuration' },
    { id: 'snap-1', name: 'Snapshot 1', description: 'Created on 2024-01-15' },
    { id: 'snap-2', name: 'Snapshot 2', description: 'Created on 2024-01-10' },
  ];
  const queryClient = useQueryClient();

  // Use controlled or uncontrolled collapsed state
  const collapsed = propsCollapsed !== undefined ? propsCollapsed : internalCollapsed;
  const setCollapsed = (value: boolean) => {
    if (propsCollapsed === undefined) {
      setInternalCollapsed(value);
    }
    onCollapse?.(value);
  };

  const {
    currentSession,
    setCurrentSession,
    setAgentType,
    sessionToken,
    setSessionMetadata,
    clearMessages,
    activeTab,
    setActiveTab,
  } = useChatStore();

  // Fetch sessions (no token needed for listing)
  const { data: sessionsData } = useQuery({
    queryKey: ['sessions'],
    queryFn: () => getSessions({ status: 'active' }),
  });

  // Create session mutation (with token if provided)
  const createMutation = useMutation({
    mutationFn: (data: { title: string; agent_type: string; metadata: Record<string, unknown>; user_context?: Record<string, unknown>; token?: string }) =>
      createSession({ title: data.title, agent_type: data.agent_type, metadata: data.metadata, user_context: data.user_context }, data.token),
    onSuccess: (newSession) => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] });
      setCurrentSession(newSession);
      clearMessages();
      setIsModalOpen(false);
      form.resetFields();
    },
  });

  // Delete session mutation (with session token if exists)
  const deleteMutation = useMutation({
    mutationFn: (sessionId: string) => deleteSession(sessionId, sessionToken || undefined),
    onSuccess: (_, sessionId) => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] });
      if (currentSession?.session_id === sessionId) {
        setCurrentSession(null);
        clearMessages();
      }
    },
  });

  const handleCreateSession = (values: {
    title?: string;
    snapshot?: string;
    userContextJson?: string;
  }) => {
    // Build metadata with snapshot info
    const metadataWithConfig: Record<string, unknown> = {};

    // Add snapshot if selected (not current)
    if (values.snapshot && values.snapshot !== 'current') {
      metadataWithConfig.snapshot = values.snapshot;
    }

    // Parse user_context JSON
    let userContext: Record<string, unknown> = {};
    if (values.userContextJson && values.userContextJson.trim()) {
      try {
        userContext = JSON.parse(values.userContextJson);
      } catch {
        message.error('User Context JSON 格式不正确');
        return;
      }
    }

    createMutation.mutate({
      title: values.title || 'New Session',
      agent_type: 'react',
      metadata: metadataWithConfig,
      user_context: userContext,
    });

    // Update store config with defaults
    setAgentType('react');
    setSessionMetadata(metadataWithConfig);
  };

  const handleSelectSession = (session: Session) => {
    setCurrentSession(session);
    clearMessages();
    setActiveTab('chat');
  };

  const handleDeleteSession = (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    Modal.confirm({
      title: 'Confirm Delete',
      content: 'Are you sure you want to delete this session?',
      onOk: () => deleteMutation.mutate(sessionId),
    });
  };

  const toggleMenu = (key: SubMenuKey) => {
    setExpandedMenus((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(key)) {
        newSet.delete(key);
      } else {
        newSet.add(key);
      }
      return newSet;
    });
  };

  const handleTabChange = (key: MenuKey) => {
    setActiveTab(key);
    // Auto expand tools menu when any agent setting is selected
    if (['skills', 'mcp', 'prompt', 'models', 'memory', 'context', 'security', 'setting', 'agent-settings', 'version-manager', 'cache-monitor', 'snapshots'].includes(key)) {
      setExpandedMenus((prev) => new Set([...prev, 'tools']));
    }
  };

  const sessions = sessionsData?.sessions || [];

  // Render session list
  const renderSessionList = () => {
    if (sessions.length === 0) {
      return null;
    }
    return (
      <div className={`${styles.menuContent} ${styles.chatSessionList}`}>
        {sessions.map((session) => (
          <div
            key={session.session_id}
            className={`${styles.sessionItem} ${
              activeTab === 'chat' && currentSession?.session_id === session.session_id ? styles.active : ''
            }`}
            onClick={() => handleSelectSession(session)}
          >
            <CommentOutlined className={styles.sessionIcon} />
            <Text ellipsis className={styles.sessionTitle}>
              {session.title || 'Untitled Session'}
            </Text>
            <Button
              type="text"
              size="small"
              icon={<DeleteOutlined />}
              onClick={(e) => handleDeleteSession(e, session.session_id)}
              className={styles.deleteBtn}
            />
          </div>
        ))}
      </div>
    );
  };

  // Render tool submenu - Session, Agent, Version Manager
  const renderToolSubMenu = () => (
    <div className={styles.subMenu}>
      <div
        className={`${styles.subMenuItem} ${activeTab === 'setting' ? styles.subMenuItemActive : ''}`}
        onClick={() => handleTabChange('setting')}
      >
        <ControlOutlined className={styles.subMenuIcon} />
        <span>Session</span>
      </div>
      <div
        className={`${styles.subMenuItem} ${activeTab === 'agent-settings' ? styles.subMenuItemActive : ''}`}
        onClick={() => handleTabChange('agent-settings')}
      >
        <RobotOutlined className={styles.subMenuIcon} />
        <span>Agent</span>
      </div>
      <div
        className={`${styles.subMenuItem} ${activeTab === 'snapshots' ? styles.subMenuItemActive : ''}`}
        onClick={() => handleTabChange('snapshots')}
      >
        <CameraOutlined className={styles.subMenuIcon} />
        <span>Snapshot</span>
      </div>
      <div
        className={`${styles.subMenuItem} ${activeTab === 'cache-monitor' ? styles.subMenuItemActive : ''}`}
        onClick={() => handleTabChange('cache-monitor')}
      >
        <ThunderboltOutlined className={styles.subMenuIcon} />
        <span>Cache Monitor</span>
      </div>
    </div>
  );

  // Render advanced submenu
  const renderAdvancedSubMenu = () => (
    <div className={styles.subMenu}>
      <div
        className={`${styles.subMenuItem} ${activeTab === 'chat-compare' ? styles.subMenuItemActive : ''}`}
        onClick={() => handleTabChange('chat-compare')}
      >
        <SplitCellsOutlined className={styles.subMenuIcon} />
        <span>Playground</span>
      </div>
    </div>
  );

  return (
    <>
      <Sider width={collapsed ? 0 : 220} className={`${styles.sider} ${collapsed ? styles.siderCollapsed : ''}`}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.logoIcon}>
            <ThunderboltOutlined />
          </div>
          <div className={styles.logoTextGroup}>
            <Title level={5} className={styles.logo}>ASRI</Title>
          </div>
        </div>

      {/* Navigation Menu (Accordion) */}
      <div className={styles.menuContainer}>
        {/* Chat Menu */}
        <div className={`${styles.menuItem} ${styles.chatMenuItem}`}>
          <div className={styles.menuHeader} onClick={() => toggleMenu('chat' as SubMenuKey)}>
            <span className={styles.menuIcon}><CommentOutlined /></span>
            <span className={styles.menuLabel}>Chat</span>
            <button
              className={styles.inlineAddBtn}
              onClick={(e) => { e.stopPropagation(); setIsModalOpen(true); }}
              title="New Session"
            >
              <PlusOutlined />
            </button>
            <RightOutlined
              className={`${styles.expandIcon} ${expandedMenus.has('chat' as SubMenuKey) ? styles.expandIconRotated : ''}`}
            />
          </div>
          <div className={`${styles.menuContentWrapper} ${expandedMenus.has('chat' as SubMenuKey) ? styles.menuContentExpanded : ''}`}>
            {renderSessionList()}
          </div>
        </div>

        {/* Settings Menu with Submenu */}
        <div className={styles.menuItem}>
          <div className={styles.menuHeader} onClick={() => toggleMenu('tools')}>
            <span className={styles.menuIcon}><SettingOutlined /></span>
            <span className={styles.menuLabel}>Settings</span>
            <RightOutlined
              className={`${styles.expandIcon} ${expandedMenus.has('tools') ? styles.expandIconRotated : ''}`}
            />
          </div>
          <div className={`${styles.menuContentWrapper} ${expandedMenus.has('tools') ? styles.menuContentExpanded : ''}`}>
            {renderToolSubMenu()}
          </div>
        </div>

        {/* Lab Menu with Submenu */}
        <div className={styles.menuItem}>
          <div className={styles.menuHeader} onClick={() => toggleMenu('advanced')}>
            <span className={styles.menuIcon}><ExperimentOutlined /></span>
            <span className={styles.menuLabel}>AI Lab</span>
            <RightOutlined
              className={`${styles.expandIcon} ${expandedMenus.has('advanced') ? styles.expandIconRotated : ''}`}
            />
          </div>
          <div className={`${styles.menuContentWrapper} ${expandedMenus.has('advanced') ? styles.menuContentExpanded : ''}`}>
            {renderAdvancedSubMenu()}
          </div>
        </div>
      </div>

      {/* Footer removed - use floating toggle instead */}

      {/* New Session Modal */}
      <Modal title="New Session" open={isModalOpen} onCancel={() => setIsModalOpen(false)} footer={null} destroyOnClose>
        <Form
          form={form}
          layout="vertical"
          onFinish={handleCreateSession}
          initialValues={{ snapshot: 'current' }}
        >
          <Form.Item label="Session Title" name="title">
            <Input placeholder="Optional session title" />
          </Form.Item>

          <Form.Item label="Config Snapshot" name="snapshot">
            <Select placeholder="Select config snapshot" allowClear>
              {snapshots.map((snap) => (
                <Option key={snap.id} value={snap.id}>
                  <div style={{ display: 'flex', flexDirection: 'column' }}>
                    <span>{snap.name}</span>
                    <span style={{ fontSize: '12px', color: '#999' }}>{snap.description}</span>
                  </div>
                </Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item style={{ marginBottom: 12 }}>
            <Button
              type="link"
              onClick={() => setShowUserContext(!showUserContext)}
              style={{ padding: 0 }}
            >
              {showUserContext ? 'Hide' : 'Show'} User Context (JSON)
            </Button>
          </Form.Item>

          {showUserContext && (
            <Form.Item
              label="User Context"
              name="userContextJson"
              help='JSON format, e.g. {"name": "张三", "role": "客服"}'
            >
              <Input.TextArea
                rows={4}
                placeholder='{"name": "张三", "role": "客服"}'
              />
            </Form.Item>
          )}

          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={createMutation.isPending}>
                Create
              </Button>
              <Button onClick={() => setIsModalOpen(false)}>Cancel</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </Sider>

    {/* Floating collapse/expand toggle on sidebar edge */}
    <button
      className={`${styles.floatToggleBtn} ${collapsed ? styles.floatToggleBtnCollapsed : ''}`}
      onClick={() => setCollapsed(!collapsed)}
      title={collapsed ? 'Expand Menu' : 'Collapse Menu'}
    >
      <MenuFoldOutlined className={`${styles.floatToggleIcon} ${collapsed ? styles.floatToggleIconRotated : ''}`} />
    </button>
    </>
  );
};

export default Sidebar;
