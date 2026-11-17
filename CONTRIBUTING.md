# 贡献指南（Contributing）

**语言：中文 | [English](CONTRIBUTING.en.md)**

感谢你愿意改进这个项目。提交前请先读一遍下面几条，可以省掉来回返工。

## 提交前自检

```bash
# 1) 语法与静态检查
python -m pyflakes src/astro_stack_gui.py tools/*.py
python -c "import ast,sys; ast.parse(open('src/astro_stack_gui.py',encoding='utf-8').read())"

# 2) 冒烟测试（不读素材，只验证界面能起来、参数能解析）
python src/astro_stack_gui.py --selftest
python src/astro_stack_gui.py --help
```

- 依赖：`pip install -r requirements.txt`，另外 `pip install git+https://github.com/esa/tetra3@master`（tetra3 不在 PyPI）
- 星表数据库不在仓库里，从 Release 下载后放进 `data/`（没有也能跑，只是识别显示"未知"）
- **不要**在代码里写死本机路径、盘符或个人信息
- **不要**提交 `gpu_runtime/`（NVIDIA CUDA 运行库，专有许可）、`*.exe`、RAW 素材

## 代码风格

- Python 3.9+，4 空格缩进，行宽尽量 ≤ 100
- 保持单文件结构（`src/astro_stack_gui.py`）——这是有意的：方便 PyInstaller 打包和用户拷贝
- 新增算法放在对应函数旁边，并写清楚**参数含义**与**默认值理由**
- 日志用 `self.log("中文说明 ...")`，面向用户，别只写英文缩写

## 提交信息

```
<范围>: <一句话说明>

范围可选: stack / register / bg / denoise / star / identify / gui / docs / build
例如:
  denoise: 加入小波色噪去除（只处理色度通道）
  gui: 修复选项区重叠
```

## 新增第三方依赖

必须同时更新三处，否则 CI/审计会不一致：

1. `requirements.txt`
2. `THIRD_PARTY_NOTICES.md`（组件、版本、许可证、用途、许可全文路径）
3. `LICENSES/`（放许可全文，文件名形如 `foo-MIT.txt`）

**不接受** GPL / AGPL / 专有许可的**运行期**依赖（构建期工具如 PyInstaller 例外，它有 bootloader exception）。

## 数据文件

- `data/objects.json` 是 OpenNGC 的衍生数据，**必须**保持 CC BY-SA 4.0，不能改成 MIT
- 星表数据库（`*.npz`）由 `tools/` 里的脚本生成，请连同生成命令一起提交

## 报告问题

请用 Issue 模板，附上：操作系统、Python 版本、堆栈模式、完整日志（`<输出名>.log`）、
以及能复现的最小参数。涉及画质的问题尽量附上截图或对比图。

## 许可

提交即表示你同意你的贡献按本项目的 MIT 许可发布（`data/` 下的 OpenNGC 衍生数据除外，
见 `NOTICE.md`）。
