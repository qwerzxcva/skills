"use strict";
// ============================================================
// 报告生成器 — 终端表格输出与 JSON 导出
// ============================================================
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.printReport = printReport;
const chalk_1 = __importDefault(require("chalk"));
const cli_table3_1 = __importDefault(require("cli-table3"));
// ── 复杂度等级样式 ──────────────────────────────────────────
const LEVEL_LABEL = {
    low: chalk_1.default.green('🟢 低'),
    medium: chalk_1.default.yellow('🟡 中'),
    high: chalk_1.default.red('🔴 高'),
    critical: chalk_1.default.bgRed.white(' 🔴 危险 '),
};
const LEVEL_ICON = {
    low: '🟢',
    medium: '🟡',
    high: '🔴',
    critical: '⛔',
};
const SUGGESTION_ICON = {
    'split-file': '📦',
    'extract-module': '🧩',
    'reduce-complexity': '🔧',
    'reduce-coupling': '🔗',
    'reduce-nesting': '📐',
    'split-function': '✂️',
    'use-dependency-injection': '💉',
};
const SEVERITY_STYLE = {
    info: chalk_1.default.blue,
    warning: chalk_1.default.yellow,
    critical: chalk_1.default.red.bold,
};
// ── 主报告函数 ──────────────────────────────────────────────
/**
 * 输出完整分析报告
 */
function printReport(result) {
    console.log('');
    printHeader(result.summary);
    console.log('');
    if (result.files.length === 0) {
        console.log(chalk_1.default.yellow('  未找到可分析的文件。'));
        console.log('');
        return;
    }
    // 按复杂度排序: critical > high > medium > low
    const levelOrder = { critical: 0, high: 1, medium: 2, low: 3 };
    const sorted = [...result.files].sort((a, b) => levelOrder[a.metrics.complexityLevel] - levelOrder[b.metrics.complexityLevel]);
    printFileTable(sorted);
    console.log('');
    // 打印高复杂度文件的详细建议
    const filesWithSuggestions = sorted.filter(f => f.suggestions.length > 0);
    if (filesWithSuggestions.length > 0) {
        printSuggestions(filesWithSuggestions);
        console.log('');
    }
    // 打印依赖关系热点
    printCouplingHotspots(sorted);
    console.log('');
    // 打印总结
    printSummary(result.summary);
    console.log('');
}
// ── 头部 ────────────────────────────────────────────────────
function printHeader(summary) {
    const langEntries = Object.entries(summary.languageBreakdown)
        .map(([lang, count]) => `${lang}(${count})`)
        .join(', ');
    const familyEntries = Object.entries(summary.familyBreakdown)
        .map(([fam, count]) => {
        const labels = { web: 'Web', ios: 'iOS', android: 'Android', unknown: '其他' };
        return `${labels[fam] || fam}: ${count}`;
    })
        .join(' | ');
    console.log(chalk_1.default.bold.cyan('┌───────────────────────────────────────────────────────────────┐'));
    console.log(chalk_1.default.bold.cyan('│') + chalk_1.default.bold.white('                    📊 项目复杂度分析报告                       ') + chalk_1.default.bold.cyan('│'));
    console.log(chalk_1.default.bold.cyan('├───────────────────────────────────────────────────────────────┤'));
    console.log(chalk_1.default.bold.cyan('│') + `  文件总数: ${chalk_1.default.bold(String(summary.totalFiles))}    代码行数: ${chalk_1.default.bold(String(summary.totalLines))}    函数: ${chalk_1.default.bold(String(summary.totalFunctions))}    类: ${chalk_1.default.bold(String(summary.totalClasses))}`.padEnd(63) + chalk_1.default.bold.cyan('│'));
    console.log(chalk_1.default.bold.cyan('│') + `  平均复杂度: ${chalk_1.default.bold(String(summary.avgComplexity))}    建议总数: ${chalk_1.default.bold(String(summary.totalSuggestions))}    严重: ${chalk_1.default.red.bold(String(summary.criticalSuggestions))}`.padEnd(63) + chalk_1.default.bold.cyan('│'));
    console.log(chalk_1.default.bold.cyan('│') + `  平台: ${familyEntries}`.padEnd(63) + chalk_1.default.bold.cyan('│'));
    console.log(chalk_1.default.bold.cyan('│') + `  语言: ${langEntries}`.padEnd(63) + chalk_1.default.bold.cyan('│'));
    console.log(chalk_1.default.bold.cyan('└───────────────────────────────────────────────────────────────┘'));
}
// ── 文件表格 ─────────────────────────────────────────────────
function printFileTable(files) {
    const table = new cli_table3_1.default({
        head: [
            chalk_1.default.bold('文件'),
            chalk_1.default.bold('语言'),
            chalk_1.default.bold('代码行'),
            chalk_1.default.bold('函数'),
            chalk_1.default.bold('类'),
            chalk_1.default.bold('CC最大'),
            chalk_1.default.bold('CC均值'),
            chalk_1.default.bold('扇出'),
            chalk_1.default.bold('嵌套'),
            chalk_1.default.bold('等级'),
        ],
        colWidths: [45, 10, 10, 8, 6, 10, 10, 8, 8, 12],
        style: { head: ['cyan'] },
        wordWrap: true,
    });
    for (const file of files) {
        const m = file.metrics;
        const name = truncatePath(file.relativePath, 42);
        table.push([
            name,
            file.language.substring(0, 4),
            String(m.codeLines),
            String(m.functionCount),
            String(m.classCount),
            colorCC(m.maxCyclomaticComplexity),
            String(m.avgCyclomaticComplexity),
            String(m.fanOut),
            colorNesting(m.maxNestingDepth),
            LEVEL_LABEL[m.complexityLevel],
        ]);
    }
    console.log(table.toString());
}
// ── 建议输出 ─────────────────────────────────────────────────
function printSuggestions(files) {
    console.log(chalk_1.default.bold.cyan('🔧 拆分与解耦建议:'));
    console.log(chalk_1.default.cyan('─'.repeat(60)));
    for (const file of files) {
        console.log('');
        console.log(chalk_1.default.bold.white(`  ${LEVEL_ICON[file.metrics.complexityLevel]} ${file.relativePath}`) +
            chalk_1.default.dim(` (CC: ${file.metrics.maxCyclomaticComplexity}, 行: ${file.metrics.codeLines}, 扇出: ${file.metrics.fanOut})`));
        for (const s of file.suggestions) {
            const icon = SUGGESTION_ICON[s.type] || '💡';
            const style = SEVERITY_STYLE[s.severity] || chalk_1.default.white;
            console.log(`     ${icon} ${style(s.message)}`);
            if (s.detail) {
                console.log(chalk_1.default.dim(`       ↳ ${s.detail}`));
            }
        }
    }
}
// ── 耦合热点 ─────────────────────────────────────────────────
function printCouplingHotspots(files) {
    // 按耦合度排序，取前 10
    const hotspots = [...files]
        .sort((a, b) => b.metrics.couplingScore - a.metrics.couplingScore)
        .slice(0, 10);
    if (hotspots[0]?.metrics.couplingScore <= 0)
        return;
    console.log(chalk_1.default.bold.cyan('🔗 耦合度热点 (Top 10):'));
    console.log(chalk_1.default.cyan('─'.repeat(60)));
    const table = new cli_table3_1.default({
        head: [chalk_1.default.bold('文件'), chalk_1.default.bold('扇出'), chalk_1.default.bold('扇入'), chalk_1.default.bold('耦合分'), chalk_1.default.bold('建议')],
        colWidths: [40, 8, 8, 10, 30],
        style: { head: ['cyan'] },
    });
    for (const file of hotspots) {
        const m = file.metrics;
        const couplingTip = m.fanOut > 10
            ? '依赖过多，建议解耦'
            : m.fanIn > 5
                ? '被多文件依赖，注意稳定性'
                : m.couplingScore > 15
                    ? '综合耦合度偏高'
                    : '正常';
        table.push([
            truncatePath(file.relativePath, 38),
            String(m.fanOut),
            String(m.fanIn),
            colorCoupling(m.couplingScore),
            couplingTip,
        ]);
    }
    console.log(table.toString());
}
// ── 总结 ─────────────────────────────────────────────────────
function printSummary(summary) {
    console.log(chalk_1.default.bold.cyan('📋 总结:'));
    console.log(chalk_1.default.cyan('─'.repeat(60)));
    const { highComplexityFiles, mediumComplexityFiles, lowComplexityFiles } = summary;
    console.log(`  复杂度分布: ${chalk_1.default.red(`高/危险 ${highComplexityFiles}`)} / ${chalk_1.default.yellow(`中 ${mediumComplexityFiles}`)} / ${chalk_1.default.green(`低 ${lowComplexityFiles}`)}`);
    if (summary.criticalSuggestions > 0) {
        console.log(chalk_1.default.red.bold(`  ⚠️  有 ${summary.criticalSuggestions} 个严重问题需要立即处理!`));
    }
    if (summary.highComplexityFiles === 0 && summary.criticalSuggestions === 0) {
        console.log(chalk_1.default.green('  ✅ 项目整体复杂度在可控范围内。'));
    }
    else if (summary.highComplexityFiles > 0) {
        console.log(chalk_1.default.yellow(`  💡 建议优先处理 ${summary.highComplexityFiles} 个高复杂度文件。`));
    }
    // 平台特定建议
    const families = Object.keys(summary.familyBreakdown);
    if (families.includes('ios')) {
        console.log(chalk_1.default.dim('  iOS 提示: 使用 extension 拆分类，用 protocol 降低耦合'));
    }
    if (families.includes('android')) {
        console.log(chalk_1.default.dim('  Android 提示: 使用 Hilt/Koin 依赖注入，MVVM 架构分层'));
    }
    if (families.includes('web')) {
        console.log(chalk_1.default.dim('  Web 提示: 按功能模块拆分，使用自定义 Hook/Composition'));
    }
}
// ── 辅助函数 ─────────────────────────────────────────────────
function truncatePath(p, maxLen) {
    if (p.length <= maxLen)
        return p;
    const parts = p.split('/');
    if (parts.length <= 2)
        return '...' + p.substring(p.length - maxLen + 3);
    return parts[0] + '/.../' + parts.slice(-2).join('/');
}
function colorCC(cc) {
    if (cc >= 20)
        return chalk_1.default.red.bold(String(cc));
    if (cc >= 10)
        return chalk_1.default.yellow(String(cc));
    return chalk_1.default.green(String(cc));
}
function colorNesting(depth) {
    if (depth > 4)
        return chalk_1.default.red.bold(String(depth));
    if (depth > 3)
        return chalk_1.default.yellow(String(depth));
    return chalk_1.default.green(String(depth));
}
function colorCoupling(score) {
    if (score > 30)
        return chalk_1.default.red.bold(String(score));
    if (score > 15)
        return chalk_1.default.yellow(String(score));
    return chalk_1.default.green(String(score));
}
//# sourceMappingURL=reporter.js.map