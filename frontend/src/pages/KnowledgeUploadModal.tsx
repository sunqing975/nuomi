import { useEffect, useRef, useState } from 'react';
import { Modal, Upload, Typography, message } from 'antd';
import { InboxOutlined } from '@ant-design/icons';
import { knowledgeApi } from '../api';

interface Props {
  open: boolean;
  onClose: () => void;
  kbId: string;
  onUploaded: () => void;
}

/** 允许的扩展名：校验正则与 accept 属性共用一份，避免两处漂移 */
const ALLOWED_EXTS = ['md', 'txt', 'markdown', 'json', 'html', 'htm', 'csv', 'tsv', 'pdf', 'docx', 'pptx', 'xlsx', 'xls'];
const ALLOWED_EXT = new RegExp(`\\.(${ALLOWED_EXTS.join('|')})$`, 'i');
/** accept 必须是扩展名列表（原实现传的是正则源码串 `\.(md|txt|…)$`，非法值 → 浏览器整个忽略） */
const ACCEPT_ATTR = ALLOWED_EXTS.map(e => `.${e}`).join(',');
const MAX_BYTES = 100 * 1024 * 1024;

/** 上传 Modal：多选/拖拽（扩展名与大小前端校验，后端兜底）。 */
export default function KnowledgeUploadModal({ open, onClose, kbId, onUploaded }: Props) {
  const [uploading, setUploading] = useState(false);
  // antd 的 beforeUpload 对 multiple/拖拽是**逐文件**调用的，还无法取消后续调用，
  // 所以只能自己攒：本轮事件循环内的文件收集成一个批次再提交。
  const pendingRef = useRef<File[]>([]);
  const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (flushTimerRef.current) clearTimeout(flushTimerRef.current);
  }, []);

  const doUpload = async (files: File[]) => {
    // 逐个判类型/大小：单个坏文件不该拖垮整批（逐文件调用时它们本来各自独立，攒批后保持同样语义）
    const accepted: File[] = [];
    for (const f of files) {
      if (!ALLOWED_EXT.test(f.name)) {
        message.error(`不支持的文件类型：${f.name}`);
      } else if (f.size > MAX_BYTES) {
        message.error(`文件超过 100MB：${f.name}`);
      } else {
        accepted.push(f);
      }
    }
    if (!accepted.length) return;

    setUploading(true);
    let okCount = 0;
    let errCount = 0;
    // 单批顺序提交一次：原来是每个文件各发一次 doUpload([file]) → N 个并发上传 + N 个轮询
    for (const f of accepted) {
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

  /** 逐文件回调 → 攒批 → 本轮事件循环末尾单批提交一次 */
  const enqueue = (file: File) => {
    pendingRef.current.push(file);
    if (flushTimerRef.current) clearTimeout(flushTimerRef.current);
    flushTimerRef.current = setTimeout(() => {
      flushTimerRef.current = null;
      const batch = pendingRef.current;
      pendingRef.current = [];
      if (batch.length) void doUpload(batch);
    }, 0);
  };

  return (
    <Modal title="上传文档" open={open} onCancel={uploading ? undefined : onClose} footer={null}>
      <Upload.Dragger
        multiple
        accept={ACCEPT_ATTR}
        showUploadList={false}
        beforeUpload={(file) => {
          enqueue(file);
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
