import React from 'react';
import { Modal, Spin, Tag } from 'antd';
import { ArrowRightOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { getVersionDiff } from '@/api/version';
import type { DiffLine, FieldDiff } from '@/types/version';
import styles from './VersionDiffView.module.css';

interface VersionDiffViewProps {
  versionIdA: string;
  versionIdB: string;
  open: boolean;
  onClose: () => void;
}

// Field display name mapping
const FIELD_LABELS: Record<string, string> = {
  name: 'Name',
  description: 'Description',
  system_template: 'System Prompt',
  user_template: 'User Prompt',
  user_template_mode: 'User Template Mode',
  extractor_config: 'Extractor Config',
  content: 'Content',
  is_active: 'Active',
  metadata: 'Metadata',
};

const getFieldLabel = (fieldName: string): string => {
  return FIELD_LABELS[fieldName] || fieldName;
};

// Render a single diff line
const DiffLineRow: React.FC<{ line: DiffLine }> = ({ line }) => {
  const lineClass =
    line.type === 'added'
      ? styles.lineAdded
      : line.type === 'removed'
        ? styles.lineRemoved
        : styles.lineUnchanged;

  return (
    <div className={`${styles.diffLine} ${lineClass}`}>
      <span className={styles.lineNumber}>
        {line.type === 'added' ? (line.line_b ?? '') : (line.line_a ?? '')}
      </span>
      <span className={styles.lineContent}>{line.content}</span>
    </div>
  );
};

// Render a field diff section
const FieldDiffSection: React.FC<{
  fieldName: string;
  fieldDiff: FieldDiff;
}> = ({ fieldName, fieldDiff }) => {
  const hasChanges = fieldDiff.lines.some((l) => l.type !== 'unchanged');

  // Separate lines for left (removed/unchanged) and right (added/unchanged)
  const leftLines = fieldDiff.lines.filter((l) => l.type === 'removed' || l.type === 'unchanged');
  const rightLines = fieldDiff.lines.filter((l) => l.type === 'added' || l.type === 'unchanged');

  return (
    <div className={styles.fieldSection}>
      <div className={styles.fieldHeader}>
        {getFieldLabel(fieldName)}
        <Tag className={styles.fieldTag} color={fieldDiff.type === 'json' ? 'blue' : 'default'}>
          {fieldDiff.type === 'json' ? 'JSON' : 'Text'}
        </Tag>
        {hasChanges && (
          <Tag className={styles.fieldTag} color="orange">
            Changed
          </Tag>
        )}
      </div>
      {!hasChanges ? (
        <div className={styles.noChanges}>No changes</div>
      ) : (
        <div className={styles.diffContainer}>
          <div className={`${styles.diffPanel} ${styles.diffPanelLeft}`}>
            <div className={styles.diffPanelTitle}>Before</div>
            <div className={styles.diffContent}>
              {leftLines.map((line, idx) => (
                <DiffLineRow key={`left-${idx}`} line={line} />
              ))}
            </div>
          </div>
          <div className={styles.diffPanel}>
            <div className={styles.diffPanelTitle}>After</div>
            <div className={styles.diffContent}>
              {rightLines.map((line, idx) => (
                <DiffLineRow key={`right-${idx}`} line={line} />
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const VersionDiffView: React.FC<VersionDiffViewProps> = ({
  versionIdA,
  versionIdB,
  open,
  onClose,
}) => {
  const { data: diffData, isLoading } = useQuery({
    queryKey: ['version-diff', versionIdA, versionIdB],
    queryFn: () => getVersionDiff(versionIdA, versionIdB),
    enabled: open && !!versionIdA && !!versionIdB,
  });

  return (
    <Modal
      title="Version Comparison"
      open={open}
      onCancel={onClose}
      footer={null}
      width="90vw"
      style={{ top: 20 }}
      destroyOnClose
    >
      {isLoading && (
        <div className={styles.loading}>
          <Spin size="large" />
        </div>
      )}

      {diffData && (
        <>
          {/* Header showing version info */}
          <div className={styles.header}>
            <span className={styles.headerLabel}>
              v{diffData.version_a.version_number}
              {diffData.version_a.label ? ` (${diffData.version_a.label})` : ''}
            </span>
            <ArrowRightOutlined className={styles.headerArrow} />
            <span className={styles.headerLabel}>
              v{diffData.version_b.version_number}
              {diffData.version_b.label ? ` (${diffData.version_b.label})` : ''}
            </span>
          </div>

          {/* Field-by-field diff */}
          {Object.entries(diffData.fields).map(([fieldName, fieldDiff]) => (
            <FieldDiffSection
              key={fieldName}
              fieldName={fieldName}
              fieldDiff={fieldDiff}
            />
          ))}
        </>
      )}
    </Modal>
  );
};

export default VersionDiffView;
