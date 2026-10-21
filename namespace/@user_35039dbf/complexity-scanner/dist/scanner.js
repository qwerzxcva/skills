"use strict";
// ============================================================
// 文件扫描器 — 发现并过滤待分析的源文件
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
exports.scanFiles = scanFiles;
const fs = __importStar(require("fs"));
const path = __importStar(require("path"));
const analyzers_1 = require("./analyzers");
const base_1 = require("./analyzers/base");
const DEFAULT_EXCLUDE = [
    'node_modules',
    '.git',
    'dist',
    'build',
    '.build',
    'DerivedData',
    'Pods',
    'Carthage',
    '.gradle',
    'vendor',
    'target',
    'bin',
    'obj',
    '__pycache__',
    '.next',
    '.nuxt',
    'coverage',
    '.idea',
    '.vscode',
    'xcuserdata',
];
/**
 * 递归扫描目录，收集所有可分析的源文件
 */
function scanFiles(options) {
    const { rootDir, languages, excludePatterns, maxDepth } = options;
    const allExcludes = [...DEFAULT_EXCLUDE, ...excludePatterns];
    // 确定需要的扩展名
    let extensions;
    if (languages && languages.length > 0) {
        extensions = new Set();
        for (const lang of languages) {
            const exts = base_1.LANGUAGE_EXTENSIONS[lang] || [];
            exts.forEach((e) => extensions.add(e));
        }
    }
    else {
        extensions = new Set((0, analyzers_1.getSupportedExtensions)());
    }
    const files = [];
    walkDir(rootDir, rootDir, extensions, allExcludes, files, 0, maxDepth);
    return files.sort();
}
function walkDir(currentDir, rootDir, extensions, excludes, files, depth, maxDepth) {
    if (maxDepth > 0 && depth > maxDepth)
        return;
    let entries;
    try {
        entries = fs.readdirSync(currentDir, { withFileTypes: true });
    }
    catch {
        return; // 无权限或其他错误
    }
    for (const entry of entries) {
        const fullPath = path.join(currentDir, entry.name);
        if (entry.isDirectory()) {
            if (excludes.includes(entry.name))
                continue;
            if (entry.name.startsWith('.') && entry.name !== '.')
                continue;
            walkDir(fullPath, rootDir, extensions, excludes, files, depth + 1, maxDepth);
        }
        else if (entry.isFile()) {
            const ext = path.extname(entry.name).toLowerCase();
            if (extensions.has(ext)) {
                // 跳过过大的文件 (> 1MB)
                try {
                    const stat = fs.statSync(fullPath);
                    if (stat.size > 1000000)
                        continue;
                }
                catch {
                    continue;
                }
                files.push(fullPath);
            }
        }
    }
}
//# sourceMappingURL=scanner.js.map