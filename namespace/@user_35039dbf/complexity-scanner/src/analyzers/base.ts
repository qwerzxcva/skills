// ============================================================
// 分析器基类 — 所有语言分析器的抽象接口
// ============================================================

import * as fs from 'fs';
import * as path from 'path';
import {
  SupportedLanguage,
  LanguageFamily,
  FileAnalysis,
  FunctionInfo,
  ClassInfo,
  ImportInfo,
  FileMetrics,
  ComplexityLevel,
  Suggestion,
} from '../core/types';

/** 分析器接口 */
export interface Analyzer {
  /** 该分析器支持的语言 */
  languages: SupportedLanguage[];
  /** 语言分类 */
  family: LanguageFamily;
  /** 文件扩展名映射 */
  extensions: string[];
  /** 分析文件 */
  analyze(filePath: string, rootDir: string): FileAnalysis;
}

/** 语言 → 扩展名映射 */
export const LANGUAGE_EXTENSIONS: Record<SupportedLanguage, string[]> = {
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
export const LANGUAGE_FAMILY: Record<SupportedLanguage, LanguageFamily> = {
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
export function inferLanguage(filePath: string): SupportedLanguage {
  const ext = path.extname(filePath).toLowerCase();
  for (const [lang, exts] of Object.entries(LANGUAGE_EXTENSIONS)) {
    if (exts.includes(ext)) return lang as SupportedLanguage;
  }
  return 'unknown';
}

/** 读取文件内容 */
export function readFileContent(filePath: string): string {
  return fs.readFileSync(filePath, 'utf-8');
}

/** 计算行数统计 */
export function countLines(content: string): {
  total: number;
  code: number;
  comment: number;
  blank: number;
} {
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
      if (trimmed.includes('*/')) inBlockComment = false;
      continue;
    }
    if (trimmed.startsWith('//') || trimmed.startsWith('#') || trimmed.startsWith('/*')) {
      comment++;
      if (trimmed.startsWith('/*') && !trimmed.includes('*/')) inBlockComment = true;
      continue;
    }
    code++;
  }

  return { total: lines.length, code, comment, blank };
}

/** 判断复杂度等级 */
export function classifyComplexity(
  cyclomaticComplexity: number,
  lineCount: number,
  fanOut: number
): ComplexityLevel {
  const score = cyclomaticComplexity * 2 + Math.floor(lineCount / 50) + fanOut;
  if (score >= 60) return 'critical';
  if (score >= 35) return 'high';
  if (score >= 15) return 'medium';
  return 'low';
}

/** 计算圈复杂度 (通用正则方式) */
export function calcCyclomaticComplexity(code: string): number {
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
    /\b\?\s*[^:]+:/g,      // 三元运算符
    /\b&&\b/g,
    /\b\|\|\b/g,
    /\?\?/g,                // 空值合并
    /\?\./g,                // 可选链
  ];

  let complexity = 1; // 基础复杂度
  for (const pattern of patterns) {
    const matches = code.match(pattern);
    if (matches) complexity += matches.length;
  }
  return complexity;
}

/** 计算最大嵌套深度 */
export function calcMaxNestingDepth(code: string): number {
  let maxDepth = 0;
  let currentDepth = 0;

  for (const char of code) {
    if (char === '{') {
      currentDepth++;
      maxDepth = Math.max(maxDepth, currentDepth);
    } else if (char === '}') {
      currentDepth = Math.max(0, currentDepth - 1);
    }
  }
  return maxDepth;
}
