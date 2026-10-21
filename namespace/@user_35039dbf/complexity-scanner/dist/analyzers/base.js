"use strict";
// ============================================================
// 分析器基类 — 所有语言分析器的抽象接口
// ============================================================
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.LANGUAGE_FAMILY = exports.LANGUAGE_EXTENSIONS = void 0;
exports.inferLanguage = inferLanguage;
exports.readFileContent = readFileContent;
exports.countLines = countLines;
exports.classifyComplexity = classifyComplexity;
exports.calcCyclomaticComplexity = calcCyclomaticComplexity;
exports.calcMaxNestingDepth = calcMaxNestingDepth;
const fs = __importStar(require("fs"));
const path = __importStar(require("path"));
/** 语言 → 扩展名映射 */
exports.LANGUAGE_EXTENSIONS = {
    typescript: ['.ts'],
    javascript: ['.js', '.mjs', '.cjs'],
    tsx: ['.tsx'],
    jsx: ['.jsx'],
    swift: ['.swift'],
    kotlin: ['.kt', '.kts'],
    java: ['.java'],
    objc: ['.m', '.mm'],
    unknown: [],
};
/** 语言分类映射 */
exports.LANGUAGE_FAMILY = {
    typescript: 'web',
    javascript: 'web',
    tsx: 'web',
    jsx: 'web',
    swift: 'ios',
    kotlin: 'android',
    java: 'android',
    objc: 'ios',
    unknown: 'unknown',
};
/** 从文件路径推断语言 */
function inferLanguage(filePath) {
    const ext = path.extname(filePath).toLowerCase();
    for (const [lang, exts] of Object.entries(exports.LANGUAGE_EXTENSIONS)) {
        if (exts.includes(ext))
            return lang;
    }
    return 'unknown';
}
/** 读取文件内容 */
function readFileContent(filePath) {
    return fs.readFileSync(filePath, 'utf-8');
}
/** 计算行数统计 */
function countLines(content) {
    const lines = content.split('\n');
    let code = 0;
    let comment = 0;
    let blank = 0;
    let inBlockComment = false;
    for (const line of lines) {
        const trimmed = line.trim();
        if (trimmed === '') {
            blank++;
            continue;
        }
        if (inBlockComment) {
            comment++;
            if (trimmed.includes('*/'))
                inBlockComment = false;
            continue;
        }
        if (trimmed.startsWith('//') || trimmed.startsWith('#') || trimmed.startsWith('/*')) {
            comment++;
            if (trimmed.startsWith('/*') && !trimmed.includes('*/'))
                inBlockComment = true;
            continue;
        }
        code++;
    }
    return { total: lines.length, code, comment, blank };
}
/** 判断复杂度等级 */
function classifyComplexity(cyclomaticComplexity, lineCount, fanOut) {
    const score = cyclomaticComplexity * 2 + Math.floor(lineCount / 50) + fanOut;
    if (score >= 60)
        return 'critical';
    if (score >= 35)
        return 'high';
    if (score >= 15)
        return 'medium';
    return 'low';
}
/** 计算圈复杂度 (通用正则方式) */
function calcCyclomaticComplexity(code) {
    // 每个分支/循环关键字贡献 +1 复杂度
    const patterns = [
        /\bif\s*\(/g,
        /\belse\s+if\s*\(/g,
        /\belse\s*\{/g,
        /\bfor\s*\(/g,
        /\bfor\s+each/g,
        /\bwhile\s*\(/g,
        /\bdo\s*\{/g,
        /\bswitch\s*\(/g,
        /\bcase\s+/g,
        /\bcatch\s*\(/g,
        /\b\?\s*[^:]+:/g, // 三元运算符
        /\b&&\b/g,
        /\b\|\|\b/g,
        /\?\?/g, // 空值合并
        /\?\./g, // 可选链
    ];
    let complexity = 1; // 基础复杂度
    for (const pattern of patterns) {
        const matches = code.match(pattern);
        if (matches)
            complexity += matches.length;
    }
    return complexity;
}
/** 计算最大嵌套深度 */
function calcMaxNestingDepth(code) {
    let maxDepth = 0;
    let currentDepth = 0;
    for (const char of code) {
        if (char === '{') {
            currentDepth++;
            maxDepth = Math.max(maxDepth, currentDepth);
        }
        else if (char === '}') {
            currentDepth = Math.max(0, currentDepth - 1);
        }
    }
    return maxDepth;
}
//# sourceMappingURL=base.js.map