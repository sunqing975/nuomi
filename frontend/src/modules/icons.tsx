/**
 * 糯米 UI 图标集 · 自绘内联 SVG（统一 24 网格、1.8px 圆头描边，currentColor）
 * 替换全部 emoji 图标，形成签名视觉。新增图标在此扩展，保持同一网格与笔触。
 */
import type { SVGProps } from "react";

interface IconProps extends Omit<SVGProps<SVGSVGElement>, "width" | "height"> {
  size?: number;
  className?: string;
}

function Base({ size = 16, className, children, ...rest }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`icon ${className ?? ""}`.trim()}
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

/** 品牌标记：糯米团子（圆润三角饭团 + 脸），用于侧栏与空态 */
export function LogoMark(props: IconProps) {
  return (
    <Base {...props}>
      <path
        d="M12 3.1c1.9 0 3.5 1.4 4.7 3.7l3.6 6.8c1.6 3-.1 5.4-3.5 5.4H7.2c-3.4 0-5.1-2.4-3.5-5.4l3.6-6.8C8.5 4.5 10.1 3.1 12 3.1Z"
        fill="currentColor"
        stroke="none"
      />
      <circle cx="9.7" cy="10.4" r="1.1" fill="#fff" stroke="none" />
      <circle cx="14.3" cy="10.4" r="1.1" fill="#fff" stroke="none" />
      <path d="M9.8 14.4c1.4 1 3 1 4.4 0" stroke="#fff" strokeWidth={1.5} strokeLinecap="round" fill="none" />
    </Base>
  );
}

/** 极简团子轮廓（用于助手/占位） */
export function MochiOutline(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M12 3.4c1.9 0 3.5 1.4 4.7 3.7l3.5 6.6c1.6 3-.1 5.3-3.4 5.3H7.2c-3.3 0-5-2.3-3.4-5.3l3.5-6.6C8.5 4.8 10.1 3.4 12 3.4Z" />
    </Base>
  );
}

export function PlusIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M12 5v14M5 12h14" />
    </Base>
  );
}

export function PuzzleIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M10 4h4v2.2a1.3 1.3 0 0 0 2.6 0V4h3.4v3.4h-2.2a1.3 1.3 0 0 0 0 2.6h2.2v3.4h-3.4a1.3 1.3 0 0 0-2.6 0v2.2H10v-2.2a1.3 1.3 0 0 0-2.6 0v2.2H4V13h2.2a1.3 1.3 0 0 0 0-2.6H4V7h3.4v2.2a1.3 1.3 0 0 0 2.6 0V4Z" />
    </Base>
  );
}

export function SearchIcon(props: IconProps) {
  return (
    <Base {...props}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m20 20-3.8-3.8" />
    </Base>
  );
}

export function GearIcon(props: IconProps) {
  return (
    <Base {...props}>
      <circle cx="12" cy="12" r="3.2" />
      <path d="M12 2.8v2.4M12 18.8v2.4M21.2 12h-2.4M5.2 12H2.8M18.5 5.5l-1.7 1.7M7.2 16.8l-1.7 1.7M18.5 18.5l-1.7-1.7M7.2 7.2 5.5 5.5" />
    </Base>
  );
}

export function PinIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M9.2 4h5.6l-1 4.4L16.5 11H7.5l2.7-2.6L9.2 4Z" />
      <path d="M12 11v9" />
    </Base>
  );
}

export function PencilIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M4 20l1.2-4.3L16.4 4.5a1.7 1.7 0 0 1 2.4 0l.7.7a1.7 1.7 0 0 1 0 2.4L8.3 18.8 4 20Z" />
      <path d="m14.8 6.1 3.1 3.1" />
    </Base>
  );
}

export function TrashIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M4.5 6.5h15M9.5 6V4.8c0-.4.4-.8.8-.8h3.4c.4 0 .8.4.8.8V6M6.5 6.5l.8 12.2c0 .7.6 1.3 1.3 1.3h6.8c.7 0 1.3-.6 1.3-1.3l.8-12.2M10 10.5v6M14 10.5v6" />
    </Base>
  );
}

export function FolderIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M3.5 6.5A1.5 1.5 0 0 1 5 5h4.2l2 2.5H19a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 19 18.5H5A1.5 1.5 0 0 1 3.5 17V6.5Z" />
    </Base>
  );
}

export function ChevronDownIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="m6 9.5 6 6 6-6" />
    </Base>
  );
}

export function MicIcon(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3" />
    </Base>
  );
}

export function SendIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M4.5 12h13M13 6.5 18.5 12 13 17.5" />
    </Base>
  );
}

export function SparkleIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M12 3.5 13.8 9 19.5 11 13.8 13 12 18.5 10.2 13 4.5 11 10.2 9 12 3.5Z" />
      <path d="M19 15.5l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7.7-2Z" />
    </Base>
  );
}

export function ZapIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M13 2.5 4.5 13.5H11l-1 8 8.5-11H12l1-8Z" />
    </Base>
  );
}

export function RefreshIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3" />
      <path d="M19.5 3.5v3.7h-3.7" />
    </Base>
  );
}

export function XIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="m6 6 12 12M18 6 6 18" />
    </Base>
  );
}

export function CheckIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="m5 12.5 4.5 4.5L19 7.5" />
    </Base>
  );
}

export function WarnIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M12 3.8 21.5 20h-19L12 3.8Z" />
      <path d="M12 10v4.5" />
      <circle cx="12" cy="17.2" r="0.4" fill="currentColor" />
    </Base>
  );
}

export function CpuIcon(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="6.5" y="6.5" width="11" height="11" rx="2" />
      <rect x="10" y="10" width="4" height="4" />
      <path d="M9 3.5v3M15 3.5v3M9 17.5v3M15 17.5v3M3.5 9h3M3.5 15h3M17.5 9h3M17.5 15h3" />
    </Base>
  );
}

export function ShieldIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M12 3.2 5 5.8v5.4c0 4.4 3 7.4 7 9.6 4-2.2 7-5.2 7-9.6V5.8L12 3.2Z" />
      <path d="m9.2 12 2 2 3.6-4" />
    </Base>
  );
}

export function FolderPlusIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M3.5 6.5A1.5 1.5 0 0 1 5 5h4.2l2 2.5H19a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 19 18.5H5A1.5 1.5 0 0 1 3.5 17V6.5Z" />
      <path d="M12 11v5M9.5 13.5h5" />
    </Base>
  );
}

export function MenuIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M4 7h16M4 12h16M4 17h16" />
    </Base>
  );
}

/** 眼睛：密钥可见性切换（设置-模型 API Key） */
export function EyeIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" />
      <circle cx="12" cy="12" r="2.6" />
    </Base>
  );
}

/** 眼睛斜杠：密钥隐藏态 */
export function EyeOffIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M4 4.5 20 19.5" />
      <path d="M10.3 6.1A9.7 9.7 0 0 1 12 6c6 0 9.5 6 9.5 6a17.2 17.2 0 0 1-2.6 3.3" />
      <path d="M6.2 7.6A16.4 16.4 0 0 0 2.5 12S6 18 12 18a9.3 9.3 0 0 0 3.4-.7" />
      <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
    </Base>
  );
}

/** 收件箱：模型空态引导 */
export function InboxIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M3.5 13.5 5.2 5.9A2 2 0 0 1 7.1 4.5h9.8a2 2 0 0 1 1.9 1.4l1.7 7.6" />
      <path d="M3.5 13.5h4.6a2 2 0 0 1 2 1.6 2.4 2.4 0 0 0 4.7 0 2 2 0 0 1 2-1.6h4.6" />
      <path d="M3.5 13.5V18a1.5 1.5 0 0 0 1.5 1.5h14A1.5 1.5 0 0 0 20.5 18v-4.5" />
    </Base>
  );
}
