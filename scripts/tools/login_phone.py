# encoding: utf-8
"""手机验证码登录并把 Cookie 写入 .env，供后续爬取复用。

需要交互输入手机号和短信验证码，请在终端直接运行。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apis.xhs_pc_login_apis import XHSLoginApi

ENV_PATH = ROOT / ".env"


def main() -> None:
    login = XHSLoginApi()
    cookies = login.phone_login()
    if not cookies:
        raise SystemExit("登录失败：未拿到有效 Cookie")
    ENV_PATH.write_text(f"COOKIES='{cookies}'\n", encoding="utf-8")
    print(f"\n登录成功，Cookie 已写入 {ENV_PATH}")


if __name__ == "__main__":
    main()
