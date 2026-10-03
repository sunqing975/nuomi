import { useCallback, useEffect, useState } from 'react';
import { Card, Table, Tag, Typography, Empty } from 'antd';
import { get, type McpServer } from '../api';

export default function McpPage() {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setServers(await get<McpServer[]>('/mcp'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const columns = [
    { title: '服务器', dataIndex: 'name', render: (n: string) => <b>{n}</b> },
    { title: '传输', dataIndex: 'transport', width: 90, render: (t: string) => <Tag color="blue">{t}</Tag> },
    { title: '命令', dataIndex: 'command', render: (c: string) => <span style={{ color: '#6b7280' }}>{c || '—'}</span> },
    { title: '参数', dataIndex: 'args', render: (a: string[]) => <span style={{ color: '#6b7280' }}>{(a || []).join(' ')}</span> },
  ];

  return (
    <>
      {servers.length === 0 && !loading ? (
        <Card><Empty description="还没有配置 MCP 服务器" /></Card>
      ) : (
        <Table<McpServer>
          rowKey="name"
          columns={columns}
          dataSource={servers}
          loading={loading}
          pagination={false}
        />
      )}
      <Card style={{ marginTop: 16 }} size="small">
        <Typography.Text strong>如何接入 MCP</Typography.Text>
        <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0, fontSize: 13, lineHeight: 1.8 }}>
          在仓库根 <Typography.Text code>.env</Typography.Text> 配置{' '}
          <Typography.Text code>NUOMI_MCP_SERVERS</Typography.Text>（JSON，langchain-mcp-adapters 格式），然后重启后端。示例：
          <br />
          <Typography.Text code style={{ fontSize: 12 }}>
            NUOMI_MCP_SERVERS={JSON.stringify({
              pet_mood: { transport: 'stdio', command: 'python', args: ['examples/pet_mood_server.py'] },
            })}
          </Typography.Text>
          <br />
          对话时工具名带 <Typography.Text code>{'{服务器名}_'}</Typography.Text> 前缀，自动对专家可用。
        </Typography.Paragraph>
      </Card>
    </>
  );
}
