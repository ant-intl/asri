import React, { useState, useRef, useEffect } from 'react';
import {
  Card,
  Button,
  Form,
  Input,
  Switch,
  message,
  Typography,
  Space,
  Tag,
  Divider,
  Modal,
  List,
  Badge,
  Select,
  Upload,
  Table,
  Spin,
  Drawer,
} from 'antd';
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ArrowLeftOutlined,
  ApiOutlined,
  CodeOutlined,
  FileTextOutlined,
  UploadOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons';
import styles from './McpConfig.module.css';
import {
  getMcpServers,
  createMcpServer,
  updateMcpServer,
  deleteMcpServer,
  toggleMcpServer,
  updateToolMockConfig,
  toggleToolMock,
  refreshMcpServerTools,
  executeMcpTool,
} from '@/api/mcpServer';
import type {
  McpServer,
  McpTool,
  MockPair,
  MockMode,
  McpToolMockConfig,
} from '@/types/mcpServer';
import { parseJsonOrThrow, safeJsonParse } from '@/utils/safeJsonParse';
import { useTenantStore } from '@/stores/tenantStore';

const { Title, Text } = Typography;
const { TextArea } = Input;

const McpConfig: React.FC = () => {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [loading, setLoading] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingServer, setEditingServer] = useState<McpServer | null>(null);
  const [selectedServer, setSelectedServer] = useState<McpServer | null>(null);
  const [mockModalOpen, setMockModalOpen] = useState(false);
  const [editingTool, setEditingTool] = useState<McpTool | null>(null);
  const [mockForm] = Form.useForm();
  const [form] = Form.useForm();
  const [csvData, setCsvData] = useState<MockPair[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isJsonMode, setIsJsonMode] = useState(false);
  const [jsonInput, setJsonInput] = useState('');

  // Tenant context for data isolation
  const currentTenantId = useTenantStore((s) => s.currentTenantId);

  // Execute tool state
  const [executingTool, setExecutingTool] = useState<McpTool | null>(null);
  const [executeResult, setExecuteResult] = useState<unknown>(null);
  const [executeLoading, setExecuteLoading] = useState(false);
  const [executeForm] = Form.useForm();

  // Load MCP servers on component mount and when tenant changes
  useEffect(() => {
    loadServers();
  }, [currentTenantId]);

  const loadServers = async () => {
    setLoading(true);
    try {
      const response = await getMcpServers();
      setServers(response.providers || []);
    } catch (error) {
      message.error('Failed to load MCP servers');
      console.error('Error loading MCP servers:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleAdd = () => {
    setEditingServer(null);
    form.resetFields();
    setIsJsonMode(false);
    setJsonInput('');
    setIsModalOpen(true);
  };

  const handleEdit = (server: McpServer, e?: React.MouseEvent) => {
    e?.stopPropagation();
    setEditingServer(server);
    form.setFieldsValue({
      name: server.name,
      description: server.description,
      command: server.command,
      args: server.args.join(' '),
      env: server.env ? JSON.stringify(server.env, null, 2) : '',
      isActive: server.isActive,
    });
    // Also prepare JSON input
    const jsonData: Record<string, unknown> = {
      name: server.name,
      description: server.description || '',
      clientType: server.clientType || 'stdio',
      command: server.command,
      args: server.args,
      env: server.env || {},
      isActive: server.isActive,
    };
    // Include config if present
    if (server.config && Object.keys(server.config).length > 0) {
      jsonData.config = server.config;
    }
    setJsonInput(JSON.stringify(jsonData, null, 2));
    setIsJsonMode(false);
    setIsModalOpen(true);
  };

  const handleDelete = async (serverId: string, e?: React.MouseEvent) => {
    e?.stopPropagation();
    Modal.confirm({
      title: 'Confirm Delete',
      content: 'Are you sure you want to delete this MCP server configuration?',
      onOk: async () => {
        try {
          await deleteMcpServer(serverId);
          message.success('Deleted successfully');
          await loadServers();
        } catch (error) {
          message.error('Failed to delete');
          console.error('Error deleting MCP server:', error);
        }
      },
    });
  };

  const handleCardClick = async (server: McpServer) => {
    setSelectedServer(server);

    // Auto-refresh tools when entering detail page
    try {
      message.loading({ content: 'Fetching tools...', key: 'refresh-tools' });
      const updatedServer = await refreshMcpServerTools(server.id);
      setSelectedServer(updatedServer);

      // Update server list with new data
      setServers(prev => prev.map(s => s.id === updatedServer.id ? updatedServer : s));

      message.success({ content: 'Tools updated', key: 'refresh-tools' });
    } catch (error) {
      console.error('Error refreshing tools:', error);
      message.error({ content: 'Failed to fetch tools, showing cached data', key: 'refresh-tools' });
    }
  };

  const handleBack = () => {
    setSelectedServer(null);
  };

  const handleSubmit = async (values: {
    name: string;
    description?: string;
    command: string;
    args: string;
    env?: string;
    isActive?: boolean;
  }) => {
    try {
      let data: Record<string, unknown>;

      if (isJsonMode) {
        // Parse JSON input
        data = parseJsonOrThrow(jsonInput, 'MCP 配置');
      } else {
        // Parse form input
        data = {
          name: values.name,
          description: values.description,
          command: values.command,
          args: values.args.split(' ').filter(Boolean),
          env: values.env ? parseJsonOrThrow(values.env, '环境变量') : undefined,
          isActive: values.isActive ?? true,
        };
      }

      if (editingServer) {
        await updateMcpServer(editingServer.id, data);
        message.success('Updated successfully');
      } else {
        await createMcpServer(data);
        message.success('Created successfully');
      }

      setIsModalOpen(false);
      form.resetFields();
      setJsonInput('');
      await loadServers();
    } catch (error) {
      if (isJsonMode && error instanceof SyntaxError) {
        message.error('Invalid JSON format, please check your input');
      } else {
        message.error(editingServer ? 'Failed to update' : 'Failed to create');
      }
      console.error('Error saving MCP server:', error);
    }
  };

  const toggleActive = async (serverId: string, e?: React.MouseEvent) => {
    e?.stopPropagation();
    try {
      await toggleMcpServer(serverId);
      await loadServers();
      if (selectedServer?.id === serverId) {
        const updated = servers.find(s => s.id === serverId);
        if (updated) {
          setSelectedServer({ ...updated, isActive: !updated.isActive });
        }
      }
    } catch (error) {
      message.error('Failed to toggle status');
      console.error('Error toggling MCP server:', error);
    }
  };

  const handleMockToggle = async (toolName: string, enabled: boolean) => {
    if (!selectedServer) return;
    try {
      const result = await toggleToolMock(selectedServer.id, toolName);
      // Update local state
      const updatedTools = selectedServer.tools?.map((tool) =>
        tool.name === toolName ? { ...tool, mock: result.mock } : tool
      );
      setSelectedServer({ ...selectedServer, tools: updatedTools });
      await loadServers();
    } catch (error) {
      message.error('Failed to toggle mock status');
      console.error('Error toggling tool mock:', error);
    }
  };

  const handleOpenMockModal = (tool: McpTool) => {
    setEditingTool(tool);
    const mode = tool.mock?.mode || 'manual';
    mockForm.setFieldsValue({
      mode,
      randomOutputs: tool.mock?.randomOutputs?.map(o => JSON.stringify(o, null, 2)).join('\n---\n') || '',
      manualInput: tool.mock?.manualInput ? JSON.stringify(tool.mock.manualInput, null, 2) : '{}',
      manualOutput: tool.mock?.manualOutput ? JSON.stringify(tool.mock.manualOutput, null, 2) : '{}',
    });
    setCsvData(tool.mock?.pairs || []);
    setMockModalOpen(true);
  };

  const handleSaveMock = async (values: {
    mode: MockMode;
    manualInput?: string;
    manualOutput?: string;
  }) => {
    if (!selectedServer || !editingTool) return;
    try {
      let mock: McpTool['mock'] = { enabled: true, mode: values.mode };

      if (values.mode === 'fixed') {
        mock.pairs = csvData;
      } else if (values.mode === 'random') {
        mock.randomOutputs = csvData.map(d => d.output);
      } else if (values.mode === 'manual') {
        mock.manualInput = safeJsonParse(values.manualInput || '{}', {});
        mock.manualOutput = safeJsonParse(values.manualOutput || '{}', {});
      }

      const config: McpToolMockConfig = {
        toolName: editingTool.name,
        mock,
      };

      await updateToolMockConfig(selectedServer.id, editingTool.name, config);

      // Update local state
      const updatedTools = selectedServer.tools?.map((tool) =>
        tool.name === editingTool.name ? { ...tool, mock } : tool
      );
      setSelectedServer({ ...selectedServer, tools: updatedTools });

      message.success('Mock configuration saved');
      setMockModalOpen(false);
      setCsvData([]);
      await loadServers();
    } catch (error) {
      message.error('Failed to save mock configuration');
      console.error('Error saving mock config:', error);
    }
  };

  const handleOpenExecuteModal = (tool: McpTool) => {
    console.log('Opening execute panel for tool:', tool.name);

    // If clicking the same tool, close it
    if (executingTool?.name === tool.name) {
      setExecutingTool(null);
      setExecuteResult(null);
      executeForm.resetFields();
      return;
    }

    setExecutingTool(tool);
    setExecuteResult(null);

    // Initialize form with default values from inputSchema
    const defaultValues: Record<string, unknown> = {};
    if (tool.inputSchema?.properties) {
      Object.entries(tool.inputSchema.properties).forEach(([key, value]) => {
        // Set default value based on type
        if (value.type === 'string') {
          defaultValues[key] = '';
        } else if (value.type === 'number' || value.type === 'integer') {
          defaultValues[key] = 0;
        } else if (value.type === 'boolean') {
          defaultValues[key] = false;
        } else if (value.type === 'array') {
          defaultValues[key] = [];
        } else if (value.type === 'object') {
          defaultValues[key] = {};
        }
      });
    }
    console.log('Default values:', defaultValues);
    executeForm.setFieldsValue({ arguments: JSON.stringify(defaultValues, null, 2) });
  };

  const handleExecuteTool = async (values: { arguments: string }) => {
    if (!selectedServer || !executingTool) return;

    setExecuteLoading(true);
    try {
      const args = parseJsonOrThrow(values.arguments, '工具参数');
      const result = await executeMcpTool(selectedServer.id, executingTool.name, args);
      setExecuteResult(result.result);
      message.success('Tool executed successfully');
    } catch (error) {
      message.error('Tool execution failed');
      console.error('Error executing tool:', error);
      setExecuteResult({ error: String(error) });
    } finally {
      setExecuteLoading(false);
    }
  };

  const handleCsvUpload = (file: File, mode: 'fixed' | 'random' = 'fixed') => {
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const text = e.target?.result as string;
        const lines = text.trim().split('\n');
        if (lines.length < 2) {
          message.error('Invalid CSV format: must include header row and at least one data row');
          return;
        }

        const headers = lines[0].split(',').map(h => h.trim());

        if (mode === 'fixed') {
          const inputKeys = headers.filter(h => h.startsWith('input_')).map(h => h.replace('input_', ''));
          const outputKeys = headers.filter(h => h.startsWith('output_')).map(h => h.replace('output_', ''));

          if (inputKeys.length === 0 || outputKeys.length === 0) {
            message.error('Invalid CSV format: must include columns with input_ and output_ prefixes');
            return;
          }

          const pairs: MockPair[] = [];
          for (let i = 1; i < lines.length; i++) {
            const values = lines[i].split(',').map(v => v.trim());
            const input: Record<string, unknown> = {};
            const output: Record<string, unknown> = {};

            headers.forEach((header, idx) => {
              const value = values[idx];
              if (header.startsWith('input_')) {
                const key = header.replace('input_', '');
                input[key] = parseValue(value);
              } else if (header.startsWith('output_')) {
                const key = header.replace('output_', '');
                output[key] = parseValue(value);
              }
            });

            pairs.push({
              id: Date.now().toString() + i,
              input,
              output,
            });
          }

          setCsvData(pairs);
          message.success(`Successfully imported ${pairs.length} records`);
        } else if (mode === 'random') {
          const outputKeys = headers.filter(h => h.startsWith('output_')).map(h => h.replace('output_', ''));

          if (outputKeys.length === 0) {
            message.error('Invalid CSV format: must include columns with output_ prefix');
            return;
          }

          const pairs: MockPair[] = [];
          for (let i = 1; i < lines.length; i++) {
            const values = lines[i].split(',').map(v => v.trim());
            const output: Record<string, unknown> = {};

            headers.forEach((header, idx) => {
              const value = values[idx];
              if (header.startsWith('output_')) {
                const key = header.replace('output_', '');
                output[key] = parseValue(value);
              }
            });

            pairs.push({
              id: Date.now().toString() + i,
              input: {},
              output,
            });
          }

          setCsvData(pairs);
          message.success(`Successfully imported ${pairs.length} output records`);
        }
      } catch (error) {
        message.error('CSV parsing failed, please check the file format');
      }
    };
    reader.readAsText(file);
    return false;
  };

  const parseValue = (value: string): unknown => {
    if (value === 'true') return true;
    if (value === 'false') return false;
    if (!isNaN(Number(value)) && value !== '') return Number(value);
    try {
      return JSON.parse(value);
    } catch {
      return value;
    }
  };

  // Render MCP Tool List View
  if (selectedServer) {
    return (
      <div className={styles.container}>
        <div className={styles.header}>
          <div className={styles.headerLeft}>
            <Button
              type="text"
              icon={<ArrowLeftOutlined />}
              onClick={handleBack}
              className={styles.backBtn}
            >
              Back
            </Button>
            <div className={styles.headerTitle}>
              <Text className={styles.title}>{selectedServer.name}</Text>
              <Tag color={selectedServer.isActive ? 'success' : 'default'}>
                {selectedServer.isActive ? 'Running' : 'Stopped'}
              </Tag>
            </div>
          </div>
          <Space>
            <Button
              type="text"
              icon={<EditOutlined />}
              onClick={(e) => handleEdit(selectedServer, e)}
            >
              Edit
            </Button>
            <Switch
              checked={selectedServer.isActive}
              onChange={() => toggleActive(selectedServer.id)}
              checkedChildren="On"
              unCheckedChildren="Off"
            />
          </Space>
        </div>

        <Divider />

        <div className={styles.detailContent}>
          {/* Server Info Card */}
          <Card className={styles.infoCard}>
            <div className={styles.infoSection}>
              <div className={styles.infoItem}>
                <FileTextOutlined className={styles.infoIcon} />
                <div>
                  <Text type="secondary">Description</Text>
                  <Text className={styles.infoValue}>
                    {selectedServer.description || 'No description'}
                  </Text>
                </div>
              </div>
              <div className={styles.infoItem}>
                <CodeOutlined className={styles.infoIcon} />
                <div>
                  <Text type="secondary">Command</Text>
                  <code className={styles.commandCode}>{selectedServer.command}</code>
                </div>
              </div>
              <div className={styles.infoItem}>
                <ApiOutlined className={styles.infoIcon} />
                <div>
                  <Text type="secondary">Arguments</Text>
                  <div className={styles.argsList}>
                    {selectedServer.args.map((arg, idx) => (
                      <Tag key={idx}>{arg}</Tag>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </Card>

          {/* Tools List */}
          <Card className={styles.toolsCard} title={`Tools (${selectedServer.tools?.length || 0})`}>
            <List
              dataSource={selectedServer.tools || []}
              renderItem={(tool) => (
                <>
                  <List.Item
                    className={styles.toolItem}
                    actions={[
                      <Button
                        key="execute"
                        type="primary"
                        size="small"
                        icon={<PlayCircleOutlined />}
                        onClick={() => handleOpenExecuteModal(tool)}
                      >
                        {executingTool?.name === tool.name ? 'Close' : 'Run'}
                      </Button>,
                      <Switch
                        key="mock"
                        size="small"
                        checked={tool.mock?.enabled}
                        onChange={(checked) => handleMockToggle(tool.name, checked)}
                        checkedChildren="Mock"
                        unCheckedChildren="Mock"
                      />,
                      <Button
                        key="config"
                        type="link"
                        size="small"
                        disabled={!tool.mock?.enabled}
                        onClick={() => handleOpenMockModal(tool)}
                      >
                        Configure
                      </Button>,
                    ]}
                  >
                    <div className={styles.toolContent}>
                      <div className={styles.toolHeader}>
                        <Badge status={selectedServer.isActive ? 'processing' : 'default'} />
                        <Text strong className={styles.toolName}>{tool.name}</Text>
                        {tool.mock?.enabled && <Tag color="blue">Mock</Tag>}
                      </div>
                      <Text type="secondary" className={styles.toolDesc}>
                        {tool.description}
                      </Text>
                      <div className={styles.toolParams}>
                        <Text type="secondary" className={styles.paramsLabel}>Parameters:</Text>
                        <div className={styles.paramsList}>
                          {Object.entries(tool.inputSchema?.properties || {}).map(([key, value]) => (
                            <Tag key={key} className={styles.paramTag}>
                              <span className={styles.paramName}>{key}</span>
                              <span className={styles.paramType}>({value.type})</span>
                              {tool.inputSchema?.required?.includes(key) && (
                                <span className={styles.paramRequired}>*</span>
                              )}
                            </Tag>
                          ))}
                        </div>
                      </div>
                    </div>
                  </List.Item>

                  {/* Inline Execute Panel */}
                  {executingTool?.name === tool.name && (
                    <div className={styles.executePanel}>
                      <div className={styles.executePanelHeader}>
                        <Text strong>Execute: {tool.name}</Text>
                        <Text type="secondary">{tool.description}</Text>
                      </div>

                      <Form form={executeForm} layout="vertical" onFinish={handleExecuteTool}>
                        {tool.inputSchema?.properties && (
                          <div className={styles.paramInfo}>
                            <Text strong>Parameter Details:</Text>
                            <div className={styles.paramList}>
                              {Object.entries(tool.inputSchema.properties).map(([key, value]) => (
                                <div key={key} className={styles.paramItem}>
                                  <Tag color="blue">{key}</Tag>
                                  <Text type="secondary">{value.description || value.type}</Text>
                                  {tool.inputSchema?.required?.includes(key) && (
                                    <Tag color="red">Required</Tag>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        <Form.Item
                          name="arguments"
                          label="Input Parameters (JSON)"
                          rules={[{ required: true, message: 'Please enter parameters' }]}
                        >
                          <TextArea
                            rows={8}
                            placeholder={`{\n  "param1": "value1",\n  "param2": "value2"\n}`}
                            style={{ fontFamily: 'monospace' }}
                          />
                        </Form.Item>

                        <Form.Item>
                          <Space>
                            <Button onClick={() => executeForm.resetFields()}>Reset</Button>
                            <Button type="primary" htmlType="submit" loading={executeLoading}>
                              Execute
                            </Button>
                          </Space>
                        </Form.Item>
                      </Form>

                      {executeResult !== null && (
                        <div className={styles.executeResult}>
                          <Divider />
                          <Text strong>Result:</Text>
                          <pre className={styles.resultContent}>
                            {typeof executeResult === 'string'
                              ? executeResult
                              : JSON.stringify(executeResult, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
            />
          </Card>

          {/* Mock Config Modal */}
          <Modal
            title={`Configure Mock - ${editingTool?.name}`}
            open={mockModalOpen}
            onCancel={() => setMockModalOpen(false)}
            footer={null}
            width={700}
          >
            <Form
              form={mockForm}
              layout="vertical"
              onFinish={handleSaveMock}
              initialValues={{ mode: 'manual' }}
            >
              <Form.Item label="Mock Mode" name="mode">
                <Select>
                  <Select.Option value="fixed">Fixed Input-Output Matching (Batch Import)</Select.Option>
                  <Select.Option value="random">Random Output (Batch Import Output List)</Select.Option>
                  <Select.Option value="manual">Manual Input-Output Pair</Select.Option>
                </Select>
              </Form.Item>

              <Form.Item noStyle shouldUpdate={(prev, curr) => prev.mode !== curr.mode}>
                {({ getFieldValue }) => {
                  const mode = getFieldValue('mode');

                  if (mode === 'fixed') {
                    const columns = [
                      {
                        title: 'Input',
                        dataIndex: 'input',
                        key: 'input',
                        render: (input: Record<string, unknown>) => (
                          <pre className={styles.jsonPreview}>{JSON.stringify(input, null, 2)}</pre>
                        ),
                      },
                      {
                        title: 'Output',
                        dataIndex: 'output',
                        key: 'output',
                        render: (output: unknown) => (
                          <pre className={styles.jsonPreview}>{JSON.stringify(output, null, 2)}</pre>
                        ),
                      },
                    ];
                    return (
                      <div>
                        <div className={styles.csvUploadSection}>
                          <Upload
                            accept=".csv"
                            beforeUpload={(file) => handleCsvUpload(file, 'fixed')}
                            showUploadList={false}
                          >
                            <Button icon={<UploadOutlined />}>Upload CSV File</Button>
                          </Upload>
                          <Text type="secondary" className={styles.csvHint}>
                            CSV format: input_xxx columns for input fields, output_xxx columns for output fields
                          </Text>
                        </div>
                        {csvData.length > 0 && (
                          <div className={styles.csvPreview}>
                            <Text strong>Imported {csvData.length} records</Text>
                            <Table
                              dataSource={csvData}
                              columns={columns}
                              rowKey="id"
                              size="small"
                              pagination={{ pageSize: 5 }}
                              scroll={{ y: 300 }}
                            />
                          </div>
                        )}
                      </div>
                    );
                  }

                  if (mode === 'random') {
                    const outputColumns = [
                      {
                        title: '#',
                        key: 'index',
                        width: 60,
                        render: (_: unknown, __: unknown, index: number) => index + 1,
                      },
                      {
                        title: 'Output',
                        dataIndex: 'output',
                        key: 'output',
                        render: (output: unknown) => (
                          <pre className={styles.jsonPreview}>{JSON.stringify(output, null, 2)}</pre>
                        ),
                      },
                    ];
                    return (
                      <div>
                        <div className={styles.csvUploadSection}>
                          <Upload
                            accept=".csv"
                            beforeUpload={(file) => handleCsvUpload(file, 'random')}
                            showUploadList={false}
                          >
                            <Button icon={<UploadOutlined />}>Upload CSV File</Button>
                          </Upload>
                          <Text type="secondary" className={styles.csvHint}>
                            CSV format: output_xxx columns for output fields, each row is a random output option
                          </Text>
                        </div>
                        {csvData.length > 0 && (
                          <div className={styles.csvPreview}>
                            <Text strong>Imported {csvData.length} output records</Text>
                            <Table
                              dataSource={csvData.map((item, idx) => ({ ...item, id: idx }))}
                              columns={outputColumns}
                              rowKey="id"
                              size="small"
                              pagination={{ pageSize: 5 }}
                              scroll={{ y: 300 }}
                            />
                          </div>
                        )}
                      </div>
                    );
                  }

                  return (
                    <>
                      <Form.Item
                        name="manualInput"
                        label="Input (JSON)"
                        rules={[{ required: true, message: 'Please enter input' }]}
                      >
                        <Input.TextArea rows={4} placeholder='{"param": "value"}' />
                      </Form.Item>
                      <Form.Item
                        name="manualOutput"
                        label="Output (JSON)"
                        rules={[{ required: true, message: 'Please enter output' }]}
                      >
                        <Input.TextArea rows={4} placeholder='{"result": "data"}' />
                      </Form.Item>
                    </>
                  );
                }}
              </Form.Item>

              <Form.Item>
                <Space>
                  <Button type="primary" htmlType="submit">
                    Save
                  </Button>
                  <Button onClick={() => setMockModalOpen(false)}>
                    Cancel
                  </Button>
                </Space>
              </Form.Item>
            </Form>
          </Modal>
        </div>
      </div>
    );
  }

  // Render Server List View
  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <Text className={styles.title}>MCP Server Configuration</Text>
        <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd} className={styles.addBtn}>
          Add Server
        </Button>
      </div>

      <Divider />

      <Spin spinning={loading}>
        <div className={styles.grid}>
          {servers.map((server) => (
          <Card
            key={server.id}
            className={styles.serverCard}
            hoverable
            onClick={() => handleCardClick(server)}
            title={
              <div className={styles.cardTitle}>
                <span>{server.name}</span>
                <Tag color={server.isActive ? 'success' : 'default'}>
                  {server.isActive ? 'Running' : 'Stopped'}
                </Tag>
              </div>
            }
            actions={[
              <div className={styles.cardFooter} key="footer">
                <Space>
                  <Button
                    type="text"
                    size="small"
                    icon={<EditOutlined />}
                    onClick={(e) => handleEdit(server, e)}
                    className={styles.actionBtn}
                  />
                  <Button
                    type="text"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={(e) => handleDelete(server.id, e)}
                    className={styles.actionBtn}
                  />
                </Space>
                <div className={styles.enableSection} onClick={(e) => e.stopPropagation()}>
                  <span className={styles.enableLabel}>Enable</span>
                  <Switch
                    checked={server.isActive}
                    onChange={() => toggleActive(server.id)}
                    size="small"
                  />
                </div>
              </div>,
            ]}
          >
            <div className={styles.cardContent}>
              <Text type="secondary" className={styles.description}>
                {server.description || 'No description'}
              </Text>
              <div className={styles.commandSection}>
                <Text className={styles.label}>Command:</Text>
                <code className={styles.command}>{server.command}</code>
              </div>
              <div className={styles.argsSection}>
                <Text className={styles.label}>Arguments:</Text>
                <div className={styles.args}>
                  {server.args.map((arg, idx) => (
                    <Tag key={idx} className={styles.argTag}>{arg}</Tag>
                  ))}
                </div>
              </div>
              <div className={styles.toolsPreview}>
                <ApiOutlined className={styles.toolsIcon} />
                <Text type="secondary">
                  {server.tools?.length || 0} tools
                </Text>
              </div>
            </div>
          </Card>
        ))}
        </div>
      </Spin>

      <Modal
        title={editingServer ? 'Edit MCP Server' : 'Add MCP Server'}
        open={isModalOpen}
        onCancel={() => {
          setIsModalOpen(false);
          setEditingServer(null);
          form.resetFields();
          setJsonInput('');
          setIsJsonMode(false);
        }}
        footer={null}
        width={600}
      >
        <div style={{ marginBottom: 16 }}>
          <Space>
            <Button
              type={isJsonMode ? 'default' : 'primary'}
              onClick={() => setIsJsonMode(false)}
            >
              Form Mode
            </Button>
            <Button
              type={isJsonMode ? 'primary' : 'default'}
              onClick={() => setIsJsonMode(true)}
            >
              JSON Mode
            </Button>
          </Space>
        </div>

        {isJsonMode ? (
          <div>
            <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
              JSON format examples (supports MCP standard configuration format):
            </Text>
            <pre style={{
              background: '#f5f5f5',
              padding: '12px',
              borderRadius: '4px',
              fontSize: '12px',
              marginBottom: '12px'
            }}>
{`// Stdio type (launched via npx/command)
{
  "name": "tavily_search",
  "clientType": "stdio",
  "command": "npx",
  "args": ["-y", "tavily-mcp@latest"],
  "env": { "TAVILY_API_KEY": "key" },
  "isActive": true
}

// HTTP type
{
  "name": "my_http_mcp",
  "clientType": "http",
  "config": {
    "endpoint": "https://mcp.example.com/api",
    "timeout": 30
  },
  "isActive": true
}

// Custom type (custom HTTP protocol)
{
  "name": "custom_mcp",
  "clientType": "custom",
  "config": {
    "endpoint": "https://api.example.com",
    "sseEndpoint": "/mcp/sse",
    "mcpName": "my_mcp",
    "listToolsPath": "/mcp/listTools",
    "executePath": "/mcp/execute",
    "timeout": 30
  },
  "isActive": true
}`}
            </pre>
            <TextArea
              rows={15}
              value={jsonInput}
              onChange={(e) => setJsonInput(e.target.value)}
              placeholder="Enter JSON server configuration, supports MCP standard format or single server format"
              style={{ fontFamily: 'monospace' }}
            />
            <div style={{ marginTop: 16, textAlign: 'right' }}>
              <Space>
                <Button onClick={() => {
                  setIsModalOpen(false);
                  setEditingServer(null);
                  setJsonInput('');
                  setIsJsonMode(false);
                }}>
                  Cancel
                </Button>
                <Button
                  type="primary"
                  onClick={async () => {
                    try {
                      const parsed = JSON.parse(jsonInput);

                      // Check if it's MCP standard format (with mcpServers)
                      if (parsed.mcpServers && typeof parsed.mcpServers === 'object') {
                        // MCP standard format - support multiple servers
                        const servers = Object.entries(parsed.mcpServers);
                        if (servers.length === 0) {
                          message.error('No server configuration found');
                          return;
                        }

                        let successCount = 0;
                        let failCount = 0;

                        for (const [serverName, serverConfig] of servers) {
                          try {
                            const cfg = serverConfig as Record<string, unknown>;
                            // Collect client-specific fields into config
                            const configKeys = ['endpoint', 'sseEndpoint', 'sse_endpoint', 'mcpName', 'mcp_name', 'listToolsPath', 'list_tools_path', 'executePath', 'execute_path', 'timeout'];
                            const config: Record<string, unknown> = {};
                            for (const key of configKeys) {
                              if (cfg[key] !== undefined) {
                                config[key] = cfg[key];
                              }
                            }

                            const data: Record<string, unknown> = {
                              name: serverName,
                              description: cfg.description || '',
                              clientType: cfg.clientType || cfg.type || 'stdio',
                              command: cfg.command || '',
                              args: cfg.args || [],
                              env: cfg.env || {},
                              config: Object.keys(config).length > 0 ? config : undefined,
                              isActive: cfg.isActive !== false,
                            };

                            if (editingServer) {
                              await updateMcpServer(editingServer.id, data);
                            } else {
                              await createMcpServer(data);
                            }
                            successCount++;
                          } catch (error) {
                            console.error(`Failed to create server ${serverName}:`, error);
                            failCount++;
                          }
                        }

                        if (successCount > 0) {
                          message.success(`Successfully ${editingServer ? 'updated' : 'created'} ${successCount} server(s)`);
                        }
                        if (failCount > 0) {
                          message.warning(`${failCount} server(s) failed to create`);
                        }

                        setIsModalOpen(false);
                        setJsonInput('');
                        await loadServers();
                      } else {
                        // Single server format
                        await handleSubmit(parsed);
                      }
                    } catch (error) {
                      if (error instanceof SyntaxError) {
                        message.error('Invalid JSON format, please check your input');
                      }
                    }
                  }}
                >
                  {editingServer ? 'Update' : 'Create'}
                </Button>
              </Space>
            </div>
          </div>
        ) : (
          <Form
            form={form}
            layout="vertical"
            onFinish={handleSubmit}
            initialValues={{ isActive: true }}
          >
            <Form.Item
              label="Server Name"
              name="name"
              rules={[{ required: true, message: 'Please enter server name' }]}
            >
              <Input placeholder="e.g. filesystem" />
            </Form.Item>

            <Form.Item label="Description" name="description">
              <Input placeholder="Server functionality description" />
            </Form.Item>

            <Form.Item
              label="Command"
              name="command"
              rules={[{ required: true, message: 'Please enter command' }]}
            >
              <Input placeholder="e.g. npx" />
            </Form.Item>

            <Form.Item
              label="Arguments"
              name="args"
              rules={[{ required: true, message: 'Please enter arguments' }]}
            >
              <Input placeholder="e.g. -y @modelcontextprotocol/server-filesystem /path" />
            </Form.Item>

            <Form.Item label="Environment Variables (JSON)" name="env">
              <TextArea
                rows={4}
                placeholder={`{\n  "KEY": "value"\n}`}
              />
            </Form.Item>

            <Form.Item label="Enabled" name="isActive" valuePropName="checked">
              <Switch />
            </Form.Item>

            <Form.Item>
              <Space className={styles.modalFooter}>
                <Button
                  onClick={() => {
                    setIsModalOpen(false);
                    setEditingServer(null);
                    form.resetFields();
                    setJsonInput('');
                    setIsJsonMode(false);
                  }}
                >
                  Cancel
                </Button>
                <Button type="primary" htmlType="submit">
                  {editingServer ? 'Update' : 'Create'}
                </Button>
              </Space>
            </Form.Item>
          </Form>
        )}
      </Modal>
    </div>
  );
};

export default McpConfig;
