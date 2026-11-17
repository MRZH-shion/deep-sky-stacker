# NOTICE — 数据来源与许可

**语言：中文 | [English](NOTICE.en.md)**

本文件说明本仓库中**数据文件**的来源与许可。代码部分的许可见 `LICENSE`（MIT）。

---

## 1. `data/objects.json` — 深空天体目录

- **来源**：[OpenNGC](https://github.com/mattiaverga/OpenNGC)（`database_files/NGC.csv`），
  由 `tools/build_objects.py` 提取 Messier / NGC / IC 子集，并补充常用中文名。
- **修改说明**：只保留 278 个热门天体，字段做了精简（编号、星等、赤经赤纬、角尺寸、类型），
  中文名为本仓库作者添加。
- **许可**：**Creative Commons Attribution-ShareAlike 4.0 International
  (CC BY-SA 4.0)**。全文见 `LICENSES/CC-BY-SA-4.0.txt`，
  或许可证官网 <https://creativecommons.org/licenses/by-sa/4.0/>。

### 使用 `objects.json` 时的义务

1. **署名**：注明数据来自 OpenNGC（链接 + 许可证名称）。
2. **相同方式共享**：如果你修改了它、或把它并入自己的数据库再发布，
   该衍生数据库也必须以 CC BY-SA 4.0（或兼容许可）发布。
3. 单独使用本项目**代码**（不涉及 `objects.json`）时，不受此条约束。

---

## 2. 星表数据库

用 [tetra3](https://github.com/esa/tetra3)（Apache-2.0, © ESA）的 `generate_database()`
生成，星表来源是 **Hipparcos 主星表（ESA, 1997）**。

- `dsso_narrow.npz`（4°–8°）是本项目自己生成的，作为 Release 附件分发，不在仓库里。
- `dsso_database.npz`（10°–30°）与 tetra3 自带的 `data/default_database.npz` 相同，
  不再单独分发，程序找不到时会自动回退到 tetra3 那份。

| 文件 | 视场 | 星表 | 星等上限 | 星数 | 模式数 | 生成参数 |
|---|---|---|---|---|---|---|
| `dsso_database.npz` | 10°–30° | hip_main | 7.0 | 8,818 | 12,369,092 | `pattern_stars_per_fov=10` |
| `dsso_narrow.npz` | 4°–8° | hip_main | 8.5 | 42,681 | 8,267,626 | `pattern_stars_per_fov=6` |

- **Hipparcos**：ESA 的公开科学星表，可自由用于科研与工程；学术使用时建议引用
  *The Hipparcos and Tycho Catalogues*, ESA SP-1200 (1997)。
- **tetra3**：Apache-2.0，见 `LICENSES/Apache-2.0.txt`。
- 生成脚本：`tools/build_db_narrow.py`（窄视场库），中视场库用同样方式生成。

---

## 3. 示例图（`docs/images/`）

`docs/images/` 下的 10 张对比图全部是**本仓库作者本人拍摄并堆栈生成**，不含任何第三方素材。

- **许可**：**CC BY-NC 4.0**（署名—非商业性使用）
  - ✅ 可以：转载、引用、在非商业文章/教程/论文里使用并修改，需署名
  - ❌ 不可以：任何**商业性使用**（含付费课程、商业软件宣传、商品页、以营利为目的的展示）
  - 全文：`LICENSES/CC-BY-NC-4.0.txt` 或 <https://creativecommons.org/licenses/by-nc/4.0/>
- **署名格式**：`MRZH / 深空堆栈工具 (CC BY-NC 4.0)`
- 拍摄器材：Sony a6400 + Tamron 18-300 mm @ 300 mm
- 其中"去光污染"与"色噪去除"两图来自另一套城市银河素材（ISO 400，500 帧）
- 如需**商业授权**，请单独联系作者

> 注意：`docs/images/` 是唯一带非商业限制的目录。代码（`src/`、`tools/`）仍是 MIT，
> 数据（`data/`）按各自的许可，二者都不受此限制。

---

## 4. 未包含的第三方内容

| 内容 | 原因 |
|---|---|
| NVIDIA CUDA 运行库（cudart/nvrtc/cublas/…） | 专有许可，禁止单独再分发；请用 `pip install cupy-cuda12x` 获取 |
| 任何 RAW 测试素材 | 体积大、且为作者个人拍摄 |
