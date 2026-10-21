#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信/钉钉推送通知模块
支持多种推送渠道
"""

import json
import os
import requests
from typing import Optional, Dict
from datetime import datetime


class NotificationConfig:
    """通知配置"""
    
    def __init__(self, config_file: str = None):
        if config_file is None:
            skill_dir = os.path.dirname(os.path.abspath(__file__))
            self.config_file = os.path.join(skill_dir, 'notifier_config.json')
        else:
            self.config_file = config_file
        
        self.config = self._load_config()
    
    def _load_config(self) -> Dict:
        """加载配置"""
        default_config = {
            'wechat': {
                'enabled': False,
                'webhook_url': '',
                'mention_mobiles': []
            },
            'dingtalk': {
                'enabled': False,
                'webhook_url': '',
                'secret': '',
                'at_mobiles': []
            },
            'bark': {
                'enabled': False,
                'device_key': ''
            },
            'serverchan': {
                'enabled': False,
                'send_key': ''
            }
        }
        
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # 合并默认配置
                    for key in default_config:
                        if key not in config:
                            config[key] = default_config[key]
                    return config
            except Exception as e:
                print(f"加载配置失败: {e}")
        
        return default_config
    
    def save(self):
        """保存配置"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存配置失败: {e}")
            return False
    
    def setup_wechat(self, webhook_url: str, mention_mobiles: list = None):
        """配置企业微信"""
        self.config['wechat']['enabled'] = True
        self.config['wechat']['webhook_url'] = webhook_url
        if mention_mobiles:
            self.config['wechat']['mention_mobiles'] = mention_mobiles
        self.save()
        print("✅ 企业微信配置已保存")
    
    def setup_dingtalk(self, webhook_url: str, secret: str = '', at_mobiles: list = None):
        """配置钉钉"""
        self.config['dingtalk']['enabled'] = True
        self.config['dingtalk']['webhook_url'] = webhook_url
        self.config['dingtalk']['secret'] = secret
        if at_mobiles:
            self.config['dingtalk']['at_mobiles'] = at_mobiles
        self.save()
        print("✅ 钉钉配置已保存")
    
    def setup_bark(self, device_key: str):
        """配置Bark（iOS推送）"""
        self.config['bark']['enabled'] = True
        self.config['bark']['device_key'] = device_key
        self.save()
        print("✅ Bark配置已保存")
    
    def setup_serverchan(self, send_key: str):
        """配置Server酱"""
        self.config['serverchan']['enabled'] = True
        self.config['serverchan']['send_key'] = send_key
        self.save()
        print("✅ Server酱配置已保存")


class Notifier:
    """通知推送器"""
    
    def __init__(self):
        self.config = NotificationConfig()
    
    def send_wechat(self, title: str, content: str) -> bool:
        """
        发送到企业微信
        
        Args:
            title: 标题
            content: 内容
        
        Returns:
            是否发送成功
        """
        if not self.config.config['wechat']['enabled']:
            return False
        
        webhook_url = self.config.config['wechat']['webhook_url']
        mention_mobiles = self.config.config['wechat']['mention_mobiles']
        
        # 构建markdown消息
        markdown_content = f"## {title}\n\n{content}"
        
        # 添加@提醒
        if mention_mobiles:
            at_text = '\n\n' + ' '.join([f"@{m}" for m in mention_mobiles])
            markdown_content += at_text
        
        data = {
            "msgtype": "markdown",
            "markdown": {
                "content": markdown_content
            }
        }
        
        try:
            response = requests.post(webhook_url, json=data, timeout=10)
            result = response.json()
            if result.get('errcode') == 0:
                print("✅ 企业微信推送成功")
                return True
            else:
                print(f"⚠️ 企业微信推送失败: {result.get('errmsg')}")
                return False
        except Exception as e:
            print(f"⚠️ 企业微信推送异常: {e}")
            return False
    
    def send_dingtalk(self, title: str, content: str) -> bool:
        """
        发送到钉钉
        
        Args:
            title: 标题
            content: 内容
        
        Returns:
            是否发送成功
        """
        if not self.config.config['dingtalk']['enabled']:
            return False
        
        webhook_url = self.config.config['dingtalk']['webhook_url']
        secret = self.config.config['dingtalk']['secret']
        at_mobiles = self.config.config['dingtalk']['at_mobiles']
        
        # 如果有secret，需要签名
        if secret:
            import time
            import hmac
            import hashlib
            import base64
            import urllib.parse
            
            timestamp = str(round(time.time() * 1000))
            string_to_sign = f"{timestamp}\n{secret}"
            hmac_code = hmac.new(secret.encode('utf-8'), string_to_sign.encode('utf-8'), digestmod=hashlib.sha256).digest()
            sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
            webhook_url = f"{webhook_url}&timestamp={timestamp}&sign={sign}"
        
        # 构建markdown消息
        markdown_text = f"### {title}\n\n{content}"
        
        data = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": markdown_text
            },
            "at": {
                "atMobiles": at_mobiles,
                "isAtAll": False
            }
        }
        
        try:
            response = requests.post(webhook_url, json=data, timeout=10)
            result = response.json()
            if result.get('errcode') == 0:
                print("✅ 钉钉推送成功")
                return True
            else:
                print(f"⚠️ 钉钉推送失败: {result.get('errmsg')}")
                return False
        except Exception as e:
            print(f"⚠️ 钉钉推送异常: {e}")
            return False
    
    def send_bark(self, title: str, content: str) -> bool:
        """
        发送到Bark（iOS推送）
        
        Args:
            title: 标题
            content: 内容
        
        Returns:
            是否发送成功
        """
        if not self.config.config['bark']['enabled']:
            return False
        
        device_key = self.config.config['bark']['device_key']
        url = f"https://api.day.app/{device_key}/{title}/{content}"
        
        try:
            response = requests.get(url, timeout=10)
            result = response.json()
            if result.get('code') == 200:
                print("✅ Bark推送成功")
                return True
            else:
                print(f"⚠️ Bark推送失败: {result}")
                return False
        except Exception as e:
            print(f"⚠️ Bark推送异常: {e}")
            return False
    
    def send_serverchan(self, title: str, content: str) -> bool:
        """
        发送到Server酱
        
        Args:
            title: 标题
            content: 内容
        
        Returns:
            是否发送成功
        """
        if not self.config.config['serverchan']['enabled']:
            return False
        
        send_key = self.config.config['serverchan']['send_key']
        url = f"https://sctapi.ftqq.com/{send_key}.send"
        
        data = {
            "title": title,
            "desp": content
        }
        
        try:
            response = requests.post(url, data=data, timeout=10)
            result = response.json()
            if result.get('code') == 0:
                print("✅ Server酱推送成功")
                return True
            else:
                print(f"⚠️ Server酱推送失败: {result.get('message')}")
                return False
        except Exception as e:
            print(f"⚠️ Server酱推送异常: {e}")
            return False
    
    def send(self, title: str, content: str, channels: list = None) -> Dict[str, bool]:
        """
        发送通知到所有已启用的渠道
        
        Args:
            title: 标题
            content: 内容
            channels: 指定渠道，None表示全部
        
        Returns:
            各渠道发送结果
        """
        results = {}
        
        all_channels = ['wechat', 'dingtalk', 'bark', 'serverchan']
        target_channels = channels if channels else all_channels
        
        for channel in target_channels:
            if channel == 'wechat':
                results['wechat'] = self.send_wechat(title, content)
            elif channel == 'dingtalk':
                results['dingtalk'] = self.send_dingtalk(title, content)
            elif channel == 'bark':
                results['bark'] = self.send_bark(title, content)
            elif channel == 'serverchan':
                results['serverchan'] = self.send_serverchan(title, content)
        
        return results
    
    def send_stock_alert(self, stock_name: str, stock_code: str, 
                         price: float, change_pct: float, alert_type: str = 'up'):
        """
        发送股票异动提醒
        
        Args:
            stock_name: 股票名称
            stock_code: 股票代码
            price: 当前价格
            change_pct: 涨跌幅
            alert_type: up/down
        """
        emoji = "📈" if alert_type == 'up' else "📉"
        title = f"{emoji} {stock_name} 异动提醒"
        
        content = f"""
**股票名称：** {stock_name} ({stock_code})

**当前价格：** {price:.2f} 元

**涨跌幅：** {change_pct:+.2f}%

**提醒类型：** {'大涨提醒' if alert_type == 'up' else '大跌提醒'}

**时间：** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

> 本提醒由股票监测助手自动发送
        """
        
        return self.send(title, content)
    
    def send_analysis_report(self, stock_name: str, stock_code: str, 
                            rating: str, score: int, suggestion: str):
        """
        发送分析报告
        
        Args:
            stock_name: 股票名称
            stock_code: 股票代码
            rating: 评级
            score: 评分
            suggestion: 建议
        """
        stars = "★" * score + "☆" * (5 - score)
        title = f"📊 {stock_name} 分析报告"
        
        content = f"""
**股票名称：** {stock_name} ({stock_code})

**综合评分：** {stars} ({score}/5)

**评级：** {rating}

**操作建议：**
{suggestion}

**时间：** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

> 本报告由股票监测助手自动生成，仅供参考
        """
        
        return self.send(title, content)
    
    def test(self):
        """测试所有已配置的推送渠道"""
        print("\n" + "="*60)
        print("测试推送通知")
        print("="*60 + "\n")
        
        title = "🦀 股票监测助手测试"
        content = "这是一条测试消息\n\n如果您收到此消息，说明推送配置成功！"
        
        results = self.send(title, content)
        
        print("\n" + "="*60)
        print("测试结果：")
        for channel, success in results.items():
            status = "✅ 成功" if success else "❌ 失败/未配置"
            print(f"  {channel}: {status}")
        print("="*60 + "\n")


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='推送通知配置')
    subparsers = parser.add_subparsers(dest='command', help='子命令')
    
    # 配置企业微信
    wechat_parser = subparsers.add_parser('wechat', help='配置企业微信')
    wechat_parser.add_argument('webhook_url', help='Webhook地址')
    wechat_parser.add_argument('--mention', '-m', nargs='*', help='@手机号列表')
    
    # 配置钉钉
    dingtalk_parser = subparsers.add_parser('dingtalk', help='配置钉钉')
    dingtalk_parser.add_argument('webhook_url', help='Webhook地址')
    dingtalk_parser.add_argument('--secret', '-s', default='', help='加签密钥')
    dingtalk_parser.add_argument('--at', '-a', nargs='*', help='@手机号列表')
    
    # 配置Bark
    bark_parser = subparsers.add_parser('bark', help='配置Bark(iOS)')
    bark_parser.add_argument('device_key', help='设备Key')
    
    # 配置Server酱
    serverchan_parser = subparsers.add_parser('serverchan', help='配置Server酱')
    serverchan_parser.add_argument('send_key', help='SendKey')
    
    # 测试
    test_parser = subparsers.add_parser('test', help='测试推送')
    
    args = parser.parse_args()
    
    config = NotificationConfig()
    
    if args.command == 'wechat':
        config.setup_wechat(args.webhook_url, args.mention)
    
    elif args.command == 'dingtalk':
        config.setup_dingtalk(args.webhook_url, args.secret, args.at)
    
    elif args.command == 'bark':
        config.setup_bark(args.device_key)
    
    elif args.command == 'serverchan':
        config.setup_serverchan(args.send_key)
    
    elif args.command == 'test':
        notifier = Notifier()
        notifier.test()
    
    else:
        parser.print_help()
        print("\n" + "="*60)
        print("支持的推送渠道：")
        print("  1. 企业微信 - 适合团队/公司")
        print("  2. 钉钉 - 适合阿里系用户")
        print("  3. Bark - 适合iOS个人用户")
        print("  4. Server酱 - 适合微信个人用户")
        print("="*60)


if __name__ == '__main__':
    main()
