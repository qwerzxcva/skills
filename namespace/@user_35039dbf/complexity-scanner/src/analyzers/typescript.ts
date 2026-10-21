// ============================================================
// TypeScript / JavaScript 分析器 — 基于 TS Compiler API
// ============================================================

import * as ts from 'typescript';
import * as path from 'path';
import {
  FileAnalysis,
  FunctionInfo,
  ClassInfo,
  ImportInfo,
  FileMetrics,
  Suggestion,
  SupportedLanguage,
  ComplexityLevel,
} from '../core/types';
import {
  Analyzer,
  readFileContent,
  countLines,
  classifyComplexity,
  calcMaxNestingDepth,
} from './base';

export class TypeScriptAnalyzer implements Analyzer {
  languages: SupportedLanguage[] = ['typescript', 'javascript', 'tsx', 'jsx'];
  family = 'web' as const;
  extensions = ['.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs'];

  analyze(filePath: string, rootDir: string): FileAnalysis {
    const content = readFileContent(filePath);
    const relativePath = path.relative(rootDir, filePath);
    const lang = this.detectLanguage(filePath);

    // 创建 TS 源文件 AST
    const sourceFile = ts.createSourceFile(
      filePath,
      content,
      ts.ScriptTarget.Latest,
      true
    );

    const functions: FunctionInfo[] = [];
    const classes: ClassInfo[] = [];
    const imports: ImportInfo[] = [];

    this.visitNode(sourceFile, functions, classes, imports, content);

    const lineStats = countLines(content);
    const fanOut = imports.length;
    const maxCC = functions.length > 0
      ? Math.max(...functions.map(f => f.cyclomaticComplexity))
      : 0;
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
      fanIn: 0, // 需要项目级分析
      couplingScore,
      complexityLevel,
    };

    const suggestions = this.generateSuggestions(metrics, functions, classes, relativePath);

    return {
      filePath,
      relativePath,
      language: lang,
      languageFamily: 'web',
      metrics,
      functions,
      classes,
      imports,
      suggestions,
    };
  }

  private detectLanguage(filePath: string): SupportedLanguage {
    const ext = path.extname(filePath).toLowerCase();
    if (ext === '.tsx') return 'tsx';
    if (ext === '.jsx') return 'jsx';
    if (ext === '.ts') return 'typescript';
    return 'javascript';
  }

  private visitNode(
    node: ts.Node,
    functions: FunctionInfo[],
    classes: ClassInfo[],
    imports: ImportInfo[],
    sourceText: string
  ): void {
    // 检测导入
    if (ts.isImportDeclaration(node)) {
      const moduleSpecifier = node.moduleSpecifier;
      if (ts.isStringLiteral(moduleSpecifier)) {
        const specifiers: string[] = [];
        if (node.importClause) {
          if (node.importClause.name) specifiers.push(node.importClause.name.text);
          if (node.importClause.namedBindings) {
            if (ts.isNamedImports(node.importClause.namedBindings)) {
              for (const el of node.importClause.namedBindings.elements) {
                specifiers.push(el.name.text);
              }
            }
          }
        }
        imports.push({
          source: moduleSpecifier.text,
          specifiers,
          isExternal: !moduleSpecifier.text.startsWith('.'),
          line: this.getLineNumber(sourceText, node.getStart()),
        });
      }
    }

    // 检测函数/方法
    if (
      ts.isFunctionDeclaration(node) ||
      ts.isMethodDeclaration(node) ||
      ts.isArrowFunction(node) ||
      ts.isFunctionExpression(node)
    ) {
      const name = this.getFunctionName(node);
      const startLine = this.getLineNumber(sourceText, node.getStart());
      const endLine = this.getLineNumber(sourceText, node.getEnd());
      const bodyText = node.getText();
      const cc = this.calcNodeComplexity(node);
      const cognitive = this.calcCognitiveComplexity(node);
      const nesting = this.calcNodeNesting(node);
      const params = this.getParameterCount(node);

      functions.push({
        name,
        startLine,
        endLine,
        lineCount: endLine - startLine + 1,
        cyclomaticComplexity: cc,
        cognitiveComplexity: cognitive,
        nestingDepth: nesting,
        parameters: params,
      });
    }

    // 检测类
    if (ts.isClassDeclaration(node)) {
      const name = node.name?.text || '<anonymous>';
      const startLine = this.getLineNumber(sourceText, node.getStart());
      const endLine = this.getLineNumber(sourceText, node.getEnd());
      let methodCount = 0;
      let propertyCount = 0;

      for (const member of node.members) {
        if (ts.isMethodDeclaration(member)) methodCount++;
        if (ts.isPropertyDeclaration(member)) propertyCount++;
      }

      classes.push({
        name,
        startLine,
        endLine,
        lineCount: endLine - startLine + 1,
        methodCount,
        propertyCount,
      });
    }

    ts.forEachChild(node, child =>
      this.visitNode(child, functions, classes, imports, sourceText)
    );
  }

  private getFunctionName(node: ts.Node): string {
    if (ts.isFunctionDeclaration(node)) return node.name?.text || '<anonymous>';
    if (ts.isMethodDeclaration(node)) {
      const key = node.name;
      if (ts.isIdentifier(key)) return key.text;
      if (ts.isStringLiteral(key)) return key.text;
      return '<computed>';
    }
    if (ts.isVariableDeclaration(node.parent)) {
      const name = node.parent.name;
      if (ts.isIdentifier(name)) return name.text;
    }
    // arrow function / function expression 走到这里
    if ('parent' in node && node.parent && ts.isVariableDeclaration(node.parent as ts.Node)) {
      const parent = node.parent as ts.VariableDeclaration;
      if (ts.isIdentifier(parent.name)) return parent.name.text;
    }
    return '<anonymous>';
  }

  private getParameterCount(node: ts.Node): number {
    if ('parameters' in node && ts.isFunctionLike(node)) {
      return (node as ts.FunctionLikeDeclaration).parameters.length;
    }
    return 0;
  }

  /** 计算节点的圈复杂度 */
  private calcNodeComplexity(node: ts.Node): number {
    let complexity = 1;
    const visit = (n: ts.Node) => {
      if (ts.isIfStatement(n)) complexity++;
      if (ts.isForStatement(n) || ts.isForInStatement(n) || ts.isForOfStatement(n)) complexity++;
      if (ts.isWhileStatement(n)) complexity++;
      if (ts.isDoStatement(n)) complexity++;
      if (ts.isSwitchStatement(n)) {
        complexity += n.caseBlock.clauses.length;
      }
      if (ts.isCatchClause(n)) complexity++;
      if (ts.isConditionalExpression(n)) complexity++;
      if (n.kind === ts.SyntaxKind.AmpersandAmpersandToken) complexity++;
      if (n.kind === ts.SyntaxKind.BarBarToken) complexity++;
      if (n.kind === ts.SyntaxKind.QuestionQuestionToken) complexity++;
      ts.forEachChild(n, visit);
    };
    visit(node);
    return complexity;
  }

  /** 计算认知复杂度 (考虑嵌套权重) */
  private calcCognitiveComplexity(node: ts.Node): number {
    let complexity = 0;
    let nestingLevel = 0;

    const visit = (n: ts.Node, depth: number) => {
      const isControl = ts.isIfStatement(n) || ts.isForStatement(n) ||
        ts.isForInStatement(n) || ts.isForOfStatement(n) ||
        ts.isWhileStatement(n) || ts.isDoStatement(n) ||
        ts.isSwitchStatement(n) || ts.isCatchClause(n);

      if (isControl) {
        complexity += 1 + depth; // 嵌套越深，权重越高
      }
      if (ts.isConditionalExpression(n)) {
        complexity += 1 + depth;
      }

      const nextDepth = isControl ? depth + 1 : depth;
      ts.forEachChild(n, child => visit(child, nextDepth));
    };

    visit(node, 0);
    return complexity;
  }

  /** 计算节点最大嵌套深度 */
  private calcNodeNesting(node: ts.Node): number {
    let maxDepth = 0;
    let currentDepth = 0;

    const visit = (n: ts.Node) => {
      const isBlock =
        ts.isBlock(n) || ts.isSwitchStatement(n);
      if (isBlock) currentDepth++;
      maxDepth = Math.max(maxDepth, currentDepth);
      ts.forEachChild(n, visit);
      if (isBlock) currentDepth--;
    };

    visit(node);
    return maxDepth;
  }

  private getLineNumber(sourceText: string, position: number): number {
    return sourceText.substring(0, position).split('\n').length;
  }

  private generateSuggestions(
    metrics: FileMetrics,
    functions: FunctionInfo[],
    classes: ClassInfo[],
    filePath: string
  ): Suggestion[] {
    const suggestions: Suggestion[] = [];

    // 文件整体复杂度过高
    if (metrics.maxCyclomaticComplexity > 20) {
      suggestions.push({
        type: 'split-file',
        severity: 'critical',
        message: `最大圈复杂度 ${metrics.maxCyclomaticComplexity} 超过阈值 20，建议拆分文件`,
        detail: `当前文件包含 ${metrics.functionCount} 个函数，${metrics.classCount} 个类`,
      });
    }

    // 文件行数过多
    if (metrics.codeLines > 300) {
      suggestions.push({
        type: 'split-file',
        severity: 'warning',
        message: `代码行数 ${metrics.codeLines} 超过 300 行，建议按职责拆分`,
      });
    }

    // 依赖扇出过高
    if (metrics.fanOut > 10) {
      suggestions.push({
        type: 'reduce-coupling',
        severity: 'warning',
        message: `依赖扇出 ${metrics.fanOut} 超过阈值 10，耦合度过高`,
        detail: '建议使用依赖注入或门面模式降低耦合',
      });
    }

    // 函数级建议
    for (const fn of functions) {
      if (fn.cyclomaticComplexity > 15) {
        suggestions.push({
          type: 'split-function',
          severity: 'critical',
          message: `函数 ${fn.name} 圈复杂度 ${fn.cyclomaticComplexity} 过高`,
          detail: `位于第 ${fn.startLine}-${fn.endLine} 行，${fn.lineCount} 行代码`,
          targetFunction: fn.name,
        });
      }
      if (fn.lineCount > 50) {
        suggestions.push({
          type: 'split-function',
          severity: 'warning',
          message: `函数 ${fn.name} 有 ${fn.lineCount} 行，建议拆分`,
          targetFunction: fn.name,
        });
      }
      if (fn.nestingDepth > 4) {
        suggestions.push({
          type: 'reduce-nesting',
          severity: 'warning',
          message: `函数 ${fn.name} 嵌套深度 ${fn.nestingDepth} 过深`,
          detail: '建议使用 early return、提取子函数或策略模式',
          targetFunction: fn.name,
        });
      }
      if (fn.parameters > 5) {
        suggestions.push({
          type: 'reduce-complexity',
          severity: 'info',
          message: `函数 ${fn.name} 有 ${fn.parameters} 个参数，建议使用配置对象`,
          targetFunction: fn.name,
        });
      }
    }

    // 类级建议
    for (const cls of classes) {
      if (cls.methodCount > 15) {
        suggestions.push({
          type: 'extract-module',
          severity: 'warning',
          message: `类 ${cls.name} 有 ${cls.methodCount} 个方法，职责过多`,
          detail: '建议按单一职责原则拆分为多个类',
        });
      }
    }

    return suggestions;
  }
}
