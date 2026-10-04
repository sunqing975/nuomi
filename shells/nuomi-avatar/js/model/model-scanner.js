// model-scanner.js - 模型自动检测（方案B：仅 VRM 3D，2D Live2D/图片已下线）

const fs = require('fs');
const path = require('path');

class ModelScanner {
    /**
     * 扫描所有可用模型
     * @param {string} basePath - 模型根目录（3D/）
     * @returns {{ vrm: Array }}
     */
    static scan(basePath) {
        const result = { vrm: [] };

        // 扫描 3D 目录（VRM 模型）
        const dir3D = path.join(basePath, '3D');
        if (fs.existsSync(dir3D)) {
            result.vrm = ModelScanner._scanVRM(dir3D);
        }

        return result;
    }

    /**
     * 扫描 VRM 模型（查找 .vrm 文件）
     */
    static _scanVRM(dir) {
        const models = [];
        try {
            const files = fs.readdirSync(dir);
            for (const file of files) {
                if (file.endsWith('.vrm')) {
                    models.push({
                        name: path.basename(file, '.vrm'),
                        file: file,
                        path: `${file}`,
                        dir: dir,
                        type: 'vrm'
                    });
                }
            }
        } catch (e) {
            console.error('扫描 VRM 模型失败:', e.message);
        }
        return models;
    }

    /**
     * 自动检测模型类型（根据文件路径）
     * @param {string} modelPath - 模型路径
     * @returns {'vrm'|null}
     */
    static detectType(modelPath) {
        if (!modelPath) return null;
        const lower = modelPath.toLowerCase();
        if (lower.endsWith('.vrm')) return 'vrm';
        return null;
    }

    /**
     * 获取默认模型（仅 VRM）
     * @param {string} basePath - 模型根目录
     * @returns {{ type, path, name }|null}
     */
    static getDefaultModel(basePath) {
        const all = ModelScanner.scan(basePath);
        if (all.vrm.length > 0) {
            return { type: 'vrm', path: `3D/${all.vrm[0].path}`, name: all.vrm[0].name };
        }
        return null;
    }

    /**
     * 获取所有可用模型列表（供 WebUI 使用）
     * @param {string} basePath - 模型根目录
     * @returns {Array<{type, path, name, label}>}
     */
    static getModelList(basePath) {
        const all = ModelScanner.scan(basePath);
        const list = [];

        for (const m of all.vrm) {
            list.push({
                type: 'vrm',
                path: `3D/${m.path}`,
                name: m.name,
                label: `[3D] ${m.name}`
            });
        }
        return list;
    }
}

module.exports = { ModelScanner };
