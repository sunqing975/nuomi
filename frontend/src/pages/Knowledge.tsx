import { useCallback, useEffect, useState } from 'react';
import {
  Button, Card, Input, Modal, Popconfirm, Space, Switch, Tag,
  Tooltip, Typography, message,
} from 'antd';
import {
  BookOutlined, DeleteOutlined, PlusOutlined, SettingOutlined,
} from '@ant-design/icons';
import {
  knowledgeApi, type KnowledgeBase, type KnowledgeCapability,
} from '../api';
import EntityGrid from '../components/EntityGrid';
import ErrorState from '../components/ErrorState';
import KnowledgeModelsModal from './KnowledgeModelsModal';
import PageLayout from '../components/PageLayout';

/** 知识库列表页：/console/#knowledge（点卡片进入独立详情页 #knowledge/detail/<id>） */
export default function KnowledgePage() {
  // —— 能力 / 模型 ——
  const [capability, setCapability] = useState<KnowledgeCapability | null>(null);
  const [modelsOpen, setModelsOpen] = useState(false);
  // —— 知识库 ——
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  // —— Modal 状态 ——
  const [createOpen, setCreateOpen] = useState(false);
  const [createName, setCreateName] = useState('');
  const [createDesc, setCreateDesc] = useState('');
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<KnowledgeBase | null>(null);
  const [renameName, setRenameName] = useState('');

  const loadCapability = useCallback(async () => {
    try { setCapability(await knowledgeApi.capability()); } catch { /* 后端离线由 Header 标记 */ }
  }, []);

  const loadBases = useCallback(async () => {
    try {
      setBases(await knowledgeApi.listBases());
      setLoadError(null);
    } catch (e) {
      // 列表加载失败原来只弹一条 toast，toast 消失后页面就是一个空网格：
      // 「后端在起 / 数据目录没挂上」和「一个知识库都没有」在界面上完全一样。
      // 改成主体位置渲染 ErrorState 并带重试，动作类失败（创建/重命名/启停/删除）仍用 message.error。
      setLoadError((e as Error).message);
    }
  }, []);

  // —— 能力状态（仅用于「管理模型」弹窗；页面不再展示状态条） ——
  useEffect(() => { void loadCapability(); void loadBases(); }, [loadCapability, loadBases]);

  const createBase = async () => {
    const name = createName.trim();
    if (!name) { message.warning('请输入知识库名称'); return; }
    try {
      await knowledgeApi.createBase({ name, description: createDesc.trim() });
      message.success(`知识库「${name}」创建成功`);
      setCreateOpen(false); setCreateName(''); setCreateDesc('');
      await loadBases();
    } catch (e) { message.error(`创建失败：${(e as Error).message}`); }
  };

  const saveRename = async () => {
    if (!renameTarget) return;
    const name = renameName.trim();
    if (!name) return;
    try {
      await knowledgeApi.patchBase(renameTarget.id, { name });
      message.success('已重命名');
      setRenameOpen(false);
      await loadBases();
    } catch (e) { message.error(`重命名失败：${(e as Error).message}`); }
  };

  const toggleEnabled = async (kb: KnowledgeBase, v: boolean) => {
    try {
      await knowledgeApi.patchBase(kb.id, { enabled: v });
      message.success(v ? `「${kb.name}」已启用` : `「${kb.name}」已停用（对话侧不再可选）`);
      await loadBases();
    } catch (e) { message.error(`设置失败：${(e as Error).message}`); }
  };

  const deleteBase = async (kb: KnowledgeBase) => {
    try {
      await knowledgeApi.deleteBase(kb.id);
      message.success(`知识库「${kb.name}」已删除`);
      await loadBases();
    } catch (e) { message.error(`删除失败：${(e as Error).message}`); }
  };

  const openDetail = (kb: KnowledgeBase) => {
    window.location.hash = `#knowledge/detail/${kb.id}`;
  };

  return (
    <PageLayout
      title="知识库"
      description="文档知识库：上传文件或新建文本，对话时按库检索引用"
      extra={
        <>
          <Button icon={<SettingOutlined />} onClick={() => setModelsOpen(true)}>管理模型…</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建知识库</Button>
        </>
      }
    >
      {/* 知识库卡片区 */}
      {loadError ? (
        <ErrorState description={loadError} onRetry={loadBases} />
      ) : (
        <EntityGrid
          items={bases}
          minWidth={340}
          emptyText="还没有知识库，点「新建知识库」创建"
          renderItem={kb => (
            <Card
              size="small"
              hoverable
              onClick={() => openDetail(kb)}
              style={kb.enabled ? { height: '100%' } : { opacity: 0.75, height: '100%' }}
              title={
                <Space>
                  <BookOutlined style={{ color: 'var(--link)' }} />
                  <span>{kb.name}</span>
                  {!kb.enabled && <Tag color="default">已停用</Tag>}
                </Space>
              }
              extra={
                <Space size={4}>
                  <Button
                    size="small" type="text"
                    onClick={e => { e.stopPropagation(); setRenameTarget(kb); setRenameName(kb.name); setRenameOpen(true); }}
                  >
                    重命名
                  </Button>
                  <Popconfirm
                    title={`删除知识库「${kb.name}」？`}
                    description="将删除全部文档、索引与文件，不可恢复"
                    okText="删除"
                    cancelText="取消"
                    onConfirm={() => deleteBase(kb)}
                  >
                    <Button size="small" danger type="text" icon={<DeleteOutlined />} onClick={e => e.stopPropagation()}>删除</Button>
                  </Popconfirm>
                </Space>
              }
            >
              <Typography.Paragraph type="secondary" ellipsis={{ rows: 2 }} style={{ fontSize: 13, minHeight: 40, marginBottom: 8 }}>
                {kb.description || '（无描述）'}
              </Typography.Paragraph>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {kb.doc_count} 文档 · {kb.embedding_dim ? `${kb.embedding_dim} 维` : '未索引'}
                </Typography.Text>
                <Tooltip title={kb.enabled ? '停用：对话侧不再可选' : '启用：对话侧可选'}>
                  <span onClick={e => e.stopPropagation()}>
                    <Switch size="small" checked={kb.enabled} onChange={v => toggleEnabled(kb, v)} />
                    <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 6 }}>
                      {kb.enabled ? '已启用' : '已停用'}
                    </Typography.Text>
                  </span>
                </Tooltip>
              </div>
            </Card>
          )}
        />
      )}

      {/* Modal */}
      <KnowledgeModelsModal open={modelsOpen} onClose={() => setModelsOpen(false)} capability={capability} onChanged={setCapability} />

      {/* 新建知识库 */}
      <Modal title="新建知识库" open={createOpen} onCancel={() => setCreateOpen(false)} onOk={createBase} okText="创建">
        <Space direction="vertical" style={{ width: '100%' }}>
          <Input placeholder="名称（必填）" value={createName} onChange={e => setCreateName(e.target.value)} />
          <Input placeholder="描述（可选）" value={createDesc} onChange={e => setCreateDesc(e.target.value)} />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            每库最多 100 个文档，知识库创建后即可上传文件 / 新建文本。
          </Typography.Text>
        </Space>
      </Modal>

      {/* 重命名知识库 */}
      <Modal title="重命名知识库" open={renameOpen} onCancel={() => setRenameOpen(false)} onOk={saveRename} okText="保存">
        <Input value={renameName} onChange={e => setRenameName(e.target.value)} />
      </Modal>
    </PageLayout>
  );
}
