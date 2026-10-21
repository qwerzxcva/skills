// ============================================================
// 文件扫描器 — 发现并过滤待分析的源文件
// ============================================================

import * as fs from 'fs';
import * as path from 'path';
import { getSupportedExtensions } from './analyzers';
import { SupportedLanguage } from './core/types';
import { LANGUAGE_EXTENSIONS } from './analyzers/base';

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

export interface ScanOptions {
  rootDir: string;
  languages?: SupportedLanguage[];
  excludePatterns: string[];
  maxDepth: number;
}

/**
 * 递归扫描目录，收集所有可分析的源文件
 */
export function scanFiles(options: ScanOptions): string[] {
  const { rootDir, languages, excludePatterns, maxDepth } = options;
  const allExcludes = [...DEFAULT_EXCLUDE, ...excludePatterns];

  // 确定需要的扩展名
  let extensions: Set<string>;
  if (languages && languages.length > 0) {
    extensions = new Set<string>();
    for (const lang of languages) {
      const exts: string[] = LANGUAGE_EXTENSIONS[lang] || [];
      exts.forEach((e: string) => extensions.add(e));
    }
  } else {
    extensions = new Set(getSupportedExtensions());
  }

  const files: string[] = [];
  walkDir(rootDir, rootDir, extensions, allExcludes, files, 0, maxDepth);
  return files.sort();
}

function walkDir(
  currentDir: string,
  rootDir: string,
  extensions: Set<string>,
  excludes: string[],
  files: string[],
  depth: number,
  maxDepth: number
): void {
  if (maxDepth > 0 && depth > maxDepth) return;

  let entries: fs.Dirent[];
  try {
    entries = fs.readdirSync(currentDir, { withFileTypes: true });
  } catch {
    return; // 无权限或其他错误
  }

  for (const entry of entries) {
    const fullPath = path.join(currentDir, entry.name);

    if (entry.isDirectory()) {
      if (excludes.includes(entry.name)) continue;
      if (entry.name.startsWith('.') && entry.name !== '.') continue;
      walkDir(fullPath, rootDir, extensions, excludes, files, depth + 1, maxDepth);
    } else if (entry.isFile()) {
      const ext = path.extname(entry.name).toLowerCase();
      if (extensions.has(ext)) {
        // 跳过过大的文件 (> 1MB)
        try {
          const stat = fs.statSync(fullPath);
          if (stat.size > 1_000_000) continue;
        } catch {
          continue;
        }
        files.push(fullPath);
      }
    }
  }
}
