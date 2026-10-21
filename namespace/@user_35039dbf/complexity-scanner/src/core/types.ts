// ============================================================
// 核心类型定义
// ============================================================

/** 支持的编程语言 */
export type SupportedLanguage =
  | 'typescript'
  | 'javascript'
  | 'tsx'
  | 'jsx'
  | 'swift'
  | 'kotlin'
  | 'java'
  | 'objc'
  | 'unknown';

/** 语言分类 */
export type LanguageFamily = 'web' | 'ios' | 'android' | 'unknown';

/** 复杂度等级 */
export type ComplexityLevel = 'low' | 'medium' | 'high' | 'critical';

/** 输出格式 */
export type OutputFormat = 'table' | 'json' | 'summary';

/** 函数/方法信息 */
export interface FunctionInfo {
  name: string;
  startLine: number;
  endLine: number;
  lineCount: number;
  cyclomaticComplexity: number;
  cognitiveComplexity: number;
  nestingDepth: number;
  parameters: number;
}

/** 类/结构体信息 */
export interface ClassInfo {
  name: string;
  startLine: number;
  endLine: number;
  lineCount: number;
  methodCount: number;
  propertyCount: number;
}

/** 导入/依赖信息 */
export interface ImportInfo {
  source: string;
  specifiers: string[];
  isExternal: boolean;
  line: number;
}

/** 文件分析结果 */
export interface FileAnalysis {
  filePath: string;
  relativePath: string;
  language: SupportedLanguage;
  languageFamily: LanguageFamily;
  metrics: FileMetrics;
  functions: FunctionInfo[];
  classes: ClassInfo[];
  imports: ImportInfo[];
  suggestions: Suggestion[];
}

/** 文件指标 */
export interface FileMetrics {
  totalLines: number;
  codeLines: number;
  commentLines: number;
  blankLines: number;
  functionCount: number;
  classCount: number;
  maxCyclomaticComplexity: number;
  avgCyclomaticComplexity: number;
  maxCognitiveComplexity: number;
  maxNestingDepth: number;
  fanOut: number;
  fanIn: number;
  couplingScore: number;
  complexityLevel: ComplexityLevel;
}

/** 建议类型 */
export type SuggestionType =
  | 'split-file'
  | 'extract-module'
  | 'reduce-complexity'
  | 'reduce-coupling'
  | 'reduce-nesting'
  | 'split-function'
  | 'use-dependency-injection';

/** 建议 */
export interface Suggestion {
  type: SuggestionType;
  severity: 'info' | 'warning' | 'critical';
  message: string;
  detail?: string;
  targetFunction?: string;
  relatedFiles?: string[];
}

/** 扫描配置 */
export interface ScanConfig {
  rootDir: string;
  languages?: SupportedLanguage[];
  excludePatterns: string[];
  complexityThreshold: number;
  fileLineThreshold: number;
  functionLineThreshold: number;
  fanOutThreshold: number;
  nestingThreshold: number;
  outputFormat: OutputFormat;
  maxDepth: number;
}

/** 项目扫描结果 */
export interface ScanResult {
  config: ScanConfig;
  files: FileAnalysis[];
  summary: ProjectSummary;
  timestamp: string;
}

/** 项目摘要 */
export interface ProjectSummary {
  totalFiles: number;
  totalLines: number;
  totalFunctions: number;
  totalClasses: number;
  avgComplexity: number;
  highComplexityFiles: number;
  mediumComplexityFiles: number;
  lowComplexityFiles: number;
  totalSuggestions: number;
  criticalSuggestions: number;
  languageBreakdown: Record<string, number>;
  familyBreakdown: Record<string, number>;
}
