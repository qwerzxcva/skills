#!/usr/bin/env node
"use strict";
// ============================================================
// complexity-scan — 项目文件复杂度检测 CLI
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
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const commander_1 = require("commander");
const chalk_1 = __importDefault(require("chalk"));
const ora_1 = __importDefault(require("ora"));
const path = __importStar(require("path"));
const fs = __importStar(require("fs"));
const scanner_1 = require("./scanner");
const analyzers_1 = require("./analyzers");
const metrics_1 = require("./core/metrics");
const reporter_1 = require("./core/reporter");
const VERSION = '1.0.0';
const program = new commander_1.Command();
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
    .action(async (directory, options) => {
    const rootDir = path.resolve(directory);
    // 验证目录
    if (!fs.existsSync(rootDir)) {
        console.error(chalk_1.default.red(`错误: 目录不存在 — ${rootDir}`));
        process.exit(1);
    }
    if (!fs.statSync(rootDir).isDirectory()) {
        console.error(chalk_1.default.red(`错误: 不是目录 — ${rootDir}`));
        process.exit(1);
    }
    // 解析选项
    const languages = parseLanguages(options.lang);
    const excludePatterns = options.exclude
        ? options.exclude.split(',').map((s) => s.trim()).filter(Boolean)
        : [];
    const outputFormat = options.format;
    const config = {
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
    const spinner = (0, ora_1.default)({ text: '扫描文件中...', spinner: 'dots' }).start();
    let files;
    try {
        files = (0, scanner_1.scanFiles)({
            rootDir,
            languages: config.languages,
            excludePatterns: config.excludePatterns,
            maxDepth: config.maxDepth,
        });
    }
    catch (err) {
        spinner.fail(chalk_1.default.red(`扫描失败: ${err.message}`));
        process.exit(1);
    }
    if (files.length === 0) {
        spinner.warn(chalk_1.default.yellow('未找到可分析的源文件'));
        console.log(chalk_1.default.dim(`  支持的文件类型: .ts .tsx .js .jsx .swift .kt .kts .java .m .mm`));
        console.log(chalk_1.default.dim(`  扫描目录: ${rootDir}`));
        if (languages.length > 0) {
            console.log(chalk_1.default.dim(`  指定语言: ${languages.join(', ')}`));
        }
        process.exit(0);
    }
    spinner.text = `分析 ${files.length} 个文件...`;
    // 分析文件
    const analyses = [];
    let processed = 0;
    for (const filePath of files) {
        const analyzer = (0, analyzers_1.getAnalyzer)(filePath);
        if (!analyzer)
            continue;
        try {
            const analysis = analyzer.analyze(filePath, rootDir);
            analyses.push(analysis);
        }
        catch (err) {
            // 跳过解析失败的文件
            console.error(chalk_1.default.dim(`  ⚠ 跳过 ${path.relative(rootDir, filePath)}: ${err.message}`));
        }
        processed++;
        if (processed % 50 === 0) {
            spinner.text = `分析中... (${processed}/${files.length})`;
        }
    }
    spinner.succeed(chalk_1.default.green(`分析完成: ${analyses.length} 个文件`));
    // 计算项目级指标
    (0, metrics_1.computeProjectMetrics)(analyses);
    // 生成摘要
    const summary = (0, metrics_1.generateSummary)(analyses, config);
    // 应用过滤
    let filteredFiles = analyses;
    if (options.top > 0) {
        filteredFiles = [...analyses]
            .sort((a, b) => b.metrics.maxCyclomaticComplexity - a.metrics.maxCyclomaticComplexity)
            .slice(0, parseInt(options.top, 10));
    }
    if (options.criticalOnly) {
        filteredFiles = filteredFiles.filter(f => f.suggestions.some(s => s.severity === 'critical'));
    }
    const result = {
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
            console.log(chalk_1.default.green(`\n✅ 报告已保存到: ${options.output}`));
        }
        else {
            console.log(jsonOutput);
        }
    }
    else {
        (0, reporter_1.printReport)(result);
    }
});
/**
 * 解析语言参数
 */
function parseLanguages(langStr) {
    if (!langStr)
        return [];
    const map = {
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
        .filter((s) => !!s);
}
program.parse();
//# sourceMappingURL=index.js.map