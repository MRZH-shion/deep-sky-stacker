# Copyright (c) 2026 MRZH
# SPDX-License-Identifier: MIT
#
# 本文件是「深空堆栈工具」的一部分，按 MIT 许可发布，详见仓库根目录 LICENSE。
"""生成窄视场星表数据库 data/dsso_narrow.npz（默认 4°~8°）。

星表用 tetra3 自带的 Hipparcos（hip_main，约 8.3 万颗星），无需联网。

用法:
    python tools/build_db_narrow.py                 # 4°~8°，星等 8.5
    python tools/build_db_narrow.py --fov 4 10 --mag 9.0
    python tools/build_db_narrow.py --out data/dsso_narrow.npz
"""
import argparse
import os

from tetra3 import Tetra3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fov", nargs=2, type=float, default=[4.0, 8.0],
                    metavar=("MIN", "MAX"), help="视场范围(度)，默认 4 8")
    ap.add_argument("--mag", type=float, default=8.5, help="星等上限，默认 8.5")
    ap.add_argument("--pattern-stars", type=int, default=6,
                    help="每个视场的模式星数(越大越稳、库越大)，默认 6")
    ap.add_argument("--verify-stars", type=int, default=30, help="验证星数，默认 30")
    ap.add_argument("--out", default=None, help="输出文件，默认 data/dsso_narrow.npz")
    a = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    out = a.out or os.path.join(root, "data", "dsso_narrow.npz")

    lo, hi = a.fov
    print("生成星表数据库: fov %.1f~%.1f deg, mag<=%.1f, pattern_stars=%d" % (
        lo, hi, a.mag, a.pattern_stars))
    t3 = Tetra3()
    t3.generate_database(max_fov=hi, min_fov=lo, save_as=out,
                         star_catalog="hip_main", star_max_magnitude=a.mag,
                         pattern_stars_per_fov=a.pattern_stars,
                         verification_stars_per_fov=a.verify_stars,
                         epoch_proper_motion="none")
    print("完成: %.1f MB -> %s" % (os.path.getsize(out) / 1e6, out))


if __name__ == "__main__":
    main()
