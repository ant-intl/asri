import { Fragment, useEffect, useRef } from 'react';
import { Trash2, Pause, Play } from 'lucide-react';

// ── Types ───────────────────────────────────────────────────────────────────

export type LogLevel = 'INFO' | 'USER' | 'AGENT' | 'TOOL' | 'DEBUG' | 'ERROR' | 'WARN' | 'LLM' | 'TTS' | 'THINK' | 'ASR' | 'NOOP' | 'PERF' | 'INTERRUPT';

export interface LogEntry {
  id: string;
  timestamp: Date;
  level: LogLevel;
  message: string;
  data?: unknown;
}

export interface AsyncThinkerEventDetail {
  event?: string;
  ts_ms?: number;
  block_idx?: number;
  trigger_ts_ms?: number;
  elapsed_ms?: number;
  text?: string;
  thinking?: string;
  need_to_think?: boolean;
  tools?: AsyncThinkerToolDetail[];
  tool_name?: string;
  tool_call_id?: string;
  arguments?: unknown;
  result?: unknown;
  status?: string;
}

export interface AsyncThinkerToolDetail {
  name?: string;
  tool_name?: string;
  tool_call_id?: string;
  arguments?: unknown;
  status?: string;
  result?: unknown;
}

export interface AsyncToolCallLogItem {
  tool_name?: string;
  tool_call_id?: string;
  arguments?: unknown;
  status?: string;
  result?: unknown;
}

export interface AsyncToolCallBatchLogData {
  event: 'tool_call_batch';
  block_idx?: number;
  tool_calls: AsyncToolCallLogItem[];
}

export interface AsrDebugEventDetail {
  event?: string;
  ts_ms?: number;
  block_idx?: number;
  asr_ms?: number;
  audio_ms?: number;
  tail_ms?: number;
  drained_chunks?: number;
  final_samples?: number;
  text?: string;
}

export interface MainToolEventDetail {
  function_name?: string;
  tool_call_id?: string;
  arguments?: unknown;
  args?: unknown;
  content?: unknown;
  result?: unknown;
  error?: unknown;
}

// ── Helper functions ────────────────────────────────────────────────────────

export function formatLogValue(value: unknown): string {
  if (value === undefined || value === null) return '';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export function truncateLogText(text: string, max = 120): string {
  return text.length > max ? `${text.slice(0, max)}...` : text;
}

function parseMaybeJson(value: unknown): unknown {
  if (typeof value !== 'string') return value;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function toolExecutionStateLabel(value: unknown): string | undefined {
  const parsed = parseMaybeJson(value);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return undefined;
  const state = (parsed as Record<string, unknown>).state;
  return typeof state === 'string' && state ? state : undefined;
}

function isEmptyObject(value: unknown): boolean {
  return (
    !!value &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    Object.keys(value as Record<string, unknown>).length === 0
  );
}

export function formatToolResultForLog(result: unknown): string {
  const state = toolExecutionStateLabel(result);
  const text = formatLogValue(result);
  const prefix = state ? `[${state}] ` : '';
  return `${prefix}${text}`;
}

export function formatMainToolArgsForLog(data: MainToolEventDetail | undefined): string {
  const args = data?.arguments !== undefined ? data.arguments : data?.args;
  return formatLogValue(args);
}

export function formatMainToolLabel(prefix: string, data: MainToolEventDetail | undefined): string {
  const toolName = data?.function_name || 'unknown';
  const argsPreview = formatMainToolArgsForLog(data);
  return argsPreview ? `${prefix}: ${toolName}(${argsPreview})` : `${prefix}: ${toolName}`;
}

export function formatMainToolResultForLog(data: MainToolEventDetail | undefined): string {
  const payload =
    data?.content !== undefined && data.content !== ''
      ? data.content
      : data?.result !== undefined && !isEmptyObject(data.result)
        ? data.result
        : data?.error;
  const state = toolExecutionStateLabel(payload);
  const prefix = state ? `[${state}] ` : '';
  return `${prefix}${formatLogValue(payload)}`;
}

export function formatAsyncToolCallItem(item: AsyncToolCallLogItem): string {
  const status = item.status ? `[${item.status}] ` : '';
  return `${status}${item.tool_name || 'unknown'}(${formatLogValue(item.arguments)})`;
}

export function formatAsyncToolCallBatchMessage(blockIdx: number | undefined, toolCalls: AsyncToolCallLogItem[]): string {
  const block = blockIdx !== undefined ? ` block=${blockIdx}` : '';
  if (toolCalls.length <= 1) {
    return `Async tool call${block}: ${formatAsyncToolCallItem(toolCalls[0] || {})}`;
  }
  const lines = toolCalls.map((item, index) => `${index + 1}. ${formatAsyncToolCallItem(item)}`);
  return `Async tool calls${block} (${toolCalls.length} concurrent):\n${lines.join('\n')}`;
}

export function logBlockIndex(log: LogEntry): number | undefined {
  const data = log.data as { block_idx?: unknown } | undefined;
  return typeof data?.block_idx === 'number' ? data.block_idx : undefined;
}

export function asyncToolCallItems(detail: AsyncThinkerEventDetail): AsyncToolCallLogItem[] {
  if (Array.isArray(detail.tools) && detail.tools.length > 0) {
    return detail.tools.map((tool) => ({
      tool_name: tool.name || tool.tool_name,
      tool_call_id: tool.tool_call_id,
      arguments: tool.arguments,
      status: tool.status,
      result: tool.result,
    }));
  }
  if (!detail.tool_name && detail.arguments === undefined) return [];
  return [{
    tool_name: detail.tool_name,
    tool_call_id: detail.tool_call_id,
    arguments: detail.arguments,
    status: detail.status,
    result: detail.result,
  }];
}

// ── System Log Panel ─────────────────────────────────────────────────────────

export function SystemLogPanel({
  logs,
  autoScroll,
  onToggleAutoScroll,
  onClear,
}: {
  logs: LogEntry[];
  autoScroll: boolean;
  onToggleAutoScroll: () => void;
  onClear: () => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, autoScroll]);

  const levelStyles: Record<LogLevel, string> = {
    INFO: 'bg-blue-100 text-blue-700 border-blue-200',
    USER: 'bg-purple-100 text-purple-700 border-purple-200',
    AGENT: 'bg-emerald-100 text-emerald-700 border-emerald-200',
    TOOL: 'bg-amber-100 text-amber-700 border-amber-200',
    DEBUG: 'bg-gray-100 text-gray-600 border-gray-200',
    ERROR: 'bg-red-100 text-red-700 border-red-200',
    WARN: 'bg-orange-100 text-orange-700 border-orange-200',
    LLM: 'bg-cyan-100 text-cyan-700 border-cyan-200',
    TTS: 'bg-pink-100 text-pink-700 border-pink-200',
    THINK: 'bg-violet-100 text-violet-700 border-violet-200',
    ASR: 'bg-sky-100 text-sky-700 border-sky-200',
    NOOP: 'bg-slate-100 text-slate-600 border-slate-200',
    PERF: 'bg-teal-100 text-teal-700 border-teal-200',
    INTERRUPT: 'bg-red-100 text-red-700 border-red-200',
  };

  const levelLabels: Record<LogLevel, string> = {
    INFO: 'INFO',
    USER: 'USER',
    AGENT: 'AGENT',
    TOOL: 'TOOL',
    DEBUG: 'DEBUG',
    ERROR: 'ERROR',
    WARN: 'WARN',
    LLM: 'LLM',
    TTS: 'TTS',
    THINK: 'THINK',
    ASR: 'ASR',
    NOOP: 'NOOP',
    PERF: 'PERF',
    INTERRUPT: 'INT',
  };

  const messageStyles: Partial<Record<LogLevel, string>> = {
    THINK: 'italic text-violet-700',
    ASR: 'text-sky-800',
    NOOP: 'text-slate-500',
    PERF: 'text-teal-700',
  };

  const rowStyles: Partial<Record<LogLevel, string>> = {
    THINK: 'bg-violet-50/60',
    ASR: 'bg-sky-50/60',
    NOOP: 'bg-slate-50/80',
    TOOL: 'bg-amber-50/60',
    PERF: 'bg-teal-50/60',
  };

  return (
    <div className="w-full h-full flex flex-col bg-card rounded-xl shadow-long border border-border overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-5 h-14 border-b border-border bg-muted/30">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">System Log</span>
          <span className="flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-emerald-100 text-emerald-700 text-[10px] font-medium">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            Live
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={onToggleAutoScroll}
            className={`p-1.5 rounded transition-colors ${autoScroll ? 'text-emerald-600 bg-emerald-50' : 'text-muted-foreground hover:bg-muted'}`}
            title={autoScroll ? 'Auto-scroll on' : 'Auto-scroll paused'}
          >
            {autoScroll ? <Play size={14} /> : <Pause size={14} />}
          </button>
          <button
            onClick={onClear}
            className="p-1.5 rounded text-muted-foreground hover:bg-muted hover:text-destructive transition-colors"
            title="Clear logs"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {/* Log list */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-2 space-y-1.5 text-xs no-scrollbar"
        style={{ maxHeight: 'calc(100vh - 120px)' }}
      >
        {logs.length === 0 && (
          <div className="flex flex-col items-center justify-center text-muted-foreground/40 py-12 gap-3">
            <div className="flex gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-current animate-bounce" style={{ animationDelay: '0ms' }} />
              <span className="w-1.5 h-1.5 rounded-full bg-current animate-bounce" style={{ animationDelay: '150ms' }} />
              <span className="w-1.5 h-1.5 rounded-full bg-current animate-bounce" style={{ animationDelay: '300ms' }} />
            </div>
            <span className="text-xs">Waiting for logs...</span>
          </div>
        )}
        {logs.map((log, index) => {
          const blockIdx = logBlockIndex(log);
          const previousBlockIdx = index > 0 ? logBlockIndex(logs[index - 1]) : undefined;
          const showBlockSeparator = blockIdx !== undefined && blockIdx !== previousBlockIdx;

          return (
            <Fragment key={log.id}>
              {showBlockSeparator && (
                <div className="flex items-center gap-2 pl-[56px] pr-1 py-1 text-[10px] font-mono text-muted-foreground/70">
                  <span className="h-px flex-1 bg-border" />
                  <span>--- async block {blockIdx} ---</span>
                  <span className="h-px flex-1 bg-border" />
                </div>
              )}
              <div className={`flex gap-1.5 items-start rounded-md px-1 py-0.5 ${rowStyles[log.level] || ''}`}>
                <span className="shrink-0 text-[10px] text-muted-foreground font-mono pt-0.5 w-[48px] text-right">
                  {log.timestamp.toLocaleTimeString('zh-CN', {
                    hour12: false,
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                  })}
                </span>
                <span
                  className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium w-[46px] text-center border flex items-center justify-center ${levelStyles[log.level]}`}
                >
                  {levelLabels[log.level]}
                </span>
                <span className={`flex-1 whitespace-pre-wrap break-all leading-relaxed ${messageStyles[log.level] || ''}`}>
                  {log.message}
                </span>
              </div>
            </Fragment>
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
