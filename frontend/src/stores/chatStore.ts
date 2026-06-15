import { create } from 'zustand';
import type { Message, AgentType } from '@/types/chat';
import type { Session } from '@/types/session';

// Default session config
const defaultConfig = {
  agentType: 'react' as AgentType,
  sessionToken: '',
};



interface ChatStore {
  // Current session
  currentSession: Session | null;
  setCurrentSession: (session: Session | null) => void;

  // Messages
  messages: Message[];
  setMessages: (messages: Message[]) => void;
  addMessage: (message: Message) => void;
  clearMessages: () => void;

  // Input
  inputValue: string;
  setInputValue: (value: string) => void;

  // Streaming state
  isStreaming: boolean;
  setIsStreaming: (streaming: boolean) => void;
  streamingContent: string;
  setStreamingContent: (content: string) => void;
  appendStreamingContent: (content: string) => void;
  clearStreamingContent: () => void;

  // Interrupt state
  pendingInterruptMessage: string | null;
  setPendingInterruptMessage: (message: string | null) => void;
  abortController: { abort: () => void } | null;
  setAbortController: (controller: { abort: () => void } | null) => void;

  // Polling state (for HTTP Long Polling)
  currentPollingMessageId: string | null;
  setCurrentPollingMessageId: (messageId: string | null) => void;
  isPolling: boolean;
  setIsPolling: (polling: boolean) => void;

  // Session config (for creating new sessions)
  agentType: AgentType;
  setAgentType: (type: AgentType) => void;
  sessionToken: string;
  setSessionToken: (token: string) => void;
  sessionMetadata: Record<string, unknown>;
  setSessionMetadata: (metadata: Record<string, unknown>) => void;

  // UI state
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (collapsed: boolean) => void;

  // Show thinking/trace in chat
  showThinking: boolean;
  setShowThinking: (show: boolean) => void;

  // Admin tab
  activeTab: 'chat' | 'agent-settings' | 'tools' | 'models' | 'skills' | 'mcp' | 'prompt' | 'advanced' | 'mcp-mock' | 'user-simulator' | 'version-manager' | 'chat-compare' | 'setting' | 'cache-monitor';
  setActiveTab: (tab: 'chat' | 'agent-settings' | 'tools' | 'models' | 'skills' | 'mcp' | 'prompt' | 'advanced' | 'mcp-mock' | 'user-simulator' | 'version-manager' | 'chat-compare' | 'setting' | 'cache-monitor') => void;
}

export const useChatStore = create<ChatStore>((set) => ({
  // Current session
  currentSession: null,
  setCurrentSession: (session) => set({ currentSession: session }),

  // Messages
  messages: [],
  setMessages: (messages) => set({ messages }),
  addMessage: (message) =>
    set((state) => ({ messages: [...state.messages, message] })),
  clearMessages: () => set({ messages: [] }),

  // Input
  inputValue: '',
  setInputValue: (value) => set({ inputValue: value }),

  // Streaming state
  isStreaming: false,
  setIsStreaming: (streaming) => set({ isStreaming: streaming }),
  streamingContent: '',
  setStreamingContent: (content) => set({ streamingContent: content }),
  appendStreamingContent: (content) =>
    set((state) => ({ streamingContent: state.streamingContent + content })),
  clearStreamingContent: () => set({ streamingContent: '' }),

  // Interrupt state
  pendingInterruptMessage: null,
  setPendingInterruptMessage: (message) => set({ pendingInterruptMessage: message }),
  abortController: null,
  setAbortController: (controller) => set({ abortController: controller }),

  // Polling state (for HTTP Long Polling)
  currentPollingMessageId: null,
  setCurrentPollingMessageId: (messageId) => set({ currentPollingMessageId: messageId }),
  isPolling: false,
  setIsPolling: (polling) => set({ isPolling: polling }),

  // Session config helpers
  // Session config (for creating new sessions)
  agentType: defaultConfig.agentType,
  setAgentType: (type) => set({ agentType: type }),
  sessionToken: defaultConfig.sessionToken,
  setSessionToken: (token) => set({ sessionToken: token }),
  sessionMetadata: {},
  setSessionMetadata: (metadata) => set({ sessionMetadata: metadata }),

  // UI state
  sidebarCollapsed: false,
  setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),

  // Show thinking/trace in chat
  showThinking: true,
  setShowThinking: (show) => set({ showThinking: show }),

  // Admin tab
  activeTab: 'chat',
  setActiveTab: (tab) => set({ activeTab: tab }),
}));
