# data 目录 / data directory

## 中文

这里放数据文件，许可跟代码（MIT）是分开的，细节见根目录 `NOTICE.md`。

| 文件 | 在仓库里？ | 内容 | 来源和许可 |
|---|---|---|---|
| `objects.json` | 是 | 278 个热门深空天体：编号、星等、赤经赤纬、角尺寸、类型、中英文名 | CC BY-SA 4.0，衍生自 [OpenNGC](https://github.com/mattiaverga/OpenNGC) |
| `dsso_narrow.npz` | 否，见 Release | 4°–8° 视场星图模式库，42,681 颗星，827 万个模式 | 用 [tetra3](https://github.com/esa/tetra3)（Apache-2.0，© ESA）拿 Hipparcos 星表生成 |
| `dsso_database.npz` | 否，也不需要 | 10°–30° 视场星图模式库 | 就是 tetra3 自带的 `data/default_database.npz`，装 tetra3 就有，程序会自动找到 |

### 星表怎么准备

只需要一个文件：把 Release 里的 `dsso_narrow.npz`（约 35 MB）放进本目录即可。

```
data/
├─ objects.json
└─ dsso_narrow.npz
```

10°–30° 的中视场库不用管——`pip install` tetra3 时会连它自带的 `default_database.npz`
一起装好，程序找不到 `dsso_database.npz` 时会自动回退到那个文件。

两个库都没有也能正常堆栈，只是识别目标那一步会失败，日志里写
"星场解算失败, 目标名称: 未知"，其它功能不受影响。

### 重新生成

```bash
# objects.json 需要 OpenNGC 的 NGC.csv，用 OPENNGC_CSV 指向它
python tools/build_objects.py

# 星表库（需先装 tetra3，见 requirements.txt）
python tools/build_db_narrow.py --fov 4 8 --mag 8.5 --out data/dsso_narrow.npz
```

---

## English

Data files live here; their licences are separate from the code (MIT). See `NOTICE.md`.

| File | In the repo? | Contents | Source and licence |
|---|---|---|---|
| `objects.json` | yes | 278 popular deep-sky objects: designation, magnitude, RA/Dec, angular size, type, Chinese and English names | CC BY-SA 4.0, derived from [OpenNGC](https://github.com/mattiaverga/OpenNGC) |
| `dsso_narrow.npz` | no, see Release | 4°–8° field pattern database, 42,681 stars, 8.27 M patterns | generated with [tetra3](https://github.com/esa/tetra3) (Apache-2.0, © ESA) from the Hipparcos catalogue |
| `dsso_database.npz` | no, and not needed | 10°–30° field pattern database | identical to tetra3's bundled `data/default_database.npz`; the program finds it automatically |

### Getting the star database

Only one file is needed: download `dsso_narrow.npz` (~35 MB) from the Release page and put
it in this directory.

```
data/
├─ objects.json
└─ dsso_narrow.npz
```

The 10°–30° medium-field database comes with tetra3 (`default_database.npz` inside the
package); the program falls back to it when `dsso_database.npz` is missing.

Without either database the program still stacks normally — only object identification
fails, logging "solve failed, object: unknown". Everything else is unaffected.

### Regenerating

```bash
# objects.json needs OpenNGC's NGC.csv, point OPENNGC_CSV at it
python tools/build_objects.py

# star database (install tetra3 first, see requirements.txt)
python tools/build_db_narrow.py --fov 4 8 --mag 8.5 --out data/dsso_narrow.npz
```
