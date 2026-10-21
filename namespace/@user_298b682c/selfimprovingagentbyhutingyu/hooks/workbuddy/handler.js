/**
 * WorkBuddy 自我改进 Hook
 *
 * WorkBuddy 没有每次工具调用的 Hook 事件，因此无法在每条命令之后实时检测错误。
 * 此 Hook 改用在会话结束时进行检测：
 *
 * - agent:bootstrap        在工作区文件注入之前注入自我改进提醒，
 *                          并在有待审核的自动检测错误时附加提示。
 * - command:new / :reset   会话结束扫描：扫描刚结束会话的对话记录中的
 *                          错误模式，将待处理条目追加到
 *                          <workspace>/.learnings/ERRORS.md。
 *
 * 扫描是可选的：仅在 <workspace>/.learnings/ 存在时运行。
 * 摘录在写入前会被截断和脱敏。
 */

const fs = require('node:fs/promises');
const path = require('node:path');

const REMINDER_NAME = 'SELF_IMPROVEMENT_REMINDER.md';
const REMINDER_PATH = REMINDER_NAME;
const REMINDER_HEADER = '## Self-Improvement Reminder';

const REMINDER_CONTENT = `
${REMINDER_HEADER}

完成任务后，评估是否有学习经验值得记录。

仅在此仓库或工作区正在使用自我改进 Skill 时记录。

记录前请注意：
- 仅创建缺失的 \`.learnings/\` 文件；绝不覆盖已有内容
- 不要记录密钥、令牌、私钥、环境变量或原始对话记录
- 优先使用简短摘要或脱敏摘录，而非完整命令输出

**记录场景：**
- 用户纠正你的错误 → \`.learnings/LEARNINGS.md\`
- 命令/操作失败 → \`.learnings/ERRORS.md\`
- 用户需要缺失的功能 → \`.learnings/FEATURE_REQUESTS.md\`
- 发现自己的知识有误 → \`.learnings/LEARNINGS.md\`
- 找到更优方法 → \`.learnings/LEARNINGS.md\`

**模式验证后提升：**
- 行为模式 → \`SOUL.md\`
- 工作流改进 → \`AGENTS.md\`
- 工具使用经验 → \`TOOLS.md\`

保持条目简洁：日期、标题、发生了什么、如何改进。
`.trim();

// 错误检测模式。按从具体到通用的顺序排列：第一个匹配的模式
// 提供标记在扫描条目上的 Pattern-Key，这使得自动检测的错误
// 可以按 key 去重和统计复现次数（参见 SKILL.md 中的
// "Pattern-Key 分类体系"部分）。
const ERROR_PATTERN_KEYS = [
  ['command not found', 'shell.command-not-found'],
  ['No such file', 'fs.no-such-file'],
  ['Permission denied', 'fs.permission-denied'],
  ['ModuleNotFoundError', 'deps.module-not-found'],
  ['npm ERR!', 'deps.npm-error'],
  ['Traceback', 'runtime.python-exception'],
  ['SyntaxError', 'runtime.syntax-error'],
  ['TypeError', 'runtime.type-error'],
  ['Exception', 'runtime.exception'],
  ['fatal:', 'vcs.fatal-error'],
  ['exit code', 'shell.nonzero-exit'],
  ['non-zero', 'shell.nonzero-exit'],
  ['error:', 'runtime.error'],
  ['Error:', 'runtime.error'],
  ['ERROR:', 'runtime.error'],
  ['failed', 'runtime.failure'],
  ['FAILED', 'runtime.failure'],
];

const SWEEP_SOURCE = 'workbuddy-error-sweep';
const MAX_EXCERPTS = 5;
const MAX_EXCERPT_LENGTH = 200;
const ERRORS_FILE_HEADER = '# Errors\n\nCommand failures and integration errors.\n\n---\n';

// 在写入任何内容之前，尽力脱敏常见密钥形态。
const REDACTION_RULES = [
  [/\b(api[_-]?key|token|secret|password|passwd|authorization|credential)s?\b(\s*[=:]\s*)\S+/gi, '$1$2[REDACTED]'],
  [/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, 'Bearer [REDACTED]'],
  [/\bgh[pousr]_[A-Za-z0-9]{16,}\b/g, '[REDACTED]'],
  [/\bxox[baprs]-[A-Za-z0-9-]{10,}\b/g, '[REDACTED]'],
  [/\bAKIA[0-9A-Z]{16}\b/g, '[REDACTED]'],
  [/\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\b/g, '[REDACTED-JWT]'],
  [/\b[A-Za-z0-9_-]{40,}\b/g, '[REDACTED-BLOB]'],
];

function isObject(value) {
  return !!value && typeof value === 'object';
}

function isInjectedReminderFile(value) {
  if (!isObject(value) || value.path !== REMINDER_PATH) {
    return false;
  }

  return (
    value.virtual === true ||
    (typeof value.content === 'string' && value.content.includes(REMINDER_HEADER))
  );
}

function redactSensitiveText(text) {
  let result = text;
  for (const [pattern, replacement] of REDACTION_RULES) {
    result = result.replace(pattern, replacement);
  }
  return result;
}

function sanitizeExcerptLine(line) {
  let excerpt = redactSensitiveText(line.trim()).split('```').join("'''");
  if (excerpt.length > MAX_EXCERPT_LENGTH) {
    excerpt = `${excerpt.slice(0, MAX_EXCERPT_LENGTH)}…`;
  }
  return excerpt;
}

function collectTextFragments(value, out, depth = 0) {
  if (depth > 4 || out.length > 200) {
    return;
  }
  if (typeof value === 'string') {
    out.push(value);
    return;
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      collectTextFragments(item, out, depth + 1);
    }
    return;
  }
  if (isObject(value)) {
    if (typeof value.text === 'string') {
      out.push(value.text);
    }
    if ('content' in value) {
      collectTextFragments(value.content, out, depth + 1);
    }
  }
}

function matchErrorPatternKey(line) {
  for (const [pattern, patternKey] of ERROR_PATTERN_KEYS) {
    if (line.includes(pattern)) {
      return patternKey;
    }
  }
  return null;
}

async function scanTranscriptForErrors(sessionFilePath) {
  let raw;
  try {
    raw = await fs.readFile(sessionFilePath, 'utf-8');
  } catch {
    return [];
  }

  const excerpts = [];
  const seen = new Set();

  for (const jsonLine of raw.split('\n')) {
    if (excerpts.length >= MAX_EXCERPTS) {
      break;
    }
    const trimmed = jsonLine.trim();
    if (!trimmed) {
      continue;
    }

    let entry;
    try {
      entry = JSON.parse(trimmed);
    } catch {
      continue;
    }
    if (!isObject(entry) || !isObject(entry.message)) {
      continue;
    }

    const fragments = [];
    collectTextFragments(entry.message.content, fragments);

    for (const fragment of fragments) {
      for (const line of fragment.split('\n')) {
        const patternKey = matchErrorPatternKey(line);
        if (!patternKey) {
          continue;
        }
        const excerpt = sanitizeExcerptLine(line);
        if (!excerpt || seen.has(excerpt)) {
          continue;
        }
        seen.add(excerpt);
        excerpts.push({ excerpt, patternKey });
        if (excerpts.length >= MAX_EXCERPTS) {
          return excerpts;
        }
      }
    }
  }

  return excerpts;
}

function resolveSessionFilePath(context, workspaceDir) {
  const sessionEntry = isObject(context.previousSessionEntry)
    ? context.previousSessionEntry
    : isObject(context.sessionEntry)
      ? context.sessionEntry
      : {};

  if (typeof sessionEntry.sessionFile === 'string' && sessionEntry.sessionFile.trim()) {
    return sessionEntry.sessionFile;
  }

  const sessionId =
    typeof sessionEntry.sessionId === 'string' ? sessionEntry.sessionId.trim() : '';
  if (sessionId && workspaceDir) {
    return path.join(workspaceDir, 'sessions', `${sessionId}.jsonl`);
  }

  return undefined;
}

function generateEntryId(timestamp) {
  const yyyymmdd = timestamp.toISOString().slice(0, 10).replace(/-/g, '');
  const suffix = Math.random().toString(36).slice(2, 5).toUpperCase().padEnd(3, '0');
  return `ERR-${yyyymmdd}-${suffix}`;
}

function formatErrorEntry(params) {
  const { excerpts, sessionKey, sessionFilePath, action, timestamp } = params;
  const plural = excerpts.length === 1 ? '' : 's';
  const patternKeys = [...new Set(excerpts.map((item) => item.patternKey))];

  return [
    `## [${generateEntryId(timestamp)}] workbuddy_session_sweep`,
    '',
    `**Logged**: ${timestamp.toISOString()}`,
    '**Priority**: medium',
    '**Status**: pending',
    '**Area**: config',
    '',
    '### Summary',
    `Session-end sweep detected ${excerpts.length} possible error${plural} in the previous WorkBuddy session.`,
    '',
    '### Error',
    '```',
    ...excerpts.map((item) => item.excerpt),
    '```',
    '',
    '### Context',
    `- Detected by the self-improving-agent-cn hook on \`/${action}\` (WorkBuddy has no per-tool-call hook, so errors are swept from the session transcript at session end)`,
    `- Session key: ${sessionKey || 'unknown'}`,
    `- Session transcript: ${sessionFilePath}`,
    '- Excerpts are truncated and redacted; check the transcript for full context',
    '',
    '### Suggested Fix',
    'Triage this entry: if the error was real and non-obvious, keep it and fill in the fix; otherwise mark it resolved or delete it. Before keeping it, grep for its Pattern-Key(s) and fold recurrences into the existing entry (bump Recurrence-Count) instead of duplicating.',
    '',
    '### Metadata',
    `- Source: ${SWEEP_SOURCE}`,
    '- Reproducible: unknown',
    ...patternKeys.map((patternKey) => `- Pattern-Key: ${patternKey}`),
    '',
    '---',
  ].join('\n');
}

async function handleSessionEndSweep(event) {
  const context = event.context;
  const workspaceDir =
    typeof context.workspaceDir === 'string' && context.workspaceDir.trim()
      ? context.workspaceDir
      : undefined;
  if (!workspaceDir) {
    return;
  }

  // 可选加入门槛：仅在工作区正在使用自我改进 Skill 时扫描。
  const learningsDir = path.join(workspaceDir, '.learnings');
  try {
    const stats = await fs.stat(learningsDir);
    if (!stats.isDirectory()) {
      return;
    }
  } catch {
    return;
  }

  const sessionFilePath = resolveSessionFilePath(context, workspaceDir);
  if (!sessionFilePath) {
    return;
  }

  const excerpts = await scanTranscriptForErrors(sessionFilePath);
  if (excerpts.length === 0) {
    return;
  }

  const errorsFilePath = path.join(learningsDir, 'ERRORS.md');
  let existing = '';
  try {
    existing = await fs.readFile(errorsFilePath, 'utf-8');
  } catch {
    // 文件缺失是正常的；下面会创建它。
  }

  const freshExcerpts = excerpts.filter((item) => !existing.includes(item.excerpt));
  if (freshExcerpts.length === 0) {
    return;
  }

  const entry = formatErrorEntry({
    excerpts: freshExcerpts,
    sessionKey: typeof event.sessionKey === 'string' ? event.sessionKey : '',
    sessionFilePath,
    action: event.action,
    timestamp: event.timestamp instanceof Date ? event.timestamp : new Date(),
  });

  if (!existing) {
    try {
      await fs.writeFile(errorsFilePath, `${ERRORS_FILE_HEADER}\n${entry}\n`, { flag: 'wx' });
      return;
    } catch (err) {
      if (!isObject(err) || err.code !== 'EEXIST') {
        throw err;
      }
    }
  }
  await fs.appendFile(errorsFilePath, `\n${entry}\n`);
}

async function countPendingSweepEntries(workspaceDir) {
  if (!workspaceDir) {
    return 0;
  }
  let content;
  try {
    content = await fs.readFile(path.join(workspaceDir, '.learnings', 'ERRORS.md'), 'utf-8');
  } catch {
    return 0;
  }

  return content
    .split(/^## /m)
    .slice(1)
    .filter(
      (section) =>
        section.includes(`Source: ${SWEEP_SOURCE}`) && section.includes('**Status**: pending'),
    ).length;
}

async function handleBootstrap(event) {
  // 跳过子 Agent 会话以避免 bootstrap 问题
  // 子 Agent 的 sessionKey 模式类似 "agent:main:subagent:..."
  const sessionKey = event.sessionKey || '';
  if (sessionKey.includes(':subagent:')) {
    return;
  }

  // 将提醒作为虚拟 bootstrap 文件注入
  // 在 push 之前检查 bootstrapFiles 是否为数组
  if (!Array.isArray(event.context.bootstrapFiles)) {
    return;
  }

  const occupiedByOtherFile = event.context.bootstrapFiles.some(
    (file) => isObject(file) && file.path === REMINDER_PATH && !isInjectedReminderFile(file),
  );
  if (occupiedByOtherFile) {
    return;
  }

  let reminderContent = REMINDER_CONTENT;
  const workspaceDir =
    typeof event.context.workspaceDir === 'string' && event.context.workspaceDir.trim()
      ? event.context.workspaceDir
      : undefined;
  const pendingSweepCount = await countPendingSweepEntries(workspaceDir);
  if (pendingSweepCount > 0) {
    const plural = pendingSweepCount === 1 ? 'y' : 'ies';
    reminderContent +=
      `\n\n**Pending triage:** ${pendingSweepCount} auto-detected error entr${plural} ` +
      `(Source: ${SWEEP_SOURCE}) in \`.learnings/ERRORS.md\` await review. ` +
      'Confirm, resolve, or delete them when convenient.';
  }

  const cleanedBootstrapFiles = event.context.bootstrapFiles.filter(
    (file, index, files) =>
      !isInjectedReminderFile(file) ||
      files.findIndex((candidate) => isInjectedReminderFile(candidate)) === index,
  );

  const reminderFile = {
    name: REMINDER_NAME,
    path: REMINDER_PATH,
    content: reminderContent,
    missing: false,
    virtual: true,
  };

  const existingIndex = cleanedBootstrapFiles.findIndex((file) => isInjectedReminderFile(file));
  if (existingIndex === -1) {
    cleanedBootstrapFiles.push(reminderFile);
  } else {
    cleanedBootstrapFiles[existingIndex] = reminderFile;
  }

  event.context.bootstrapFiles = cleanedBootstrapFiles;
}

const handler = async (event) => {
  // 事件结构安全检查
  if (!event || typeof event !== 'object') {
    return;
  }
  if (!event.context || typeof event.context !== 'object') {
    return;
  }

  try {
    if (event.type === 'agent' && event.action === 'bootstrap') {
      await handleBootstrap(event);
      return;
    }
    if (event.type === 'command' && (event.action === 'new' || event.action === 'reset')) {
      await handleSessionEndSweep(event);
    }
  } catch (err) {
    // Hook 失败绝不中断网关。
    if (process.env.SELF_IMPROVEMENT_DEBUG) {
      console.error('[self-improving-agent-cn] hook failed:', err);
    }
  }
};

module.exports = handler;
module.exports.default = handler;
