// ============================================================
// 指标引擎 — 项目级指标聚合与 fan-in 计算
// ============================================================

import * as path from 'path';
import { FileAnalysis, ProjectSummary, ScanConfig } from './types';

/**
 * 计算项目级指标 (fan-in 等跨文件依赖)
 */
export function computeProjectMetrics(files: FileAnalysis[]): void {
  // 构建文件名 → 分析结果的映射
  const fileMap = new Map<string, FileAnalysis>();
  for (const f of files) {
    fileMap.set(f.relativePath, f);
    // 也用文件名(不含路径)做索引
    const basename = path.basename(f.relativePath, path.extname(f.relativePath));
    if (!fileMap.has(basename)) {
      fileMap.set(basename, f);
    }
  }

  // 计算 fan-in: 有多少文件导入了当前文件
  for (const file of files) {
    let fanIn = 0;
    for (const other of files) {
      if (other === file) continue;
      for (const imp of other.imports) {
        // 匹配导入路径与文件路径
        const target = imp.source;
        if (matchImport(target, file.relativePath, file.filePath)) {
          fanIn++;
          break; // 同一文件只计一次
        }
      }
    }
    file.metrics.fanIn = fanIn;
    // 更新耦合度评分 (fan-in 权重较小，fan-out 权重较大)
    file.metrics.couplingScore = Math.round(
      (file.metrics.fanOut * 3 + file.metrics.fanIn * 1.5 + file.metrics.functionCount * 0.5) * 10
    ) / 10;
  }
}

/**
 * 匹配导入路径与文件路径
 */
function matchImport(importPath: string, relativePath: string, fullPath: string): boolean {
  // 去掉文件扩展名
  const relNoExt = relativePath.replace(/\.[^.]+$/, '');
  const importNorm = importPath.replace(/\.[^.]+$/, '');

  // 精确匹配
  if (importNorm === relNoExt) return true;
  if (importNorm.endsWith('/' + path.basename(relNoExt))) return true;

  // 匹配 basename
  const baseName = path.basename(relNoExt);
  if (importNorm === baseName) return true;
  if (importNorm.endsWith('/' + baseName)) return true;

  return false;
}

/**
 * 生成项目摘要
 */
export function generateSummary(files: FileAnalysis[], config: ScanConfig): ProjectSummary {
  const totalFiles = files.length;
  const totalLines = files.reduce((s, f) => s + f.metrics.codeLines, 0);
  const totalFunctions = files.reduce((s, f) => s + f.metrics.functionCount, 0);
  const totalClasses = files.reduce((s, f) => s + f.metrics.classCount, 0);

  const complexities = files.map(f => f.metrics.maxCyclomaticComplexity);
  const avgComplexity = complexities.length > 0
    ? Math.round(complexities.reduce((s, c) => s + c, 0) / complexities.length)
    : 0;

  const highComplexityFiles = files.filter(f => f.metrics.complexityLevel === 'critical' || f.metrics.complexityLevel === 'high').length;
  const mediumComplexityFiles = files.filter(f => f.metrics.complexityLevel === 'medium').length;
  const lowComplexityFiles = files.filter(f => f.metrics.complexityLevel === 'low').length;

  const totalSuggestions = files.reduce((s, f) => s + f.suggestions.length, 0);
  const criticalSuggestions = files.reduce(
    (s, f) => s + f.suggestions.filter(sv => sv.severity === 'critical').length, 0
  );

  // 语言分布
  const languageBreakdown: Record<string, number> = {};
  const familyBreakdown: Record<string, number> = {};

  for (const f of files) {
    languageBreakdown[f.language] = (languageBreakdown[f.language] || 0) + 1;
    familyBreakdown[f.languageFamily] = (familyBreakdown[f.languageFamily] || 0) + 1;
  }

  return {
    totalFiles,
    totalLines,
    totalFunctions,
    totalClasses,
    avgComplexity,
    highComplexityFiles,
    mediumComplexityFiles,
    lowComplexityFiles,
    totalSuggestions,
    criticalSuggestions,
    languageBreakdown,
    familyBreakdown,
  };
}
