import React, { useEffect, useState, useCallback, useRef } from 'react';
import { Button, Typography } from 'antd';
import {
  CheckOutlined,
  CloseOutlined,
  ClockCircleOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import type { ToolConfirmRequest } from '../../types/hook';
import styles from './ToolConfirmModal.module.css';

const { Text, Paragraph } = Typography;

interface ToolConfirmInlineProps {
  confirmData: ToolConfirmRequest | null;
  onConfirm: (confirmationId: string, approved: boolean) => void;
  onTimeout: (confirmationId: string) => void;
}

const formatJsonSafe = (raw: string): string => {
  try {
    const parsed = JSON.parse(raw);
    return JSON.stringify(parsed, null, 2);
  } catch {
    return raw;
  }
};

const ToolConfirmInline: React.FC<ToolConfirmInlineProps> = ({
  confirmData,
  onConfirm,
  onTimeout,
}) => {
  const [countdown, setCountdown] = useState(confirmData?.timeout || 0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [hasResponded, setHasResponded] = useState(false);
  const hasRespondedRef = useRef(false);
  const timeoutTriggeredRef = useRef(false);
  const [visible, setVisible] = useState(false);

  // Entry animation
  useEffect(() => {
    if (confirmData) {
      // Small delay to ensure DOM is ready for animation
      requestAnimationFrame(() => {
        setVisible(true);
      });
    } else {
      setVisible(false);
    }
  }, [confirmData]);

  // Reset state when confirmData changes
  useEffect(() => {
    if (confirmData) {
      setCountdown(confirmData.timeout);
      setHasResponded(false);
      hasRespondedRef.current = false;
      timeoutTriggeredRef.current = false;
    }
  }, [confirmData]);

  // ── Countdown Timer ────────────────────────────────────────────
  useEffect(() => {
    if (!confirmData) return;

    const capturedOnTimeout = onTimeout;
    const capturedCid = confirmData.confirmation_id;

    if (timerRef.current) clearInterval(timerRef.current);

    timerRef.current = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          if (timerRef.current) {
            clearInterval(timerRef.current);
            timerRef.current = null;
          }
          if (!timeoutTriggeredRef.current) {
            timeoutTriggeredRef.current = true;
            queueMicrotask(() => {
              hasRespondedRef.current = true;
              setHasResponded(true);
              capturedOnTimeout(capturedCid);
            });
          }
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [confirmData?.confirmation_id]);

  // ── Handlers ───────────────────────────────────────────────────
  const respond = useCallback(
    (approved: boolean) => {
      if (!confirmData || hasRespondedRef.current) return;
      hasRespondedRef.current = true;
      setHasResponded(true);
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      onConfirm(confirmData.confirmation_id, approved);
    },
    [confirmData, onConfirm]
  );

  const handleApprove = useCallback(() => respond(true), [respond]);
  const handleDeny = useCallback(() => respond(false), [respond]);

  // ── Render ─────────────────────────────────────────────────────
  if (!confirmData) return null;

  const progress = confirmData.timeout > 0
    ? ((confirmData.timeout - countdown) / confirmData.timeout) * 100
    : 0;

  return (
    <div
      className={`${styles.container} ${visible ? styles.containerVisible : ''}`}
      role="alert"
      aria-live="polite"
    >
      {/* Top accent bar */}
      <div className={styles.accentBar} />

      <div className={styles.body}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerLeft}>
            <WarningOutlined className={styles.warningIcon} />
            <span className={styles.title}>工具执行确认</span>
          </div>
          <div className={styles.countdownBadge}>
            <ClockCircleOutlined className={styles.clockIcon} />
            <span className={styles.countdownText}>{countdown}s</span>
          </div>
        </div>

        {/* Tool name */}
        <div className={styles.toolNameRow}>
          <Text className={styles.toolLabel}>工具：</Text>
          <Text strong className={styles.toolValue}>{confirmData.tool_name}</Text>
        </div>

        {/* Arguments */}
        <div className={styles.argsSection}>
          <Paragraph className={styles.argsLabel} type="secondary">
            参数：
          </Paragraph>
          <pre className={styles.argsCode}>
            {formatJsonSafe(confirmData.arguments)}
          </pre>
        </div>

        {/* Progress bar */}
        <div className={styles.progressTrack}>
          <div
            className={styles.progressBar}
            style={{ width: `${Math.min(progress, 100)}%` }}
          />
        </div>

        {/* Actions */}
        <div className={styles.actions}>
          <Button
            danger
            icon={<CloseOutlined />}
            onClick={handleDeny}
            disabled={hasResponded}
            className={styles.denyBtn}
            size="large"
            block
          >
            {hasResponded ? '已拒绝' : '拒绝'}
          </Button>
          <Button
            type="primary"
            icon={<CheckOutlined />}
            onClick={handleApprove}
            disabled={hasResponded}
            className={styles.approveBtn}
            size="large"
            block
          >
            {hasResponded ? '已批准' : '批准'}
          </Button>
        </div>

        {/* Timeout hint */}
        {hasResponded && (
          <div className={styles.respondedHint}>
            {timeoutTriggeredRef.current
              ? '⏰ 确认超时，已自动拒绝'
              : '✅ 已响应，等待后端处理...'}
          </div>
        )}
      </div>
    </div>
  );
};

export default ToolConfirmInline;
