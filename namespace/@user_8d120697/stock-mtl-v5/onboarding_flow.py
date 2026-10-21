#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新股民交互式引导流程 v1.0

设计理念：
  - 不一次问完所有问题，分步交互，从简单到复杂
  - 每个问题都说明"为什么要问"，让股民理解价值
  - 股民可以跳过任何问题，给出合理的默认值
  - 最终生成完整的用户配置文件

使用场景：
  当新用户首次使用stock-monitor Skill时，AI助手调用此模块进行交互式引导。

流程（5步）：
  Step 1: 你好，自我介绍 + 了解持仓（最重要）
  Step 2: 补充持仓信息（成本价/仓位）
  Step 3: 推送偏好设置（企微为主）
  Step 4: 监测需求确认（盯哪些股票）
  Step 5: 总结确认 → 启动服务

用法：
  from onboarding_flow import OnboardingFlow
  
  flow = OnboardingFlow()
  # AI助手逐步调用各步骤，获取问题文本
  question = flow.step_1_hello()
  # 用户回答后
  flow.save_answer('step_1', user_answer)
  
  # 或者一次性运行完整流程（CLI模式）
  python onboarding_flow.py --interactive
"""

import json
import os
from datetime import date
from typing import Dict, List, Optional, Tuple, Any


# ============================================================
# 引导流程管理器
# ============================================================

class OnboardingFlow:
    """
    新股民交互式引导
    
    核心设计原则：
      1. 每步只问1-2个问题，不信息轰炸
      2. 每个问题附带"为什么问这个"说明
      3. 支持跳过/跳过时用默认值
      4. 收集的信息用于个性化服务
    """

    def __init__(self, config_dir: str = None):
        if config_dir is None:
            config_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_dir = config_dir
        self.config_file = os.path.join(config_dir, 'user_profile.json')
        self.answers: Dict[str, Any] = {}
        self.current_step = 0
        self._load()

    # ----------------------------------------------------------
    # 步骤定义：每个步骤返回 (问题文本, 提示说明, 默认值)
    # ----------------------------------------------------------

    def step_1_hello(self) -> dict:
        """
        Step 1: 自我介绍 + 第一只股票
        
        这一步最关键——先建立信任，再开始收集信息。
        """
        self.current_step = 1
        return {
            'step': 1,
            'title': '👋 您好！我是您的股票监测助手',
            'question': (
                "我先简单介绍一下自己能做什么：\n\n"
                "**我的能力** 🦀\n"
                "- 实时监测您关注的股票，有异动立刻通知您\n"
                "- 计算您的浮盈/浮亏，给出操作建议\n"
                "- 每天推送竞价报告、午间盘点、收盘复盘\n"
                "- 大盘异动预警（涨停/跌停/大单/突破等）\n\n"
                "**现在想了解一下：**\n\n"
                "您目前持有或关注的第一只股票是什么？\n"
                "(说名字或代码都行，比如「茅台」或者「600519」)"
            ),
            'hint': '比如：浙能电力、贵州茅台、600519、sh000001',
            'why_ask': (
                "知道您关注哪只股票后，我可以立即帮您启动监测，"
                "盘中一旦有重要变化就会第一时间通知到您的企业微信。"
            ),
            'field': 'first_stock',
            'required': True,
            'examples': ['茅台', '平安银行', '600519', 'sh600023', '宁德时代'],
        }

    def step_2_position(self) -> dict:
        """
        Step 2: 持仓细节（成本价+仓位）
        
        这是给操作建议的基础数据。如果不知道就跳过。
        """
        self.current_step = 2
        first_stock = self.answers.get('step_1', {}).get('value', '')
        
        return {
            'step': 2,
            'title': f'📊 关于{first_stock or "这只股票"}',
            'question': (
                f"好的，已记录 **{first_stock}** ✅\n\n"
                f"接下来我想了解几个关键信息，这样我能给您更精准的建议：\n\n"
                f"**1. 您的买入成本价是多少元？**\n"
                f"(如果您只是关注还没买，可以说「没买」)"
            ),
            'hint': '比如：5.60 / 大概5块6 / 还没买',
            'why_ask': (
                "知道成本价，我才能算出您是赚还是亏，"
                "并告诉您该继续持有还是该止损。没有成本价的建议都是空谈。"
            ),
            'field': 'cost_price',
            'required': False,  # 可以跳过
            'follow_up_question': (
                "**2. 您持有多少股？（大概也行）**\n"
                "(100股=1手，1000股=10手)"
            ),
            'follow_up_field': 'shares',
            'follow_up_hint': '比如：1000 / 10手 / 几百股吧',
        }

    def step_3_notification(self) -> dict:
        """
        Step 3: 推送方式设置
        """
        self.current_step = 3
        return {
            'step': 3,
            'title': '📱 通知方式',
            'question': (
                "收到！接下来设置消息推送。\n\n"
                "我支持通过以下方式给您发消息：\n"
                "- **企业微信群机器人**（推荐，最稳定）\n"
                "- 钉钉机器人\n"
                "- 手机Bark推送(iOS)\n"
                "- Server酱(微信/QQ)\n\n"
                "**您希望用哪种方式接收股票提醒？**"
            ),
            'hint': '企微 / 钉钉 / Bark / 都行 / 先默认企微',
            'default_value': 'wechat',
            'why_ask': (
                "选对推送方式，关键时刻的消息才能第一时间送到你手上。"
                "首推企业微信，因为大多数股民都有企微，而且群机器人免费稳定。"
            ),
            'field': 'notification_method',
            'required': True,
            
            # 如果选了企微，还需要webhook
            'follow_up_if_wechat': {
                'question': "请提供您的企微群机器人Webhook地址",
                'hint': '在企微群里添加机器人时会自动生成，格式类似 https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx',
                'field': 'wechat_webhook',
            },
        }

    def step_4_more_stocks(self) -> dict:
        """
        Step 4: 还有其他股票吗？
        """
        self.current_step = 4
        return {
            'step': 4,
            'title': '➕ 其他股票',
            'question': (
                "除了上面说的那只，**还有其他股票需要一起监测的吗？**\n\n"
                "(没有的话直接说「没了」就行)"
            ),
            'hint': '比如：还持有茅台和平安银行 / 没了 / 再加一个宁德时代',
            'why_ask': (
                "多只股票一起看，我可以在每天收盘后给你一个整体持仓概览，"
                "帮你判断今天整体是赚了还是亏了，哪只需要关注。"
            ),
            'field': 'more_stocks',
            'required': False,
            # 这个步骤可能重复（用户可能说多只）
            'is_repeatable': True,
        }

    def step_5_confirm(self) -> dict:
        """
        Step 5: 总结确认 + 启动
        """
        self.current_step = 5
        profile = self._build_profile_summary()
        
        return {
            'step': 5,
            'title': '✅ 配置完成',
            'summary': profile,
            'question': (
                "以上是我记录的信息，**确认无误的话我就开始工作了！**\n\n"
                "如果有需要修改的地方随时告诉我。"
            ),
            'field': 'confirm',
            'required': True,
        }

    # ----------------------------------------------------------
    # 答案处理
    # ----------------------------------------------------------

    def save_answer(self, step_id: str, answer: str, field: str = None):
        """保存用户的答案"""
        self.answers[step_id] = {
            'value': answer,
            'field': field,
            'timestamp': date.today().isoformat(),
        }
        self._save()

    def get_current_step(self) -> int:
        """获取当前步骤"""
        return self.current_step

    def is_complete(self) -> bool:
        """是否完成了全部必要步骤"""
        required_steps = ['step_1', 'step_3', 'step_5']
        return all(s in self.answers for s in required_steps)

    def _build_profile_summary(self) -> str:
        """构建用户配置摘要"""
        lines = ["**您的配置摘要**", ""]
        
        # 持仓
        stock = self.answers.get('step_1', {}).get('value', '未填写')
        lines.append(f"📌 关注股票：{stock}")
        
        cost = self.answers.get('step_2', {}).get('value', '未填写')
        shares_key = 'step_2_followup'
        shares = self.answers.get(shares_key, {}).get('value', '未填写')
        if cost and cost not in ['没买', '不知道', '不清楚']:
            lines.append(f"💰 成本价：{cost}")
        if shares and shares not in ['不知道', '不清楚']:
            lines.append(f"📊 持仓：{shares}股")
        
        lines.append("")
        
        # 通知方式
        notify = self.answers.get('step_3', {}).get('value', '企微(默认)')
        method_map = {
            'wechat': '企业微信', 'dingtalk': '钉钉',
            'bark': 'Bark', 'serverchan': 'Server酱',
        }
        display_method = method_map.get(notify.lower(), notify)
        lines.append(f"📱 通知方式：{display_method}")
        
        # 其他股票
        more = self.answers.get('step_4', {}).get('value', '')
        if more and more not in ['没了', '没有', '无', '']:
            lines.append(f"➕ 其他股票：{more}")
        
        lines.append("")
        lines.append("---")
        lines.append("配置将保存到 user_profile.json")
        
        return "\n".join(lines)

    # ----------------------------------------------------------
    # 生成最终配置
    # ----------------------------------------------------------

    def generate_config(self) -> dict:
        """根据收集到的答案生成完整配置"""
        config = {
            'user_info': {},
            'positions': [],
            'notification': {},
            'monitor_settings': {},
            'created_at': date.today().isoformat(),
        }
        
        # 基本信息
        stock_raw = self.answers.get('step_1', {}).get('value', '')
        config['user_info']['primary_stock'] = stock_raw
        
        # 持仓
        cost_str = self.answers.get('step_2', {}).get('value', '')
        shares_str = ''
        # 检查followup
        for k, v in self.answers.items():
            if 'followup' in k.lower() or 'shares' in k.lower():
                shares_str = v.get('value', '')
        
        if stock_raw:
            pos_entry = {'raw_name': stock_raw}
            try:
                if cost_str and cost_str not in ['没买', '不知道', '不清楚', '未填写']:
                    pos_entry['cost_price'] = float(cost_str.replace('元', '').strip())
                if shares_str and shares_str not in ['不知道', '不清楚', '未填写']:
                    # 解析中文数字
                    s = shares_str.replace('股', '').replace('手', '').strip()
                    try:
                        pos_entry['shares'] = int(float(s))
                    except ValueError:
                        pos_entry['shares_raw'] = shares_str
            except (ValueError, TypeError):
                pass
            
            if pos_entry.get('cost_price') or pos_entry.get('shares'):
                config['positions'].append(pos_entry)
        
        # 更多股票
        more_raw = self.answers.get('step_4', {}).get('value', '')
        if more_raw and more_raw not in ['没了', '没有', '无', '', '未填写']:
            config['user_info']['extra_stocks'] = more_raw
        
        # 通知方式
        notify_method = self.answers.get('step_3', {}).get('value', 'wechat').lower()
        config['notification']['method'] = notify_method
        if notify_method == 'wechat':
            webhook = self.answers.get('step_3_webhook', {}).get('value', '')
            if webhook:
                config['notification']['wechat_webhook'] = webhook
        
        # 监测设置
        config['monitor_settings'] = {
            'interval_seconds': 30,
            'smart_notify': True,
            'position_based_advice': True,
        }
        
        return config

    # ----------------------------------------------------------
    # 持久化
    # ----------------------------------------------------------

    def _save(self):
        """保存进度"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'answers': self.answers,
                    'current_step': self.current_step,
                    'last_updated': date.today().isoformat(),
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Onboarding] 保存失败: {e}")

    def _load(self):
        """加载进度"""
        if not os.path.exists(self.config_file):
            return
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.answers = data.get('answers', {})
            self.current_step = data.get('current_step', 0)
        except Exception as e:
            print(f"[Onboarding] 加载失败: {e}")

    def reset(self):
        """重置引导流程"""
        self.answers = {}
        self.current_step = 0
        if os.path.exists(self.config_file):
            os.remove(self.config_file)


# ============================================================
# AI辅助函数：供AI助手调用的问题生成器
# ============================================================

def get_next_question(flow: OnboardingFlow) -> Optional[dict]:
    """
    获取下一步应该问的问题
    
    AI助手在每次用户回复后调用此函数，决定下一步问什么
    
    Returns:
        下一个问题字典，None表示流程结束
    """
    step = flow.current_step
    
    if step == 0:
        return flow.step_1_hello()
    elif step == 1:
        return flow.step_2_position()
    elif step == 2:
        return flow.step_3_notification()
    elif step == 3:
        return flow.step_4_more_stocks()
    elif step == 4:
        return flow.step_5_confirm()
    else:
        return None  # 流程结束


def parse_user_response(response: str, current_step: int) -> Tuple[str, Optional[str]]:
    """
    解析用户的自然语言回答
    
    Args:
        response: 用户原始输入
        current_step: 当前步骤号
    
    Returns:
        (清理后的答案值, 对应字段名)
    """
    text = response.strip()
    
    # 常见跳过词
    skip_words = ['跳过', '不说', '保密', '不知道', '算了', '随便', 
                   '下次', '默认', '没买', '还没买', '没了', '没有', '无']
    
    if any(w in text for w in skip_words) or len(text) <= 1:
        return '__SKIP__', None
    
    return text, None


# ============================================================
# 命令行测试入口（交互模式）
# ============================================================

def main():
    """命令行交互式引导"""
    import argparse
    parser = argparse.ArgumentParser(description='新股民引导流程')
    parser.add_argument('--interactive', action='store_true', help='进入交互模式')
    parser.add_argument('--reset', action='store_true', help='重置引导')
    parser.add_argument('--status', action='store_true', help='查看当前进度')
    args = parser.parse_args()

    flow = OnboardingFlow()

    if args.reset:
        flow.reset()
        print("引导流程已重置")
        return

    if args.status:
        print(f"当前步骤: {flow.current_step}/5")
        print(f"已完成: {len(flow.answers)} 个问题")
        if flow.is_complete():
            print("状态: ✅ 已完成")
        else:
            print("状态: ⏳ 进行中")
        return

    if args.interactive:
        print("\n" + "=" * 50)
        print("  🦀 股票监测助手 - 首次使用引导")
        print("=" * 50 + "\n")

        steps = [
            ('step_1', lambda: flow.step_1_hello()),
            ('step_2', lambda: flow.step_2_position()),
            ('step_3', lambda: flow.step_3_notification()),
            ('step_4', lambda: flow.step_4_more_stocks()),
            ('step_5', lambda: flow.step_5_confirm()),
        ]

        for step_id, step_fn in steps:
            q = step_fn()
            print(f"\n--- 第{q['step']}步 ---\n")
            print(q['question'])
            print(f"\n💡 {q.get('why_ask', '')}")
            hint = q.get('hint', '')
            if hint:
                print(f"   示例：{hint}")
            
            answer = input("\n> ").strip()
            field = q.get('field')
            flow.save_answer(step_id, answer, field)

            # Step 2 有追问
            if step_id == 'step_2' and answer.lower() not in ['没买', '不知道', '不清楚', '跳过']:
                fq = q.get('follow_up_question', '')
                fh = q.get('follow_up_hint', '')
                ff = q.get('follow_up_field', '')
                if fq:
                    print(f"\n  {fq}")
                    if fh:
                        print(f"  示例：{fh}")
                    fanswer = input("> ").strip()
                    flow.save_answer(step_id + '_followup', fanswer, ff)

        # 完成
        final_q = flow.step_5_confirm()
        print(f"\n{'=' * 50}")
        print(final_q['summary'])
        print(f"\n{'=' * 50}")
        
        confirm = input("\n确认启动？(y/n): ").strip().lower()
        if confirm in ['y', 'yes', '是', '确认', '好']:
            config = flow.generate_config()
            cfg_path = os.path.join(flow.config_dir, 'user_final_config.json')
            with open(cfg_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            print(f"\n✅ 配置已保存到 {cfg_path}")
            print("现在可以用以下命令启动监测：")
            print("  python monitor.py <股票代码>")
        else:
            print("\n已取消。随时可以重新运行引导。")
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
