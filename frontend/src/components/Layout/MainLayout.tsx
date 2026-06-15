import React, { useCallback, useState } from 'react';
import { Layout, Select, Button, Modal, Form, Input, message } from 'antd';
import { UserOutlined, LogoutOutlined, PlusOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import Sidebar from './Sidebar';
import { useChatStore } from '@/stores/chatStore';
import { useTenantStore } from '@/stores/tenantStore';
import { getTenants, createTenant } from '@/api/tenant';
import type { CreateTenantRequest } from '@/api/tenant';
import styles from './MainLayout.module.css';

const { Header, Content } = Layout;

interface MainLayoutProps {
  children: React.ReactNode;
}

const MainLayout: React.FC<MainLayoutProps> = ({ children }) => {
  const { activeTab, sidebarCollapsed, setSidebarCollapsed } = useChatStore();
  const { currentTenantId, setCurrentTenant } = useTenantStore();
  const queryClient = useQueryClient();
  const isChatPage = activeTab === 'chat' || activeTab === 'chat-compare';

  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm<CreateTenantRequest>();

  const { data: tenants = [] } = useQuery({
    queryKey: ['tenants'],
    queryFn: getTenants,
    staleTime: 5 * 60 * 1000,
  });

  const handleTenantChange = useCallback((tenantId: string) => {
    setCurrentTenant(tenantId);
    // Force refetch all queries (active + inactive tabs) with new tenant context
    queryClient.invalidateQueries({ refetchType: 'all' });
  }, [setCurrentTenant, queryClient]);

  const createMutation = useMutation({
    mutationFn: (data: CreateTenantRequest) => createTenant(data),
    onSuccess: (newTenant) => {
      queryClient.invalidateQueries({ queryKey: ['tenants'] });
      setCurrentTenant(newTenant.tenant_id);
      queryClient.invalidateQueries({ refetchType: 'all' });
      message.success(`Tenant "${newTenant.name}" created and switched`);
      setModalOpen(false);
      form.resetFields();
    },
    onError: (error: any) => {
      const msg = error?.response?.data?.error || 'Failed to create tenant';
      message.error(msg);
    },
  });

  const handleModalOk = () => {
    form.validateFields().then((values) => {
      createMutation.mutate(values);
    });
  };

  const handleModalCancel = () => {
    setModalOpen(false);
    form.resetFields();
  };

  return (
    <Layout className={styles.layout}>
      <Sidebar collapsed={sidebarCollapsed} onCollapse={setSidebarCollapsed} />
      <Layout className={`${styles.contentLayout} ${isChatPage ? styles.chatLayout : ''} ${sidebarCollapsed ? styles.collapsed : ''}`}>
        <Header className={styles.header}>
          <div className={styles.headerRight}>
            <UserOutlined className={styles.headerIcon} />
            <Select
              value={currentTenantId}
              onChange={handleTenantChange}
              style={{ width: 180 }}
              options={tenants.map((t) => ({ label: t.name, value: t.tenant_id }))}
            />
            <Button
              icon={<PlusOutlined />}
              size="small"
              type="text"
              title="New Tenant"
              onClick={() => setModalOpen(true)}
              className={styles.headerIcon}
            />
            <LogoutOutlined className={styles.headerIcon} />
          </div>
        </Header>
        <Content className={styles.content}>{children}</Content>
      </Layout>

      <Modal
        title="Create New Tenant"
        open={modalOpen}
        onOk={handleModalOk}
        onCancel={handleModalCancel}
        confirmLoading={createMutation.isPending}
        okText="Create"
        cancelText="Cancel"
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            label="Tenant ID"
            name="tenant_id"
            rules={[
              { required: true, message: 'Tenant ID is required' },
              { pattern: /^[a-zA-Z0-9_-]+$/, message: 'Only letters, numbers, underscores and hyphens allowed' },
            ]}
          >
            <Input placeholder="e.g. my_tenant" autoComplete="off" />
          </Form.Item>
          <Form.Item
            label="Name"
            name="name"
            rules={[{ required: true, message: 'Name is required' }]}
          >
            <Input placeholder="e.g. My Tenant" autoComplete="off" />
          </Form.Item>
        </Form>
      </Modal>
    </Layout>
  );
};

export default MainLayout;
