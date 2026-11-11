// list-vrm-expressions.js — 枚举 VRM 模型的 blend shape 表情清单
// 用法: node list-vrm-expressions.js [dir]
const os = require('os');
const fs = require('fs');
const path = require('path');

// ---- Node 环境最小 polyfill（同 verify-vrma.js）----
globalThis.self = globalThis;
globalThis.createImageBitmap = async () => ({ width: 2, height: 2, close() {} });
if (typeof URL.createObjectURL !== 'function') {
  URL.createObjectURL = () => `blob:mock-${Math.random()}`;
  URL.revokeObjectURL = () => {};
}
if (typeof globalThis.ProgressEvent !== 'function') {
  globalThis.ProgressEvent = class ProgressEvent extends Event {
    constructor(type, init = {}) {
      super(type);
      this.lengthComputable = !!init.lengthComputable;
      this.loaded = init.loaded || 0;
      this.total = init.total || 0;
    }
  };
}
// ----------------------------------------------------

const { GLTFLoader } = require('../../js/lib/gltf-loader-bundle.cjs');
const { VRMLoaderPlugin } = require('@pixiv/three-vrm');

function toArrayBuffer(buf) {
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
}

async function loadVrm(filePath) {
  const loader = new GLTFLoader();
  loader.register((parser) => new VRMLoaderPlugin(parser));
  const data = toArrayBuffer(fs.readFileSync(filePath));
  return new Promise((resolve, reject) => {
    loader.parse(data, '', (g) => resolve(g.userData.vrm), (e) => reject(e));
  });
}

async function main() {
  // 用法：node list-vrm-expressions.js [模型目录]
  // 默认取数据根（NUOMI_HOME，默认 ~/Nuomi）下的 models/3D
  const dir = process.argv[2]
    || path.join(process.env.NUOMI_HOME || path.join(os.homedir(), 'Nuomi'), 'models', '3D');
  if (!fs.existsSync(dir)) {
    console.error(`目录不存在: ${dir}`);
    process.exit(1);
  }
  const files = fs.readdirSync(dir).filter((f) => f.toLowerCase().endsWith('.vrm'));
  console.log(`扫描 ${dir} 共 ${files.length} 个 VRM 模型\n`);
  for (const f of files) {
    const filePath = path.join(dir, f);
    try {
      const vrm = await loadVrm(filePath);
      // three-vrm 3.x：VRM 0.x 用 expressionManager；VRM 1.0 用 expressions
      const raw =
        vrm.expressionManager?._expressionMap ||
        vrm.expressions?.expressions ||
        {};
      const names =
        typeof raw.keys === 'function' ? Array.from(raw.keys()) : Object.keys(raw);
      console.log(`■ ${f}`);
      console.log(`  版本: VRM ${vrm.meta?.metaVersion ?? '?'} | 表情数: ${names.length}`);
      console.log(`  表情: ${names.join(', ')}\n`);
    } catch (e) {
      console.log(`■ ${f} — 加载失败: ${e.message}\n`);
    }
  }
}

main();
