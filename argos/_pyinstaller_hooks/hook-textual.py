"""收集 Textual 的 CSS/资源与子模块(TUI 渲染需要 .tcss / widgets 资源)。"""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hiddenimports = collect_submodules("textual") + collect_submodules("rich")
datas = collect_data_files("textual", include_py_files=False) + collect_data_files("rich")
