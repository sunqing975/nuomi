import { useEffect, useState } from 'react';
import { Input, Modal, Radio, Space, Typography } from 'antd';
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

  useEffect(() => {
    if (!open) return;
    if (doc) {
      setName(doc.filename.replace(/\.(md|txt)$/, ''));
      setFormat(doc.filename.endsWith('.txt') ? 'txt' : 'md');
      setContent('');
      setLoading(true);
      knowledgeApi.readContent(kbId, doc.id)
        .then(r => setContent(r.text))
        .catch(() => setContent(''))
        .finally(() => setLoading(false));
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
