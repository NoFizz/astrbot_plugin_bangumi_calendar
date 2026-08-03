# Changelog

本项目的所有重要变更都会记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [1.1.0] - 2026-08-03

### Added

- **Rank 优先排序**：评分模式先按 Bangumi 全站排名高到低，未上榜的按评分高到低（asc 对称反转）
- **评分/在看人数下限过滤**：新增 `enable_score_min`/`score_min`/`enable_doing_min`/`doing_min` 四个配置项（开关各自生效，同时开启时须同时满足）
- **Bangumi 标签展示**：卡片显示番剧类型标签（来源 → 放送方式 → 题材，最多 5 个，按添加人数排序，排除国家 tag），rank 与 tags 同接口并发获取（内存缓存）
- **Rank 胶囊**：番剧名右侧蓝色胶囊显示全站排名（Rank N），未上榜不显示
- **三栏卡片布局**：序号（左）| 封面（中）| 番剧信息（右），760px 宽
- **ultra 高清渲染**：device_scale_factor 1.8x（输出 1368px 宽）
- **作者署名**：页脚 "Presented by NoFizz"，Birthstone 手写体（woff2 base64 内嵌，远端渲染不依赖本地字体）
- 渲染失败自动重试（最多 2 次额外尝试）
- 封面下载并发限制（信号量 5）
- 原子 MIME 感知的封面缓存（临时文件 + 原子替换，按 content-type 存扩展名）
- UMO 去重，避免重复推送
- 封面缓存周期清理（每日推送后执行，按 max(atime, mtime) 判定）
- 英文命令（/bangumi today/push/status）返回英文文案
- 卡片模板注入转义（Jinja2 | e），防止恶意番剧名破坏渲染
- 单元测试与测试框架接入（hermetic，本地开发用，不随仓库发布）
- README：功能特性、推送卡片展示图、FAQ 章节

### Changed

- 将单文件 `main.py` 拆分为 models / parser / service / card 多模块（依赖方向单向）
- 配置页选项改名：`按评分` → `评分（Rank优先）`、`按在看人数` → `在看人数`
- 卡片视觉迭代：B 站官方色卡（品牌粉 #FF6699）、淡灰页面背景、番剧卡片浮雕投影、标题浮动胶囊（纯色 #FF8CB0）、序号区白色窄栏（64px）品牌粉数字、页脚无分隔线与外围同色、全插件字体统一微软雅黑
- rank 注入时机修正：排序前注入（Rank 优先排序生效）
- 中英文命令处理器去重（提取共享核心）
- 网络异常收窄为 httpx.HTTPError + JSONDecodeError，AsyncClient 跨重试复用
- 异步路径文件 I/O 卸载到线程池
- 依赖下限锁定 `httpx[socks]>=0.26`

### Fixed

- 排序时 rank 未注入导致"无 rank 排在有 rank 前面"（rank 获取移到排序前）
- 序号区胶囊化后遗留的底部白色高光条（header::after 移除）
- 封面缓存读取失败（损坏文件）时自动删除并重新下载
- `anime_id` 路径穿越防护（safe_anime_id）
- `id=0` 的番剧被误判为缺失而丢弃的问题

## [1.0.0] - 2026-07-27

### Added

- 每日定时向指定群聊推送今日新番日历卡片图（PNG）
- 卡片包含封面缩略图、中/日文名、评分、在看人数、首播日期
- 支持按评分 / 在看人数排序，排序方向可配置
- 支持 `max_items` 限制每日推送数量，0 为不限制
- 支持手动触发推送、即时查看今日新番、查看运行状态
- 封面本地缓存，30 天自动清理
- 支持 HTTP / SOCKS5 代理，兼容环境变量回退
- API 请求失败自动重试（次数可配置，线性退避）
