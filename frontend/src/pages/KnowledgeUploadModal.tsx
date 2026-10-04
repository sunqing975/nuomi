import { useState } from 'react';
import { Modal, Upload, Typography, message } from 'antd';
import { InboxOutlined } from '@ant-design/icons';
import { knowledgeApi } from '../api';

interface Props {
  open: boolean;
  onClose: () => void;
  kbId: string;
  onUploaded: () => void;
}

const ALLOWED_EXT = /\.(md|txt|markdown|json|html|htm|csv|tsv|pdf|docx|pptx|xlsx|xls)$/i;
const MAX_BYTES = 100 * 1024 * 1024;

/** 上传 Modal：多选/拖拽（扩展名与大小前端校验，后端兜底）。 */
export default function KnowledgeUploadModal({ open, onClose, kbId, onUploaded }: Props) {
  const [uploading, setUploading] = useState(false);

  const doUpload = async (files: File[]) => {
    const bad = files.find(f => !ALLOWED_EXT.test(f.name));
    if (bad) {
      message.error(`不支持的文件类型：${bad.name}`);
      return;
    }
    const tooBig = files.find(f => f.size > MAX_BYTES);
    if (tooBig) {
      message.error(`文件超过 100MB：${tooBig.name}`);
      return;
    }
    setUploading(true);
    let okCount = 0;
    let errCount = 0;
    for (const f of files) {
      try {
        await knowledgeApi.uploadDoc(kbId, f);
        okCount += 1;
      } catch (e) {
        errCount += 1;
        message.error(`${f.name} 上传失败：${(e as Error).message}`);
      }
    }
    setUploading(false);
    if (okCount > 0) {
      message.success(`上传完成 ${okCount} 个文档（正在后台索引）`);
      onUploaded();
      onClose();
    }
    if (errCount > 0 && okCount === 0) {
      message.error('全部上传失败，请检查文件类型与大小');
    }
  };

  return (
    <Modal title="上传文档" open={open} onCancel={uploading ? undefined : onClose} footer={null}>
      <Upload.Dragger
        multiple
        accept={ALLOWED_EXT.source}
        showUploadList={false}
        beforeUpload={(file) => {
          void doUpload([file]);
          return false; // 自行控制
        }}
      >
        <p className="ant-upload-drag-icon"><InboxOutlined /></p>
        <p className="ant-upload-text">点击或拖拽文件到此处上传</p>
        <p className="ant-upload-hint">
          支持 md / txt / json / html / csv / tsv / pdf / docx / pptx / xlsx / xls，单文件 ≤ 100MB
        </p>
      </Upload.Dragger>
      {uploading && <Typography.Text type="secondary">上传中，请稍候…</Typography.Text>}
    </Modal>
  );
}
