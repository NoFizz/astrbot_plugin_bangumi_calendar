# 新番日推 v1.0.0

AstrBot 插件 — 每日定时推送 Bangumi 今日新番日历卡片图。


## 功能特性

- 每日定时向指定群聊推送今日新番日历卡片（PNG 图片）
- 卡片包含：封面缩略图、中/日文名、评分、在看人数、首播日期
- 默认按评分降序排列，支持自定义排序依据和方向
- 支持手动触发推送和即时查看今日新番
- 推送时间、推送数量、排序方式可配置
- 封面图本地缓存（30 天自动清理），减少重复下载
- 支持配置 HTTP/SOCKS5 代理，兼容环境变量回退

## 指令

| 中文指令 | 英文指令 | 说明 | 权限 |
|----------|----------|------|------|
| `/新番 今日` | `/bangumi today` | 在当前聊天查看今日新番卡片 | 所有人 |
| `/新番 推送` | `/bangumi push` | 手动推送到所有已配置目标 | 管理员 |
| `/新番 状态` | `/bangumi status` | 查看插件运行状态与下次推送倒计时 | 管理员 |

## 配置

在 AstrBot WebUI → 插件管理 → 新番日推 中配置：

| 配置项 | 类型 | 说明 | 默认值 |
|--------|------|------|--------|
| `umos` | list | 推送目标 UMO 列表 | `[]` |
| `push_time` | string | 每日推送时间（H:MM 或 HH:MM，服务器时区） | `07:00` |
| `max_items` | int | 每天最大推送番数，0 为不限制 | `0` |
| `sort_by` | string | 排序依据（下拉框：按评分 / 按在看人数） | `score` |
| `sort_order` | string | 排序方向（下拉框：降序 / 升序） | `desc` |
| `proxy` | string | 代理地址，留空使用直连 | `""` |
| `max_retries` | int | API 请求最大重试次数 | `3` |

**UMO 格式**：`Bot名:GroupMessage:群号`，例如 `AstrBot:GroupMessage:123456789`

**代理格式**：支持 `http://127.0.0.1:7897` 或 `socks5://127.0.0.1:1080`

## 安装

1. 将本插件目录放入 AstrBot 的 `data/plugins/` 下
2. 安装依赖：`pip install httpx[socks]`
3. 在 WebUI 插件页重载插件
4. 配置推送目标 UMO 和推送时间

## 技术细节

- **数据源**：[Bangumi 每周放送日历 API](https://bangumi.github.io/api/)（`https://api.bgm.tv/calendar`），无需认证
- **渲染**：HTML + Jinja2 模板 → AstrBot 内置 `html_render`（Playwright）→ PNG 图片
- **封面处理**：宿主机预下载封面并转 base64 data URI 嵌入 HTML，解决 Docker 内 Playwright 无法加载外部图片的问题
- **网络**：所有 HTTP 请求使用 `httpx`，启用 `follow_redirects`，代理优先读取配置、回退到环境变量
- **排序**：先对全部当日番剧按配置排序，再按 `max_items` 截断，确保"评分最高的 N 部"语义正确
- **容错**：API 请求可配置重试次数（默认 3 次，线性退避），渲染/推送失败静默降级并记录日志
