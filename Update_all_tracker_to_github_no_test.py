import requests
import datetime
import base64
import re
import time
import os
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
REPO_NAME = os.getenv("REPO_NAME", "Library")
TRACKERS_FILE_PATH = "trackers.txt"
README_FILE_PATH = "README.md"

# 数据源 URLs
URLS = [
    "https://raw.githubusercontent.com/XIU2/TrackersListCollection/master/all.txt",
    "https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_all.txt",
    "https://raw.githubusercontent.com/XIU2/TrackersListCollection/master/best.txt",
    "https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_best.txt",
    "https://raw.githubusercontent.com/DeSireFire/animeTrackerList/master/AT_best.txt",
    "https://raw.githubusercontent.com/BoxMiao007/Library/main/Trackers/trackers.txt",
    "https://raw.githubusercontent.com/BoxMiao007/Library/main/Trackers/trackers_best.txt",
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
            logger.warning(f"请求超时: {url} (尝试 {attempt + 1}/{retries})")
            if attempt < retries - 1:
                time.sleep(RETRY_DELAY)

        except requests.exceptions.ConnectionError:
            logger.warning(f"连接错误: {url} (尝试 {attempt + 1}/{retries})")
            if attempt < retries - 1:
                time.sleep(RETRY_DELAY)

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
    """
    获取 GitHub 文件的 SHA 值

    Args:
        file_path: 文件路径
        headers: 请求头

    Returns:
        SHA 值或 None
    """
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{file_path}"
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            return response.json()["sha"]
        elif response.status_code == 404:
            logger.warning(f"文件不存在: {file_path}")
            return None
        else:
            logger.error(f"获取 SHA 失败: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"获取 SHA 错误: {e}")
        return None


def update_github_file(
    file_path: str, content: str, message: str, headers: Dict[str, str]
) -> bool:
    """
    更新 GitHub 文件

    Args:
        file_path: 文件路径
        content: 文件内容（Base64 编码后）
        message: 提交信息
        headers: 请求头

    Returns:
        是否成功
    """
    sha = get_github_file_sha(file_path, headers)
    if sha is None and file_path != TRACKERS_FILE_PATH:
        # 如果是 README 且不存在，可能需要创建
        logger.warning(f"无法获取 {file_path} 的 SHA")
        return False

    data = {"message": message, "content": content}
    if sha:
        data["sha"] = sha

    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{file_path}"
    try:
        response = requests.put(
            url, headers=headers, json=data, timeout=REQUEST_TIMEOUT
        )
        if response.status_code == 200:
            logger.info(f"成功更新文件: {file_path}")
            return True
        else:
            logger.error(f"更新文件失败 {file_path}: {response.status_code}")
            logger.error(response.text)
            return False
    except Exception as e:
        logger.error(f"更新文件异常: {e}")
        return False


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

    # 计算运行时间
    fetch_time = time.time()

    # 输出结果
    display_results_table(results, len(trackers_list), fetch_time - start_time)

    # 准备 GitHub 认证头
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    # 更新 trackers.txt
    print(f"\n{Fore.YELLOW}正在更新 trackers.txt...{Fore.RESET}")
    encoded_content = base64.b64encode("\n".join(trackers_list).encode()).decode()
    commit_message = f"Update trackers on {current_date} - {len(trackers_list)} items"

    if update_github_file(TRACKERS_FILE_PATH, encoded_content, commit_message, headers):
        print(f"{Fore.GREEN}✓ Trackers 文件更新成功！{Fore.RESET}")
    else:
        print(f"{Fore.RED}✗ Trackers 文件更新失败！{Fore.RESET}")
        return

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

        if update_github_file(
            README_FILE_PATH, encoded_readme, commit_message, headers
        ):
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
