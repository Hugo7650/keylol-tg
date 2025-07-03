# Keylol Telegram Bot

自动从Keylol论坛获取最新帖子并发送到Telegram频道的机器人。

## 功能特性

- 定时检查论坛新帖子
- 自动登录论坛（支持验证码处理）
- 发送格式化的帖子到Telegram频道
- 避免重复发送
- 登录失效时通知管理员

## 安装和配置

1. 安装依赖：
```bash
pip install -e .
```

2. 复制配置文件：
```bash
cp .env.example .env
```

3. 编辑 `.env` 文件，填入你的配置信息

4. 运行机器人：
```bash
python main.py
```

## 验证码处理

当论坛需要验证码时，机器人会通过Telegram私聊通知管理员。管理员只需回复验证码内容即可。
