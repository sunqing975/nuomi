/**
 * ErrorState：统一错误态（图标 + 文案 + 可重试）。
 *
 * 管理页加载失败时的标准呈现：失败不能只靠 message.error 一闪而过，
 * 页面主体要给一个可恢复的出口（重试按钮）。
 */

import { Button, Result } from 'antd';
import type { ReactNode } from 'react';

export interface ErrorStateProps {
  title?: ReactNode;
  description?: ReactNode;
  /** 提供后显示「重试」按钮 */
  onRetry?: () => void;
  retryText?: string;
}

export default function ErrorState({
  title = '加载失败',
  description,
  onRetry,
  retryText = '重试',
}: ErrorStateProps) {
  return (
    <Result
      status="error"
      title={title}
      subTitle={description}
      extra={
        onRetry ? (
          <Button type="primary" onClick={onRetry}>
            {retryText}
          </Button>
        ) : undefined
      }
    />
  );
}
