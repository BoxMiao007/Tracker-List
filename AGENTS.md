# PROJECT KNOWLEDGE BASE

**Generated:** 2026/02/18
**Commit:** 2d63578
**Branch:** main

## OVERVIEW

个人使用的 Tracker 列表聚合仓库。Python 脚本从多个数据源抓取 BitTorrent tracker 地址，去重后推送到 GitHub。

## STRUCTURE

```
.
├── update_trackers.py                        # 主脚本 - 抓取、健康检测、更新 trackers
├── trackers.txt                             # 全量 tracker 列表
├── trackers_best.txt                        # 精选 tracker 列表（自动健康检测）
├── requirements.txt                         # Python 依赖
├── README.md                                # 仓库说明
├── .github/workflows/update-trackers.yml    # tracker 列表定时更新
└── .github/workflows/sync-apk-reverse.yml   # 把 apk-reverse fork 快进到上游
```

## WHERE TO LOOK

| 任务 | 位置 | 说明 |
|------|------|------|
| 修改数据源 | `update_trackers.py:27-36` | `URLS` 列表 |
| 调整并发/超时 | `update_trackers.py:39-42` | `MAX_WORKERS`, `REQUEST_TIMEOUT` |
| 健康检测参数 | `update_trackers.py:263-266` | `HEALTH_CHECK_TIMEOUT`, `BEST_TRACKERS_COUNT` |
| 修改 CI 定时 | `.github/workflows/update-trackers.yml:5-6` | cron 表达式 |
| apk-reverse 同步 | `.github/workflows/sync-apk-reverse.yml` | 只快进 fork 的 `main`；secret `APK_REVERSE_SYNC_TOKEN` |
| 添加新依赖 | `requirements.txt` | pip 安装列表 |

## CONVENTIONS

- **环境变量配置**：敏感信息通过环境变量传递（`GITHUB_TOKEN`, `REPO_OWNER`, `REPO_NAME`）
- **中文注释**：代码注释使用中文
- **重试机制**：网络请求采用指数退避重试（1s, 2s, 4s）
- **日志输出**：同时输出到控制台和 `tracker_update.log`
- **变化检测**：内容无变化时跳过 GitHub 提交
- **安全检查**：trackers 数量 < 50 时终止提交

## ANTI-PATTERNS (THIS PROJECT)

- **不要硬编码 Token**：`GITHUB_TOKEN` 必须通过环境变量提供，无默认值
- **不要跳过重试**：网络不稳定时重试机制很重要
- **不要忽略限流**：GitHub API 限流时需等待重置
- **apk-reverse 同步不要改成 merge 或 force push**：fork 的 `main` 一旦有自己的提交，任务必须失败停下

## NOTES

- CI 每日 UTC 0:00（北京时间 8:00）自动运行
- 数据源来自 XIU2、ngosang、DeSireFire 等 GitHub 仓库
- 输出文件通过 GitHub API 推送，非 git commit
- `trackers_best.txt` 通过健康检测自动生成（存活+低延迟）
- `sync-apk-reverse.yml` 每天北京时间 08:17 把 `BoxMiao007/apk-reverse` 的 `main` 快进到 `newliver666/apk-reverse`。不能快进就失败，不合并、不 force push。推送用 secret `APK_REVERSE_SYNC_TOKEN`（只授权该 fork 的 Contents 写权限），不用 `GITHUB_TOKEN`

## COMMANDS

```bash
# 安装依赖
pip install -r requirements.txt

# 本地运行（需设置环境变量）
GITHUB_TOKEN=xxx python update_trackers.py

# 手动触发 CI
gh workflow run update-trackers.yml
```
