# 第三方组件与数据来源声明（Third-Party Notices）

**语言：中文 | [English](THIRD_PARTY_NOTICES.en.md)**

本项目（深空堆栈工具 / Deep-Sky Stacker）在**源代码层面**只使用宽松许可（MIT / BSD /
Apache-2.0）的库，可以自由地公开、修改、商用。

分发**打包好的可执行文件**时，请注意下面第 3 节的义务。

---

## 1. 运行期依赖（会进入 exe）

| 组件 | 版本 | 许可证 | 用途 | 许可全文 |
|---|---|---|---|---|
| NumPy | 2.5.4 | BSD-3-Clause（含 0BSD/MIT/Zlib/CC0 子组件） | 数值运算 | `LICENSES/numpy-BSD-3.txt` |
| SciPy | 1.18.1 | BSD-3-Clause | 滤波/插值/距离变换/KD 树 | `LICENSES/scipy-BSD-3.txt` |
| Pillow | 12.3.0 | MIT-CMU | 图像读写 | `LICENSES/pillow-MIT-CMU.txt` |
| tifffile | 2026.11.8 | BSD-3-Clause | 16bit TIFF 读写 | `LICENSES/tifffile-BSD-3.txt` |
| rawpy | 0.28.0 | MIT | RAW 解码封装 | `LICENSES/rawpy-MIT.txt` |
| **LibRaw**（随 rawpy 以 `raw_r.dll` 分发） | 0.21+ | **LGPL-2.1** | 实际解析 ARW/DNG 等 | `LICENSES/LibRaw-LGPL-2.1.txt` |
| tetra3 | ESA 版 | Apache-2.0 | 星场盲解（plate solving） | `LICENSES/Apache-2.0.txt` |
| CuPy（可选，GPU 模式） | 14.2.0 | MIT（wheel 内 LICENSE；个别子组件为 Apache-2.0/BSD，见 `cupy-license.rst.txt`） | GPU 重采样与累加 | `LICENSES/cupy-MIT.txt`、`LICENSES/cupy-license.rst.txt` |
| Python 标准库 | 3.12 | PSF-2.0 | — | `LICENSES/python-PSF-2.0.txt` |

### 构建期依赖（不进入 exe）

| 组件 | 版本 | 许可证 |
|---|---|---|
| PyInstaller | 6.22.3 | GPLv2 **+ bootloader exception**（`LICENSES/pyinstaller-GPL-2.0-with-exception.txt`） |

> PyInstaller 的例外条款明确允许用它构建并分发**闭源/商业**程序；只有修改 bootloader
> 本身才需要开源那部分修改。

---

## 2. 数据与星表

| 数据 | 来源 | 许可 / 义务 |
|---|---|---|
| `data/objects.json` | [OpenNGC](https://github.com/mattiaverga/OpenNGC)（`database_files/NGC.csv`） | **CC BY-SA 4.0**：必须署名，衍生作品须以相同许可发布 |
| `data/dsso_narrow.npz`（Release 附件） | 由 tetra3 用 **Hipparcos** 星表（ESA，1997）生成 | Hipparcos 为 ESA 公开科学数据；tetra3 为 Apache-2.0 |
| `data/dsso_database.npz`（10°–30°） | 与 tetra3 自带的 `default_database.npz` 相同，不再分发 | 同上 |
| 中文天体名（`tools/build_objects.py`） | 作者整理 | 随本项目代码，MIT |

`objects.json` 是 OpenNGC 的**衍生数据库**，因此本仓库把它单独按 **CC BY-SA 4.0** 提供
（见 `NOTICE.md`），与代码的 MIT 许可相互独立。

---

## 3. 分发二进制时需要注意的三件事

1. **LibRaw 是 LGPL-2.1（不是 MIT）**
   - 我们没有修改 LibRaw，它作为**独立 DLL**（`raw_r.dll`）被调用——这满足 LGPL 的动态链接要求。
   - 义务：告知名与许可、提供 LibRaw 源码获取方式（<https://www.libraw.org/>）。
   - 如果打包成 **onefile exe**，DLL 会被压进 exe、运行时解压到临时目录，用户替换不便；
     想更严谨可用 **onedir** 打包，让 `raw_r.dll` 明摆着可替换。

2. **PyInstaller 的 GPL 例外**只覆盖"用它打包"这一行为，不改变你程序的许可。

3. **不要把 NVIDIA 的 CUDA 库提交进仓库**
   `gpu_runtime/` 里的 `cudart / nvrtc / nvjitlink / cublas / cufft / cusolver /
   cusparse / curand` 是 **NVIDIA 专有**（`LicenseRef-NVIDIA-Proprietary`）。
   CUDA Toolkit EULA 允许它们**随应用一起**再分发，但禁止单独分发/再许可。
   - 本仓库**不包含**这些文件（见 `.gitignore`）。
   - 用户需要 GPU 加速时，自行 `pip install cupy-cuda12x`（会自动带上对应运行库）。
   - 程序在没有 `gpu_runtime/` 时会自动退化为 CPU 模式，功能完整。

---

## 4. 许可证全文位置

```
LICENSES/
├─ Apache-2.0.txt                        tetra3 / CuPy 部分组件
├─ CC-BY-NC-4.0.txt                      docs/images/ 示例图
├─ CC-BY-SA-4.0.txt                      data/objects.json
├─ LibRaw-LGPL-2.1.txt                   raw_r.dll
├─ cupy-MIT.txt, cupy-license.rst.txt  CuPy
├─ numpy-BSD-3.txt                       NumPy
├─ pillow-MIT-CMU.txt                    Pillow
├─ pyinstaller-GPL-2.0-with-exception.txt PyInstaller（仅构建期）
├─ python-PSF-2.0.txt                    Python 运行时
├─ rawpy-MIT.txt                         rawpy
├─ scipy-BSD-3.txt                       SciPy
└─ tifffile-BSD-3.txt                    tifffile
```
