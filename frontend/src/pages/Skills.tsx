import { useCallback, useEffect, useState } from 'react';
import { Table, Switch, message, Typography } from 'antd';
import { get, patch, type Skill } from '../api';

export default function SkillsPage() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setSkills(await get<Skill[]>('/skills'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggle = async (s: Skill, enabled: boolean) => {
    await patch(`/skills/${s.name}`, { enabled });
    message.success(enabled ? '已启用（重启专家实例生效）' : '已停用');
    load();
  };

  const columns = [
    { title: '技能', dataIndex: 'name', render: (n: string) => <b>{n}</b> },
    { title: '描述', dataIndex: 'description', render: (d: string) => <span style={{ color: '#6b7280' }}>{d || '—'}</span> },
    { title: '启用', width: 90, render: (_: unknown, s: Skill) => (
        <Switch checked={s.enabled} onChange={v => toggle(s, v)} />) },
  ];

  return (
    <>
      <Table<Skill>
        rowKey="name"
        columns={columns}
        dataSource={skills}
        loading={loading}
        pagination={false}
      />
      <Typography.Paragraph type="secondary" style={{ marginTop: 10, fontSize: 12 }}>
        技能目录：<Typography.Text code>工作区/skills/&lt;技能名&gt;/SKILL.md</Typography.Text>（frontmatter 定义 name/description）。
        内置技能（apple-notes / plan / 提醒 等）随 harness 注入专家。
      </Typography.Paragraph>
    </>
  );
}
