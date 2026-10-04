const fs = require('fs');
globalThis.self = globalThis;
globalThis.createImageBitmap = async () => ({ width: 2, height: 2, close() {} });
if (typeof URL.createObjectURL !== 'function') { URL.createObjectURL = () => `blob:mock-${Math.random()}`; URL.revokeObjectURL = () => {}; }
if (typeof globalThis.ProgressEvent !== 'function') {
  globalThis.ProgressEvent = class ProgressEvent extends Event { constructor(t, i = {}) { super(t); this.lengthComputable = !!i.lengthComputable; this.loaded = i.loaded || 0; this.total = i.total || 0; } };
}
const { GLTFLoader } = require('./js/lib/gltf-loader-bundle.cjs');
const { VRMLoaderPlugin } = require('@pixiv/three-vrm');
const modelPath = process.argv[2];
const target = process.argv[3] || 'happy';
const toArrayBuffer = (b) => b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);

(async () => {
  const loader = new GLTFLoader();
  loader.register((parser) => new VRMLoaderPlugin(parser));
  const gltf = await new Promise((res, rej) => loader.parse(toArrayBuffer(fs.readFileSync(modelPath)), '', res, rej));
  const vrm = gltf.userData.vrm;
  const em = vrm.expressionManager;

  // 检查 map 键
  console.log('_expressionMap keys:', Object.keys(em._expressionMap).join(', '));

  // 快照 morph 权重
  const snapshot = () => {
    const out = [];
    vrm.scene.traverse((o) => {
      if (o.isMesh && o.morphTargetInfluences) {
        out.push({ name: o.name || '(mesh)', inf: [...o.morphTargetInfluences] });
      }
    });
    return out;
  };

  console.log('=== 播放 ' + target + ' ===');
  em.setValue(target, 1.0);
  vrm.update(0.016);
  const expr = em._expressionMap[target];
  console.log('expression:', expr ? expr.name : 'NULL', '| weight:', expr && expr.weight, '| binds:', expr && expr.binds.length);
  if (expr && expr.binds) {
    expr.binds.forEach((b, i) => {
      const mesh = b.mesh;
      const idx = mesh.morphTargetDictionary ? mesh.morphTargetDictionary[b.defName] : undefined;
      console.log(`  bind#${i}: mesh=${mesh.name || '?'} defName=${b.defName} idx=${idx} influence=${idx != null ? mesh.morphTargetInfluences[idx] : 'n/a'}`);
    });
  }
  // 对比中性 vs happy 的 morph 权重
  em.resetValues();
  vrm.update(0.016);
  const neutralInf = snapshot();
  em.setValue(target, 1.0);
  vrm.update(0.016);
  const happyInf = snapshot();
  let changed = 0;
  neutralInf.forEach((m, i) => {
    const h = happyInf[i];
    m.inf.forEach((v, j) => { if (Math.abs(v - h.inf[j]) > 0.001) changed++; });
  });
  console.log('morph 权重变化数:', changed);
})();
