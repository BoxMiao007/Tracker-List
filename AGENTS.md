# PROJECT KNOWLEDGE BASE

**Generated:** 2026-02-18
**Commit:** 6713ce9
**Branch:** main

## OVERVIEW

BT Tracker 自动更新工具。从多个数据源聚合 tracker 列表，每日通过 GitHub Actions 自动推送到仓库。Python 3.11。

## STRUCTURE

```
Library/
├── Update_all_tracker_to_github_no_test.py   # 主脚本 (384行)
├── trackers.txt                               # 完整 tracker 列表
├── trackers_best.txt                          # 精选 tracker (4个)
├── README.md                                  # 项目说明
└── .github/workflows/update-trackers.yml      # CI 配置
```

## WHERE TO LOOK

| 任务 | 位置 | 备注 |
|------|------|------|
| 修改数据源 | `Update_all...py:27-36` | `URLS` 列表 |
| 调整并发/重试 | `Update_all...py:39-42` | `MAX_WORKERS`, `RETRY_TIMES` |
| CI 调度时间 | `.github/workflows/update-trackers.yml:6` | cron 表达式 |
| 添加新输出文件 | `Update_all...py:143-182` | `update_github_file()` |

## CONVENTIONS

- **敏感信息**: `GITHUB_TOKEN` 必须通过环境变量提供，无硬编码
- **日志**: 同时输出到控制台和 `tracker_update.log`
- **并发**: 使用 `ThreadPoolExecutor`，默认 4 线程
- **输出格式**: tracker 列表去重后按字母排序

## COMMANDS

```bash
# 本地运行 (需要设置 GITHUB_TOKEN)
pip install requests colorama tabulate
GITHUB_TOKEN=xxx python Update_all_tracker_to_github_no_test.py

# 手动触发 CI
gh workflow run update-trackers.yml
```

## NOTES

- CI 每日 UTC 0:00 (北京 8:00) 自动运行
- 运行日志保存 7 天作为 artifact
- 脚本名含 `_no_test` 表示无单元测试
