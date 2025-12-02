/**
 * 统一的日志工具
 * 提供分级日志输出，方便调试和生产环境切换
 */

const Logger = {
    // 日志级别
    LEVELS: {
        DEBUG: 0,
        INFO: 1,
        WARN: 2,
        ERROR: 3,
        NONE: 4
    },
    
    // 当前日志级别（可在生产环境设置为INFO或WARN）
    currentLevel: 0, // DEBUG级别，显示所有日志
    
    /**
     * 设置日志级别
     * @param {number} level - 日志级别
     */
    setLevel(level) {
        this.currentLevel = level;
    },
    
    /**
     * DEBUG级别日志 - 详细的调试信息
     */
    debug(message, ...args) {
        if (this.currentLevel <= this.LEVELS.DEBUG) {
            console.log(`🔍 [DEBUG]`, message, ...args);
        }
    },
    
    /**
     * INFO级别日志 - 一般信息
     */
    info(message, ...args) {
        if (this.currentLevel <= this.LEVELS.INFO) {
            console.log(`ℹ️ [INFO]`, message, ...args);
        }
    },
    
    /**
     * WARN级别日志 - 警告信息
     */
    warn(message, ...args) {
        if (this.currentLevel <= this.LEVELS.WARN) {
            console.warn(`⚠️ [WARN]`, message, ...args);
        }
    },
    
    /**
     * ERROR级别日志 - 错误信息
     */
    error(message, ...args) {
        if (this.currentLevel <= this.LEVELS.ERROR) {
            console.error(`❌ [ERROR]`, message, ...args);
        }
    },
    
    /**
     * 成功信息
     */
    success(message, ...args) {
        if (this.currentLevel <= this.LEVELS.INFO) {
            console.log(`✅ [SUCCESS]`, message, ...args);
        }
    },
    
    /**
     * 分组日志开始
     */
    group(title) {
        if (this.currentLevel <= this.LEVELS.DEBUG) {
            console.group(title);
        }
    },
    
    /**
     * 分组日志结束
     */
    groupEnd() {
        if (this.currentLevel <= this.LEVELS.DEBUG) {
            console.groupEnd();
        }
    },
    
    /**
     * 表格日志
     */
    table(data) {
        if (this.currentLevel <= this.LEVELS.DEBUG) {
            console.table(data);
        }
    }
};

// 挂载到window对象，供全局使用
if (typeof window !== 'undefined') {
    window.Logger = Logger;
}

// 也支持ES6模块导出
if (typeof module !== 'undefined' && module.exports) {
    module.exports = Logger;
}
