/** 自绘 SVG 机器人脸：糯米品牌的"机械萌脸"。
 *  状态（mode）：idle 待机（眨眼）· listening 聆听（天线灯亮、眼睛聚焦）
 *               thinking 思考（瞳孔上移 + 光圈呼吸）· speaking 说话（嘴型开合）
 *  情绪（emotion）：neutral · happy（眯眼 + 腮红）· surprised（瞪眼）· sad（垂眼）
 *  全部表情由 CSS 动画驱动（robot-face.css），design token 着色，零依赖。
 *  替代 agent-robot-avatar：风格与全站统一、完全可控、可平滑换 three.js 3D 脸。 */
import type { CSSProperties } from "react";

export type RobotFaceMode = "idle" | "listening" | "thinking" | "speaking";
export type RobotEmotion = "neutral" | "happy" | "surprised" | "sad";

export interface RobotFaceProps {
  mode?: RobotFaceMode;
  emotion?: RobotEmotion;
  className?: string;
  style?: CSSProperties;
}

export default function RobotFace({ mode = "idle", emotion = "neutral", className = "", style }: RobotFaceProps) {
  const cls = `robot-face-svg mode-${mode} emotion-${emotion}${className ? " " + className : ""}`;
  return (
    <svg viewBox="0 0 240 240" className={cls} role="img" aria-label="糯米机器人" style={style}>
      <defs>
        <radialGradient id="rf-body" cx="50%" cy="36%" r="68%">
          <stop offset="0%" stopColor="#2b2b2e" />
          <stop offset="100%" stopColor="#18181b" />
        </radialGradient>
        <radialGradient id="rf-screen" cx="50%" cy="40%" r="62%">
          <stop offset="0%" stopColor="#212124" />
          <stop offset="100%" stopColor="#141416" />
        </radialGradient>
      </defs>

      {/* 背景光环：思考/说话时呼吸 */}
      <circle className="rf-halo" cx="120" cy="138" r="86" fill="var(--accent)" opacity="0.08" />

      {/* 天线 + 指示灯（聆听时点亮） */}
      <g className="rf-antenna">
        <rect x="115.5" y="16" width="9" height="30" rx="4.5" fill="var(--surface)" stroke="var(--line-2)" strokeWidth="1.5" />
        <circle className="rf-antenna-light" cx="120" cy="12" r="7" fill="var(--line-2)" />
      </g>

      {/* 机身 + 内屏 */}
      <g className="rf-body">
        <rect x="18" y="46" width="204" height="182" rx="56" fill="url(#rf-body)" stroke="var(--line-2)" strokeWidth="2" />
        <rect x="33" y="62" width="174" height="148" rx="40" fill="url(#rf-screen)" stroke="var(--line-2)" strokeWidth="1.5" opacity="0.92" />
      </g>

      {/* 眼睛：眼白 + 瞳孔 + 高光（眨眼 / 眯眼 / 瞪眼 / 垂眼 由 CSS 控制） */}
      <g className="rf-eyes">
        <ellipse className="rf-eye rf-eye-l" cx="88" cy="120" rx="27" ry="31" fill="#f4f4f6" />
        <ellipse className="rf-eye rf-eye-r" cx="152" cy="120" rx="27" ry="31" fill="#f4f4f6" />
        <circle className="rf-pupil rf-pupil-l" cx="92" cy="125" r="12.5" fill="var(--label)" />
        <circle className="rf-pupil rf-pupil-r" cx="156" cy="125" r="12.5" fill="var(--label)" />
        <circle className="rf-glint rf-glint-l" cx="81" cy="111" r="5" fill="#fff" />
        <circle className="rf-glint rf-glint-r" cx="145" cy="111" r="5" fill="#fff" />
      </g>

      {/* 嘴（说话时开合） */}
      <g className="rf-mouth">
        <rect x="101" y="170" width="38" height="11" rx="5.5" fill="var(--label-2)" />
      </g>

      {/* 腮红（高兴时点亮） */}
      <g className="rf-blush">
        <ellipse cx="55" cy="148" rx="17" ry="9.5" fill="var(--accent)" opacity="0.22" />
        <ellipse cx="185" cy="148" rx="17" ry="9.5" fill="var(--accent)" opacity="0.22" />
      </g>
    </svg>
  );
}
