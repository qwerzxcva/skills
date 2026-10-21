#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
进程守护脚本 v1.0
自动监测monitor.py的运行状态，异常退出时自动重启

核心能力：
  - 每5分钟检查一次监测进程是否存活
  - 进程意外死亡后自动重启（最多重启5次/天）
  - 仅在交易时间内(9:15-15:10)守护
  - 非交易时间不启动也不重启
  - 守护日志记录到 guardian.log
  - 支持Windows/Linux/Mac跨平台
  - 支持后台静默运行

用法：
  # 启动守护（后台）
  python guardian.py start --stock "sh600023:浙能电力:2.0"
  
  # 停止守护
  python guardian.py stop
  
  # 查看状态
  python guardian.py status
  
  # 直接前台运行（调试用）
  python guardian.py run --stock "sh600023:浙能电力:2.0"
  
  # 作为独立守护循环运行（推荐方式，开机自启）
  python guardian.py daemon --stock "sh600023:浙能电力:2.0"
"""

import sys
import os
import time
import json
import signal
import subprocess
import platform
from datetime import datetime, time as dtime, date
from typing import Optional, List, Dict

# Windows GBK兼容
if sys.platform == 'win32':
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass


# ============================================================
# 路径配置
# ============================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(SCRIPT_DIR, 'guardian.log')
STATE_FILE = os.path.join(SCRIPT_DIR, '.guardian_state.json')
PID_FILE = os.path.join(SCRIPT_DIR, '.guardian.pid')
MONITOR_SCRIPT = os.path.join(SCRIPT_DIR, 'monitor.py')
PYTHON_EXE = sys.executable  # 当前Python解释器


# ============================================================
# 交易时间判断
# ============================================================

def is_trading_time() -> bool:
    """
    判断当前是否在交易时间内
    
    A股交易时间：
      - 上午：9:15 ~ 11:35（含竞价+延后缓冲）
      - 下午：12:55 ~ 15:10（含尾盘+缓冲）
    
    排除周末和法定节假日（简单判断，不考虑调休）
    
    Returns:
        True=在交易时间内需要监控
    """
    now = datetime.now()
    
    # 排除周末
    if now.weekday() >= 5:
        return False
    
    t = now.time()
    
    # 上午时段
    morning_start = dtime(9, 15)
    morning_end = dtime(11, 35)
    
    # 下午时段
    afternoon_start = dtime(12, 55)
    afternoon_end = dtime(15, 10)
    
    return (morning_start <= t <= morning_end) or (afternoon_start <= t <= afternoon_end)


def is_market_open() -> bool:
    """
    判断市场是否已开盘（9:25竞价结束后算开盘）
    """
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    
    t = now.time()
    return t >= dtime(9, 25) and t <= dtime(15, 5)


def seconds_until_market_close() -> int:
    """距离收盘还有多少秒"""
    now = datetime.now()
    close_time = datetime(now.year, now.month, now.day, 15, 10)
    if now >= close_time:
        return 0
    return int((close_time - now).total_seconds())


def seconds_until_market_open() -> int:
    """距离开盘还有多少秒（9:15）"""
    now = datetime.now()
    open_time = datetime(now.year, now.month, now.day, 9, 15)
    if now < open_time:
        return int((open_time - now).total_seconds())
    # 已过今天开盘，返回明天
    from datetime import timedelta
    tomorrow_open = open_time + timedelta(days=1)
    # 跳过周末
    while tomorrow_open.weekday() >= 5:
        tomorrow_open += timedelta(days=1)
    return int((tomorrow_open - now).total_seconds())


# ============================================================
# 进程管理
# ============================================================

class ProcessManager:
    """跨平台进程管理器"""

    @staticmethod
    def find_monitor_processes() -> List[Dict]:
        """
        查找所有正在运行的monitor.py进程
        
        Returns:
            进程信息列表 [{'pid': int, 'cmdline': str, 'start_time': str}, ...]
        """
        results = []
        
        if platform.system() == 'Windows':
            try:
                import subprocess
                output = subprocess.check_output(
                    ['wmic', 'process', 'where', 
                     f"name='python.exe' and commandline like '%monitor.py%'", 
                     'get', 'ProcessId,CommandLine', '/format:list'],
                    encoding='utf-8', errors='ignore', timeout=10
                )
                lines = [l.strip() for l in output.strip().split('\n\n') if l.strip()]
                for block in lines:
                    pid = cmdline = ''
                    for line in block.split('\n'):
                        if line.startswith('ProcessId'):
                            pid = line.split('=')[-1].strip()
                        elif line.startswith('CommandLine'):
                            cmdline = line.split('=', 1)[-1].strip() if '=' in line else ''
                    if pid and cmdline:
                        results.append({'pid': int(pid), 'cmdline': cmdline})
            except subprocess.CalledProcessError:
                pass
            except Exception:
                pass
        else:
            # Linux/Mac 用ps命令
            try:
                output = subprocess.check_output(
                    ['ps', 'aux'], 
                    timeout=10
                ).decode('utf-8', errors='ignore')
                for line in output.split('\n'):
                    if 'monitor.py' in line and 'grep' not in line:
                        parts = line.split(None, 10)
                        if len(parts) >= 11:
                            results.append({
                                'pid': int(parts[1]),
                                'cmdline': parts[10],
                            })
            except Exception:
                pass
        
        return results

    @staticmethod
    def kill_process(pid: int) -> bool:
        """杀掉指定进程"""
        try:
            if platform.system() == 'Windows':
                os.kill(pid, signal.SIGTERM)
            else:
                import subprocess
                subprocess.run(['kill', str(pid)], timeout=5)
            
            time.sleep(1)  # 等待进程退出
            return True
        except Exception as e:
            print(f"[Guardian] 杀进程{pid}失败: {e}")
            return False

    @staticmethod
    def start_monitor(stock_config: str, duration_minutes: int = 390,
                      interval: int = 30) -> Optional[subprocess.Popen]:
        """
        启动一个monitor.py进程
        
        Args:
            stock_config: "sh600023:浙能电力:2.0"
            duration_minutes: 运行时长(分钟)
            interval: 监测间隔(秒)
        
        Returns:
            Popen对象或None
        """
        if not os.path.exists(MONITOR_SCRIPT):
            print(f"[Guardian] 找不到 {MONITOR_SCRIPT}")
            return None
        
        cmd_args = [
            PYTHON_EXE, '-X', 'utf8',
            MONITOR_SCRIPT,
            f'"{stock_config}"',
            '--interval', str(interval),
            '--duration', str(duration_minutes),
        ]

        cmd_str = ' '.join(cmd_args)
        
        print(f"[Guardian] 启动监测: {cmd_str}")

        try:
            if platform.system() == 'Windows':
                # Windows后台启动
                proc = subprocess.Popen(
                    cmd_str,
                    shell=True,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                    stdout=open(os.devnull, 'w'),
                    stderr=open(os.devnull, 'w'),
                )
            else:
                proc = subprocess.Popen(
                    cmd_args,
                    shell=True,
                    stdout=open(os.devnull, 'w'),
                    stderr=open(os.devnull, 'w'),
                    preexec_fn=os.setsid,
                )

            print(f"[Guardian] monitor.py PID={proc.pid} 启动成功")
            return proc
            
        except Exception as e:
            print(f"[Guardian] 启动失败: {e}")
            return None


# ============================================================
# 状态管理
# ============================================================

class GuardianState:
    """守护状态持久化"""

    def __init__(self):
        self.state = {
            'stock_config': '',
            'start_count_today': 0,
            'restart_count_today': 0,
            'max_restarts_per_day': 5,
            'last_restart_time': None,
            'date': date.today().isoformat(),
            'guardian_pid': os.getpid(),
            'status': 'stopped',  # stopped / running / paused
            'history': [],
        }
        self._load()

    def _load(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                # 新的一天重置计数器
                if saved.get('date') != date.today().isoformat():
                    saved['restart_count_today'] = 0
                    saved['start_count_today'] = 0
                    saved['date'] = date.today().isoformat()
                self.state.update(saved)
            except Exception:
                pass

    def _save(self):
        try:
            with open(STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Guardian] 状态保存失败: {e}")

    def can_restart(self) -> bool:
        """判断今天还能不能重启"""
        return self.state['restart_count_today'] < self.state['max_restarts_per_day']

    def record_restart(self):
        """记录一次重启"""
        self.state['restart_count_today'] += 1
        self.state['last_restart_time'] = datetime.now().isoformat()
        self.state['history'].append({
            'action': 'restart',
            'time': datetime.now().isoformat(),
        })
        # 只保留最近20条历史
        self.state['history'] = self.state['history'][-20:]
        self._save()

    def set_stock(self, stock_config: str):
        self.state['stock_config'] = stock_config
        self._save()

    def set_status(self, status: str):
        self.state['status'] = status
        self._save()


# ============================================================
# 日志系统
# ============================================================

class GuardianLogger:
    """简单日志"""

    @staticmethod
    def log(message: str, level: str = 'INFO'):
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        line = f"[{ts}] [{level}] {message}"
        print(line)
        try:
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except Exception:
            pass


# ============================================================
# 核心守护类
# ============================================================

class StockGuardian:
    """
    股票监测进程守护者
    
    工作模式：
      1. 检查交易时间 → 非交易时间休眠
      2. 检查monitor.py进程是否存在
      3. 不存在且在交易时间 → 自动重启
      4. 记录重启次数，超过上限停止
      5. 收盘后进入等待模式
    """

    CHECK_INTERVAL = 300  # 5分钟检查一次
    OFF_HOURS_CHECK = 900  # 非交易时间每15分钟检查一次（等开盘）

    def __init__(self, stock_config: str = '', duration: int = 390, interval: int = 30):
        self.stock_config = stock_config
        self.duration = duration
        self.interval = interval
        self.state = GuardianState()
        self.logger = GuardianLogger()
        self.running = True
        self.monitor_proc = None
        
        if stock_config:
            self.state.set_stock(stock_config)

    def check_and_maintain(self) -> bool:
        """
        执行一次检查和维护
        
        Returns:
            True=一切正常或已修复, False=不可修复
        """
        processes = ProcessManager.find_monitor_processes()
        
        # === 情况1：进程在跑 → 正常 ===
        if processes:
            pids = [p['pid'] for p in processes]
            self.logger.log(f"monitor.py 运行中(PID: {pids}) ✅")
            return True
        
        # === 情况2：进程不在跑 ===
        self.logger.log("monitor.py 未运行 ⚠️", "WARN")
        
        # 检查是否在交易时间
        if not is_trading_time():
            self.logger.log("非交易时间，暂不启动。等待开盘...")
            return False
        
        # 检查重启次数
        if not self.state.can_restart():
            self.logger.log(
                f"今日已重启{self.state['restart_count_today']}次"
                f"(上限{self.state['max_restarts_per_day']}次)，不再自动重启",
                "ERROR"
            )
            self.state.set_status('paused')
            return False
        
        # 尝试重启
        self.logger.log(f"尝试自动重启... (第{self.state['restart_count_today']+1}次)")
        
        config = self.state.get('stock_config', '') or self.stock_config
        if not config:
            self.logger.log("未设置股票配置，无法启动", "ERROR")
            return False
        
        proc = ProcessManager.start_monitor(config, self.duration, self.interval)
        if proc:
            self.state.record_restart()
            self.state.set_status('running')
            self.logger.log(f"自动重启成功！PID={proc.pid} ✅")
            return True
        else:
            self.logger.log("自动重启失败 ❌", "ERROR")
            return False

    def run_once(self):
        """执行一次检查（用于定时任务调用）"""
        return self.check_and_maintain()

    def daemon_loop(self):
        """
        守护主循环 — 持续运行直到被终止
        
        这是最推荐的运行方式，作为后台服务持续运行
        """
        self.logger("=" * 60)
        self.logger.log("🦀 StockGuardian 守护进程启动")
        self.logger.log(f"  股票配置: {self.stock_config or '(从状态文件读取)'}")
        self.logger.log(f"  检查间隔: {self.CHECK_INTERVAL}秒")
        self.logger.log(f"  最大重启次数/天: {self.state['max_restarts_per_day']}")
        self.logger("=" * 60)

        # 写入PID文件
        try:
            with open(PID_FILE, 'w') as f:
                f.write(str(os.getpid()))
        except Exception:
            pass
        
        self.state.set_status('running')

        while self.running:
            try:
                now = datetime.now()
                
                # === 非交易时间处理 ===
                if not is_trading_time():
                    # 计算下次开盘时间
                    wait_seconds = self.OFF_HOURS_CHECK
                    
                    # 如果刚过收盘不久，给个提示
                    if now.hour == 15 and now.minute < 30:
                        self.logger.log("收盘了，今日守护结束。明天见！👋")
                    
                    # 如果是早上还没到开盘
                    if now.hour < 9 or (now.hour == 9 and now.minute < 14):
                        secs_to_open = seconds_until_market_open()
                        if secs_to_open > 0 and secs_to_open < self.OFF_HOURS_CHECK:
                            wait_seconds = secs_to_open
                            hours_left = secs_to_open // 3600
                            mins_left = (secs_to_open % 3600) // 60
                            self.logger.log(
                                f"距开盘还有{hours_left}小时{mins_left}分钟，届时自动启动..."
                            )
                    
                    time.sleep(wait_seconds)
                    continue
                
                # === 交易时间：执行检查 ===
                self.check_and_maintain()
                
                # 等待下一次检查
                time.sleep(self.CHECK_INTERVAL)
                
                # 收盘后重置次日标志
                if now.date() != date.today():
                    self.state.state['restart_count_today'] = 0
                    self.state.state['date'] = date.today().isoformat()
                    self._save()
                    
            except KeyboardInterrupt:
                self.logger.log("收到中断信号，正在关闭...")
                self.running = False
                break
            except Exception as e:
                self.logger.log(f"守护循环异常: {e}", "ERROR")
                time.sleep(60)  # 异常时等待1分钟再试
        
        self.state.set_status('stopped')
        # 清理PID文件
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        self.logger.log("StockGuardian 已停止")

    def stop(self):
        """停止守护"""
        self.running = False
        self.state.set_status('stopped')


# ============================================================
# 命令行入口
# ============================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='🦀 股票监测进程守护者',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python guardian.py start --stock "sh600023:浙能电力:2.0"   # 后台启动守护
  python guardian.py daemon --stock "sh600023:浙能电力:2.0"   # 前台守护循环
  python guardian.py status                                     # 查看状态
  python guardian.py stop                                        # 停止守护
  python guardian.py check                                       # 单次检查
        """
    )

    parser.add_argument('command', nargs='?', default='run',
                        choices=['start', 'stop', 'daemon', 'status', 'check', 'run'],
                        help='命令')

    parser.add_argument('--stock', '-s', default='',
                        help='股票配置 (格式: "sh600023:浙能电力:2.0")')
    parser.add_argument('--duration', '-d', type=int, default=390,
                        help='monitor运行时长(分钟), 默认390(全天)')
    parser.add_argument('--interval', '-i', type=int, default=30,
                        help='monitor监测间隔(秒), 默认30')

    args = parser.parse_args()

    guardian = StockGuardian(
        stock_config=args.stock or '',
        duration=args.duration,
        interval=args.interval,
    )

    if args.command == 'start':
        # Windows后台启动守护
        if platform.system() == 'Windows':
            stock_arg = args.stock or guardian.state.get('stock_config', '')
            if not stock_arg:
                print("❌ 请使用 --stock 指定要守护的股票")
                return
            cmd = (
                f'cd /d "{SCRIPT_DIR}" && '
                f'{PYTHON_EXE} -X utf8 "{os.path.abspath(__file__)}" daemon '
                f'--stock "{stock_arg}" '
                f'--duration {args.duration} --interval {args.interval}'
            )
            print(f"启动后台守护...")
            subprocess.Popen(
                cmd,
                shell=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                stdout=open(os.devnull, 'w'),
                stderr=open(os.devnull, 'w'),
            )
            print(f"✅ 守护已在后台启动，PID信息写入 {PID_FILE}")
            print(f"   日志: {LOG_FILE}")
            print(f"   使用 `python guardian.py status` 查看状态")
            print(f"   使用 `python guardian.py stop` 停止守护")
        else:
            # Linux/Mac用nohup
            stock_arg = args.stock or guardian.state.get('stock_config', '')
            cmd = [
                'nohup', PYTHON_EXE, '-X', 'utf8',
                os.path.abspath(__file__), 'daemon',
                '--stock', stock_arg,
                '--duration', str(args.duration),
                '--interval', str(args.interval),
                '>', os.devnull, '2>&1', '&'
            ]
            subprocess.Popen(' '.join(cmd), shell=True)
            print("✅ 守护已后台启动")

    elif args.command == 'daemon':
        # 前台守护循环（主要运行模式）
        if not args.stock and not guardian.state.get('stock_config'):
            print("❌ 请先通过 `python guardian.py start --stock xxx` 设置股票配置")
            return
        guardian.daemon_loop()

    elif args.command == 'stop':
        # 停止守护
        if os.path.exists(PID_FILE):
            with open(PID_FILE, 'r') as f:
                pid = f.read().strip()
            try:
                os.kill(int(pid), signal.SIGTERM)
                print(f"✅ 守护进程(PID:{pid})已发送停止信号")
                if os.path.exists(PID_FILE):
                    os.remove(PID_FILE)
            except Exception as e:
                print(f"⚠️ 停止失败: {e}")
                # 尝试用进程名杀
                procs = ProcessManager.find_monitor_processes()
                for p in procs:
                    if 'guardian' in p.get('cmdline', '').lower():
                        ProcessManager.kill_process(p['pid'])
                        print(f"✅ 强制停止守护(PID:{p['pid']})")
        else:
            # 没有PID文件，尝试找进程
            print("没有找到守护进程PID文件")
            
            # 也停掉所有monitor进程
            procs = ProcessManager.find_monitor_processes()
            if procs:
                for p in procs:
                    ProcessManager.kill_process(p['pid'])
                    print(f"  monitor.py(PID:{p['pid']})已停止")

    elif args.command == 'status':
        # 显示状态
        state = guardian.state.state
        print("\n" + "=" * 50)
        print("  📊 StockGuardian 状态")
        print("=" * 50)
        print(f"  状态:       {state.get('status', 'unknown')}")
        print(f"  股票配置:   {state.get('stock_config', '(未设置)')}")
        print(f"  今日重启:   {state.get('restart_count_today', 0)} / "
              f"{state.get('max_restarts_per_day', 5)} 次")
        last = state.get('last_restart_time', '')
        if last:
            print(f"  上次重启:   {last}")
        
        # 检查进程
        procs = ProcessManager.find_monitor_processes()
        if procs:
            print(f"\n  monitor.py: 运行中 ({len(procs)}个进程)")
            for p in procs:
                print(f"             PID={p['pid']}")
        else:
            print(f"\n  monitor.py: 未运行")
        
        if os.path.exists(PID_FILE):
            with open(PID_FILE, 'r') as f:
                print(f"  守护PID:   {f.read().strip()}")
        else:
            print(f"  守护PID:   (未运行)")
        
        trading = is_trading_time()
        print(f"  交易时间:   {'✅ 是' if trading else '❌ 否'}")
        print("=" * 50)

    elif args.command == 'check':
        # 单次检查
        result = guardian.run_once()
        sys.exit(0 if result else 1)

    elif args.command == 'run':
        # 默认：单次检查然后退出
        if args.stock:
            guardian.state.set_stock(args.stock)
        guardian.run_once()


if __name__ == '__main__':
    main()
