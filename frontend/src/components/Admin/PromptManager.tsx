import React, { useState, useEffect, useMemo } from 'react';
import {
  Card,
  Button,
  Input,
  message,
  Typography,
  Divider,
  Space,
  Spin,
  Radio,
  Collapse,
} from 'antd';
import {
  SaveOutlined,
  FileTextOutlined,
  UserOutlined,
  EditOutlined,
  EyeOutlined,
  HistoryOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useTenantStore } from '@/stores/tenantStore';
import { getPromptTemplates, updatePromptTemplate, createPromptTemplate, enablePromptTemplate } from '@/api/promptTemplate';
import type { CreatePromptTemplateRequest, PromptLayer } from '@/types/promptTemplate';
import VersionHistoryPanel from './VersionHistoryPanel';
import PromptLayerEditor from './PromptLayerEditor';
import styles from './PromptManager.module.css';

const { TextArea } = Input;
const { Text, Title } = Typography;

// Default extractor config (from base.py)
const DEFAULT_EXTRACTOR_CONFIG = {
  extractor: {
    type: 'xml_tags',
    default_type: 'think',
  },
  mapper: {
    tool_keys: ['tool_call'],
    think_keys: ['think'],
    answer_keys: ['answer'],
  },
};

// Default prompts (markdown format)
const DEFAULT_SYSTEM_PROMPT = `# AI Assistant Configuration

You are a **helpful AI assistant** with the following capabilities:

## Core Abilities

- Answer questions based on your knowledge
- Use available tools when needed
- Provide accurate and helpful responses

## Guidelines

1. Be concise and clear
2. Use markdown formatting when appropriate
3. Acknowledge limitations when uncertain

> Note: Always prioritize user safety and helpfulness.`;

const DEFAULT_USER_PROMPT = `## User Query

{{query}}

---

**Context:**
{{history}}

**Available Skills:**
{{skills}}`;

// Markdown Preview Component
const MarkdownPreview: React.FC<{ content: string }> = ({ content }) => (
  <div className={styles.markdownPreview}>
    <ReactMarkdown remarkPlugins={[remarkGfm]}>{content || '(empty)'}</ReactMarkdown>
  </div>
);

// Prompt Editor Component with Preview/Edit toggle
const PromptEditor: React.FC<{
  label: string;
  desc: string;
  value: string;
  onChange: (value: string) => void;
  rows: number;
}> = ({ label, desc, value, onChange, rows }) => {
  const [isEditing, setIsEditing] = useState(false);

  return (
    <div className={styles.promptSection}>
      <div className={styles.sectionHeader}>
        <Title level={5} className={styles.sectionTitle}>
          {label}
        </Title>
        <Button
          type="text"
          icon={isEditing ? <EyeOutlined /> : <EditOutlined />}
          onClick={() => setIsEditing(!isEditing)}
          className={styles.toggleBtn}
        >
          {isEditing ? 'Preview' : 'Edit'}
        </Button>
      </div>
      <Text type="secondary" className={styles.sectionDesc}>
        {desc}
      </Text>

      {isEditing ? (
        <TextArea
          rows={rows}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Enter markdown content..."
          className={styles.editTextArea}
        />
      ) : (
        <div className={styles.previewContainer}>
          <MarkdownPreview content={value} />
        </div>
      )}
    </div>
  );
};

const PromptManager: React.FC = () => {
  const queryClient = useQueryClient();
  const currentTenantId = useTenantStore((s) => s.currentTenantId);
  const [systemPrompt, setSystemPrompt] = useState(DEFAULT_SYSTEM_PROMPT);
  const [userPrompt, setUserPrompt] = useState(DEFAULT_USER_PROMPT);
  const [userTemplateMode, setUserTemplateMode] = useState<'generic' | 'custom'>('generic');
  const [layers, setLayers] = useState<PromptLayer[]>([]);
  const [extractorConfig, setExtractorConfig] = useState('{}');
  const [extractorConfigError, setExtractorConfigError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [versionPanelOpen, setVersionPanelOpen] = useState(false);

  // Load prompt templates from backend
  const { data: templatesData, isLoading } = useQuery({
    queryKey: ['prompt-templates', currentTenantId],
    queryFn: getPromptTemplates,
  });

  // Find the active template
  const activeTemplate = useMemo(() => {
    if (!templatesData?.templates) return null;
    return templatesData.templates.find((t) => t.is_active) ?? null;
  }, [templatesData]);

  // Sync active template to local state, or use default
  useEffect(() => {
    if (activeTemplate) {
      setSystemPrompt(activeTemplate.system_template || DEFAULT_SYSTEM_PROMPT);
      setUserPrompt(activeTemplate.user_template || DEFAULT_USER_PROMPT);
      setUserTemplateMode(activeTemplate.user_template_mode || 'generic');
      setLayers(activeTemplate.layers || []);
      setExtractorConfig(
        activeTemplate.extractor_config && Object.keys(activeTemplate.extractor_config).length > 0
          ? JSON.stringify(activeTemplate.extractor_config, null, 2)
          : '{}'
      );
    } else {
      // No active template, use default
      setSystemPrompt(DEFAULT_SYSTEM_PROMPT);
      setUserPrompt(DEFAULT_USER_PROMPT);
      setUserTemplateMode('generic');
      setLayers([]);
      setExtractorConfig('{}');
    }
  }, [activeTemplate]);

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<CreatePromptTemplateRequest> }) =>
      updatePromptTemplate(id, data),
    onSuccess: () => {
      message.success('Saved successfully');
      queryClient.invalidateQueries({ queryKey: ['prompt-templates', currentTenantId] });
    },
    onError: () => {
      message.error('Save failed');
    },
  });

  // Validate extractor config JSON
  const validateExtractorConfig = (jsonStr: string): boolean => {
    try {
      JSON.parse(jsonStr);
      setExtractorConfigError(null);
      return true;
    } catch {
      setExtractorConfigError('Invalid JSON format');
      return false;
    }
  };

  // Handle save
  const handleSave = async () => {
    // Validate extractor config JSON
    if (!validateExtractorConfig(extractorConfig)) {
      message.error('Extractor config JSON format error');
      return;
    }

    let extractorConfigObj = {};
    try {
      extractorConfigObj = JSON.parse(extractorConfig);
    } catch {
      // Won't reach here due to validation above
    }

    if (activeTemplate) {
      // Update existing template
      updateMutation.mutate({
        id: activeTemplate.id,
        data: {
          system_template: systemPrompt,
          user_template: userPrompt,
          user_template_mode: userTemplateMode,
          layers,
          extractor_config: extractorConfigObj,
        },
      });
    } else {
      // Create new template and enable it
      setIsSaving(true);
      try {
        // Create new template with current prompts
        const newTemplate = await createPromptTemplate({
          name: 'Default',
          description: 'Default prompt template',
          system_template: systemPrompt,
          user_template_mode: userTemplateMode,
          user_template: userPrompt,
          layers,
          extractor_config: extractorConfigObj,
          is_active: false,
        });

        // Enable the new template (syncs to tenant config)
        await enablePromptTemplate(newTemplate.id);

        message.success('Created and enabled prompt template');
        queryClient.invalidateQueries({ queryKey: ['prompt-templates', currentTenantId] });
      } catch (error) {
        console.error('Failed to create prompt template:', error);
        message.error('Failed to create prompt template');
      } finally {
        setIsSaving(false);
      }
    }
  };

  // Handle reset to default
  const handleReset = () => {
    setSystemPrompt(DEFAULT_SYSTEM_PROMPT);
    setUserPrompt(DEFAULT_USER_PROMPT);
    setUserTemplateMode('generic');
    setLayers([]);
    setExtractorConfig('{}');
    setExtractorConfigError(null);
    message.info('Reset to default values');
  };

  if (isLoading) {
    return (
      <div className={styles.container}>
        <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <Title level={4} className={styles.title}>Prompt Manager</Title>
          <Text type="secondary" className={styles.subtitle}>
            Configure system prompt and user prompt templates (Markdown format)
          </Text>
        </div>
        <Space>
          <Button
            icon={<HistoryOutlined />}
            onClick={() => setVersionPanelOpen(true)}
            disabled={!activeTemplate}
          >
            History
          </Button>
          <Button onClick={handleReset}>
            Reset
          </Button>
          <Button
            type="primary"
            onClick={handleSave}
            loading={updateMutation.isPending || isSaving}
            icon={<SaveOutlined />}
          >
            Save
          </Button>
        </Space>
      </div>

      <Card className={styles.card}>
        {/* User Template Mode Configuration */}
        <div className={styles.configSection}>
          <Text strong>User Template Mode</Text>
          <Radio.Group
            value={userTemplateMode}
            onChange={(e) => setUserTemplateMode(e.target.value)}
            style={{ marginTop: 8, marginBottom: 8 }}
          >
            <Radio value="generic">Generic Mode (Standard OpenAI Format)</Radio>
            <Radio value="custom">Custom Mode (Use User Template)</Radio>
          </Radio.Group>
          <Text type="secondary" style={{ display: 'block', fontSize: 12 }}>
            {userTemplateMode === 'generic'
              ? 'Messages structure: [system, *history, user]'
              : 'Use custom user_template for message construction'}
          </Text>
        </div>

        <Divider />

        {/* System Prompt */}
        <PromptEditor
          label={
            <span>
              <FileTextOutlined className={styles.icon} />
              System Prompt
            </span>
          }
          desc="Define AI assistant's basic behavior and capabilities"
          value={systemPrompt}
          onChange={setSystemPrompt}
          rows={12}
        />

        <Divider />

        {/* User Prompt - Only shown in custom mode */}
        {userTemplateMode === 'custom' && (
          <>
            <PromptEditor
              label={
                <span>
                  <UserOutlined className={styles.icon} />
                  User Prompt
                </span>
              }
              desc="Define user message template format. Supported variables: {{query}}, {{history}}, {{skills}}"
              value={userPrompt}
              onChange={setUserPrompt}
              rows={8}
            />

            <Divider />
          </>
        )}

        {/* Extractor Configuration - Collapsible */}
        <Collapse
          items={[
            {
              key: 'extractor',
              label: 'Advanced: Extractor Configuration',
              children: (
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      Configure how to parse LLM responses (JSON format)
                    </Text>
                    <Button
                      size="small"
                      onClick={() => {
                        setExtractorConfig(JSON.stringify(DEFAULT_EXTRACTOR_CONFIG, null, 2));
                        validateExtractorConfig(JSON.stringify(DEFAULT_EXTRACTOR_CONFIG, null, 2));
                      }}
                    >
                      Reset to Default
                    </Button>
                  </div>
                  <TextArea
                    rows={10}
                    value={extractorConfig}
                    onChange={(e) => {
                      setExtractorConfig(e.target.value);
                      validateExtractorConfig(e.target.value);
                    }}
                    style={{ fontFamily: 'monospace' }}
                    placeholder="{}"
                  />
                  {extractorConfigError && (
                    <Text type="danger" style={{ display: 'block', marginTop: 4 }}>
                      {extractorConfigError}
                    </Text>
                  )}
                </div>
              ),
            },
          ]}
          style={{ marginTop: 16 }}
        />

        {/* Layer Configuration - Collapsible */}
        <Collapse
          items={[
            {
              key: 'layers',
              label: (
                <span>
                  Layers Configuration
                  {activeTemplate && (
                    <span style={{ marginLeft: 8, fontSize: 12, color: '#999' }}>
                      {userTemplateMode === 'custom'
                        ? '(Not available in Custom mode)'
                        : '(Manage prompt segments by target and strategy)'}
                    </span>
                  )}
                </span>
              ),
              children: userTemplateMode === 'custom' ? (
                <Text type="secondary" style={{ display: 'block', padding: '12px 0' }}>
                  Layers are only available in Generic mode. Switch to Generic mode
                  above to manage prompt layers.
                </Text>
              ) : (
                <PromptLayerEditor
                  layers={layers}
                  onChange={setLayers}
                />
              ),
            },
          ]}
          style={{ marginTop: 16 }}
        />
      </Card>

      {/* Version History Panel */}
      {activeTemplate && (
        <VersionHistoryPanel
          entityType="prompt_template"
          entityId={activeTemplate.id}
          open={versionPanelOpen}
          onClose={() => setVersionPanelOpen(false)}
          onVersionActivated={() => {
            queryClient.invalidateQueries({ queryKey: ['prompt-templates', currentTenantId] });
          }}
        />
      )}
    </div>
  );
};

export default PromptManager;
