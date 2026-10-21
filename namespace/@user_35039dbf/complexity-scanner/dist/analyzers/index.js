"use strict";
// ============================================================
// 分析器注册表 — 管理所有语言分析器
// ============================================================
Object.defineProperty(exports, "__esModule", { value: true });
exports.KotlinAnalyzer = exports.SwiftAnalyzer = exports.TypeScriptAnalyzer = void 0;
exports.getAnalyzer = getAnalyzer;
exports.getAllAnalyzers = getAllAnalyzers;
exports.getSupportedExtensions = getSupportedExtensions;
exports.getAnalyzerByLanguage = getAnalyzerByLanguage;
const typescript_1 = require("./typescript");
const swift_1 = require("./swift");
const kotlin_1 = require("./kotlin");
/** 全局分析器注册表 */
const analyzers = [
    new typescript_1.TypeScriptAnalyzer(),
    new swift_1.SwiftAnalyzer(),
    new kotlin_1.KotlinAnalyzer(),
];
/** 根据文件路径获取合适的分析器 */
function getAnalyzer(filePath) {
    const ext = require('path').extname(filePath).toLowerCase();
    for (const analyzer of analyzers) {
        if (analyzer.extensions.includes(ext)) {
            return analyzer;
        }
    }
    return null;
}
/** 获取所有已注册的分析器 */
function getAllAnalyzers() {
    return analyzers;
}
/** 获取所有支持的文件扩展名 */
function getSupportedExtensions() {
    return analyzers.flatMap(a => a.extensions);
}
/** 获取指定语言的分析器 */
function getAnalyzerByLanguage(lang) {
    return analyzers.find(a => a.languages.includes(lang)) || null;
}
var typescript_2 = require("./typescript");
Object.defineProperty(exports, "TypeScriptAnalyzer", { enumerable: true, get: function () { return typescript_2.TypeScriptAnalyzer; } });
var swift_2 = require("./swift");
Object.defineProperty(exports, "SwiftAnalyzer", { enumerable: true, get: function () { return swift_2.SwiftAnalyzer; } });
var kotlin_2 = require("./kotlin");
Object.defineProperty(exports, "KotlinAnalyzer", { enumerable: true, get: function () { return kotlin_2.KotlinAnalyzer; } });
//# sourceMappingURL=index.js.map