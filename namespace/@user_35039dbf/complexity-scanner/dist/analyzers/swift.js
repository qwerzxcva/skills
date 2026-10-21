"use strict";
// ============================================================
// Swift 分析器 — 基于正则模式匹配
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
exports.SwiftAnalyzer = void 0;
const path = __importStar(require("path"));
const base_1 = require("./base");
class SwiftAnalyzer {
    constructor() {
        this.languages = ['swift'];
        this.family = 'ios';
        this.extensions = ['.swift'];
    }
    analyze(filePath, rootDir) {
        const content = (0, base_1.readFileContent)(filePath);
        const relativePath = path.relative(rootDir, filePath);
        const lines = content.split('\n');
        const functions = this.extractFunctions(lines, content);
        const classes = this.extractClasses(lines, content);
        const imports = this.extractImports(lines);
        const lineStats = (0, base_1.countLines)(content);
        const fanOut = imports.length;
        const maxCC = functions.length > 0
            ? Math.max(...functions.map(f => f.cyclomaticComplexity))
            : (0, base_1.calcCyclomaticComplexity)(content);
        const avgCC = functions.length > 0
            ? Math.round(functions.reduce((s, f) => s + f.cyclomaticComplexity, 0) / functions.length)
            : 0;
        const maxCognitive = functions.length > 0
            ? Math.max(...functions.map(f => f.cognitiveComplexity))
            : 0;
        const maxNesting = functions.length > 0
            ? Math.max(...functions.map(f => f.nestingDepth))
            : (0, base_1.calcMaxNestingDepth)(content);
        const complexityLevel = (0, base_1.classifyComplexity)(maxCC, lineStats.code, fanOut);
        const couplingScore = Math.round((fanOut * 3 + functions.length * 0.5) * 10) / 10;
        const metrics = {
            totalLines: lineStats.total,
            codeLines: lineStats.code,
            commentLines: lineStats.comment,
            blankLines: lineStats.blank,
            functionCount: functions.length,
            classCount: classes.length,
            maxCyclomaticComplexity: maxCC,
            avgCyclomaticComplexity: avgCC,
            maxCognitiveComplexity: maxCognitive,
            maxNestingDepth: maxNesting,
            fanOut,
            fanIn: 0,
            couplingScore,
            complexityLevel,
        };
        const suggestions = this.generateSuggestions(metrics, functions, classes);
        return {
            filePath,
            relativePath,
            language: 'swift',
            languageFamily: 'ios',
            metrics,
            functions,
            classes,
            imports,
            suggestions,
        };
    }
    extractFunctions(lines, content) {
        const functions = [];
        // 匹配 func 关键字 (包括实例方法和静态方法)
        const funcPattern = /^\s*(public\s+|private\s+|internal\s+|open\s+|fileprivate\s+|static\s+|class\s+)*func\s+(\w+)/;
        // 也匹配闭包赋值: let handler = { ... }
        let i = 0;
        while (i < lines.length) {
            const match = lines[i].match(funcPattern);
            if (match) {
                const name = match[2];
                const startLine = i + 1;
                const { endLine, body } = this.findBlockEnd(lines, i);
                const lineCount = endLine - startLine + 1;
                const cc = this.calcSwiftComplexity(body);
                const cognitive = this.calcSwiftCognitive(body);
                const nesting = (0, base_1.calcMaxNestingDepth)(body);
                const params = (lines[i].match(/,/g) || []).length + 1;
                functions.push({
                    name,
                    startLine,
                    endLine,
                    lineCount,
                    cyclomaticComplexity: cc,
                    cognitiveComplexity: cognitive,
                    nestingDepth: nesting,
                    parameters: params,
                });
                i = endLine;
            }
            else {
                i++;
            }
        }
        return functions;
    }
    extractClasses(lines, content) {
        const classes = [];
        // 匹配 class, struct, enum, protocol
        const classPattern = /^\s*(public\s+|private\s+|internal\s+|open\s+|fileprivate\s+)*(class|struct|enum|protocol)\s+(\w+)/;
        let i = 0;
        while (i < lines.length) {
            const match = lines[i].match(classPattern);
            if (match) {
                const name = match[3];
                const startLine = i + 1;
                const { endLine, body } = this.findBlockEnd(lines, i);
                const methodCount = (body.match(/\bfunc\s+\w+/g) || []).length;
                const propertyCount = (body.match(/\b(var|let)\s+\w+/g) || []).length;
                classes.push({
                    name,
                    startLine,
                    endLine,
                    lineCount: endLine - startLine + 1,
                    methodCount,
                    propertyCount,
                });
                i = endLine;
            }
            else {
                i++;
            }
        }
        return classes;
    }
    extractImports(lines) {
        const imports = [];
        const importPattern = /^\s*import\s+(\w+)/;
        for (let i = 0; i < lines.length; i++) {
            const match = lines[i].match(importPattern);
            if (match) {
                const source = match[1];
                imports.push({
                    source,
                    specifiers: [source],
                    isExternal: true,
                    line: i + 1,
                });
            }
        }
        return imports;
    }
    /** 找到代码块的结束位置 (匹配花括号) */
    findBlockEnd(lines, startLine) {
        let depth = 0;
        let started = false;
        const bodyLines = [];
        for (let i = startLine; i < lines.length; i++) {
            const line = lines[i];
            for (const char of line) {
                if (char === '{') {
                    depth++;
                    started = true;
                }
                else if (char === '}') {
                    depth--;
                }
            }
            bodyLines.push(line);
            if (started && depth === 0) {
                return { endLine: i + 1, body: bodyLines.join('\n') };
            }
        }
        return { endLine: lines.length, body: bodyLines.join('\n') };
    }
    /** Swift 特定的圈复杂度计算 */
    calcSwiftComplexity(code) {
        let cc = 1;
        // Swift 控制流
        const patterns = [
            /\bif\s+/g,
            /\blet\s+.+\s*=\s*.*\?/g, // if let
            /\bguard\s+/g,
            /\bfor\s+/g,
            /\bwhile\s+/g,
            /\brepeat\s+/g,
            /\bswitch\s+/g,
            /\bcase\s+/g,
            /\bcatch\s+/g,
            /\btry\?/g,
            /\btry!/g,
            /\?\?/g, // nil 合并
            /\b&&\b/g,
            /\b\|\|\b/g,
        ];
        for (const pattern of patterns) {
            const matches = code.match(pattern);
            if (matches)
                cc += matches.length;
        }
        return cc;
    }
    /** 认知复杂度 */
    calcSwiftCognitive(code) {
        let cognitive = 0;
        let nestingLevel = 0;
        const lines = code.split('\n');
        for (const line of lines) {
            const trimmed = line.trim();
            if (trimmed.includes('{'))
                nestingLevel++;
            if (trimmed.includes('}'))
                nestingLevel = Math.max(0, nestingLevel - 1);
            const isControl = /\b(if|guard|for|while|switch|catch)\b/.test(trimmed);
            if (isControl) {
                cognitive += 1 + nestingLevel;
            }
        }
        return cognitive;
    }
    generateSuggestions(metrics, functions, classes) {
        const suggestions = [];
        if (metrics.maxCyclomaticComplexity > 20) {
            suggestions.push({
                type: 'split-file',
                severity: 'critical',
                message: `最大圈复杂度 ${metrics.maxCyclomaticComplexity} 超过阈值 20`,
                detail: `包含 ${metrics.functionCount} 个函数，建议按功能模块拆分`,
            });
        }
        if (metrics.codeLines > 300) {
            suggestions.push({
                type: 'split-file',
                severity: 'warning',
                message: `代码行数 ${metrics.codeLines} 超过 300 行`,
                detail: 'Swift 推荐单文件 200 行以内，建议使用 extension 拆分',
            });
        }
        if (metrics.fanOut > 10) {
            suggestions.push({
                type: 'reduce-coupling',
                severity: 'warning',
                message: `导入数量 ${metrics.fanOut} 过多`,
                detail: '建议使用协议抽象降低模块间依赖',
            });
        }
        for (const fn of functions) {
            if (fn.cyclomaticComplexity > 15) {
                suggestions.push({
                    type: 'split-function',
                    severity: 'critical',
                    message: `函数 ${fn.name} 圈复杂度 ${fn.cyclomaticComplexity} 过高`,
                    detail: `第 ${fn.startLine}-${fn.endLine} 行`,
                    targetFunction: fn.name,
                });
            }
            if (fn.lineCount > 40) {
                suggestions.push({
                    type: 'split-function',
                    severity: 'warning',
                    message: `函数 ${fn.name} 有 ${fn.lineCount} 行`,
                    detail: 'Swift 推荐函数 20 行以内',
                    targetFunction: fn.name,
                });
            }
            if (fn.nestingDepth > 3) {
                suggestions.push({
                    type: 'reduce-nesting',
                    severity: 'warning',
                    message: `函数 ${fn.name} 嵌套深度 ${fn.nestingDepth}`,
                    detail: '建议使用 guard let 提前返回',
                    targetFunction: fn.name,
                });
            }
        }
        for (const cls of classes) {
            if (cls.methodCount > 12) {
                suggestions.push({
                    type: 'extract-module',
                    severity: 'warning',
                    message: `${cls.name} 有 ${cls.methodCount} 个方法`,
                    detail: '建议使用 extension 按协议/功能拆分',
                });
            }
        }
        return suggestions;
    }
}
exports.SwiftAnalyzer = SwiftAnalyzer;
//# sourceMappingURL=swift.js.map