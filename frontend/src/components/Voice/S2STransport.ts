/**
 * Custom Transport for OpenAI Realtime API → RTVI protocol translation.
 *
 * Connects to our S2S backend and translates events to/from RTVI frames
 * so that PipecatClient and voice-ui-kit components can work natively.
 */

import {
  Transport,
  RTVIMessage,
  RTVI_PROTOCOL_VERSION,
  type PipecatClientOptions,
  type TransportConnectionParams,
  type TransportState,
  type Tracks,
  DeviceError,
} from '@pipecat-ai/client-js';

// ── OpenAI Realtime API event types ──────────────────────────────────────────

interface OpenAIServerEvent {
  type: string;
  event?: string;
  session_id?: string;
  transcript?: string;
  name?: string;
  arguments?: string | Record<string, unknown>;
  call_id?: string;
  tool_call_id?: string;
  content?: string;
  delta?: string;
  block_idx?: number;
  trigger_ts_ms?: number;
  elapsed_ms?: number;
  text?: string;
  thinking?: string;
  need_to_think?: boolean;
  tools?: Array<{
    name?: string;
    tool_name?: string;
    tool_call_id?: string;
    arguments?: Record<string, unknown>;
    status?: string;
    result?: unknown;
  }>;
  tool_name?: string;
  result?: unknown;
  status?: string;
  error?: unknown;
  asr_ms?: number;
  audio_ms?: number;
  tail_ms?: number;
  drained_chunks?: number;
  final_samples?: number;
}

// ── S2STransport ─────────────────────────────────────────────────────────────

export interface S2STransportOptions {
  wsUrl?: string;
}

export class S2STransport extends Transport {
  private _ws: WebSocket | null = null;
  private _wsUrl: string;
  private _micEnabled = true;
  private _camEnabled = false;
  private _screenShareEnabled = false;
  private _selectedMic: MediaDeviceInfo | Record<string, never> = {};
  private _selectedCam: MediaDeviceInfo | Record<string, never> = {};
  private _selectedSpeaker: MediaDeviceInfo | Record<string, never> = {};
  private _localAudioTrack: MediaStreamTrack | undefined;
  private _botAudioTrack: MediaStreamTrack | undefined;
  private _audioContext: AudioContext | null = null;
  private _mediaStreamDestination: MediaStreamAudioDestinationNode | null = null;
  private _processorNode: ScriptProcessorNode | null = null;
  private _mediaStream: MediaStream | null = null;
  private _botAudioCtx: AudioContext | null = null;
  private _botNextPlayTime = 0;
  private _botActiveSources: AudioBufferSourceNode[] = [];
  private _micAnalyser: AnalyserNode | null = null;
  private _botAnalyser: AnalyserNode | null = null;

  constructor(options?: S2STransportOptions) {
    super();
    this._state = 'disconnected' as TransportState;
    this._wsUrl = options?.wsUrl || `ws://localhost:8000/v1/realtime/audio`;
    // Ensure _callbacks is never undefined — PipecatClient sets it via initialize()
    // but some methods (e.g. disconnect during cleanup) may be called before that.
    if (!this._callbacks) {
      (this as Record<string, unknown>)._callbacks = {};
    }
  }

  // ── Transport abstract methods ──────────────────────────────────────────

  override initialize(
    options: PipecatClientOptions,
    messageHandler: (ev: RTVIMessage) => void
  ): void {
    this._options = options;
    this._onMessage = messageHandler;
    // PipecatClient passes callbacks via options.callbacks —
    // extract them into _callbacks so all callback calls work.
    this._callbacks = options.callbacks || {};
  }

  override async initDevices(): Promise<void> {
    try {
      // Must getUserMedia first to get permission, otherwise enumerateDevices
      // returns empty labels and voice-ui-kit can't find the mic.
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((t) => t.stop()); // release immediately

      const devices = await navigator.mediaDevices.enumerateDevices();
      const mics = devices.filter((d) => d.kind === 'audioinput');
      if (mics.length > 0) {
        this._selectedMic = mics[0];
      }
      this._callbacks?.onMicUpdated?.(mics[0]);
    } catch (e) {
      this._callbacks?.onDeviceError?.(
        new DeviceError([], 'unknown', String(e))
      );
    }
  }

  override _validateConnectionParams(
    connectParams?: TransportConnectionParams
  ): unknown {
    return connectParams || {};
  }

  override async _connect(
    _connectParams?: TransportConnectionParams
  ): Promise<void> {
    this._state = 'connecting' as TransportState;
    this._callbacks?.onTransportStateChanged?.('connecting');

    // Close any stale WebSocket from a previous connection
    if (this._ws) {
      try { this._ws.close(); } catch { /* ignore */ }
      this._ws = null;
    }

    return new Promise<void>((resolve, reject) => {
      let settled = false;
      let sessionReady = false;

      const ws = new WebSocket(this._wsUrl + (this._wsUrl.includes('?') ? '&' : '?') + 'force=true');

      // Timeout: if no session.created within 10s, fail
      const connectTimeout = setTimeout(() => {
        if (!settled) {
          fail('Connection timed out (no session.created within 10s)');
        }
      }, 10000);

      const fail = (reason: string) => {
        clearTimeout(connectTimeout);
        if (settled) return;
        settled = true;
        this._state = 'disconnected' as TransportState;
        this._callbacks?.onTransportStateChanged?.('disconnected');
        try { ws.close(); } catch { /* ignore */ }
        this._ws = null;
        reject(new Error(reason));
      };

      ws.onopen = () => {
        this._ws = ws;
        // Don't resolve yet — wait for session.created from the backend.
        // The backend may reject the connection (e.g. concurrent session limit)
        // AFTER onopen fires, so we must wait for the first message.
      };

      ws.onmessage = (event) => {
        try {
          const data: OpenAIServerEvent = JSON.parse(event.data);

          if (!sessionReady) {
            if (data.type === 'session.created') {
              sessionReady = true;
              // Now proceed with audio setup
              this._state = 'initialized' as TransportState;
              this._callbacks?.onTransportStateChanged?.('initialized');

              this._state = 'connected' as TransportState;
              this._callbacks?.onTransportStateChanged?.('connected');
              this._callbacks?.onConnected?.();

              this._startLocalAudio()
                .then(() => this._setupBotAudio())
                .then(() => {
                  if (this._onMessage) {
                    this._onMessage(
                      new RTVIMessage('bot-ready', {
                        version: RTVI_PROTOCOL_VERSION,
                      })
                    );
                  }
                  this._state = 'ready' as TransportState;
                  this._callbacks?.onTransportStateChanged?.('ready');

                  if (this._localAudioTrack) {
                    this._callbacks?.onTrackStarted?.(this._localAudioTrack);
                  }
                  if (this._botAudioTrack) {
                    this._callbacks?.onTrackStarted?.(this._botAudioTrack);
                  }

                  if (!settled) {
                    settled = true;
                    clearTimeout(connectTimeout);
                    resolve();
                  }
                })
                .catch((err) => {
                  console.warn('[S2STransport] Mic access failed, continuing without mic:', err);
                  this._setupBotAudio().then(() => {
                    if (this._onMessage) {
                      this._onMessage(
                        new RTVIMessage('bot-ready', {
                          version: RTVI_PROTOCOL_VERSION,
                        })
                      );
                    }
                    this._state = 'ready' as TransportState;
                    this._callbacks?.onTransportStateChanged?.('ready');
                    if (this._botAudioTrack) {
                      this._callbacks?.onTrackStarted?.(this._botAudioTrack);
                    }
                    if (!settled) {
                      settled = true;
                      clearTimeout(connectTimeout);
                      resolve();
                    }
                  });
                });
            } else if (data.type === 'error') {
              const msg = (data as Record<string, unknown>).error as Record<string, unknown> | undefined;
              fail(`Connection rejected: ${msg?.message || 'unknown error'}`);
              return;
            }
            return;
          }

          // Normal message handling after session is established
          this._handleOpenAIEvent(data);
        } catch {
          // ignore non-JSON
        }
      };

      ws.onclose = () => {
        if (!sessionReady && !settled) {
          // Connection closed before session was established
          fail('WebSocket closed before connection established');
          return;
        }
        if (this._state !== 'disconnected') {
          this._state = 'disconnected' as TransportState;
          this._callbacks?.onTransportStateChanged?.('disconnected');
          this._callbacks?.onDisconnected?.();
        }
        this._ws = null;
      };

      ws.onerror = () => {
        if (!settled) {
          fail('WebSocket connection failed');
        }
        this._state = 'disconnected' as TransportState;
      };
    });
  }

  override async _disconnect(): Promise<void> {
    this._state = 'disconnecting' as TransportState;
    this._callbacks?.onTransportStateChanged?.('disconnecting');
    this._stopLocalAudio();
    this._stopBotAudio();
    if (this._ws) {
      this._ws.close();
      this._ws = null;
    }
    this._state = 'disconnected' as TransportState;
    this._callbacks?.onTransportStateChanged?.('disconnected');
    this._callbacks?.onDisconnected?.();
  }

  override sendReadyMessage(): void {
    // Don't fire bot-ready here — wait until audio pipeline is fully
    // initialised so VoiceVisualizer has analysers when connect() resolves.
  }

  override sendMessage(message: RTVIMessage): void {
    if (!this._ws || this._ws.readyState !== WebSocket.OPEN) return;

    switch (message.type) {
      case 'llm-function-call-result': {
        const data = message.data as {
          function_name?: string;
          tool_call_id?: string;
          result?: unknown;
        };
        if (data?.tool_call_id) {
          this._ws.send(
            JSON.stringify({
              type: 'conversation.item.create',
              item: {
                type: 'function_call_output',
                call_id: data.tool_call_id,
                output: JSON.stringify(data.result),
              },
            })
          );
        }
        break;
      }
      case 'disconnect-bot': {
        this._disconnect();
        break;
      }
      default:
        break;
    }
  }

  // ── Device methods ──────────────────────────────────────────────────────

  override async getAllMics(): Promise<MediaDeviceInfo[]> {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((d) => d.kind === 'audioinput');
  }

  override async getAllCams(): Promise<MediaDeviceInfo[]> {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((d) => d.kind === 'videoinput');
  }

  override async getAllSpeakers(): Promise<MediaDeviceInfo[]> {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((d) => d.kind === 'audiooutput');
  }

  override updateMic(micId: string): void {
    this.getAllMics().then((mics) => {
      const mic = mics.find((m) => m.deviceId === micId);
      if (mic) {
        this._selectedMic = mic;
        this._callbacks?.onMicUpdated?.(mic);
        this._restartLocalAudio();
      }
    });
  }

  override updateCam(_camId: string): void {
    // No camera support
  }

  override updateSpeaker(_speakerId: string): void {
    // Not implemented
  }

  override enableMic(enable: boolean): void {
    this._micEnabled = enable;
    if (this._localAudioTrack) {
      this._localAudioTrack.enabled = enable;
    }
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('s2s-mic-enabled-change', {
        detail: { enabled: enable },
      }));
    }
  }

  override enableCam(_enable: boolean): void {
    this._camEnabled = false;
  }

  override enableScreenShare(_enable: boolean): void {
    this._screenShareEnabled = false;
  }

  // ── Getters ─────────────────────────────────────────────────────────────

  override get state(): TransportState {
    return this._state as TransportState;
  }
  override set state(val: TransportState) {
    this._state = val;
  }

  override get selectedMic() {
    return this._selectedMic;
  }
  override get selectedCam() {
    return this._selectedCam;
  }
  override get selectedSpeaker() {
    return this._selectedSpeaker;
  }
  override get isCamEnabled() {
    return this._camEnabled;
  }
  override get isMicEnabled() {
    return this._micEnabled;
  }
  override get isSharingScreen() {
    return this._screenShareEnabled;
  }

  override tracks(): Tracks {
    return {
      local: {
        audio: this._localAudioTrack,
        video: undefined,
        screenAudio: undefined,
        screenVideo: undefined,
      },
      bot: {
        audio: this._botAudioTrack,
        video: undefined,
      },
    };
  }

  getMicAnalyser(): AnalyserNode | null {
    return this._micAnalyser;
  }

  getBotAnalyser(): AnalyserNode | null {
    return this._botAnalyser;
  }

  // ── Audio handling ──────────────────────────────────────────────────────

  private async _startLocalAudio(): Promise<void> {
    const TARGET_SAMPLE_RATE = 16000;

    this._mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1 },
    });

    this._audioContext = new AudioContext();
    await this._audioContext.resume();
    const source = this._audioContext.createMediaStreamSource(this._mediaStream);
    const browserRate = this._audioContext.sampleRate;

    const bufferSize = 4096;
    this._processorNode = this._audioContext.createScriptProcessor(bufferSize, 1, 1);

    this._processorNode.onaudioprocess = (event) => {
      if (!this._micEnabled || !this._ws || this._ws.readyState !== WebSocket.OPEN) return;

      const inputData = event.inputBuffer.getChannelData(0);
      const downsampled = downsample(inputData, browserRate, TARGET_SAMPLE_RATE);
      const pcm16 = float32ToPcm16(downsampled);
      const base64Audio = arrayBufferToBase64(pcm16.buffer as ArrayBuffer);

      this._ws.send(
        JSON.stringify({
          type: 'input_audio_buffer.append',
          audio: base64Audio,
        })
      );
    };

    this._micAnalyser = this._audioContext.createAnalyser();
    this._micAnalyser.fftSize = 256;

    source.connect(this._micAnalyser);
    this._micAnalyser.connect(this._processorNode);
    this._processorNode.connect(this._audioContext.destination);

    this._localAudioTrack = this._mediaStream.getAudioTracks()[0] || undefined;
  }

  private _stopLocalAudio(): void {
    if (this._processorNode) {
      this._processorNode.disconnect();
      this._processorNode = null;
    }
    this._micAnalyser = null;
    if (this._audioContext) {
      this._audioContext.close();
      this._audioContext = null;
    }
    if (this._mediaStream) {
      this._mediaStream.getTracks().forEach((t) => t.stop());
      this._mediaStream = null;
    }
    this._localAudioTrack = undefined;
  }

  private async _restartLocalAudio(): Promise<void> {
    this._stopLocalAudio();
    await this._startLocalAudio();
    if (this._localAudioTrack) {
      this._callbacks?.onTrackStarted?.(this._localAudioTrack);
    }
  }

  private async _setupBotAudio(): Promise<void> {
    this._botAudioCtx = new AudioContext({ sampleRate: 16000 });
    await this._botAudioCtx.resume();
    this._botAnalyser = this._botAudioCtx.createAnalyser();
    this._botAnalyser.fftSize = 256;
    // Do NOT connect analyser to destination — BotAudioOutput handles playback
    // via the MediaStreamDestination track. Connecting both would play audio twice.
    this._mediaStreamDestination = this._botAudioCtx.createMediaStreamDestination();
    this._botAnalyser.connect(this._mediaStreamDestination);
    this._botAudioTrack = this._mediaStreamDestination.stream.getAudioTracks()[0];
    this._botNextPlayTime = 0;
    this._botActiveSources = [];
  }

  private _stopBotAudio(): void {
    for (const src of this._botActiveSources) {
      try { src.stop(); } catch { /* ignore */ }
    }
    this._botActiveSources = [];
    this._botAnalyser = null;
    if (this._botAudioCtx) {
      this._botAudioCtx.close();
      this._botAudioCtx = null;
    }
    this._botAudioTrack = undefined;
    this._mediaStreamDestination = null;
  }

  private _enqueueBotAudio(base64Pcm16: string): void {
    if (!this._botAudioCtx || !this._botAnalyser) return;

    const pcm16 = base64ToInt16Array(base64Pcm16);
    const float32 = int16ArrayToFloat32(pcm16);

    const audioBuffer = this._botAudioCtx.createBuffer(1, float32.length, 16000);
    audioBuffer.getChannelData(0).set(float32);

    const now = this._botAudioCtx.currentTime;
    if (this._botNextPlayTime < now) this._botNextPlayTime = now;

    const source = this._botAudioCtx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(this._botAnalyser!);
    source.start(this._botNextPlayTime);
    this._botNextPlayTime += audioBuffer.duration;

    if (this._botActiveSources.length === 0) {
      console.log(
        `[S2STransport] first audio chunk: ${float32.length} samples (${(audioBuffer.duration * 1000).toFixed(0)}ms)`
      );
    }

    this._botActiveSources.push(source);
    source.onended = () => {
      const idx = this._botActiveSources.indexOf(source);
      if (idx > -1) this._botActiveSources.splice(idx, 1);
    };
  }

  private _scheduleBotStoppedSpeaking(): void {
    if (!this._botAudioCtx || this._botActiveSources.length === 0) {
      // No audio playing — fire immediately
      this._onMessage?.(new RTVIMessage('bot-stopped-speaking', {}));
      return;
    }
    // Wait for the last scheduled source to finish playing
    const lastSource = this._botActiveSources[this._botActiveSources.length - 1];
    const originalOnended = lastSource.onended;
    lastSource.onended = () => {
      originalOnended?.call(lastSource, new Event('ended'));
      // Only fire if this is still the last response (not interrupted)
      if (this._botActiveSources.length === 0) {
        this._onMessage?.(new RTVIMessage('bot-stopped-speaking', {}));
      }
    };
  }

  private _interruptBotAudio(): void {
    const count = this._botActiveSources.length;
    for (const src of this._botActiveSources) {
      try { src.stop(); } catch { /* ignore */ }
    }
    this._botActiveSources = [];
    if (this._botAudioCtx) {
      this._botNextPlayTime = this._botAudioCtx.currentTime;
    }
    if (count > 0) {
      console.log(`[S2STransport] interrupt bot audio: stopped ${count} source(s)`);
      this._onMessage?.(new RTVIMessage('bot-stopped-speaking', {}));
      window.dispatchEvent(new CustomEvent('s2s-bot-audio-interrupted', {
        detail: { stoppedSources: count },
      }));
    }
  }

  // ── OpenAI → RTVI event translation ─────────────────────────────────────

  private _handleOpenAIEvent(event: OpenAIServerEvent): void {
    if (!this._onMessage) return;

    switch (event.type) {
      case 'session.created': {
        // Don't fire bot-ready yet — audio pipeline not initialised.
        // bot-ready is emitted after _startLocalAudio / _setupBotAudio complete.
        break;
      }

      case 'input_audio_buffer.speech_started': {
        this._interruptBotAudio();
        if (this._ws && this._ws.readyState === WebSocket.OPEN) {
          this._ws.send(JSON.stringify({ type: 'response.cancel' }));
        }
        this._onMessage(new RTVIMessage('user-started-speaking', {}));
        // Emit interim user-transcription with recording placeholder
        // The App component will update this with actual recording duration
        this._onMessage(
          new RTVIMessage('user-transcription', {
            text: 'Recording: 0.000s',
            final: false,
            timestamp: new Date().toISOString(),
            user_id: 'user',
          })
        );
        break;
      }

      case 'input_audio_buffer.speech_stopped': {
        this._onMessage(new RTVIMessage('user-stopped-speaking', {}));
        break;
      }

      case 'conversation.item.input_audio_transcription.completed': {
        this._onMessage(
          new RTVIMessage('user-transcription', {
            text: event.transcript || '',
            final: true,
            timestamp: new Date().toISOString(),
            user_id: 'user',
          })
        );
        break;
      }

      case 'response.output_audio_transcript.done': {
        this._onMessage(
          new RTVIMessage('bot-output', {
            text: event.transcript || '',
            spoken: true,
            aggregated_by: 'sentence',
          })
        );
        break;
      }

      case 'response.output_audio.delta': {
        if (event.delta) {
          if (this._botActiveSources.length === 0) {
            this._onMessage(new RTVIMessage('bot-started-speaking', {}));
            this._onMessage(new RTVIMessage('bot-tts-started', {}));
            window.dispatchEvent(new CustomEvent('s2s-bot-audio-start'));
          }
          this._enqueueBotAudio(event.delta);
        }
        break;
      }

      case 'response.output_audio.done': {
        this._onMessage(new RTVIMessage('bot-tts-stopped', {}));
        // bot-stopped-speaking fires when the last audio chunk finishes playing,
        // not when the backend finishes sending — so the user sees accurate timing.
        this._scheduleBotStoppedSpeaking();
        break;
      }

      case 'response.function_call_arguments.done': {
        let args: Record<string, unknown> = {};
        try {
          args = typeof event.arguments === 'string'
            ? JSON.parse(event.arguments || '{}')
            : event.arguments || {};
        } catch { /* ignore */ }
        this._onMessage(
          new RTVIMessage('llm-function-call-started', {
            function_name: event.name,
            tool_call_id: event.call_id || '',
            arguments: args,
          })
        );
        this._onMessage(
          new RTVIMessage('llm-function-call-in-progress', {
            function_name: event.name,
            tool_call_id: event.call_id || '',
            arguments: args,
          })
        );
        break;
      }

      case 'response.tool_result': {
        let result: unknown;
        try {
          result = JSON.parse(event.content || '{}');
        } catch {
          result = event.content || '';
        }
        this._onMessage(
          new RTVIMessage('llm-function-call-stopped', {
            function_name: event.name || '',
            tool_call_id: event.tool_call_id || event.call_id || '',
            cancelled: false,
            content: event.content || '',
            result,
            error: event.error,
          })
        );
        break;
      }

      case 'heartbeat_thinking': {
        window.dispatchEvent(new CustomEvent('s2s-heartbeat-thinking', {
          detail: event,
        }));
        break;
      }

      case 'asr_debug': {
        window.dispatchEvent(new CustomEvent('s2s-asr-debug', {
          detail: event,
        }));
        break;
      }

      default:
        break;
    }
  }
}

// ── Audio utility functions ──────────────────────────────────────────────────

function float32ToPcm16(float32Array: Float32Array): Int16Array {
  const pcm16 = new Int16Array(float32Array.length);
  for (let i = 0; i < float32Array.length; i++) {
    const s = Math.max(-1, Math.min(1, float32Array[i]));
    pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return pcm16;
}

function downsample(
  buffer: Float32Array,
  inputRate: number,
  outputRate: number
): Float32Array {
  if (inputRate === outputRate) return buffer;
  const ratio = inputRate / outputRate;
  const newLength = Math.round(buffer.length / ratio);
  const result = new Float32Array(newLength);
  for (let i = 0; i < newLength; i++) {
    const idx = i * ratio;
    const low = Math.floor(idx);
    const high = Math.min(low + 1, buffer.length - 1);
    const frac = idx - low;
    result[i] = buffer[low] * (1 - frac) + buffer[high] * frac;
  }
  return result;
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

function base64ToInt16Array(base64: string): Int16Array {
  const binaryStr = atob(base64);
  const bytes = new Uint8Array(binaryStr.length);
  for (let i = 0; i < binaryStr.length; i++) {
    bytes[i] = binaryStr.charCodeAt(i);
  }
  return new Int16Array(bytes.buffer);
}

function int16ArrayToFloat32(pcm16: Int16Array): Float32Array {
  const float32 = new Float32Array(pcm16.length);
  for (let i = 0; i < pcm16.length; i++) {
    float32[i] = pcm16[i] / 32768.0;
  }
  return float32;
}
