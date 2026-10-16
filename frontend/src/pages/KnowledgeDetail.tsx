import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Button, Card, Empty, Input, Modal, Popconfirm, Space, Table, Tag,
  Tooltip, Typography, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  BookOutlined, DeleteOutlined, FileOutlined, FolderOutlined,
  RedoOutlined, ReloadOutlined, UploadOutlined,
} from '@ant-design/icons';
import {
  knowledgeApi, type KnowledgeBase, type KnowledgeDocument,
} from '../api';
import ErrorState from '../components/ErrorState';
import KnowledgeDocEditorModal from './KnowledgeDocEditorModal';
import KnowledgeUploadModal from './KnowledgeUploadModal';

// 用 Record<string, ...> 而不是 Record<KnowledgeDocument['status'], ...>：后端新增状态值时
// 前端类型仍是旧联合，`STATUS_TAG[d.status].color` 会取到 undefined 再读 .color → TypeError
// 渲染期抛错、整页白屏。宽化索引类型 + 下面显式兜底，未知状态降级为中性标签。
const STATUS_TAG: Record<string, { color: string; label: string }> = {
  ready: { color: 'green', label: '就绪' },
  processing: { color: 'blue', label: '索引中…' },
  pending: { color: 'default', label: '待索引' },
  failed: { color: 'red', label: '失败' },
};

/** 未知状态的兜底展示（原样显示后端值，便于排查而不是吞掉） */
function statusTag(status: string): { color: string; label: string } {
  return STATUS_TAG[status] ?? { color: 'default', label: status || '未知状态' };
}

function fmtSize(n: number): string {
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}KB`;
  return `${(n / 1024 / 1024).toFixed(1)}MB`;
}

/** 知识库详情独立页面：/console/#knowledge/detail/<kbId> */
export default function KnowledgeDetailPage({ kbId }: { kbId: string }) {
  const [kb, setKb] = useState<KnowledgeBase | null>(null);
  const [docs, setDocs] = useState<KnowledgeDocument[]>([]);
  const [prefix, setPrefix] = useState('');
  const [docLoading, setDocLoading] = useState(false);
  const [missing, setMissing] = useState(false);
  // 主体（库信息 + 文档表）加载失败：原来只弹 toast，页面主体渲染不出来又没有出口，
  // 用户只看到一片空白，分不清是「库被删了」还是「后端没起来」。
  const [loadError, setLoadError] = useState<string | null>(null);
  // —— Modal 状态 ——
  const [docRenameOpen, setDocRenameOpen] = useState(false);
  const [docRenameTarget, setDocRenameTarget] = useState<KnowledgeDocument | null>(null);
  const [docRenameName, setDocRenameName] = useState('');
  const [uploadOpen, setUploadOpen] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorDoc, setEditorDoc] = useState<KnowledgeDocument | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [preview, setPreview] = useState<{ filename: string; text: string } | null>(null);

  const loadBase = useCallback(async () => {
    try {
      const rows = await knowledgeApi.listBases();
      const hit = rows.find(b => b.id === kbId);
      if (!hit) { setKb(null); setMissing(true); return; }
      setKb(hit);
      setMissing(false);
      setLoadError(null);
    } catch (e) {
      // 「库不存在」走上面的 missing（Empty 文案），这里只处理请求本身失败：两者必须区分，
      // 否则后端离线会被误报成「知识库已被删除」。
      setLoadError(`加载知识库失败：${(e as Error).message}`);
    }
  }, [kbId]);

  // 文档请求竞态保护：删除库/切换前缀后，旧请求的响应直接丢弃（reqId 递增）
  const docsReqRef = useRef(0);
  const loadDocs = useCallback(async (id: string, p: string) => {
    const req = ++docsReqRef.current;
    setDocLoading(true);
    try {
      const rows = await knowledgeApi.listDocs(id, p || undefined);
      if (req !== docsReqRef.current) return;
      setDocs(rows);
      setLoadError(null);
    } catch (e) {
      if (req !== docsReqRef.current) return;
      setLoadError(`加载文档失败：${(e as Error).message}`);
    } finally {
      if (req === docsReqRef.current) setDocLoading(false);
    }
  }, []);

  useEffect(() => { void loadBase(); }, [loadBase]);

  useEffect(() => {
    if (kb) void loadDocs(kb.id, prefix);
  }, [kb, prefix, loadDocs]);

  const refreshAll = useCallback(() => {
    void loadBase();
    if (kb) void loadDocs(kb.id, prefix);
  }, [loadBase, loadDocs, kb, prefix]);

  // 上传后自动轮询刷新索引状态（最多 6 次）
  const pollAfterUpload = useCallback(() => {
    let n = 0;
    const t = setInterval(() => {
      n += 1;
      if (kb) void loadDocs(kb.id, prefix);
      if (n >= 6) clearInterval(t);
    }, 2000);
  }, [kb, prefix, loadDocs]);

  const enterFolder = (path: string) => setPrefix(path);
  const goUp = () => {
    const idx = prefix.lastIndexOf('/');
    setPrefix(idx > 0 ? prefix.slice(0, idx) : '');
  };

  const openPreview = async (doc: KnowledgeDocument) => {
    if (!kb) return;
    try {
      const r = await knowledgeApi.previewDoc(kb.id, doc.id);
      setPreview({ filename: r.filename, text: r.text });
      setPreviewOpen(true);
    } catch (e) { message.error(`预览失败：${(e as Error).message}`); }
  };

  const openEdit = (doc: KnowledgeDocument) => {
    const editable = doc.content_type === 'text/markdown' || doc.content_type === 'text/plain';
    if (!editable) { message.info('仅 md / txt 文档支持在线编辑'); return; }
    setEditorDoc(doc);
    setEditorOpen(true);
  };

  const renameDoc = async () => {
    if (!kb || !docRenameTarget) return;
    const name = docRenameName.trim();
    if (!name) return;
    try {
      await knowledgeApi.renameDoc(kb.id, docRenameTarget.id, name);
      message.success('已重命名');
      setDocRenameOpen(false);
      await loadDocs(kb.id, prefix);
    } catch (e) { message.error(`重命名失败：${(e as Error).message}`); }
  };

  const reindexDoc = async (doc: KnowledgeDocument) => {
    if (!kb) return;
    try {
      await knowledgeApi.reindexDoc(kb.id, doc.id);
      message.success('已重新入队索引');
      await loadDocs(kb.id, prefix);
    } catch (e) { message.error(`重索引失败：${(e as Error).message}`); }
  };

  const deleteDoc = async (doc: KnowledgeDocument) => {
    if (!kb) return;
    try {
      await knowledgeApi.deleteDoc(kb.id, doc.id);
      message.success(`已删除 ${doc.filename}`);
      await loadDocs(kb.id, prefix);
    } catch (e) { message.error(`删除失败：${(e as Error).message}`); }
  };

  // —— 文档表格 ——
  const columns: ColumnsType<KnowledgeDocument> = [
    {
      title: '文件名',
      dataIndex: 'filename',
      render: (_, d) => (
        <Space>
          {d.is_dir ? <FolderOutlined style={{ color: 'var(--accent)' }} /> : <FileOutlined style={{ color: 'var(--label-3)' }} />}
          <Typography.Text
            style={{ cursor: d.is_dir ? 'pointer' : 'default', color: d.is_dir ? 'var(--link)' : undefined }}
            onClick={d.is_dir ? () => enterFolder(d.path) : undefined}
          >
            {d.is_dir ? `${d.filename}/` : d.filename}
          </Typography.Text>
        </Space>
      ),
    },
    { title: '大小', width: 90, render: (_, d) => (d.is_dir ? '—' : fmtSize(d.byte_size)) },
    { title: '分块', width: 70, render: (_, d) => (d.is_dir ? '—' : d.chunk_count) },
    {
      title: '状态', width: 110,
      render: (_, d) => {
        if (d.is_dir) return <Tag>文件夹</Tag>;
        const meta = statusTag(d.status);
        return (
          <Tooltip title={d.status === 'failed' ? d.error_message : undefined}>
            <Tag color={meta.color}>{meta.label}</Tag>
          </Tooltip>
        );
      },
    },
    {
      title: '操作', width: 320,
      render: (_, d) => d.is_dir ? (
        <Space size="small">
          <Button size="small" type="link" onClick={() => enterFolder(d.path)}>进入</Button>
        </Space>
      ) : (
        <Space size={0}>
          <Button size="small" type="link" onClick={() => openPreview(d)}>预览</Button>
          <Button size="small" type="link" onClick={() => openEdit(d)}>编辑</Button>
          {kb && (
            <Button size="small" type="link" href={knowledgeApi.fileUrl(kb.id, d.id)} target="_blank">下载</Button>
          )}
          <Button size="small" type="link" onClick={() => reindexDoc(d)}>重索引</Button>
          <Button size="small" type="link" onClick={() => { setDocRenameTarget(d); setDocRenameName(d.filename.replace(/\.\w+$/, '')); setDocRenameOpen(true); }}>重命名</Button>
          <Popconfirm title={`删除 ${d.filename}？`} onConfirm={() => deleteDoc(d)} okText="删除" cancelText="取消">
            <Button size="small" type="link" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  if (missing) {
    return (
      <Card style={{ maxWidth: 1080 }}>
        <Empty description="知识库不存在或已被删除" />
      </Card>
    );
  }

  return (
    <div style={{ maxWidth: 1080 }}>
      {loadError ? (
        <ErrorState description={loadError} onRetry={refreshAll} />
      ) : kb && (
        <Card
          title={
            <Space>
              <BookOutlined style={{ color: 'var(--link)' }} />
              <span>{kb.name}</span>
              {!kb.enabled && <Tag color="default">已停用</Tag>}
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                {prefix ? `${prefix}/ · ` : ''}{docs.filter(d => !d.is_dir).length} 文档
              </Typography.Text>
            </Space>
          }
          extra={
            <Space>
              <Button size="small" icon={<UploadOutlined />} onClick={() => setUploadOpen(true)}>上传</Button>
              <Button size="small" icon={<ReloadOutlined />} onClick={refreshAll}>刷新</Button>
            </Space>
          }
        >
          {prefix && (
            <Button size="small" type="link" icon={<RedoOutlined />} onClick={goUp} style={{ marginBottom: 8 }}>
              返回上级（{prefix.slice(0, prefix.lastIndexOf('/')) || '根目录'}）
            </Button>
          )}
          <Table<KnowledgeDocument>
            rowKey="id"
            size="small"
            loading={docLoading}
            columns={columns}
            dataSource={docs}
            pagination={false}
            locale={{ emptyText: <Empty description="还没有文档，点击「上传」或「新建文本」" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
          />
        </Card>
      )}

      <KnowledgeUploadModal open={uploadOpen} onClose={() => setUploadOpen(false)} kbId={kb?.id ?? ''} onUploaded={pollAfterUpload} />
      <KnowledgeDocEditorModal
        open={editorOpen}
        onClose={() => setEditorOpen(false)}
        kbId={kb?.id ?? ''}
        doc={editorDoc}
        onSaved={() => { message.success('已保存并重新索引'); refreshAll(); }}
      />

      {/* 重命名文档 */}
      <Modal title="重命名文档" open={docRenameOpen} onCancel={() => setDocRenameOpen(false)} onOk={renameDoc} okText="保存">
        <Input value={docRenameName} onChange={e => setDocRenameName(e.target.value)} />
      </Modal>

      {/* 预览 */}
      <Modal
        title={preview?.filename ?? '预览'}
        open={previewOpen}
        onCancel={() => setPreviewOpen(false)}
        footer={null}
        width={720}
      >
        <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: '60vh', overflow: 'auto', fontSize: 13 }}>
          {preview?.text ?? ''}
        </pre>
      </Modal>
    </div>
  );
}
