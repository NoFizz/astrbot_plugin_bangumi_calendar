# Changelog

本项目的所有重要变更都会记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [1.1.0] - 2026-08-02

### Added

- 渲染失败自动重试（最多 2 次额外尝试）
- 封面下载并发限制（信号量 5）
- 原子 MIME 感知的封面缓存（临时文件 + 原子替换，按 content-type 存扩展名）
- UMO 去重，避免重复推送
- 封面缓存周期清理（每日推送后执行，按 max(atime, mtime) 判定）
- 英文命令（/bangumi today/push/status）返回英文文案
- 卡片模板注入转义（Jinja2 | e），防止恶意番剧名破坏渲染
- 单元测试与测试框架接入（hermetic，96 个测试）
- CI 流水线（GitHub Actions，Python 3.10-3.12 + ruff + pytest）
- 卡片视觉重设计（Bilibili 设计系统：品牌粉渐变、思源字体、卡片化布局）
- README 增加截图与 FAQ 章节

### Changed

- 将单文件 `main.py` 拆分为 models / parser / service / card 多模块（依赖方向单向）
- 中英文命令处理器去重（提取共享核心）
- 网络异常收窄为 httpx.HTTPError + JSONDecodeError，AsyncClient 跨重试复用
- 异步路径文件 I/O 卸载到线程池
- 依赖下限锁定 `httpx[socks]>=0.26`

### Fixed

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
