# -*- coding: utf-8 -*-
"""测试入口：跑单元测试，可选跑真实素材的端到端回归。

用法:
    python tests/run_tests.py                 # 只跑单元测试
    set STACKER_TEST_LIGHTS=D:\\photos\\light   # 加跑 8 帧端到端
    python tests/run_tests.py
"""
import os
import subprocess
import sys
import tempfile
import time
import traceback

# CI 的 Windows 控制台默认是 cp1252/GBK，直接打印中文会 UnicodeEncodeError
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)


def run_unit():
    import test_units as T

    fails = []
    for fn in T.TESTS:
        name = fn.__name__
        t0 = time.time()
        try:
            msg = fn() or ""
            print("  [ok]   %-34s %5.2fs  %s" % (name, time.time() - t0, msg))
        except Exception as e:  # noqa
            fails.append((name, e))
            print("  [FAIL] %-34s %5.2fs  %r" % (name, time.time() - t0, e))
            traceback.print_exc()
    return fails


def run_integration():
    lights = os.environ.get("STACKER_TEST_LIGHTS")
    if not lights or not os.path.isdir(lights):
        print("  [skip] 未设置 STACKER_TEST_LIGHTS，跳过端到端")
        return []
    src = os.path.join(ROOT, "src", "astro_stack_gui.py")
    tmp = tempfile.mkdtemp(prefix="stacker_it_")
    out = os.path.join(tmp, "out.tif")
    cmd = [sys.executable, src, "--cli", "--lights", lights, "--limit", "8",
           "--threads", "4", "--no-identify", "--out-kind", "linear", "--out", out]
    print("  [run]  " + " ".join(cmd[:3] + cmd[3:]))
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    cost = time.time() - t0
    if r.returncode != 0 or not os.path.exists(out):
        print("  [FAIL] 端到端退出码 %s" % r.returncode)
        print((r.stdout or "")[-1500:])
        print((r.stderr or "")[-1500:])
        return [("integration", RuntimeError("exit %s" % r.returncode))]

    import numpy as np
    import tifffile
    a = np.asarray(tifffile.imread(out))
    assert a.ndim == 3 and a.shape[2] == 3, a.shape
    flat = a.astype(np.float32).mean(axis=2)
    sky = flat[20:120, 20:120]
    noise = float(np.std(sky - np.median(sky)))
    peak = float(flat.max())
    if peak <= 0 or noise <= 0:
        print("  [FAIL] 输出异常 peak=%.1f noise=%.2f" % (peak, noise))
        return [("integration", RuntimeError("bad output"))]
    print("  [ok]   integration                          %5.2fs  %s σ=%.2f 峰值=%.0f" % (cost, a.shape, noise, peak))
    return []


def main():
    print("单元测试")
    fails = run_unit()
    print("端到端回归")
    fails += run_integration()
    print()
    if fails:
        print("失败 %d 项: %s" % (len(fails), ", ".join(n for n, _ in fails)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
