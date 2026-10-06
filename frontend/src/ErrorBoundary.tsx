import { Component, type ReactNode } from 'react';import { Button, Result } from 'antd';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * 顶层错误边界。
 *
 * 为什么需要：全仓此前没有错误边界，任何一个渲染期 TypeError 都会让 React 卸载整棵树
 * → 白屏，且只能手动刷新。典型触发是后端新增/改名了一个枚举值，前端却按下标取值
 * （例如 KnowledgeDetail 的 `STATUS_TAG[d.status].color`）。这里兜住并给一条恢复路径。
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  // 不实现 componentDidCatch：前端没有上报通道，React 默认会把 error + 组件栈打到 console
  // （项目约定不留 console.log，这里也不额外打）。

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <Result
        status="error"
        title="页面渲染出错"
        subTitle={error.message || '未知错误'}
        extra={
          <Button type="primary" onClick={() => this.setState({ error: null })}>
            重试
          </Button>
        }
      />
    );
  }
}
