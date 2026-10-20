import argparse
import csv
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import psutil


RUSTFS_DIR = Path(r"D:\rustfs")
STAGE3_SCRIPT = RUSTFS_DIR / "stage3.py"
RESULTS_DIR = RUSTFS_DIR / "results"
PROFILE_FILE = RESULTS_DIR / "stage3_profile.csv"

ATTEMPTS = 3
SAMPLE_INTERVAL_SECONDS = 0.05


def process_tree_memory_mb(process):
    processes = [process]

    try:
        processes.extend(process.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    total_bytes = 0

    for child in processes:
        try:
            total_bytes += child.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return total_bytes / (1024 * 1024)


def run_attempt(disk_count, attempt):
    started_at = datetime.now().isoformat(timespec="seconds")
    command = [sys.executable, str(STAGE3_SCRIPT)]

    process = subprocess.Popen(command, cwd=RUSTFS_DIR)
    monitored_process = psutil.Process(process.pid)

    start_time = time.perf_counter()
    peak_memory_mb = 0.0

    while process.poll() is None:
        peak_memory_mb = max(
            peak_memory_mb,
            process_tree_memory_mb(monitored_process),
        )
        time.sleep(SAMPLE_INTERVAL_SECONDS)

    return_code = process.wait()
    elapsed_seconds = time.perf_counter() - start_time

    result = {
        "disks": disk_count,
        "attempt": attempt,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "peak_python_memory_mb": round(peak_memory_mb, 2),
        "return_code": return_code,
        "started_at": started_at,
    }

    print(
        f"Конфигурация: {disk_count} дисков; "
        f"попытка: {attempt}; "
        f"время: {result['elapsed_seconds']} с; "
        f"пик памяти Python: {result['peak_python_memory_mb']} МБ; "
        f"код завершения: {return_code}"
    )

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("disks", type=int, choices=(4, 6, 8))
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    rows = [
        run_attempt(args.disks, attempt)
        for attempt in range(1, ATTEMPTS + 1)
    ]

    file_exists = PROFILE_FILE.exists()

    with open(PROFILE_FILE, "a", encoding="utf-8" if file_exists else "utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "disks",
                "attempt",
                "elapsed_seconds",
                "peak_python_memory_mb",
                "return_code",
                "started_at",
            ],
            delimiter=";",
        )

        if not file_exists:
            writer.writeheader()

        writer.writerows(rows)

    print(f"Замеры добавлены в {PROFILE_FILE}")


if __name__ == "__main__":
    main()