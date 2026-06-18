# Keylol 标签支持矩阵

## 数据来源

- 分页快照： [test/case/keylol_guide_pages](../test/case/keylol_guide_pages)
- 抓取清单： [test/case/keylol_guide_pages/manifest.json](../test/case/keylol_guide_pages/manifest.json)
- parser/formatter 对照数据： [test/case/keylol_guide_pages/parser_report.json](../test/case/keylol_guide_pages/parser_report.json)
- 根帖提取： [infrastructure/services/thread_page_extractor.py](../infrastructure/services/thread_page_extractor.py)
- HTML 解析： [infrastructure/services/forum_content_parser.py](../infrastructure/services/forum_content_parser.py)
- Telegram 格式化： [infrastructure/services/telegram_formatter.py](../infrastructure/services/telegram_formatter.py)
- Telegram 发送： [clients/telegram_client.py](../clients/telegram_client.py)
- 论坛抓取入口： [clients/forum_client.py](../clients/forum_client.py)

## 全局判断

1. 当前项目依然不是按 BBCode 解析，而是按“浏览器渲染后的 HTML”解析。
2. 此前几个链路级缺口已经补齐：
  - [clients/forum_client.py](../clients/forum_client.py) 已支持根帖 `[page]` 分页合并。
  - [infrastructure/services/thread_page_extractor.py](../infrastructure/services/thread_page_extractor.py) 已同时支持 `postmessage_*` 和 `postpw_*`。
  - [infrastructure/services/telegram_formatter.py](../infrastructure/services/telegram_formatter.py) 与 [clients/telegram_client.py](../clients/telegram_client.py) 已消费结构化语义，输出 HTML parse mode，且单帖只发一条 Telegram 消息。
3. 当前的主要问题已经不再是“抓不到/发不出”，而是“少数标签仍然只能降级表达”，重点集中在 `script`/Flash、`ruby`、`hover`、`table`、`float`、复杂列表等结构保真度不足。

## 状态定义

- 正常：论坛效果能较完整地保留到 parser 输出，发送层不会再明显破坏。
- 部分：正文还能保住，但结构、样式或交互语义明显丢失。
- 有问题：论坛支持，但当前实现存在明确缺陷，输出结果会误导或失真。
- 未验证：论坛支持，但这批页面只展示了教程或截图，无法从 fixture 直接验证真实渲染；只能结合代码推断。

## 支持矩阵

| 能力/标签 | 证据页 | 当前状态 | 判断 |
| --- | --- | --- | --- |
| code | cp=3 | 正常 | 当前会产出代码块节点，Telegram 以 `<pre>` 发送。 |
| hide | cp=4 | 部分 | 隐藏块语义已保留，Telegram 以 expandable blockquote 展示；积分/回复/偷看次数等论坛专有细节没有完整建模。 |
| collapse | cp=4 | 部分 | 折叠标题和正文已保留，Telegram 以 expandable blockquote 展示，但论坛原始交互样式不会复刻。 |
| spoiler / spoil | cp=4 | 部分 | 剧透/旧版折叠正文已保留；`spoiler` 会映射到 Telegram spoiler，旧版 `spoil` 走折叠块降级。 |
| url | cp=5 | 正常 | 自定义文案和 URL 都会保留为可点击 HTML 链接。 |
| sframe / sfpack / scframe | cp=6 | 部分 | Steam 信息盒已精简为单个 Steam/蒸汽平台链接，并尽量显示游戏/包名；原始 widget 卡片和附属链接被有意移除。 |
| flash | cp=7 | 有问题 | 页面通过 script + AC_FL_RunContent 动态插入播放器；parser 跳过 script，旧版 flash 播放器完全抓不到。 |
| 163 / 163custom | cp=7 | 未验证 | 本页证明论坛支持，但 fixture 里没有实际 iframe 版本，只能确认旧 flash 路径当前会丢。 |
| media(B站/优酷) | cp=8,9 | 部分 | iframe 会保留为单个可点击链接，但不会变成内嵌播放器。 |
| b / i | cp=10 | 正常 | bold/italic 已映射到 Telegram HTML。 |
| u / s / color / size / font / align | cp=10 | 部分 | 下划线/删除线可保留；颜色、字号、字体、对齐等样式仍会降级。 |
| quote | cp=10 | 部分 | 引用正文会保留为 blockquote，但引用来源/论坛装饰信息不会完整保留。 |
| list / * | cp=10 | 部分 | 列表项文字和基础项目符号已保留，但嵌套/有序列表语义仍有限。 |
| qq | cp=10 | 有问题 | QQ 按钮这类特殊链接会退化成普通图片/链接噪声，不是业务上想要的表达。 |
| fly | cp=11 | 部分 | 只能保住文字，飞行动画语义完全丢失。 |
| index / #1 / #2 / #3 | cp=12 | 有问题 | 指南页能展示目录代码，但当前抓取链路不会构建跨页目录，也不会保留目录结构。 |
| page | cp=12,18 | 正常 | 根帖分页现在会在抓取层合并，并在结构化结果中保留分页断点。 |
| img | cp=13 | 正常 | 图片 URL 能被 parser 提取，并在 Telegram 正文中保留为单个可点击图片链接。 |
| table / tr / td | cp=14 | 部分 | 表格中的文字能保住，但行列结构被压平成一段文本。 |
| float | cp=15 | 部分 | 图文内容能保住，浮动布局语义丢失。 |
| password | cp=16,17 | 部分 | `postpw_*` 容器已能提取，不再直接失败；但密码校验本身并没有单独建模成专门语义。 |
| steamlink / steam | cp=19 | 部分 | HTTP Steam 链接会正常输出；`steam://`/`steamchina://` 是否可点击仍受 Telegram 客户端限制。 |
| 图片上传教程 | cp=20 | 正常 | 只是普通图片和 B 站教程链接，当前 parser 可以拿到基本内容。 |
| free / 帖子背景 / 悬赏背景 | cp=21 | 部分 | 可见文本和配图会被保住，但免费内容/帖子背景这类论坛 UI 语义不会被结构化保留。 |
| rb | cp=22 | 有问题 | ruby 注音会被压平成“正文 + 注音”的线性文本，无法保持正文/注音关系。 |
| hover | cp=22 | 有问题 | 悬浮正文和弹出内容被拼接到同一段文本，失去“默认隐藏，悬停才出现”的语义。 |
| sh0-sh5 | cp=22 | 部分 | 标题文字存在，但样式等级和视觉层级完全丢失。 |
| k0-k5 | cp=23 | 部分 | 美化标题文字存在，但美化样式不再存在。 |
| countdown | cp=24 | 未验证 | 当前 guide 只给了截图；parser 代码里有 iframe countdown 分支，但本页 fixture 没有实际倒计时 iframe。 |

## 已完成的链路修复

### 1. 根帖分页已经打通

- [clients/forum_client.py](../clients/forum_client.py) 现在会抓取并合并 `threadindex=yes&viewpid=...&cp=...` 的分页内容。
- 真实根帖用了 `[page]` 时，后续页内容可以进入 structured pipeline。

### 2. `postpw_*` 不再导致根帖提取失败

- [infrastructure/services/thread_page_extractor.py](../infrastructure/services/thread_page_extractor.py) 已同时查找 `postmessage_*` 和 `postpw_*`。
- 密码效果页至少不会因为容器类型不同而直接抽取失败。

### 3. 发送层已经消费结构化语义

- [infrastructure/services/telegram_formatter.py](../infrastructure/services/telegram_formatter.py) 现在输出 Telegram HTML parse mode。
- [clients/telegram_client.py](../clients/telegram_client.py) 现在按单帖单消息发送，不再把同一帖子拆成多条媒体补发消息。
- 超过 500 字的单段正文会折叠，整条消息超过 4096 字符时会自动截断正文并保留原帖链接。

### 4. Steam 信息盒已从“噪声块”收敛为单个链接

- `sframe` / `sfpack` / `scframe` 当前都会被收敛成单个 Steam/蒸汽平台链接。
- 链接文本优先使用游戏或包名，不再把商店/评测/SteamDB/Barter/ASF 等附属链接整段输出到 Telegram。

## 仍然明确存在的缺口

### 1. `script`/Flash 注入类内容仍抓不到真实播放器

- cp=7 的网易云音乐页核心问题没有变：播放器是脚本动态注入，不是静态 iframe。
- [infrastructure/services/forum_content_parser.py](../infrastructure/services/forum_content_parser.py) 目前仍然跳过 `script`。

### 2. `ruby`、`hover`、表格和复杂布局仍以降级文本为主

- cp=22 的 `rb`、`hover` 还没有专门节点。
- cp=14,15 的 `table`、`float` 只能保住正文，结构和布局信息仍会丢失。
- cp=10 的列表目前只有基础项目符号，没有完整嵌套/有序列表语义。

## 优先级建议

1. 优先补 parser：给 `script`/Flash 降级提取、`ruby`、`hover`、`table`、复杂 `list` 建更明确的结构节点。
2. 继续优化 formatter：让表格、列表、引用来源等降级输出更稳定，而不是只保住文本。
3. 视需要再扩发送层：如果后续需要多媒体卡片或更强的预览策略，再评估是否引入额外发送模式。

## 备注

- cp=2 是空白页，本次按“无内容页”处理。
- 这份矩阵以论坛实时抓取到的 24 个 cp fixture 和当前代码实现为准，而不是只根据主楼目录推断。
- `parser_report.json` 仍可作为旧行为对照，但不再代表当前实现的 golden output。