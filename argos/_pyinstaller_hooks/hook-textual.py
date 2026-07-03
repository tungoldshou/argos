from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hiddenimports = collect_submodules("textual") + collect_submodules("rich")
datas = collect_data_files("textual", include_py_files=False) + collect_data_files("rich")
