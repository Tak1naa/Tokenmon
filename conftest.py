# 让 pytest 把项目根目录加入 sys.path,从而可以直接 import tokenmon(单文件模块)。
# 导入 tokenmon 不需要 PySide6(缺失时 HAVE_QT=False),测试可在无 GUI 环境运行。

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Tk 重构后数据层独立为 tokenmon_core.py;旧测试直接 import tokenmon 并 patch
# "tokenmon._get_json"。这里把 tokenmon 名称映射到 tokenmon_core, 让旧测试
# 无需修改即可命中真实数据层(mock.patch 的字符串路径同样按 sys.modules 解析)。
import tokenmon_core  # noqa: E402

sys.modules.setdefault("tokenmon", tokenmon_core)
