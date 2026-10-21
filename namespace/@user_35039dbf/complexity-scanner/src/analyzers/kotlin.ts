// ============================================================
// Kotlin / Java 分析器 — 基于正则模式匹配
// ============================================================

import * as path from 'path';
import {
  FileAnalysis,
  FunctionInfo,
  ClassInfo,
  ImportInfo,
  FileMetrics,
  Suggestion,
  SupportedLanguage,
} from '../core/types';
import {
  Analyzer,
  readFileContent,
  countLines,
  classifyComplexity,
  calcCyclomaticComplexity,
  calcMaxNestingDepth,
} from './base';

export class KotlinAnalyzer implements Analyzer {
  languages: SupportedLanguage[] = ['kotlin', 'java'];
  family = 'android' as const;
  extensions = ['.kt', '.kts', '.java'];

  analyze(filePath: string, rootDir: string): FileAnalysis {
    const content = readFileContent(filePath);
    const relativePath = path.relative(rootDir, filePath);
    const lines = content.split('\n');
    const lang = this.detectLanguage(filePath);

    const functions = this.extractFunctions(lines, content, lang);
    const classes = this.extractClasses(lines, content, lang);
    const imports = this.extractImports(lines);

    const lineStats = countLines(content);
    const fanOut = imports.length;
    const maxCC = functions.length > 0
      ? Math.max(...functions.map(f => f.cyclomaticComplexity))
      : calcCyclomaticComplexity(content);
    const avgCC = functions.length > 0
      ? Math.round(functions.reduce((s, f) => s + f.cyclomaticComplexity, 0) / functions.length)
      : 0;
    const maxCognitive = functions.length > 0
      ? Math.max(...functions.map(f => f.cognitiveComplexity))
      : 0;
    const maxNesting = functions.length > 0
      ? Math.max(...functions.map(f => f.nestingDepth))
      : calcMaxNestingDepth(content);

    const complexityLevel = classifyComplexity(maxCC, lineStats.code, fanOut);
    const couplingScore = Math.round((fanOut * 3 + functions.length * 0.5) * 10) / 10;

    const metrics: FileMetrics = {
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

    const suggestions = this.generateSuggestions(metrics, functions, classes, lang);

    return {
      filePath,
      relativePath,
      language: lang,
      languageFamily: 'android',
      metrics,
      functions,
      classes,
      imports,
      suggestions,
    };
  }

  private detectLanguage(filePath: string): SupportedLanguage {
    return filePath.endsWith('.java') ? 'java' : 'kotlin';
  }

  private extractFunctions(lines: string[], content: string, lang: SupportedLanguage): FunctionInfo[] {
    const functions: FunctionInfo[] = [];
    // Kotlin: fun, Java: 返回类型 + 方法名
    const funcPattern = lang === 'kotlin'
      ? /^\s*(public\s+|private\s+|protected\s+|internal\s+|open\s+|override\s+|suspend\s+|inline\s+)*fun\s+(?:<[^>]+>\s+)?(\w+)/
      : /^\s*(public\s+|private\s+|protected\s+|static\s+|final\s+|abstract\s+|synchronized\s+|native\s+)*([\w<>\[\]]+)\s+(\w+)\s*\(/;

    let i = 0;
    while (i < lines.length) {
      const match = lines[i].match(funcPattern);
      if (match && !lines[i].trim().startsWith('//') && !lines[i].trim().startsWith('*')) {
        const name = lang === 'kotlin' ? match[2] : match[3];
        // 排除关键字
        if (['if', 'for', 'while', 'switch', 'catch', 'class', 'interface', 'enum'].includes(name)) {
          i++;
          continue;
        }

        const startLine = i + 1;
        const { endLine, body } = this.findBlockEnd(lines, i);
        const lineCount = endLine - startLine + 1;
        const cc = this.calcKotlinJavaComplexity(body);
        const cognitive = this.calcCognitive(body);
        const nesting = calcMaxNestingDepth(body);
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
      } else {
        i++;
      }
    }

    return functions;
  }

  private extractClasses(lines: string[], content: string, lang: SupportedLanguage): ClassInfo[] {
    const classes: ClassInfo[] = [];
    const classPattern = lang === 'kotlin'
      ? /^\s*(public\s+|private\s+|internal\s+|open\s+|abstract\s+|sealed\s+|data\s+)*(class|object|interface|enum\s+class)\s+(\w+)/
      : /^\s*(public\s+|private\s+|protected\s+|abstract\s+|final\s+|static\s+)*(class|interface|enum)\s+(\w+)/;

    let i = 0;
    while (i < lines.length) {
      const match = lines[i].match(classPattern);
      if (match && !lines[i].trim().startsWith('//')) {
        const name = match[3];
        const startLine = i + 1;
        const { endLine, body } = this.findBlockEnd(lines, i);

        const methodPattern = lang === 'kotlin'
          ? /\bfun\s+\w+/g
          : /\b(public|private|protected|static)\s+[\w<>\[\]]+\s+\w+\s*\(/g;
        const methodCount = (body.match(methodPattern) || []).length;
        const propPattern = lang === 'kotlin'
          ? /\b(val|var)\s+\w+/g
          : /\b(private|public|protected|static)\s+[\w<>\[\]]+\s+\w+\s*[;=]/g;
        const propertyCount = (body.match(propPattern) || []).length;

        classes.push({
          name,
          startLine,
          endLine,
          lineCount: endLine - startLine + 1,
          methodCount,
          propertyCount,
        });
        i = endLine;
      } else {
        i++;
      }
    }

    return classes;
  }

  private extractImports(lines: string[]): ImportInfo[] {
    const imports: ImportInfo[] = [];
    const importPattern = /^\s*import\s+([\w.]+)/;

    for (let i = 0; i < lines.length; i++) {
      const match = lines[i].match(importPattern);
      if (match) {
        const source = match[1];
        imports.push({
          source,
          specifiers: [source.split('.').pop() || source],
          isExternal: !source.startsWith('com.example'),
          line: i + 1,
        });
      }
    }

    return imports;
  }

  private findBlockEnd(lines: string[], startLine: number): { endLine: number; body: string } {
    let depth = 0;
    let started = false;
    const bodyLines: string[] = [];

    for (let i = startLine; i < lines.length; i++) {
      const line = lines[i];
      for (const char of line) {
        if (char === '{') { depth++; started = true; }
        else if (char === '}') { depth--; }
      }
      bodyLines.push(line);
      if (started && depth === 0) {
        return { endLine: i + 1, body: bodyLines.join('\n') };
      }
    }
    return { endLine: lines.length, body: bodyLines.join('\n') };
  }

  private calcKotlinJavaComplexity(code: string): number {
    let cc = 1;
    const patterns = [
      /\bif\s*\(/g,
      /\belse\s+if\s*\(/g,
      /\bfor\s*\(/g,
      /\bwhile\s*\(/g,
      /\bdo\s*\{/g,
      /\bswitch\s*\(/g,
      /\bcase\s+/g,
      /\bcatch\s*\(/g,
      /\bwhen\s*\(/g,          // Kotlin when
      /\?\s*[^:]+:/g,          // 三元运算符
      /\b&&\b/g,
      /\b\|\|\b/g,
      /\?\./g,                 // 安全调用
      /\?\?/g,                 // Elvis 运算符
      /\btry\b/g,
    ];

    for (const pattern of patterns) {
      const matches = code.match(pattern);
      if (matches) cc += matches.length;
    }

    return cc;
  }

  private calcCognitive(code: string): number {
    let cognitive = 0;
    let nestingLevel = 0;

    const lines = code.split('\n');
    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.includes('{')) nestingLevel++;
      if (trimmed.includes('}')) nestingLevel = Math.max(0, nestingLevel - 1);

      const isControl = /\b(if|for|while|switch|when|catch|try)\b/.test(trimmed);
      if (isControl) {
        cognitive += 1 + nestingLevel;
      }
    }

    return cognitive;
  }

  private generateSuggestions(
    metrics: FileMetrics,
    functions: FunctionInfo[],
    classes: ClassInfo[],
    lang: SupportedLanguage
  ): Suggestion[] {
    const suggestions: Suggestion[] = [];
    const langName = lang === 'kotlin' ? 'Kotlin' : 'Java';

    if (metrics.maxCyclomaticComplexity > 20) {
      suggestions.push({
        type: 'split-file',
        severity: 'critical',
        message: `最大圈复杂度 ${metrics.maxCyclomaticComplexity} 超过阈值 20`,
        detail: `${langName} 文件建议控制在 200 行以内`,
      });
    }

    if (metrics.codeLines > 300) {
      suggestions.push({
        type: 'split-file',
        severity: 'warning',
        message: `代码行数 ${metrics.codeLines} 超过 300 行`,
        detail: lang === 'kotlin'
          ? '建议将功能拆分到扩展函数或独立文件'
          : '建议按职责拆分为多个类',
      });
    }

    if (metrics.fanOut > 10) {
      suggestions.push({
        type: 'reduce-coupling',
        severity: 'warning',
        message: `导入数量 ${metrics.fanOut} 过多`,
        detail: '建议使用接口抽象和依赖注入 (Dagger/Hilt/Koin)',
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
          targetFunction: fn.name,
        });
      }
      if (fn.nestingDepth > 3) {
        suggestions.push({
          type: 'reduce-nesting',
          severity: 'warning',
          message: `函数 ${fn.name} 嵌套深度 ${fn.nestingDepth}`,
          detail: lang === 'kotlin'
            ? '建议使用 ?.let / early return / when 表达式'
            : '建议使用 early return / 策略模式',
          targetFunction: fn.name,
        });
      }
    }

    for (const cls of classes) {
      if (cls.methodCount > 15) {
        suggestions.push({
          type: 'extract-module',
          severity: 'warning',
          message: `${cls.name} 有 ${cls.methodCount} 个方法`,
          detail: lang === 'kotlin'
            ? '建议使用扩展函数拆分功能'
            : '建议拆分为多个职责单一的类',
        });
      }
    }

    return suggestions;
  }
}
