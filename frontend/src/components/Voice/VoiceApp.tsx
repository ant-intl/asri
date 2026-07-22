import '@/voice.css';
import { useState, useEffect, useCallback, useRef } from 'react';
import {
  RTVIEvent,
  type BotReadyData,
  type TranscriptData,
  type BotOutputData,
  type LLMFunctionCallStartedData,
  type LLMFunctionCallInProgressData,
  type LLMFunctionCallStoppedData,
  type PipecatMetricsData,
  RTVIMessage,
} from '@pipecat-ai/client-js';
import {
  usePipecatClient,
  useRTVIClientEvent,
  usePipecatClientTransportState,
} from '@pipecat-ai/client-react';
import {
  ConnectButton,
  Conversation,
  UserAudioControl,
  BotAudioControl,
} from '@pipecat-ai/voice-ui-kit';
import { S2STransport } from './S2STransport';
import { AutoOpenFunctionCall } from './AutoOpenFunctionCall';
import {
  type LogLevel,
  type LogEntry,
  type AsyncThinkerEventDetail,
  type AsyncToolCallBatchLogData,
  type AsrDebugEventDetail,
  type MainToolEventDetail,
  asyncToolCallItems,
  formatAsyncToolCallBatchMessage,
  formatToolResultForLog,
  formatMainToolLabel,
  formatMainToolResultForLog,
  truncateLogText,
  SystemLogPanel,
} from './SystemLogPanel';
import { Mic, PanelRightClose, PanelRightOpen } from 'lucide-react';

// ── Status Badge Component ──────────────────────────────────────────────────

function StatusBadge({ label, state }: { label: string; state: string }) {
  const getDotColor = () => {
    switch (state) {
      case 'ready':
      case 'connected':
        return 'bg-emerald-500';
      case 'connecting':
      case 'initialized':
      case 'authenticating':
        return 'bg-amber-500 animate-pulse';
      case 'error':
        return 'bg-red-500';
      default:
        return 'bg-gray-400';
    }
  };

  const getBorderColor = () => {
    switch (state) {
      case 'ready':
      case 'connected':
        return 'border-emerald-500/30';
      case 'connecting':
      case 'initialized':
      case 'authenticating':
        return 'border-amber-500/30';
      case 'error':
        return 'border-red-500/30';
      default:
        return 'border-gray-400/30';
    }
  };

  // Shorten long state names for consistent display
  const displayState = state === 'ready' ? 'READY' :
                      state === 'disconnected' ? 'OFFLINE' :
                      state === 'connecting' ? 'CONN...' :
                      state === 'connected' ? 'CONN' :
                      state === 'error' ? 'ERROR' :
                      state.toUpperCase();

  return (
    <div className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg border ${getBorderColor()} bg-white/50 dark:bg-black/20 w-[90px]`}>
      <span className={`w-2 h-2 rounded-full ${getDotColor()}`} />
      <div className="flex flex-col leading-none overflow-hidden">
        <span className="text-[10px] text-muted-foreground font-medium">{label}</span>
        <span className="text-[11px] font-semibold uppercase tracking-wide truncate">{displayState}</span>
      </div>
    </div>
  );
}

function ConnectionStatus() {
  const transportState = usePipecatClientTransportState();

  // Map transport state to client/agent states
  const clientState = transportState === 'ready' ? 'ready' :
                      transportState === 'connected' ? 'connected' :
                      transportState === 'connecting' || transportState === 'initialized' ? 'connecting' :
                      transportState === 'error' ? 'error' : 'disconnected';

  const agentState = transportState === 'ready' ? 'ready' :
                     transportState === 'connected' ? 'connecting' :
                     'disconnected';

  return (
    <div className="flex items-center gap-3">
      <StatusBadge label="Client" state={clientState} />
      <StatusBadge label="Agent" state={agentState} />
    </div>
  );
}

// ── Bottom volume bar ──────────────────────────────────────────────────────

function VolumeBar({
  analyser,
  color,
  label,
  active = true,
}: {
  analyser: AnalyserNode | null;
  color: string;
  label: string;
  active?: boolean;
}) {
  const barRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef(0);
  const levelRef = useRef(0);

  useEffect(() => {
    const data = analyser ? new Uint8Array(analyser.frequencyBinCount) : null;

    const tick = () => {
      let target = 0;
      if (analyser && data && active) {
        analyser.getByteFrequencyData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) sum += data[i];
        target = Math.min(sum / data.length / 128, 1);
      }

      const current = levelRef.current;
      const next = target >= current
        ? current + (target - current) * 0.55
        : current * 0.86;
      levelRef.current = next < 0.005 ? 0 : next;

      if (barRef.current) {
        barRef.current.style.width = `${levelRef.current * 100}%`;
      }
      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [analyser, active]);

  return (
    <div className="flex items-center gap-2 w-full">
      <span className="text-[10px] text-muted-foreground shrink-0 w-6">{label}</span>
      <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
        <div
          ref={barRef}
          className="h-full rounded-full transition-all duration-[80ms]"
          style={{ width: '1%', background: color }}
        />
      </div>
    </div>
  );
}

// ── Toast ──────────────────────────────────────────────────────────────────

function Toast({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 2000);
    return () => clearTimeout(t);
  }, [message, onDismiss]);

  return (
    <div className="fixed top-5 left-1/2 -translate-x-1/2 z-50 px-5 py-3 bg-red-600 text-white text-sm rounded-lg shadow-lg animate-in fade-in slide-in-from-top-2">
      {message}
    </div>
  );
}

// ── Voice App ───────────────────────────────────────────────────────────────

function VoiceApp() {
  const client = usePipecatClient();
  const [micAnalyser, setMicAnalyser] = useState<AnalyserNode | null>(null);
  const [botAnalyser, setBotAnalyser] = useState<AnalyserNode | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [autoScroll, setAutoScroll] = useState(true);
  const [micEnabledForBar, setMicEnabledForBar] = useState(true);
  const [showLogPanel, setShowLogPanel] = useState(true);
  const logIdRef = useRef(0);
  const recordingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const conversationRef = useRef<HTMLDivElement>(null);
  const recordingStartTimeRef = useRef<number | null>(null);

  const transportState = usePipecatClientTransportState();
  const isConnected = transportState === 'ready' || transportState === 'connected';

  // Find the "Recording: X.XXXs" DOM node inside Conversation and update its text
  const updateRecordingText = useCallback((durationMs: number) => {
    if (!conversationRef.current) return;
    const text = `Recording: ${(durationMs / 1000).toFixed(3)}s`;
    // Find the user message containing "Recording:" and update its text node
    const walker = document.createTreeWalker(
      conversationRef.current,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode: (node) => {
          if (node.textContent?.includes('Recording:')) return NodeFilter.FILTER_ACCEPT;
          return NodeFilter.FILTER_SKIP;
        },
      }
    );
    const node = walker.nextNode();
    if (node) {
      node.textContent = text;
    }
  }, []);

  // Add log helper
  const addLog = useCallback((level: LogLevel, message: string, data?: unknown) => {
    setLogs((prev) => [
      ...prev,
      {
        id: String(++logIdRef.current),
        timestamp: new Date(),
        level,
        message,
        data,
      },
    ]);
  }, []);

  const addOrMergeAsyncToolCallLog = useCallback((detail: AsyncThinkerEventDetail) => {
    const items = asyncToolCallItems(detail);
    if (items.length === 0) return;
    const blockIdx = detail.block_idx;

    setLogs((prev) => {
      const last = prev[prev.length - 1];
      const lastData = last?.data as AsyncToolCallBatchLogData | undefined;
      const canMerge =
        !!last &&
        last.level === 'TOOL' &&
        lastData?.event === 'tool_call_batch' &&
        lastData.block_idx === blockIdx &&
        blockIdx !== undefined;

      if (canMerge) {
        const toolCalls = [...lastData.tool_calls, ...items];
        return [
          ...prev.slice(0, -1),
          {
            ...last,
            message: formatAsyncToolCallBatchMessage(blockIdx, toolCalls),
            data: {
              ...lastData,
              tool_calls: toolCalls,
            },
          },
        ];
      }

      const batchData: AsyncToolCallBatchLogData = {
        event: 'tool_call_batch',
        block_idx: blockIdx,
        tool_calls: items,
      };
      return [
        ...prev,
        {
          id: String(++logIdRef.current),
          timestamp: new Date(),
          level: 'TOOL',
          message: formatAsyncToolCallBatchMessage(blockIdx, items),
          data: batchData,
        },
      ];
    });
  }, []);

  // Event listeners for logging

  const handleUserStartedSpeaking = useCallback(() => {
    recordingStartTimeRef.current = Date.now();
    // Start interval to update the "Recording: X.XXXs" text in the Conversation DOM
    recordingIntervalRef.current = setInterval(() => {
      if (recordingStartTimeRef.current) {
        updateRecordingText(Date.now() - recordingStartTimeRef.current);
      }
    }, 100);
    addLog('USER', 'Recording started...');
  }, [addLog, updateRecordingText]);

  const handleUserStoppedSpeaking = useCallback(() => {
    const duration = recordingStartTimeRef.current
      ? Date.now() - recordingStartTimeRef.current
      : 0;
    addLog('USER', `Recording: ${duration}ms`);
    recordingStartTimeRef.current = null;
    if (recordingIntervalRef.current) {
      clearInterval(recordingIntervalRef.current);
      recordingIntervalRef.current = null;
    }
  }, [addLog]);

  useRTVIClientEvent(RTVIEvent.UserStartedSpeaking, handleUserStartedSpeaking);
  useRTVIClientEvent(RTVIEvent.UserStoppedSpeaking, handleUserStoppedSpeaking);

  useRTVIClientEvent(RTVIEvent.BotStartedSpeaking, () => {
    addLog('AGENT', 'Started speaking');
  });

  useRTVIClientEvent(RTVIEvent.BotStoppedSpeaking, () => {
    addLog('AGENT', 'Stopped speaking');
  });

  useRTVIClientEvent(RTVIEvent.BotLlmStarted, () => {
    addLog('LLM', 'Generation started');
  });

  useRTVIClientEvent(RTVIEvent.BotLlmStopped, () => {
    addLog('LLM', 'Generation complete');
  });

  useRTVIClientEvent(RTVIEvent.BotTtsStarted, () => {
    addLog('TTS', 'Synthesis started');
  });

  useRTVIClientEvent(RTVIEvent.BotTtsStopped, () => {
    addLog('TTS', 'Synthesis complete');
  });

  useRTVIClientEvent(RTVIEvent.UserTranscript, (data: TranscriptData) => {
    if (data?.text && data.text !== 'Listening...' && !data.text.startsWith('Recording:')) {
      addLog('USER', `Transcript: "${data.text}"`, data);
    }
  });

  useRTVIClientEvent(RTVIEvent.BotOutput, (data: BotOutputData) => {
    if (data?.text) {
      addLog('AGENT', `Response: "${data.text}"`, data);
    }
  });

  useRTVIClientEvent(RTVIEvent.LLMFunctionCallStarted, (data: LLMFunctionCallStartedData) => {
    addLog('TOOL', formatMainToolLabel('Function call', data as MainToolEventDetail), data);
  });

  useRTVIClientEvent(RTVIEvent.LLMFunctionCallInProgress, (data: LLMFunctionCallInProgressData) => {
    addLog('TOOL', formatMainToolLabel('Executing', data as MainToolEventDetail), data);
  });

  useRTVIClientEvent(RTVIEvent.LLMFunctionCallStopped, (data: LLMFunctionCallStoppedData) => {
    const toolData = data as MainToolEventDetail;
    const toolName = toolData?.function_name || 'unknown';
    const resultPreview = formatMainToolResultForLog(toolData);
    addLog(
      'TOOL',
      resultPreview ? `Completed: ${toolName} -> ${resultPreview}` : `Completed: ${toolName}`,
      data
    );
  });

  useRTVIClientEvent(RTVIEvent.Connected, () => {
    addLog('INFO', 'WebSocket connected');
  });

  useRTVIClientEvent(RTVIEvent.Disconnected, () => {
    addLog('INFO', 'WebSocket disconnected');
  });

  useRTVIClientEvent(RTVIEvent.BotReady, (data: BotReadyData) => {
    const version = data?.version || 'unknown';
    addLog('INFO', `Session ready (RTVI ${version})`, data);
  });

  useRTVIClientEvent(RTVIEvent.Error, (message: RTVIMessage) => {
    const errorData = message.data as { message?: string; fatal?: boolean };
    addLog('ERROR', errorData?.message || 'Error occurred', message);
  });

  useRTVIClientEvent(RTVIEvent.Metrics, (data: PipecatMetricsData) => {
    if (data?.processing) {
      data.processing.forEach((m) => {
        addLog('DEBUG', `Metrics [${m.processor}]: ${m.value.toFixed(2)}ms`, m);
      });
    }
    if (data?.ttfb) {
      data.ttfb.forEach((m) => {
        addLog('DEBUG', `TTFB [${m.processor}]: ${m.value.toFixed(2)}ms`, m);
      });
    }
  });

  // Audio playback logging
  useEffect(() => {
    const onInterrupt = (e: Event) => {
      const d = (e as CustomEvent).detail;
      addLog('TTS', `Audio interrupted (${d.stoppedSources} stopped)`);
    };
    window.addEventListener('s2s-bot-audio-interrupted', onInterrupt);
    return () => {
      window.removeEventListener('s2s-bot-audio-interrupted', onInterrupt);
    };
  }, [addLog]);

  useEffect(() => {
    const onMicEnabledChange = (event: Event) => {
      const detail = (event as CustomEvent<{ enabled?: boolean }>).detail;
      setMicEnabledForBar(detail?.enabled !== false);
    };
    window.addEventListener('s2s-mic-enabled-change', onMicEnabledChange);
    return () => {
      window.removeEventListener('s2s-mic-enabled-change', onMicEnabledChange);
    };
  }, []);

  // Async thinker side-branch logging
  useEffect(() => {
    const onAsyncThinker = (event: Event) => {
      const detail = (event as CustomEvent<AsyncThinkerEventDetail>).detail;
      if (!detail) return;

      const block = detail.block_idx !== undefined ? ` block=${detail.block_idx}` : '';

      switch (detail.event) {
        case 'trigger':
          // The ASR debug event already shows the transcript and latency for
          // this block. Hide the trigger event to avoid duplicate ASR-looking
          // rows in the right-side log.
          break;
        case 'response':
          // Raw response events are usually noisy, but some HeartBeat paths
          // already emit the canonical action/thinking/tools shape here.
          if (detail.thinking || (Array.isArray(detail.tools) && detail.tools.length > 0)) {
            if (detail.thinking) {
              addLog(
                'THINK',
                `Thinking${block}: ${truncateLogText(detail.thinking)}`,
                detail
              );
            }
            addOrMergeAsyncToolCallLog(detail);
          }
          break;
        case 'thinking':
          addLog(
            'THINK',
            `Thinking${block}: ${truncateLogText(detail.thinking || '')}`,
            detail
          );
          addOrMergeAsyncToolCallLog(detail);
          break;
        case 'no_think':
          addLog('NOOP', `<no_need_to_think>${block}`, detail);
          break;
        case 'tool_call':
          addOrMergeAsyncToolCallLog(detail);
          break;
        case 'tool_result':
          addLog(
            'TOOL',
            `HeartBeat tool result${block}: ${detail.tool_name || 'unknown'} -> ${formatToolResultForLog(detail.result)}`,
            detail
          );
          break;
        default:
          addLog('DEBUG', `HeartBeat Thinking event: ${detail.event || 'unknown'}`, detail);
          break;
      }
    };

    window.addEventListener('s2s-heartbeat-thinking', onAsyncThinker);
    return () => {
      window.removeEventListener('s2s-heartbeat-thinking', onAsyncThinker);
    };
  }, [addLog, addOrMergeAsyncToolCallLog]);

  // Realtime ASR diagnostics from vadasr
  useEffect(() => {
    const onAsrDebug = (event: Event) => {
      const detail = (event as CustomEvent<AsrDebugEventDetail>).detail;
      if (!detail) return;

      const asr = detail.asr_ms !== undefined ? ` ${detail.asr_ms}ms` : '';
      const audio = detail.audio_ms !== undefined ? ` audio=${detail.audio_ms}ms` : '';
      const blockValue = detail.block_idx !== undefined ? detail.block_idx : 'unknown';
      const audioValue = detail.audio_ms !== undefined ? `${detail.audio_ms}ms` : 'unknown';
      const latencyValue = detail.asr_ms !== undefined ? `${detail.asr_ms}ms` : 'unknown';

      switch (detail.event) {
        case 'interim':
          addLog(
            'ASR',
            `Realtime ASR: audio=${audioValue} block=${blockValue} latency=${latencyValue}`,
            detail
          );
          addLog('ASR', `"${truncateLogText(detail.text || '')}"`, detail);
          break;
        case 'backlog_drained':
          addLog(
            'PERF',
            `ASR backlog drained before TURN_END chunks=${detail.drained_chunks ?? 0}${audio}`,
            detail
          );
          break;
        case 'final_start':
          addLog('PERF', `Final ASR started${audio}`, detail);
          break;
        case 'final_done':
          addLog(
            'PERF',
            `Final ASR done${asr}${audio}: "${truncateLogText(detail.text || '')}"`,
            detail
          );
          break;
        case 'final_reuse':
          addLog(
            'ASR',
            `Final transcript reused tail=${detail.tail_ms ?? 0}ms${audio}: "${truncateLogText(detail.text || '')}"`,
            detail
          );
          break;
        case 'final_empty':
          addLog('PERF', `Final ASR empty${audio}`, detail);
          break;
        default:
          addLog('DEBUG', `ASR debug event: ${detail.event || 'unknown'}`, detail);
          break;
      }
    };

    window.addEventListener('s2s-asr-debug', onAsrDebug);
    return () => {
      window.removeEventListener('s2s-asr-debug', onAsrDebug);
    };
  }, [addLog]);

  const handleConnect = useCallback(async () => {
    if (!client) return;
    try {
      addLog('INFO', 'Connecting...');
      await client.connect({});
      const t = client.transport as S2STransport;
      setMicAnalyser(t.getMicAnalyser());
      setBotAnalyser(t.getBotAnalyser());
      setMicEnabledForBar(t.isMicEnabled);
      addLog('INFO', 'Connected');
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error('Connect failed:', err);
      setError(`Connect failed: ${msg}`);
      addLog('ERROR', `Connect failed: ${msg}`);
    }
  }, [client, addLog]);

  const handleDisconnect = useCallback(async () => {
    if (!client) return;
    try {
      addLog('INFO', 'Disconnecting...');
      await client.disconnect();
      addLog('INFO', 'Disconnected');
    } catch (err) {
      console.error('Disconnect failed:', err);
    }
    setMicAnalyser(null);
    setBotAnalyser(null);
    setMicEnabledForBar(false);
  }, [client, addLog]);

  const clearLogs = useCallback(() => {
    setLogs([]);
    addLog('INFO', 'Logs cleared');
  }, [addLog]);

  return (
    <div className="flex gap-4 h-[calc(100vh-40px)] max-w-[1400px] w-full">
      {/* Main conversation area */}
      <div className="flex-1 flex flex-col bg-card rounded-xl shadow-long overflow-hidden border border-border">
        {error && <Toast message={error} onDismiss={() => setError(null)} />}

        {/* Header */}
        <div className="flex items-center justify-between px-5 h-14 border-b border-border">
          <ConnectionStatus />
          <div className="flex items-center gap-2">
            <BotAudioControl size="lg" />
            <UserAudioControl size="lg" noDevicePicker noVisualizer classNames={{ button: 'w-auto flex-none' }} />
            <ConnectButton
              size="lg"
              onConnect={handleConnect}
              onDisconnect={handleDisconnect}
            />
            <button
              onClick={() => setShowLogPanel(!showLogPanel)}
              className="h-11 w-11 flex items-center justify-center rounded-lg bg-muted/40 text-muted-foreground hover:bg-muted hover:text-foreground border border-border transition-colors"
              title={showLogPanel ? 'Hide log panel' : 'Show log panel'}
            >
              {showLogPanel ? <PanelRightClose size={20} /> : <PanelRightOpen size={20} />}
            </button>
          </div>
        </div>

        {/* Conversation */}
        <div className="flex-1 min-h-0 relative" ref={conversationRef}>
          <Conversation
            noTextInput
            textRenderMode="instant"
            assistantLabel="ASSISTANT"
            clientLabel="User"
            classNames={{
              container: 'px-6 no-scrollbar',
            }}
            functionCallRenderer={(fc) => (
              <AutoOpenFunctionCall
                key={`${fc.tool_call_id}-${fc.status}`}
                functionCall={fc}
              />
            )}
          />
          {!isConnected && (
            <div className="absolute inset-0 flex items-center justify-center bg-background/60 backdrop-blur-sm">
              <div className="text-center p-8">
                <div className="mx-auto mb-4 w-16 h-16 rounded-full bg-muted flex items-center justify-center ring-4 ring-muted/50">
                  <Mic size={28} className="text-muted-foreground" />
                </div>
                <h2 className="text-lg font-semibold text-foreground mb-1.5">Ready to Connect</h2>
                <p className="text-sm text-muted-foreground max-w-xs">
                  Click the Connect button above to start a voice conversation.
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Bottom volume bars */}
        <div className="shrink-0 flex flex-col gap-1.5 px-4 py-2 border-t border-border bg-muted/20">
          <VolumeBar
            analyser={botAnalyser}
            color="#6366f1"
            label="BOT"
          />
          <VolumeBar
            analyser={micAnalyser}
            color="#22c55e"
            label="MIC"
            active={micEnabledForBar}
          />
        </div>
      </div>

      {/* System Log Panel */}
      {showLogPanel && (
        <div className="w-[400px] lg:w-[440px] xl:w-[480px] shrink-0">
          <SystemLogPanel
            logs={logs}
            autoScroll={autoScroll}
            onToggleAutoScroll={() => setAutoScroll((v) => !v)}
            onClear={clearLogs}
          />
        </div>
      )}
    </div>
  );
}

export default VoiceApp;
