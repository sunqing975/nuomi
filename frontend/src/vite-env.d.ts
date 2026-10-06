/// <reference types="vite/client" />

/** `?raw` 导入（Vite 内置）：用于在测试里直接读取样式/文本资源 */
declare module '*?raw' {
  const content: string;
  export default content;
}
