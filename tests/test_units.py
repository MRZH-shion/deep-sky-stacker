# -*- coding: utf-8 -*-
"""单元测试：纯函数、数值流程、内存自适应。不依赖 pytest，直接 python 运行。"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import astro_stack_gui as G  # noqa: E402


def _synthetic_stars(h=240, w=320, n=24, seed=7):
    """合成一张带星点的图，返回 (image, [(y, x), ...])。"""
    rng = np.random.default_rng(seed)
    img = rng.normal(100.0, 3.0, (h, w)).astype(np.float32)
    pos = []
    for _ in range(n):
        y = int(rng.integers(14, h - 14))
        x = int(rng.integers(14, w - 14))
        yy, xx = np.mgrid[y - 5:y + 6, x - 5:x + 6]
        g = 400.0 * np.exp(-((yy - y) ** 2 + (xx - x) ** 2) / (2 * 1.6 ** 2))
        img[y - 5:y + 6, x - 5:x + 6] += g.astype(np.float32)
        pos.append((y, x))
    return img, pos


# ------------------------------------------------------------------ 语言
def test_language_switch():
    G.set_lang("en")
    assert G.tr("就绪") == "Ready", G.tr("就绪")
    assert G.obj_display_name("M42 猎户座大星云 (Great Orion Nebula)") == "Great Orion Nebula"
    assert G.short_label("M42 猎户座大星云 (Great Orion Nebula)") == "Great Orion Nebula"
    G.set_lang("zh")
    assert G.tr("就绪") == "就绪"
    assert G.short_label("M42 猎户座大星云 (Great Orion Nebula)") == "M42 猎户座大星云"
    return "中英切换与名称截取正常"


# ------------------------------------------------------------------ 星点检测
def test_detect_stars():
    img, pos = _synthetic_stars()
    xy, _ = G.detect_stars(img, max_stars=200)
    assert len(xy) >= 18, "只检出 %d 颗" % len(xy)
    # 每个注入星点附近 3 px 内应有一个检出
    hit = 0
    for (y, x) in pos:
        d = np.hypot(xy[:, 0] - x, xy[:, 1] - y)
        if d.min() <= 3.0:
            hit += 1
    assert hit >= 18, "只匹配上 %d/%d" % (hit, len(pos))
    return "注入 %d 颗，检出 %d 颗，匹配 %d 颗" % (len(pos), len(xy), hit)


# ------------------------------------------------------------------ 质量评分与权重
def test_frame_quality_and_weights():
    img, _ = _synthetic_stars()
    good = G.frame_quality(img, 24)
    noisy = G.frame_quality(img + np.random.default_rng(1).normal(0, 25, img.shape).astype(np.float32), 24)
    assert noisy["noise"] > good["noise"], (good["noise"], noisy["noise"])

    w = G.frame_weights([good, good, noisy, good])
    assert abs(float(w.mean()) - 1.0) < 1e-3, w.mean()
    assert w[2] < w[0], (w[2], w[0])
    assert 0.25 <= float(w.min()) and float(w.max()) <= 3.0
    return "坏帧权重 %.2f < 好帧 %.2f，均值 %.3f" % (w[2], w[0], w.mean())


# ------------------------------------------------------------------ 局部归一化
def test_ln_correct():
    rng = np.random.default_rng(3)
    ref = rng.normal(500.0, 8.0, (512, 512)).astype(np.float32)
    darker = (ref * 0.95 + 8.0).astype(np.float32)      # 暗 5% 再抬 8（在 ±8% 限幅内）
    fixed = G.ln_correct(darker, ref)
    before = abs(float(np.median(darker)) - float(np.median(ref)))
    after = abs(float(np.median(fixed)) - float(np.median(ref)))
    assert after < before * 0.5, "校正前差 %.1f，校正后差 %.1f" % (before, after)
    # 本来就一致的平面不应该被改动
    same = G.ln_correct(ref, ref)
    assert np.allclose(same, ref, atol=1e-3), "一致平面被改动"
    return "偏差 %.1f -> %.1f ADU，相同平面不动作" % (before, after)


# ------------------------------------------------------------------ 色彩校准
def test_color_balance():
    rng = np.random.default_rng(5)
    base = rng.normal(1000.0, 20.0, (200, 200)).astype(np.float32)
    rgb = np.stack([base, base * 1.15, base * 0.95], axis=2)
    out, gains = G.color_balance(rgb)
    med = [float(np.percentile(out[:, :, c], 30)) for c in range(3)]
    spread = (max(med) - min(med)) / max(med)
    assert spread < 0.02, "校准后通道差 %.2f%%" % (spread * 100)
    assert out.min() >= 0, "出现负值"
    return "通道差 %.2f%%，增益 %s" % (spread * 100, np.round(gains, 3))


# ------------------------------------------------------------------ 小波 / 背景
def test_atrous_and_noise_estimate():
    rng = np.random.default_rng(11)
    img = rng.normal(200.0, 10.0, (128, 128)).astype(np.float32)
    b = G._atrous_blur(img, 1)
    assert abs(float(img.mean()) - float(b.mean())) < 0.5, "均值不守恒"
    assert float(b.std()) < float(img.std()), "平滑后波动没有下降"
    sd = G._mad_sd(img)
    assert 8.5 < sd < 11.5, "噪声估计 %.2f 偏离 10" % sd
    return "均值守恒，σ 估计 %.2f（真值 10）" % sd


# ------------------------------------------------------------------ 内存/线程
def test_memory_adaptive_threads():
    total, avail = G.mem_info_gb()
    assert total >= 0 and avail >= 0
    big = G.auto_threads(6000, 4000, 12.0, cpu=32)
    small = G.auto_threads(600, 400, 12.0, cpu=32)
    assert 1 <= big <= 32 and 1 <= small <= 32
    assert big <= small, (big, small)
    per_big = G.thread_memory_gb(6000, 4000)
    per_small = G.thread_memory_gb(600, 400)
    assert per_big > per_small * 50, (per_big, per_small)
    # 预算极小的时候至少要给 1 个线程
    assert G.auto_threads(6000, 4000, 0.01, cpu=32) == 1
    return "6000x4000 -> %d 线程 (%.2f GB/线程)，小图 -> %d 线程" % (big, per_big, small)


# ------------------------------------------------------------------ 数学工具
def test_umeyama_and_triangles():
    rng = np.random.default_rng(13)
    pts = rng.uniform(0, 500, (30, 2))
    ang = np.deg2rad(7.0)
    R = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]])
    moved = pts @ R.T + np.array([12.0, -8.0])
    M, t = G.umeyama(pts, moved)
    assert np.allclose(M, R, atol=1e-3), M
    assert np.allclose(t, [12.0, -8.0], atol=1e-2), t
    cen, inv = G.triangle_keys(pts[:10])
    assert inv.ndim == 2 and inv.shape[1] == 3, inv.shape
    assert inv.shape[0] >= 8, "三角描述子只有 %d 个" % inv.shape[0]
    assert cen.shape[0] == inv.shape[0], (cen.shape, inv.shape)
    return "相似变换复原（旋转 7°、平移 (12,-8)），三角描述子 %d 个" % inv.shape[0]


# ------------------------------------------------------------------ 拉伸
def test_stretch_is_monotonic():
    rng = np.random.default_rng(17)
    img = np.clip(rng.normal(600.0, 200.0, (64, 64, 3)), 0, None).astype(np.float32)
    gray = np.repeat(img.mean(axis=2, keepdims=True), 3, axis=2).astype(np.float32)
    y = G._stretch_float(gray, sat=1.0, wb=(1.0, 1.0, 1.0), gain=3.0, asinh_k=6.0)
    assert y.shape == gray.shape
    assert 0.0 <= float(y.min()) and float(y.max()) <= 1.0
    src = gray[:, :, 0].ravel()
    dst = y[:, :, 0].ravel()
    # 背景以下会被剪到 0（并列名次），只对背景以上的像素要求单调
    keep = src > np.median(src) + 1e-6
    assert keep.sum() > 1000, "背景以上像素太少"
    rs = np.argsort(np.argsort(src[keep]))
    rd = np.argsort(np.argsort(dst[keep]))
    rho = np.corrcoef(rs, rd)[0, 1]
    assert rho > 0.999, "秩相关 %.5f，拉伸不是单调的" % rho
    assert float(dst.max() - dst.min()) > 0.2, "动态范围被压没了"
    return "输出 0~1，背景以上秩相关 %.5f，动态范围 %.2f" % (rho, float(dst.max() - dst.min()))


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
