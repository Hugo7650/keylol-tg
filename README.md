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

	可选配置：`STRUCTURED_PIPELINE_MODE=structured|legacy|compare`
	- `structured`: 只发送新的结构化 pipeline 输出
	- `legacy`: 使用兼容 ForumPost 投影路径构建输出
	- `compare`: 发送结构化输出，同时和 legacy 输出做并行比对并通知管理员差异

	网络稳健性相关配置：
	- `FORUM_REQUEST_RETRIES`: 论坛请求失败后的额外重试次数，默认 `2`
	- `FORUM_RETRY_BACKOFF`: 重试退避基数秒数，默认 `1.0`，实际等待为 `1s`、`2s`、`4s` 递增
	- 临时的 SSL EOF、连接中断、超时或 `5xx/429` 会先重试，再决定是否跳过本轮抓取

4. 运行机器人：
```bash
python main.py
```

## 验证码处理

当论坛需要验证码时，机器人会通过Telegram私聊通知管理员。管理员只需回复验证码内容即可。
