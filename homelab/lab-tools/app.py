import os

import labtools.tools  # noqa: F401  导入即注册所有工具
from labtools.runtime import mcp
from labtools.selftest import run_selftest


if __name__ == "__main__":
    if os.getenv("SELFTEST") == "1":
        run_selftest()
    else:
        mcp.run(transport="streamable-http")
