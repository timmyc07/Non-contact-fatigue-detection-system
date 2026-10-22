"""拒絕將 .gitignore 指定的本機檔案納入版本控制。"""

from __future__ import annotations

import os
import subprocess


def main() -> int:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--ignored", "--exclude-standard", "-z"],
        check=True, stdout=subprocess.PIPE,
    )
    paths = [os.fsdecode(path) for path in result.stdout.split(b"\0") if path]
    if paths:
        print("下列檔案應只保留本機，請先取消追蹤：")
        for path in paths:
            print(f"  {path}")
        return 1
    print("版本庫檢查通過：沒有追蹤應留本機的檔案。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
