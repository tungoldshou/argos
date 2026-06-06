"""收集 smolagents(LocalPythonExecutor)的子模块与数据(CodeAct 执行器,spec §14)。"""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hiddenimports = collect_submodules("smolagents")
datas = collect_data_files("smolagents")
