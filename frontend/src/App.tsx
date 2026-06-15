import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConfigProvider } from 'antd';
import { MainLayout } from '@/components/Layout';
import ChatPage from '@/pages/ChatPage';
import TracePage from '@/pages/TracePage';
import ErrorBoundary from '@/components/ErrorBoundary';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider
        theme={{
          token: {
            colorPrimary: '#1677ff',
            borderRadius: 6,
            colorBgLayout: '#f5f7fa',
          },
        }}
      >
        <BrowserRouter>
          <ErrorBoundary>
            <Routes>
              <Route path="/trace/:sessionId" element={<TracePage />} />
              <Route path="/*" element={
                <MainLayout>
                  <Routes>
                    <Route path="/" element={<Navigate to="/chat" replace />} />
                    <Route path="/chat" element={<ChatPage />} />
                    <Route path="/chat/:sessionId" element={<ChatPage />} />
                  </Routes>
                </MainLayout>
              } />
            </Routes>
          </ErrorBoundary>
        </BrowserRouter>
      </ConfigProvider>
    </QueryClientProvider>
  );
}

export default App;
