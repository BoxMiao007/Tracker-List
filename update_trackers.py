import requests
import datetime
import base64
import re
import time
import os
import sys
import logging
from typing import List, Set, Optional, Dict, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from colorama import Fore, init
from tabulate import tabulate

# 初始化 colorama
init(autoreset=True)

# ==================== 配置区域 ====================
# 建议通过环境变量或配置文件管理这些敏感信息

# GitHub 配置
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # 必须通过环境变量提供，无默认值
REPO_OWNER = os.getenv("REPO_OWNER", "BoxMiao007")
REPO_NAME = os.getenv("REPO_NAME", "Tracker-List")
TRACKERS_FILE_PATH = "trackers.txt"
README_FILE_PATH = "README.md"

# 数据源 URLs
URLS = [
    "https://raw.githubusercontent.com/XIU2/TrackersListCollection/master/all.txt",
    "https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_all.txt",
    "https://raw.githubusercontent.com/XIU2/TrackersListCollection/master/best.txt",
    "https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_best.txt",
    "https://raw.githubusercontent.com/DeSireFire/animeTrackerList/master/AT_best.txt",
    "https://raw.githubusercontent.com/BoxMiao007/Tracker-List/main/trackers.txt",
    "https://raw.githubusercontent.com/BoxMiao007/Tracker-List/main/trackers_best.txt",
    "http://github.itzmx.com/1265578519/OpenTracker/master/tracker.txt",
]

# 请求配置
REQUEST_TIMEOUT = 10  # 秒
MAX_WORKERS = 4  # 并发线程数
RETRY_TIMES = 3  # 重试次数
RETRY_DELAY = 2  # 重试间隔（秒）

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("tracker_update.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ==================== 工具函数 ====================
def fetch_url_with_retry(
    url: str, timeout: int = REQUEST_TIMEOUT, retries: int = RETRY_TIMES
) -> Tuple[Optional[str], str]:
    """
    获取 URL 内容，支持重试机制

    Args:
        url: 目标 URL
        timeout: 超时时间
        retries: 重试次数

    Returns:
        Tuple[内容, 状态信息]
    """
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            logger.info(f"成功获取链接: {url}")
            return response.text, "success"

        except requests.exceptions.Timeout:
            delay = RETRY_DELAY * (2**attempt)
            logger.warning(
                f"请求超时: {url} (尝试 {attempt + 1}/{retries}), 等待 {delay}s"
            )
            if attempt < retries - 1:
                time.sleep(delay)

        except requests.exceptions.ConnectionError:
            delay = RETRY_DELAY * (2**attempt)
            logger.warning(
                f"连接错误: {url} (尝试 {attempt + 1}/{retries}), 等待 {delay}s"
            )
            if attempt < retries - 1:
                time.sleep(delay)

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else "unknown"
            logger.error(f"HTTP 错误 {status_code}: {url}")
            return None, f"HTTP {status_code}"

        except Exception as e:
            logger.error(f"获取链接失败: {url} - {str(e)}")
            return None, str(e)

    return None, "最大重试次数达到"


def process_trackers(content: str) -> Set[str]:
    """
    处理 trackers 内容：去重、去除空行

    Args:
        raw_content: 原始内容

    Returns:
        处理后的 tracker 集合
    """
    lines = content.splitlines()
    # 去除空行和空白字符
    cleaned_lines = [line.strip() for line in lines if line.strip()]
    return set(cleaned_lines)


def get_github_file_sha(file_path: str, headers: Dict[str, str]) -> Optional[str]:
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{file_path}"
    for attempt in range(RETRY_TIMES):
        try:
            response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

            if "X-RateLimit-Remaining" in response.headers:
                remaining = int(response.headers["X-RateLimit-Remaining"])
                reset = int(response.headers.get("X-RateLimit-Reset", 0))
                if remaining <= 1 and reset:
                    sleep_time = max(reset - int(time.time()), 1)
                    logger.warning(f"API 限流即将触发，等待 {sleep_time}s")
                    time.sleep(sleep_time)
                    continue

            if response.status_code == 200:
                return response.json()["sha"]
            elif response.status_code == 404:
                logger.warning(f"文件不存在: {file_path}")
                return None
            elif response.status_code == 403:
                if "X-RateLimit-Remaining" in response.headers:
                    reset = int(response.headers.get("X-RateLimit-Reset", 0))
                    sleep_time = max(reset - int(time.time()), 1)
                    logger.warning(f"触发限��，等待 {sleep_time}s")
                    time.sleep(sleep_time)
                    continue
                logger.error(f"权限不足: {file_path}")
                return None
            else:
                logger.error(f"获取 SHA 失败: {response.status_code}")
                return None
        except requests.exceptions.RequestException as e:
            delay = RETRY_DELAY * (2**attempt)
            logger.warning(
                f"请求失败: {url} (尝试 {attempt + 1}/{RETRY_TIMES}), 等待 {delay}s"
            )
            if attempt < RETRY_TIMES - 1:
                time.sleep(delay)
        except Exception as e:
            logger.error(f"获取 SHA 错误: {e}")
            return None
    return None


def get_github_file_content(
    file_path: str, headers: Dict[str, str]
) -> Tuple[Optional[str], Optional[str]]:
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{file_path}"
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            data = response.json()
            return base64.b64decode(data["content"]).decode(), data["sha"]
        return None, None
    except Exception as e:
        logger.error(f"获取文件内容错误: {e}")
        return None, None


def has_content_changed(
    new_content: str, file_path: str, headers: Dict[str, str]
) -> Tuple[bool, Optional[str]]:
    existing_content, sha = get_github_file_content(file_path, headers)
    if existing_content is None:
        return True, sha
    return existing_content.strip() != new_content.strip(), sha


def update_github_file(
    file_path: str,
    content: str,
    message: str,
    headers: Dict[str, str],
    skip_if_unchanged: bool = True,
) -> Tuple[bool, str]:
    if skip_if_unchanged:
        changed, existing_sha = has_content_changed(
            base64.b64decode(content).decode(), file_path, headers
        )
        if not changed:
            logger.info(f"内容无变化，跳过更新: {file_path}")
            return True, "skipped"
        sha = existing_sha
    else:
        sha = get_github_file_sha(file_path, headers)

    if sha is None and file_path != TRACKERS_FILE_PATH:
        logger.warning(f"无法获取 {file_path} 的 SHA")
        return False, "no_sha"

    data = {"message": message, "content": content}
    if sha:
        data["sha"] = sha

    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{file_path}"
    for attempt in range(RETRY_TIMES):
        try:
            response = requests.put(
                url, headers=headers, json=data, timeout=REQUEST_TIMEOUT
            )

            if "X-RateLimit-Remaining" in response.headers:
                remaining = int(response.headers["X-RateLimit-Remaining"])
                reset = int(response.headers.get("X-RateLimit-Reset", 0))
                if remaining <= 1 and reset:
                    sleep_time = max(reset - int(time.time()), 1)
                    logger.warning(f"API 限流即将触发，等待 {sleep_time}s")
                    time.sleep(sleep_time)
                    continue

            if response.status_code == 200:
                logger.info(f"成功更新文件: {file_path}")
                return True, "updated"
            elif response.status_code == 403:
                if "X-RateLimit-Remaining" in response.headers:
                    reset = int(response.headers.get("X-RateLimit-Reset", 0))
                    sleep_time = max(reset - int(time.time()), 1)
                    logger.warning(f"触发限流，等待 {sleep_time}s")
                    time.sleep(sleep_time)
                    continue
                logger.error(f"权限不足: {file_path}")
                return False, "forbidden"
            else:
                logger.error(f"更新文件失败 {file_path}: {response.status_code}")
                logger.error(response.text)
                return False, f"http_{response.status_code}"
        except requests.exceptions.RequestException as e:
            delay = RETRY_DELAY * (2**attempt)
            logger.warning(
                f"更新失败: {file_path} (尝试 {attempt + 1}/{RETRY_TIMES}), 等待 {delay}s"
            )
            if attempt < RETRY_TIMES - 1:
                time.sleep(delay)
        except Exception as e:
            logger.error(f"更新文件异常: {e}")
            return False, str(e)
    return False, "max_retries"


# ==================== Tracker 健康检测模块 ====================
import socket
import struct

UDP_CONNECT_REQUEST = struct.pack("!QII", 0x41727101980, 0, 0x12345678)
HEALTH_CHECK_TIMEOUT = 5
BEST_TRACKERS_COUNT = 4


def check_http_tracker(
    tracker: str, timeout: int = HEALTH_CHECK_TIMEOUT
) -> Tuple[bool, float]:
    if not (tracker.startswith("http://") or tracker.startswith("https://")):
        return False, 0.0
    url = tracker.rstrip("/") + "/announce"
    try:
        start = time.perf_counter()
        resp = requests.get(
            url, timeout=timeout, headers={"User-Agent": "BitTorrent/2.0"}
        )
        elapsed = time.perf_counter() - start
        return 200 <= resp.status_code < 300, elapsed
    except Exception:
        return False, timeout


def check_udp_tracker(
    tracker: str, timeout: int = HEALTH_CHECK_TIMEOUT
) -> Tuple[bool, float]:
    if not tracker.startswith("udp://"):
        return False, 0.0
    try:
        parts = tracker[6:].split(":")
        if len(parts) != 2:
            return False, 0.0
        host, port = parts[0], int(parts[1])
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        start = time.perf_counter()
        sock.sendto(UDP_CONNECT_REQUEST, (host, port))
        data, _ = sock.recvfrom(16)
        elapsed = time.perf_counter() - start
        sock.close()
        if len(data) >= 8:
            return True, elapsed
        return False, elapsed
    except Exception:
        return False, timeout


def check_tracker_health(tracker: str) -> Dict:
    if tracker.startswith("udp://"):
        alive, delay = check_udp_tracker(tracker)
    elif tracker.startswith("http"):
        alive, delay = check_http_tracker(tracker)
    else:
        return {"tracker": tracker, "alive": False, "delay": 0.0, "score": 0.0}
    score = float(alive) * max(0, 1 - delay / 5.0)
    return {"tracker": tracker, "alive": alive, "delay": delay, "score": score}


def filter_best_trackers(
    trackers: List[str], top_n: int = BEST_TRACKERS_COUNT
) -> List[str]:
    logger.info(f"开始检测 {len(trackers)} 个 tracker 健康状态...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(check_tracker_health, t) for t in trackers]
        results = [f.result() for f in as_completed(futures)]

    best = sorted(
        [r for r in results if r["score"] > 0.5], key=lambda x: x["score"], reverse=True
    )[:top_n]
    logger.info(f"筛选出 {len(best)} 个最佳 trackers")

    if best:
        print("\n" + "=" * 70)
        print("最佳 Tracker 健康检测结果：")
        print("=" * 70)
        for i, r in enumerate(best, 1):
            status = (
                f"{Fore.GREEN}✓{Fore.RESET}"
                if r["alive"]
                else f"{Fore.RED}✗{Fore.RESET}"
            )
            print(
                f"{i:2}. {status} {r['tracker'][:60]:<60} 延迟: {r['delay']:.2f}s 得分: {r['score']:.2f}"
            )
        print("=" * 70)

    return [r["tracker"] for r in best]


# ==================== 主逻辑 ====================
def fetch_all_trackers_concurrent(urls: List[str]) -> Tuple[Set[str], Dict]:
    """
    并发获取所有 trackers

    Args:
        urls: URL 列表

    Returns:
        去重后的 tracker 集合
    """
    all_trackers = set()
    results = {}

    logger.info(f"开始并发获取 {len(urls)} 个数据源...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_url = {
            executor.submit(fetch_url_with_retry, url): url for url in urls
        }

        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                content, status = future.result()
                if content:
                    processed = process_trackers(content)
                    all_trackers.update(processed)
                    results[url] = {"status": "success", "count": len(processed)}
                    logger.info(f"✓ {url} - 获取到 {len(processed)} 个 trackers")
                else:
                    results[url] = {"status": "failed", "error": status}
                    print(f"{Fore.RED}✗ 获取失败: {url} - {status}{Fore.RESET}")
            except Exception as e:
                results[url] = {"status": "error", "error": str(e)}
                print(f"{Fore.RED}✗ 异常: {url} - {e}{Fore.RESET}")

    return all_trackers, results


def update_readme_content(
    readme_content: str, current_date: str, tracker_count: int
) -> str:
    """
    更新 README 内容

    Args:
        readme_content: 原始 README 内容
        current_date: 当前日期
        tracker_count: tracker 数量

    Returns:
        更新后的 README 内容
    """
    # 替换日期
    date_pattern = r"\[!\[Last update\]\(https://img.shields.io/badge/Last%20update-\d{4}/\d{2}/\d{2}-%232ea043\?style=flat-square&logo=github\)\]\(#\)"
    updated_content = re.sub(
        date_pattern,
        f"[![Last update](https://img.shields.io/badge/Last%20update-{current_date}-%232ea043?style=flat-square&logo=github)](#)",
        readme_content,
    )

    # 替换 tracker 数量
    count_pattern = r"All Tracker list &emsp; \(\d+ trackers\)"
    updated_content = re.sub(
        count_pattern,
        f"All Tracker list &emsp; ({tracker_count} trackers)",
        updated_content,
    )

    return updated_content


def display_results_table(results: Dict, total_count: int, run_time: float):
    """
    显示结果表格

    Args:
        results: 获取结果
        total_count: 总数量
        run_time: 运行时间
    """
    print("\n" + "=" * 60)
    print("获取链接结果：")
    print("=" * 60)

    table_data = []
    for idx, url in enumerate(URLS):
        result = results.get(url, {"status": "pending", "count": 0})
        status = result.get("status", "unknown")
        count = result.get("count", 0)

        if status == "success":
            status_display = f"{Fore.GREEN}✓{Fore.RESET}"
            count_display = f"{Fore.CYAN}{count}{Fore.RESET}"
        elif status == "failed":
            status_display = f"{Fore.RED}✗{Fore.RESET}"
            count_display = f"{Fore.RED}失败{Fore.RESET}"
        else:
            status_display = f"{Fore.YELLOW}!{Fore.RESET}"
            count_display = f"{Fore.YELLOW}未知{Fore.RESET}"

        table_data.append([idx + 1, status_display, url, count_display])

    print(
        tabulate(table_data, headers=["#", "状态", "URL", "Trackers"], tablefmt="grid")
    )

    print(f"\n{Fore.CYAN}追踪器总数: {total_count}{Fore.RESET}")
    print(f"脚本运行时间: {run_time:.2f} 秒")
    print("=" * 60)


def main():
    """主函数"""
    logger.info("========== Tracker 更新任务开始 ==========")

    # 记录开始时间
    start_time = time.time()

    # 获取当前日期
    current_date = datetime.date.today().strftime("%Y/%m/%d")

    # 并发获取所有 trackers
    all_trackers, results = fetch_all_trackers_concurrent(URLS)

    # 转换为列表并排序（可选）
    trackers_list = sorted(list(all_trackers))

    # 最小数量安全检查：防止提交空文件或异常数据
    MIN_TRACKERS = 50
    if len(trackers_list) < MIN_TRACKERS:
        logger.error(
            f"Trackers 数量过少 ({len(trackers_list)} < {MIN_TRACKERS})，终止提交"
        )
        print(
            f"{Fore.RED}✗ 安全检查失败：Trackers 数量不足，可能存在数据源问题{Fore.RESET}"
        )
        sys.exit(1)

    # 计算运行时间
    fetch_time = time.time()

    # 输出结果
    display_results_table(results, len(trackers_list), fetch_time - start_time)

    # 健康检测：筛选最佳 trackers
    print(f"\n{Fore.YELLOW}正在检测 Tracker 健康状态...{Fore.RESET}")
    best_trackers = filter_best_trackers(trackers_list, BEST_TRACKERS_COUNT)

    # 准备 GitHub 认证头
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    # 更新 trackers.txt
    print(f"\n{Fore.YELLOW}正在更新 trackers.txt...{Fore.RESET}")
    encoded_content = base64.b64encode("\n".join(trackers_list).encode()).decode()
    commit_message = f"Update trackers on {current_date} - {len(trackers_list)} items"

    success, status = update_github_file(
        TRACKERS_FILE_PATH, encoded_content, commit_message, headers
    )
    if success:
        if status == "skipped":
            print(f"{Fore.CYAN}⊙ Trackers 内容无变化，跳过更新{Fore.RESET}")
        else:
            print(f"{Fore.GREEN}✓ Trackers 文件更新成功！{Fore.RESET}")
    else:
        print(f"{Fore.RED}✗ Trackers 文件更新失败！{Fore.RESET}")
        sys.exit(1)

    # 更新 trackers_best.txt
    if best_trackers:
        print(f"\n{Fore.YELLOW}正在更新 trackers_best.txt...{Fore.RESET}")
        encoded_best = base64.b64encode("\n".join(best_trackers).encode()).decode()
        success, status = update_github_file(
            "trackers_best.txt",
            encoded_best,
            f"Update best trackers on {current_date}",
            headers,
        )
        if success:
            if status == "skipped":
                print(f"{Fore.CYAN}⊙ Best trackers 无变化，跳过更新{Fore.RESET}")
            else:
                print(f"{Fore.GREEN}✓ Best trackers 更新成功！{Fore.RESET}")
        else:
            print(f"{Fore.YELLOW}⚠ Best trackers 更新失败，但不影响主流程{Fore.RESET}")

    # 更新 README.md
    print(f"\n{Fore.YELLOW}正在更新 README.md...{Fore.RESET}")
    try:
        readme_url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/{README_FILE_PATH}"
        readme_response = requests.get(readme_url, timeout=REQUEST_TIMEOUT)
        readme_response.raise_for_status()
        readme_content = readme_response.text

        updated_readme = update_readme_content(
            readme_content, current_date, len(trackers_list)
        )
        encoded_readme = base64.b64encode(updated_readme.encode()).decode()

        success, status = update_github_file(
            README_FILE_PATH, encoded_readme, commit_message, headers
        )
        if success:
            if status == "skipped":
                print(f"{Fore.CYAN}⊙ README 内容无变化，跳过更新{Fore.RESET}")
            else:
                print(f"{Fore.GREEN}✓ README 文件更新成功！{Fore.RESET}")
        else:
            print(f"{Fore.RED}✗ README 文件更新失败！{Fore.RESET}")

    except Exception as e:
        logger.error(f"README 更新失败: {e}")
        print(f"{Fore.RED}✗ README 更新异常: {e}{Fore.RESET}")

    # 总运行时间
    total_time = time.time() - start_time
    print(f"\n{Fore.CYAN}总运行时间: {total_time:.2f} 秒{Fore.RESET}")

    # 检查是否需要优化的警告
    if total_time > 30:
        print(f"{Fore.YELLOW}⚠️  运行时间较长，建议检查网络连接或增加并发数{Fore.RESET}")

    if len(trackers_list) < 100:
        print(f"{Fore.YELLOW}⚠️  Trackers 数量较少，可能存在数据源问题{Fore.RESET}")

    logger.info("========== Tracker 更新任务完成 ==========")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Fore.RED}用户中断执行{Fore.RESET}")
        logger.info("任务被用户中断")
    except Exception as e:
        logger.error(f"程序异常退出: {e}")
        print(f"{Fore.RED}程序异常: {e}{Fore.RESET}")
