// unified-model-adapter.js - 统一模型适配器（方案B：仅 VRM）
// 包装 VRMModelAdapter，提供统一接口，让其他代码无需关心底层模型类型

const EventEmitter = require('events');

class UnifiedModelAdapter extends EventEmitter {
    /**
     * @param {object} innerModel - VRMModelAdapter
     * @param {object} app - appProxy（three 场景代理）
     * @param {'vrm'} modelType
     * @param {object} config - 配置
     */
    constructor(innerModel, app, modelType, config) {
        super();
        this._inner = innerModel;
        this._app = app;
        this.modelType = modelType;
        this._config = config;

        // 转发 EventEmitter 事件（VRM 用 Node EventEmitter）
        this._forwardEvents();
    }

    // === 统一属性 ===

    get visible() { return this._inner.visible; }
    set visible(val) { this._inner.visible = val; }

    get x() { return this._inner.x; }
    set x(val) { this._inner.x = val; }

    get y() { return this._inner.y; }
    set y(val) { this._inner.y = val; }

    get width() { return this._inner.width; }
    get height() { return this._inner.height; }

    get scale() { return this._inner.scale; }

    get interactive() { return this._inner.interactive; }
    set interactive(val) { this._inner.interactive = val; }

    get app() { return this._app; }
    get innerModel() { return this._inner; }

    // VRM 视口区域
    get viewRect() {
        return this._inner.viewRect || null;
    }
    set viewRect(rect) {
        if (this._inner.viewRect !== undefined) {
            this._inner.viewRect = rect;
        }
    }

    // === 统一方法 ===

    /** 触发动作（点击等） */
    motion(group, index) {
        this._inner.motion(group, index);
    }

    /** 触发表情 */
    expression(name) {
        this._inner.expression(name);
    }

    /** 按中文情绪名触发表情（统一入口） */
    playEmotionExpression(emotionName) {
        if (this._inner.playEmotionExpression) {
            this._inner.playEmotionExpression(emotionName);
        } else if (this._inner.expression) {
            this._inner.expression(emotionName);
        }
    }

    /** 插件触发情绪入口（统一接口） */
    triggerEmotion(emotion) {
        if (this._inner.triggerEmotion) {
            this._inner.triggerEmotion(emotion);
        } else {
            this.playEmotionExpression(emotion);
        }
    }

    /** 命中检测（点格式 {x, y}） */
    containsPoint(point) {
        return this._inner.containsPoint(point);
    }

    /** 嘴型同步 */
    setMouthOpenY(v) {
        if (this._inner.setMouthOpenY) {
            this._inner.setMouthOpenY(v);
        }
    }

    /** 帧更新（VRM 需要） */
    update(deltaTime) {
        if (this._inner.update) {
            this._inner.update(deltaTime);
        }
    }

    /** 获取 internalModel（兼容旧代码） */
    get internalModel() {
        return this._inner.internalModel;
    }

    /** 获取可用表情列表 */
    getAvailableExpressions() {
        if (this._inner.getAvailableExpressions) {
            return this._inner.getAvailableExpressions();
        }
        return [];
    }

    // === VRM 事件转发 ===

    _forwardEvents() {
        // VRMModelAdapter 使用 Node EventEmitter，
        // 而 UnifiedModelAdapter 也继承 EventEmitter，
        // 需要将内部模型的事件转发到外部
        const events = ['mousedown', 'mousemove', 'mouseover', 'mouseout', 'click', 'rightdown'];
        for (const event of events) {
            this._inner.on(event, (...args) => this.emit(event, ...args));
        }
    }
}

module.exports = { UnifiedModelAdapter };
