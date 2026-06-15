import React, { Component, ErrorInfo, ReactNode } from 'react';
import { Button, Result } from 'antd';
import styles from './ErrorBoundary.module.css';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * ErrorBoundary component that catches JavaScript errors in the child component tree and displays a fallback UI.
 * Must use a class component because Error Boundary is a React class component-specific feature.
 */
class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error('[ErrorBoundary] Uncaught error:', error);
    console.error('[ErrorBoundary] Component stack:', errorInfo.componentStack);
  }

  handleReload = (): void => {
    window.location.reload();
  };

  render(): ReactNode {
    const { hasError, error } = this.state;
    const { children } = this.props;

    if (hasError) {
      return (
        <div className={styles.container}>
          <Result
            status="error"
            title="页面加载失败"
            subTitle="抱歉，页面遇到了意外错误。请尝试重新加载。"
            extra={
              <Button type="primary" onClick={this.handleReload}>
                重新加载
              </Button>
            }
          >
            {process.env.NODE_ENV === 'development' && error && (
              <div className={styles.errorDetails}>
                <pre>{error.message}</pre>
              </div>
            )}
          </Result>
        </div>
      );
    }

    return children;
  }
}

export default ErrorBoundary;
