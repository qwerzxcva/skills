// ============================================================
// 分析器注册表 — 管理所有语言分析器
// ============================================================

import { Analyzer } from './base';
import { TypeScriptAnalyzer } from './typescript';
import { SwiftAnalyzer } from './swift';
import { KotlinAnalyzer } from './kotlin';
import { SupportedLanguage } from '../core/types';

/** 全局分析器注册表 */
const analyzers: Analyzer[] = [
  new TypeScriptAnalyzer(),
  new SwiftAnalyzer(),
  new KotlinAnalyzer(),
];

/** 根据文件路径获取合适的分析器 */
export function getAnalyzer(filePath: string): Analyzer | null {
  const ext = require('path').extname(filePath).toLowerCase();
  for (const analyzer of analyzers) {
    if (analyzer.extensions.includes(ext)) {
      return analyzer;
    }
  }
  return null;
}

/** 获取所有已注册的分析器 */
export function getAllAnalyzers(): Analyzer[] {
  return analyzers;
}

/** 获取所有支持的文件扩展名 */
export function getSupportedExtensions(): string[] {
  return analyzers.flatMap(a => a.extensions);
}

/** 获取指定语言的分析器 */
export function getAnalyzerByLanguage(lang: SupportedLanguage): Analyzer | null {
  return analyzers.find(a => a.languages.includes(lang)) || null;
}

export { Analyzer } from './base';
export { TypeScriptAnalyzer } from './typescript';
export { SwiftAnalyzer } from './swift';
export { KotlinAnalyzer } from './kotlin';
