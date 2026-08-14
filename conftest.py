# 让 pytest 把项目根目录加入 sys.path,从而可以直接 import tokenmon(单文件模块)。
# 导入 tokenmon 不需要 PySide6(缺失时 HAVE_QT=False),测试可在无 GUI 环境运行。
