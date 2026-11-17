# data 目录

这里放数据文件，许可跟代码（MIT）是分开的，细节见根目录 `NOTICE.md`。

| 文件 | 在仓库里？ | 内容 | 来源和许可 |
|---|---|---|---|
| `objects.json` | 是 | 278 个热门深空天体：编号、星等、赤经赤纬、角尺寸、类型、中英文名 | CC BY-SA 4.0，衍生自 [OpenNGC](https://github.com/mattiaverga/OpenNGC) |
| `dsso_narrow.npz` | 否，见 Release | 4°–8° 视场星图模式库，42,681 颗星，827 万个模式 | 用 [tetra3](https://github.com/esa/tetra3)（Apache-2.0，© ESA）拿 Hipparcos 星表生成 |
| `dsso_database.npz` | 否，也不需要 | 10°–30° 视场星图模式库 | 就是 tetra3 自带的 `data/default_database.npz`，装 tetra3 就有，程序会自动找到 |

## 星表怎么准备

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

## 重新生成

```bash
# objects.json 需要 OpenNGC 的 NGC.csv，用 OPENNGC_CSV 指向它
python tools/build_objects.py

# 星表库（需先装 tetra3，见 requirements.txt）
python tools/build_db_narrow.py --fov 4 8 --mag 8.5 --out data/dsso_narrow.npz
```
