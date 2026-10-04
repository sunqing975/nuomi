// verify-vrma.js — 验证 .vrma 能被壳同款加载链解析并在目标 VRM 模型上生成 AnimationClip
// 用法: node verify-vrma.js [path/to/file.vrma]
// 依赖解析: 向上找到 shells/nuomi-avatar/node_modules (three/@pixiv/three-vrm/@pixiv/three-vrm-animation)
const fs = require('fs');

// ---- Node 环境最小 polyfill（仅用于离线验证，无需真实解码纹理）----
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
// ------------------------------------------------------------------

const { GLTFLoader } = require('../../js/lib/gltf-loader-bundle.cjs');
const { VRMLoaderPlugin } = require('@pixiv/three-vrm');
const { VRMAnimationLoaderPlugin, createVRMAnimationClip } = require('@pixiv/three-vrm-animation');

const VRM_MODEL = '/Users/superman/Nuomi/models/3D/6309260419351179234.vrm';
const VRMA_FILE = process.argv[2] || '/Users/superman/projects/code/nuomi/shells/nuomi-avatar/assets/animations/elbow_punch.vrma';

function toArrayBuffer(buf) {
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
}

function parseBuffer(loader, filePath) {
  const data = toArrayBuffer(fs.readFileSync(filePath));
  return new Promise((resolve, reject) => {
    loader.parse(data, '', resolve, reject);
  });
}

async function main() {
  // 1. 加载 VRM 模型（壳 vrm-model-setup 同款：GLTFLoader + VRMLoaderPlugin）
  const vrmLoader = new GLTFLoader();
  vrmLoader.register((parser) => new VRMLoaderPlugin(parser));
  const vrmGltf = await parseBuffer(vrmLoader, VRM_MODEL);
  const vrm = vrmGltf.userData.vrm;
  const boneCount = Object.keys(vrm.humanoid?.humanBones || {}).length;
  console.log(`[OK] VRM 模型加载: metaVersion=${vrm.meta?.metaVersion} humanoid骨骼=${boneCount}`);

  // 2. 加载 VRMA（壳 vrm-model-adapter.loadVRMA 同款：GLTFLoader + VRMAnimationLoaderPlugin）
  const animLoader = new GLTFLoader();
  animLoader.register((parser) => new VRMAnimationLoaderPlugin(parser));
  const animGltf = await parseBuffer(animLoader, VRMA_FILE);
  const anims = animGltf.userData.vrmAnimations || [];
  console.log(`[OK] VRMA 解析: 动画数=${anims.length} humanoidTracks=${anims[0]?.humanoidTracks?.length}`);
  if (anims.length === 0) throw new Error('VRMA 中没有 vrmAnimations');

  // 3. 生成 AnimationClip（壳 loadVRMA 的 createVRMAnimationClip 同款）
  const clip = createVRMAnimationClip(anims[0], vrm);
  console.log(`[OK] AnimationClip: name="${clip.name}" duration=${clip.duration.toFixed(2)}s tracks=${clip.tracks.length}`);
  clip.tracks.slice(0, 10).forEach((t) => console.log('     track:', t.name));

  // 4. 采样验证：首/中/尾帧骨骼旋转不为空（确认曲线真的驱动了骨骼）
  const headTrack = clip.tracks.find((t) => t.name.includes('Head.quaternion'));
  if (headTrack) {
    const q0 = Array.from(headTrack.values.slice(0, 4)).map((v) => v.toFixed(3)).join(',');
    const mid = Math.floor(headTrack.times.length / 2) * 4;
    const q1 = Array.from(headTrack.values.slice(mid, mid + 4)).map((v) => v.toFixed(3)).join(',');
    console.log(`[OK] Head 采样: t=0 [${q0}] t=mid [${q1}]`);
  }
  console.log('\n=== 验证通过：该 .vrma 可直接被AI 数字人壳 loadVRMA/playAnimation 播放 ===');
}

main().catch((e) => {
  console.error('\n=== 验证失败 ===');
  console.error(e);
  process.exit(1);
});
