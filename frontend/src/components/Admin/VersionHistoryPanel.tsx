import React, { useState } from 'react';
import {
  Drawer,
  Button,
  Input,
  Tag,
  message,
  Empty,
  Tooltip,
} from 'antd';
import {
  SaveOutlined,
  SwapOutlined,
  DeleteOutlined,
  RollbackOutlined,
  CloseOutlined,
  EditOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getVersions,
  createVersion,
  activateVersion,
  deleteVersion,
  updateVersion,
} from '@/api/version';
import type { EntityType, VersionSnapshot } from '@/types/version';
import VersionDiffView from './VersionDiffView';
import styles from './VersionHistoryPanel.module.css';

interface VersionHistoryPanelProps {
  entityType: EntityType;
  entityId: string;
  open: boolean;
  onClose: () => void;
  onVersionActivated: () => void;
}

const VersionHistoryPanel: React.FC<VersionHistoryPanelProps> = ({
  entityType,
  entityId,
  open,
  onClose,
  onVersionActivated,
}) => {
  const queryClient = useQueryClient();
  const [labelInput, setLabelInput] = useState('');
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [diffOpen, setDiffOpen] = useState(false);
  const [diffVersionA, setDiffVersionA] = useState('');
  const [diffVersionB, setDiffVersionB] = useState('');
  const [editingVersionId, setEditingVersionId] = useState<string | null>(null);
  const [editingLabel, setEditingLabel] = useState('');

  // Fetch versions
  const { data: versionsData, isLoading } = useQuery({
    queryKey: ['versions', entityType, entityId],
    queryFn: () => getVersions(entityType, entityId, 1, 50),
    enabled: open && !!entityId,
  });

  const versions = versionsData?.versions || [];

  // Create version mutation
  const createMutation = useMutation({
    mutationFn: () =>
      createVersion({
        entity_type: entityType,
        entity_id: entityId,
        label: labelInput,
      }),
    onSuccess: () => {
      message.success('Version snapshot created');
      setLabelInput('');
      queryClient.invalidateQueries({ queryKey: ['versions', entityType, entityId] });
    },
    onError: () => {
      message.error('Failed to create version');
    },
  });

  // Activate version mutation
  const activateMutation = useMutation({
    mutationFn: activateVersion,
    onSuccess: () => {
      message.success('Version activated');
      queryClient.invalidateQueries({ queryKey: ['versions', entityType, entityId] });
      onVersionActivated();
    },
    onError: () => {
      message.error('Failed to activate version');
    },
  });

  // Delete version mutation
  const deleteMutation = useMutation({
    mutationFn: deleteVersion,
    onSuccess: () => {
      message.success('Version deleted');
      queryClient.invalidateQueries({ queryKey: ['versions', entityType, entityId] });
      setSelectedIds(prev => prev.filter(id => !prev.includes(id)));
    },
    onError: (error: Error) => {
      message.error(error.message || 'Failed to delete version');
    },
  });

  // Update label mutation
  const updateLabelMutation = useMutation({
    mutationFn: ({ versionId, label }: { versionId: string; label: string }) =>
      updateVersion(versionId, { label }),
    onSuccess: () => {
      message.success('Label updated');
      queryClient.invalidateQueries({ queryKey: ['versions', entityType, entityId] });
      setEditingVersionId(null);
      setEditingLabel('');
    },
    onError: () => {
      message.error('Failed to update label');
    },
  });

  // Handle compare toggle
  const handleToggleCompare = (id: string) => {
    setSelectedIds(prev => {
      if (prev.includes(id)) {
        return prev.filter(i => i !== id);
      }
      if (prev.length >= 2) {
        return [prev[1], id];
      }
      return [...prev, id];
    });
  };

  // Handle remove single selected version
  const handleRemoveSelected = (id: string) => {
    setSelectedIds(prev => prev.filter(i => i !== id));
  };

  // Clear all selections
  const handleClearSelection = () => {
    setSelectedIds([]);
  };

  const handleCompare = () => {
    if (selectedIds.length !== 2) {
      message.warning('Please select exactly 2 versions to compare');
      return;
    }
    const a = versions.find(v => v.id === selectedIds[0]);
    const b = versions.find(v => v.id === selectedIds[1]);
    if (a && b) {
      if (a.version_number < b.version_number) {
        setDiffVersionA(a.id);
        setDiffVersionB(b.id);
      } else {
        setDiffVersionA(b.id);
        setDiffVersionB(a.id);
      }
      setDiffOpen(true);
    }
  };

  const handleActivate = (versionId: string) => {
    activateMutation.mutate(versionId);
  };

  const handleDelete = (version: VersionSnapshot) => {
    if (version.is_active) {
      message.warning('Cannot delete the currently active version');
      return;
    }
    deleteMutation.mutate(version.id);
  };

  const formatTime = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  const handleStartEdit = (version: VersionSnapshot) => {
    setEditingVersionId(version.id);
    setEditingLabel(version.label);
  };

  const handleSaveEdit = () => {
    if (editingVersionId) {
      updateLabelMutation.mutate({
        versionId: editingVersionId,
        label: editingLabel.trim(),
      });
    }
  };

  const handleCancelEdit = () => {
    setEditingVersionId(null);
    setEditingLabel('');
  };

  const handleEditKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSaveEdit();
    } else if (e.key === 'Escape') {
      handleCancelEdit();
    }
  };

  const getSelectionRank = (id: string): number => {
    const idx = selectedIds.indexOf(id);
    return idx >= 0 ? idx + 1 : 0;
  };

  const selectedVersions = selectedIds
    .map(id => versions.find(v => v.id === id))
    .filter((v): v is VersionSnapshot => !!v);

  return (
    <>
      <Drawer
        title="Version History"
        placement="right"
        width={400}
        open={open}
        onClose={onClose}
        mask={false}
        destroyOnClose
      >
        <div className={styles.container}>
          {/* Create version section */}
          <div className={styles.createSection}>
            <div className={styles.createRow}>
              <Input
                placeholder="Version label (optional)"
                value={labelInput}
                onChange={(e) => setLabelInput(e.target.value)}
                size="small"
                style={{ flex: 1 }}
              />
              <Button
                type="primary"
                size="small"
                icon={<SaveOutlined />}
                onClick={() => createMutation.mutate()}
                loading={createMutation.isPending}
              >
                Save
              </Button>
            </div>
          </div>

          {/* Version list */}
          <div className={styles.versionList}>
            {isLoading && <div style={{ textAlign: 'center', padding: 20 }}>Loading...</div>}
            {!isLoading && versions.length === 0 && (
              <Empty description="No versions yet" className={styles.emptyState} />
            )}
            {versions.map((v) => {
              const selectionRank = getSelectionRank(v.id);
              const isSelected = selectionRank > 0;
              return (
                <div
                  key={v.id}
                  className={`${styles.versionItem} ${isSelected ? styles.versionItemSelected : ''} ${v.is_active ? styles.versionItemActive : ''}`}
                >
                  {/* Compare toggle */}
                  <button
                    className={`${styles.compareToggle} ${isSelected ? styles.compareToggleSelected : ''}`}
                    onClick={() => handleToggleCompare(v.id)}
                    title={isSelected ? 'Remove from comparison' : 'Select for comparison'}
                    type="button"
                  >
                    {isSelected ? selectionRank : '○'}
                  </button>

                  <span className={`${styles.versionBadge} ${v.is_active ? styles.versionBadgeActive : ''}`}>
                    v{v.version_number}
                  </span>
                  <div className={styles.versionInfo}>
                    {editingVersionId === v.id ? (
                      <div className={styles.editLabelRow}>
                        <Input
                          size="small"
                          value={editingLabel}
                          onChange={(e) => setEditingLabel(e.target.value)}
                          onBlur={handleSaveEdit}
                          onKeyDown={handleEditKeyDown}
                          autoFocus
                          className={styles.editLabelInput}
                          maxLength={128}
                          placeholder="Enter label"
                        />
                        <Button
                          type="text"
                          size="small"
                          icon={<CloseOutlined />}
                          onClick={handleCancelEdit}
                          className={styles.editLabelCancel}
                        />
                      </div>
                    ) : (
                      <div className={styles.versionLabel} onClick={() => handleStartEdit(v)} title="Click to edit label">
                        <EditOutlined className={styles.editIcon} />
                        <span>{v.label || `Version ${v.version_number}`}</span>
                      </div>
                    )}
                    <div className={styles.versionMeta}>
                      <span>{formatTime(v.gmt_create)}</span>
                      {v.is_active && (
                        <Tag color="success" style={{ fontSize: 11, lineHeight: '16px', padding: '0 4px', margin: 0 }}>
                          Active
                        </Tag>
                      )}
                    </div>
                  </div>
                  <div className={styles.versionActions}>
                    {!v.is_active && (
                      <Tooltip title="Activate this version">
                        <Button
                          type="text"
                          size="small"
                          icon={<RollbackOutlined />}
                          onClick={() => handleActivate(v.id)}
                          loading={activateMutation.isPending}
                        />
                      </Tooltip>
                    )}
                    {!v.is_active && (
                      <Tooltip title="Delete">
                        <Button
                          type="text"
                          size="small"
                          danger
                          icon={<DeleteOutlined />}
                          onClick={() => handleDelete(v)}
                          loading={deleteMutation.isPending}
                        />
                      </Tooltip>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Compare bar */}
          {selectedIds.length > 0 && (
            <div className={styles.compareBar}>
              <div className={styles.compareInfo}>
                {selectedVersions.map((v, idx) => (
                  <span key={v.id} className={styles.compareChip}>
                    <span className={styles.compareChipRank}>{idx + 1}</span>
                    <span className={styles.compareChipLabel}>v{v.version_number}</span>
                    <button
                      className={styles.compareChipRemove}
                      onClick={() => handleRemoveSelected(v.id)}
                      type="button"
                      title={`Remove v${v.version_number}`}
                    >
                      <CloseOutlined style={{ fontSize: 10 }} />
                    </button>
                    {idx < selectedVersions.length - 1 && (
                      <span className={styles.compareArrow}>→</span>
                    )}
                  </span>
                ))}
              </div>
              <div className={styles.compareActions}>
                <Button size="small" type="link" onClick={handleClearSelection}>
                  Clear
                </Button>
                <Button
                  size="small"
                  type="primary"
                  icon={<SwapOutlined />}
                  disabled={selectedIds.length !== 2}
                  onClick={handleCompare}
                >
                  Compare
                </Button>
              </div>
            </div>
          )}
        </div>
      </Drawer>

      {/* Diff Modal */}
      <VersionDiffView
        versionIdA={diffVersionA}
        versionIdB={diffVersionB}
        open={diffOpen}
        onClose={() => setDiffOpen(false)}
      />
    </>
  );
};

export default VersionHistoryPanel;
