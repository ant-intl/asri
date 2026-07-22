import { useEffect, useState } from 'react';
import { PipecatClient } from '@pipecat-ai/client-js';
import { PipecatClientProvider } from '@pipecat-ai/client-react';
import { ThemeProvider, BotAudioOutput } from '@pipecat-ai/voice-ui-kit';
import { S2STransport } from '@/components/Voice/S2STransport';
import VoiceApp from '@/components/Voice/VoiceApp';

export default function VoicePage() {
  const [client, setClient] = useState<PipecatClient | null>(null);

  useEffect(() => {
    // WebSocket URL: always same origin (Django serves both HTTP and WS)
    // 1. VITE_VOICE_WS_URL env var (explicit override)
    // 2. Same host:port — Django Channels handles /v1/realtime/audio
    const voiceWsUrl = import.meta.env.VITE_VOICE_WS_URL
      || `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/v1/realtime/audio`;

    const transport = new S2STransport({
      wsUrl: voiceWsUrl,
    });
    const pcClient = new PipecatClient({
      transport,
      enableMic: true,
      enableCam: false,
    });
    setClient(pcClient);

    return () => {
      pcClient.disconnect();
      setClient(null);
    };
  }, []);

  if (!client) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground gap-3">
        <div className="flex gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-current animate-bounce" style={{ animationDelay: '0ms' }} />
          <span className="w-1.5 h-1.5 rounded-full bg-current animate-bounce" style={{ animationDelay: '150ms' }} />
          <span className="w-1.5 h-1.5 rounded-full bg-current animate-bounce" style={{ animationDelay: '300ms' }} />
        </div>
        <span className="text-sm">Initializing voice agent...</span>
      </div>
    );
  }

  return (
    <ThemeProvider defaultTheme="light" disableStorage>
      <PipecatClientProvider client={client}>
        <BotAudioOutput />
        <div className="flex items-center justify-center h-full p-5 bg-gradient-to-br from-slate-50 via-background to-slate-100">
          <VoiceApp />
        </div>
      </PipecatClientProvider>
    </ThemeProvider>
  );
}
