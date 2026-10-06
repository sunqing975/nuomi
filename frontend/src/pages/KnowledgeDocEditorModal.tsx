import { useEffect, useRef, useState } from 'react';
import { Input, Modal, Radio, Space, Typography, message } from 'antd';
import { knowledgeApi, type KnowledgeDocument } from '../api';

interface Props {
  open: boolean;
  onClose: () => void;
  kbId: string;
  /** 编辑模式传入文档；新建模式传 null */
  doc: KnowledgeDocument | null;
  onSaved: (row: KnowledgeDocument) => void;
}

/** 新建 / 编辑 md·txt 文档（对齐 Octop TextDocumentEditorModal，nuomi 简化版）。 */
export default function KnowledgeDocEditorModal({ open, onClose, kbId, doc, onSaved }: Props) {
  const [name, setName] = useState('');
  const [format, setFormat] = useState<'md' | 'txt'>('md');
  const [content, setContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(false);

  const isEdit = doc != null;

  // 请求守卫：先点开 A 再点开 B 时，A 的响应可能后到。没有这层就会把 A 的内容显示在
  // B 的编辑器里，用户一保存就把 B 写坏（写接口只认 doc.id，内容却来自 A）。
  const loadReqRef = useRef(0);

  useEffect(() => {
    if (!open) return;
    const req = ++loadReqRef.current;
    const isCurrent = () => req === loadReqRef.current;
    if (doc) {
      setName(doc.filename.replace(/\.(md|txt)$/, ''));
      setFormat(doc.filename.endsWith('.txt') ? 'txt' : 'md');
      setContent('');
      setLoading(true);
      knowledgeApi.readContent(kbId, doc.id)
        .then(r => { if (isCurrent()) setContent(r.text); })
        .catch((e: Error) => {
          if (!isCurrent()) return;
          setContent('');
          message.error(`读取文档失败：${e.message}`);
        })
        // 只有最新一次请求才有权解锁编辑框，否则 A 的响应会提前把 B 的 loading 关掉
        .finally(() => { if (isCurrent()) setLoading(false); });
    } else {
      setName('');
      setFormat('md');
      setContent('');
      setLoading(false);
    }
  }, [open, doc, kbId]);

  const save = async () => {
    const n = name.trim();
    if (!n) return;
    setSaving(true);
    try {
      const row = isEdit
        ? await knowledgeApi.writeContent(kbId, doc!.id, content)
        : await knowledgeApi.createTextDoc(kbId, { name: n, format, content });
      onSaved(row);
      onClose();
    } catch (e) {
      // 原实现没有 catch：保存失败完全静默，用户以为存上了，关掉弹窗内容就没了
      message.error(`保存失败：${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const canSave = name.trim().length > 0;

  return (
    <Modal
      title={isEdit ? `编辑 ${doc!.filename}` : '新建文本文档'}
      open={open}
      onCancel={onClose}
      onOk={save}
      okText={isEdit ? '保存并重新索引' : '创建并索引'}
      okButtonProps={{ disabled: !canSave, loading: saving }}
      width={640}
    >
      {!isEdit && (
        <Space style={{ marginBottom: 12 }}>
          <Input
            placeholder="文件名（如 README）"
            value={name}
            onChange={e => setName(e.target.value)}
            style={{ width: 260 }}
          />
          <Radio.Group value={format} onChange={e => setFormat(e.target.value)}>
            <Radio.Button value="md">.md</Radio.Button>
            <Radio.Button value="txt">.txt</Radio.Button>
          </Radio.Group>
        </Space>
      )}
      <Typography.Paragraph type="secondary" style={{ fontSize: 12, margin: isEdit ? 0 : '0 0 8px' }}>
        {isEdit ? '保存后文档将重新分块并更新向量索引。' : '创建后立即进入索引队列。'}
      </Typography.Paragraph>
      <Input.TextArea
        value={content}
        onChange={e => setContent(e.target.value)}
        placeholder="文档内容（Markdown / 纯文本）"
        autoSize={{ minRows: 8, maxRows: 24 }}
        disabled={loading}
      />
    </Modal>
  );
}
