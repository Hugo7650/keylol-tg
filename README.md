# Keylol Telegram Bot

自动从 Keylol 论坛抓取帖子并投递到 Telegram 的机器人。

## 当前能力

- 定时抓取最新帖子列表，并避免重复发送
- 自动登录论坛，支持会话持久化和请求重试
- 根帖支持 `[page]` 分页合并，支持 `postmessage_*` 和 `postpw_*` 两类容器
- 使用“浏览器渲染后的 HTML”而不是 BBCode 做结构化解析
- 已支持的核心语义包括：代码块、隐藏/折叠/剧透、链接、图片、引用、Steam 信息盒、常见 iframe/embed、分页断点
- Telegram 输出使用 HTML parse mode，单帖只发送一条消息
- 单段可见文本超过 500 字会自动折叠为 expandable blockquote
- 单条消息超过 Telegram 4096 字符上限时，会自动截断正文并保留标题、作者信息和原帖链接
- Steam 商店信息盒会被精简为单个 Steam/蒸汽平台链接，文本优先使用游戏或包名

## 已知限制

- `script`/Flash 注入类内容仍然无法可靠还原
- `ruby`、`hover`、`table`、`float`、复杂列表等结构仍以降级文本为主，保真度有限
- `color`、`size`、`font`、`align` 等论坛样式不会一比一映射到 Telegram
- `steam://`、`steamchina://` 这类协议链接能保留为链接，但是否可点击取决于 Telegram 客户端行为

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

网络稳健性相关配置：
- `FORUM_REQUEST_RETRIES`: 论坛请求失败后的额外重试次数，默认 `2`
- `FORUM_RETRY_BACKOFF`: 重试退避基数秒数，默认 `1.0`，实际等待为 `1s`、`2s`、`4s` 递增
- 临时的 SSL EOF、连接中断、超时或 `5xx/429` 会先重试，再决定是否跳过本轮抓取

4. 运行机器人：

```bash
python main.py
```

## 测试

```bash
.venv\Scripts\python.exe -m unittest discover -s test -p "test_*.py"
```

## 文档

- 标签支持矩阵与当前能力判断： [analysis/keylol_tag_support_matrix.md](analysis/keylol_tag_support_matrix.md)

## 验证码处理

当论坛需要验证码时，机器人会通过 Telegram 私聊通知管理员。管理员只需回复验证码内容即可。
