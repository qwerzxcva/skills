#!/usr/bin/env node
// ============================================================
// complexity-scan — 项目文件复杂度检测 CLI
// ============================================================

import { Command } from 'commander';
import chalk from 'chalk';
import ora from 'ora';
import * as path from 'path';
import * as fs from 'fs';
import { scanFiles } from './scanner';
import { getAnalyzer } from './analyzers';
import { computeProjectMetrics, generateSummary } from './core/metrics';
import { printReport } from './core/reporter';
import {
  ScanConfig,
  ScanResult,
  SupportedLanguage,
  OutputFormat,
} from './core/types';

const VERSION = '1.0.0';

const program = new Command();

program
  .name('complexity-scan')
  .description('检测项目文件复杂度，提供拆分建议，降低耦合度')
  .version(VERSION)
  .argument('[directory]', '要扫描的项目目录', '.')
  .option('-l, --lang <languages>', '只分析指定语言 (逗号分隔: ts,swift,kotlin,java,js,tsx,jsx,objc)')
  .option('-t, --threshold <number>', '圈复杂度告警阈值', '15')
  .option('--file-threshold <number>', '文件行数告警阈值', '300')
  .option('--func-threshold <number>', '函数行数告警阈值', '50')
  .option('--fanout-threshold <number>', '依赖扇出告警阈值', '10')
  .option('--nesting-threshold <number>', '嵌套深度告警阈值', '4')
  .option('-e, --exclude <patterns>', '排除目录 (逗号分隔)', '')
  .option('-f, --format <format>', '输出格式 (table|json|summary)', 'table')
  .option('-d, --depth <number>', '最大扫描深度 (0=不限)', '0')
  .option('-o, --output <file>', '输出 JSON 到文件')
  .option('--top <number>', '只显示最复杂的 N 个文件', '0')
  .option('--critical-only', '只显示严重问题')
  .action(async (directory: string, options: any) => {
    const rootDir = path.resolve(directory);

    // 验证目录
    if (!fs.existsSync(rootDir)) {
      console.error(chalk.red(`错误: 目录不存在 — ${rootDir}`));
      process.exit(1);
    }

    if (!fs.statSync(rootDir).isDirectory()) {
      console.error(chalk.red(`错误: 不是目录 — ${rootDir}`));
      process.exit(1);
    }

    // 解析选项
    const languages = parseLanguages(options.lang);
    const excludePatterns = options.exclude
      ? options.exclude.split(',').map((s: string) => s.trim()).filter(Boolean)
      : [];
    const outputFormat: OutputFormat = options.format;

    const config: ScanConfig = {
      rootDir,
      languages: languages.length > 0 ? languages : undefined,
      excludePatterns,
      complexityThreshold: parseInt(options.threshold, 10),
      fileLineThreshold: parseInt(options.fileThreshold, 10),
      functionLineThreshold: parseInt(options.funcThreshold, 10),
      fanOutThreshold: parseInt(options.fanoutThreshold, 10),
      nestingThreshold: parseInt(options.nestingThreshold, 10),
      outputFormat,
      maxDepth: parseInt(options.depth, 10),
    };

    // 扫描文件
    const spinner = ora({ text: '扫描文件中...', spinner: 'dots' }).start();

    let files: string[];
    try {
      files = scanFiles({
        rootDir,
        languages: config.languages,
        excludePatterns: config.excludePatterns,
        maxDepth: config.maxDepth,
      });
    } catch (err: any) {
      spinner.fail(chalk.red(`扫描失败: ${err.message}`));
      process.exit(1);
    }

    if (files.length === 0) {
      spinner.warn(chalk.yellow('未找到可分析的源文件'));
      console.log(chalk.dim(`  支持的文件类型: .ts .tsx .js .jsx .swift .kt .kts .java .m .mm`));
      console.log(chalk.dim(`  扫描目录: ${rootDir}`));
      if (languages.length > 0) {
        console.log(chalk.dim(`  指定语言: ${languages.join(', ')}`));
      }
      process.exit(0);
    }

    spinner.text = `分析 ${files.length} 个文件...`;

    // 分析文件
    const analyses: ScanResult['files'] = [];
    let processed = 0;

    for (const filePath of files) {
      const analyzer = getAnalyzer(filePath);
      if (!analyzer) continue;

      try {
        const analysis = analyzer.analyze(filePath, rootDir);
        analyses.push(analysis);
      } catch (err: any) {
        // 跳过解析失败的文件
        console.error(chalk.dim(`  ⚠ 跳过 ${path.relative(rootDir, filePath)}: ${err.message}`));
      }

      processed++;
      if (processed % 50 === 0) {
        spinner.text = `分析中... (${processed}/${files.length})`;
      }
    }

    spinner.succeed(chalk.green(`分析完成: ${analyses.length} 个文件`));

    // 计算项目级指标
    computeProjectMetrics(analyses);

    // 生成摘要
    const summary = generateSummary(analyses, config);

    // 应用过滤
    let filteredFiles = analyses;
    if (options.top > 0) {
      filteredFiles = [...analyses]
        .sort((a, b) => b.metrics.maxCyclomaticComplexity - a.metrics.maxCyclomaticComplexity)
        .slice(0, parseInt(options.top, 10));
    }
    if (options.criticalOnly) {
      filteredFiles = filteredFiles.filter(
        f => f.suggestions.some(s => s.severity === 'critical')
      );
    }

    const result: ScanResult = {
      config,
      files: filteredFiles,
      summary,
      timestamp: new Date().toISOString(),
    };

    // 输出
    if (outputFormat === 'json' || options.output) {
      const jsonOutput = JSON.stringify(result, null, 2);
      if (options.output) {
        fs.writeFileSync(options.output, jsonOutput, 'utf-8');
        console.log(chalk.green(`\n✅ 报告已保存到: ${options.output}`));
      } else {
        console.log(jsonOutput);
      }
    } else {
      printReport(result);
    }
  });

/**
 * 解析语言参数
 */
function parseLanguages(langStr?: string): SupportedLanguage[] {
  if (!langStr) return [];

  const map: Record<string, SupportedLanguage> = {
    ts: 'typescript',
    typescript: 'typescript',
    js: 'javascript',
    javascript: 'javascript',
    tsx: 'tsx',
    jsx: 'jsx',
    swift: 'swift',
    kotlin: 'kotlin',
    kt: 'kotlin',
    java: 'java',
    objc: 'objc',
  };

  return langStr
    .split(',')
    .map(s => s.trim().toLowerCase())
    .map(s => map[s])
    .filter((s): s is SupportedLanguage => !!s);
}

program.parse();
