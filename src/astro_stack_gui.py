#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
astro_stack_gui.py — 深空照片堆栈工具 (Sony ARW / 通用 RAW)

功能:
  * 导入亮场 / 暗场 / 平场文件夹
  * 自动生成主暗场、主平场(逐 CFA 通道归一)
  * 星点检测 + 相似变换配准(平移/旋转/缩放)
  * CFA 四平面域叠加, 3σ 剔除
  * 输出线性 16bit TIFF (不做白平衡/色彩矩阵, 供后续自行处理) + 预览图

命令行(无界面)用法:
  astro_stack_gui.exe --cli --lights DIR [--darks DIR] [--flats DIR] [--out FILE]
"""
import os
import re
import sys
import glob
import time
import math
import threading
import queue
import traceback
import datetime
import struct
import json

import numpy as np

try:
    import rawpy
except Exception:  # pragma: no cover
    rawpy = None

from scipy import ndimage as ndi
from scipy.spatial import cKDTree

# 叠加模式: twopass(原始) / onepass(CPU 优化) / gpu(GPU 加速) / auto(自动)
DEFAULT_STACK_MODE = os.environ.get("STACKER_MODE", "auto")


def _gpu_available():
    """GPU 叠加是否可用: 只看 gpu_runtime 是否随程序一起提供(真正的导入失败会在
    叠加时自动回退 CPU, 不会中断流程)."""
    try:
        base = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
                else os.path.dirname(os.path.abspath(__file__)))
        return os.path.isdir(os.path.join(base, "gpu_runtime"))
    except Exception:
        return False


def _resolve_mode(mode):
    mode = str(mode or "auto").lower()
    if mode in ("twopass", "onepass", "gpu"):
        return mode
    return "gpu" if _gpu_available() else "onepass"


def _bootstrap_gpu_runtime():
    """如果 exe 同目录有 gpu_runtime 文件夹, 就把它加进搜索路径(CuPy + CUDA DLL + 头文件)."""
    try:
        base = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
                else os.path.dirname(os.path.abspath(__file__)))
        gpu = os.path.join(base, "gpu_runtime")
        if not os.path.isdir(gpu):
            return
        if gpu not in sys.path:
            sys.path.insert(0, gpu)
        nv = os.path.join(gpu, "nvidia")
        if os.path.isdir(nv):
            for d in os.listdir(nv):
                b = os.path.join(nv, d, "bin")
                if os.path.isdir(b):
                    try:
                        os.add_dll_directory(b)
                    except Exception:
                        pass
                    os.environ["PATH"] = b + os.pathsep + os.environ.get("PATH", "")
        shim = os.path.join(gpu, "cuda_shim")
        if os.path.isdir(shim):
            os.environ.setdefault("CUDA_PATH", shim)
    except Exception:
        pass


_bootstrap_gpu_runtime()

# GPU 版: 在启动时(线程还没跑起来)就把 CuPy 加载好, 避免稍后在高负载下
# cuda.pathfinder 的探测子进程超时(会退化成 CPU)
try:
    if DEFAULT_STACK_MODE in ("gpu", "auto") and _gpu_available():
        import cupy as _cp_warmup  # noqa: F401
        _cp_warmup.zeros((4,), _cp_warmup.float32).sum()
except Exception:
    pass



RAW_EXT = (".arw", ".srf", ".sr2", ".dng", ".cr2", ".nef", ".raf", ".orf", ".rw2", ".pef")
EXIF_TIME_TAGS = (0x9003, 0x0132)


# --------------------------------------------------------------------------
# 基础图像工具
# --------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 双语 / bilingual
# ---------------------------------------------------------------------------
LANG = "zh"
EN = {'深空堆栈工具  Deep-Sky Stacker': 'Deep-Sky Stacker', '语言': 'Language', '选择文件夹': 'Select folder', '输出 TIFF': 'Output TIFF', '浏览…': 'Browse…', '亮场文件夹': 'Lights folder', '暗场文件夹': 'Darks folder', '平场文件夹': 'Flats folder', '输出文件': 'Output file', '选项': 'Options', 'σ 剔除倍数': 'Sigma rejection (κ)', '线程数': 'Threads', '叠加方式': 'Stacking mode', '已检测到可用 GPU': 'GPU available', '未检测到 GPU（已禁用 GPU 选项）': 'No GPU detected (GPU mode disabled)', '或手动指定': 'Or set object', '输出内容': 'Output content', '去光污染': 'Light pollution', '自动按素材判断': 'Auto (from data)', '手动设置': 'Manual', '逐帧去光污染': 'Per-frame LP removal', '开': 'On', '减法': 'Subtract', '除法': 'Divide', '结构保护': 'Structure protection', '色噪去除': 'Chroma denoise', '多项式阶': 'Polynomial degree', 'RBF 平滑': 'RBF smoothing', '小波降噪': 'Wavelet denoise', '（层数 4，只处理亮度）': '(4 scales, luminance only)', '星点处理': 'Star handling', '强度': 'Strength', '快速重采样（双线性，略软·更快）': 'Fast resampling (bilinear, softer, faster)', '自动裁剪到公共覆盖区域': 'Auto crop to common area', '自动识别目标': 'Auto object identification', '按目标类型优化': 'Optimise by object type', 'TIFF 白平衡版': 'White-balanced TIFF', '额外输出 16bit PNG': 'Extra 16-bit PNG', '背景平整(旧算法)': 'Background flatten (legacy)', '请手动选择下面各项': 'Pick the items below manually', '自动判断素材光污染，参数由程序定': 'Light pollution graded automatically', '就绪': 'Ready', '开始堆栈': 'Start stacking', '取消': 'Cancel', '单独识别星空…': 'Identify frame…', '加白边成品…': 'Framed output…', '自动拉伸…': 'Auto stretch…', '识别结果': 'Identification', '完成': 'Done', '已停止': 'Stopped', '出错': 'Error', '无法开始堆栈': 'Cannot start stacking', '提示': 'Notice', '请先选择亮场文件夹': 'Please choose the lights folder first', '准备中…': 'Preparing…', '未知': 'unknown', '已取消': 'Cancelled', '识别中…': 'Identifying…', '未填': 'unset', '选择要识别的图片或 RAW 文件': 'Choose an image or RAW file to identify', 'RAW 或图像': 'RAW or image', '所有文件': 'All files', '选择要拉伸的线性 TIFF': 'Choose a linear TIFF to stretch', '正在取消…': 'Cancelling…', '原版(两遍叠加)': 'Two-pass', 'CPU 单遍优化': 'CPU single-pass', 'GPU 加速': 'GPU', '线性 + 拉伸（都生成）': 'Linear + stretched (both)', '只生成线性 TIFF': 'Linear only', '只生成拉伸 TIFF': 'Stretched only', '自动判断（推荐）': 'Auto (recommended)', '低（郊区/暗夜）': 'Low (suburban / dark)', '中（城郊）': 'Mid (outskirts)', '高（城市）': 'High (city)', '不处理': 'Off', '缩星': 'Reduce', '去星': 'Remove', '关': 'Off', '轻': 'Light', '中': 'Medium', '强': 'Strong', '（自动识别）': '(auto identify)', '自动选择': 'Auto', '不填(未知)': 'Not set (unknown)', '全画幅 36×24': 'Full frame 36x24', 'APS-C(佳能) 22.3×14.9': 'APS-C (Canon) 22.3x14.9', '1 英寸 13.2×8.8': '1 inch 13.2x8.8', '窄视场 4°~8°': 'Narrow 4-8 deg', '中等 10°~30°': 'Medium 10-30 deg', '宽视场 12°~60°': 'Wide 12-60 deg', '亮场 %d 张, 暗场 %d 张, 平场 %d 张': 'lights %d, darks %d, flats %d', '输出目录: %s': 'Output directory: %s', '已按拍摄时间排序亮场': 'Lights sorted by capture time', '正在识别拍摄目标(内置星表盲解) ...': 'Identifying field (blind solve) ...', '星场解算失败, 目标名称: 未知': 'Solve failed, object unknown', '未识别出具体目标, 跳过按类型优化': 'No object identified, skipping type tuning', '配准完成: %d/%d 帧': 'Registration done: %d/%d frames', '去马赛克 ...': 'Demosaicing ...', 'GPU 单遍叠加 (重采样+累加在显卡上) ...': 'GPU single-pass stacking ...', 'CPU 单遍叠加 (在线 κσ 剔除) ...': 'CPU single-pass stacking ...', 'Background2D 完成': 'Background2D done', '已保存线性 16bit TIFF: %s': 'Linear 16-bit TIFF saved: %s', '总耗时 %.1f 分钟, 叠加 %d 帧, 目标: %s': 'Finished in %.1f min, %d frames, object: %s', 'RAW 亮场/暗场/平场 配准堆栈': 'Register and stack RAW lights, darks and flats', '界面语言: zh(中文) / en(English)': 'interface language: zh / en', '只处理前 N 张亮场(调试用)': 'process only the first N lights (debug)', '不做目标识别': 'skip object identification', '手动指定目标名称, 例如 M42': 'set the object manually, e.g. M42', '单独识别图片/RAW 文件, 不做堆栈': 'identify one image/RAW file without stacking', '画幅, 如 APS-C / 全画幅 / M4/3': 'sensor, e.g. APS-C / full frame / M4/3', '焦距 mm': 'focal length in mm', '裁切系数, 覆盖 --sensor': 'crop factor, overrides --sensor', '星表: auto / 窄视场 / 中等 / 宽视场 / 全部尝试': 'catalogue: auto / narrow / medium / wide / all', '额外输出 16bit PNG 彩色预览图': 'also write a 16-bit colour PNG preview', '输出内容: both=线性+拉伸(默认) / linear=只线性 / stretch=只拉伸': 'output: both=linear+stretched (default) / linear / stretch', '等同于 --out-kind linear (兼容旧用法)': 'same as --out-kind linear (legacy)', '拉伸图饱和度倍数': 'saturation of the stretched image', '背景平整(叠加后): 去大尺度渐变': 'flatten background after stacking: remove large gradients', '逐帧去光污染(适合重度光害/无跟踪)': 'per-frame LP removal (heavy light pollution / untracked)', '重采样用双线性(更快, 星点略软); 默认三次插值': 'bilinear resampling (faster, softer stars); cubic is default', '小波降噪强度: off/light(0.30)/medium(0.50)/strong(0.70)': 'wavelet denoise: off/light(0.30)/medium(0.50)/strong(0.70)', '小波层数(默认 4)': 'wavelet scales (default 4)', 'JPG 长边像素上限(默认 2600)': 'JPG long-edge limit (default 2600)', 'JPG 质量(默认 92)': 'JPG quality (default 92)', '叠加后的星点处理: off / reduce(缩星) / remove(去星)': 'star handling after stacking: off / reduce / remove', '星点处理强度 0~1': 'star handling strength 0..1', '关闭按目标类型优化': 'disable type-based tuning', '预览饱和度倍数, 默认 1.0': 'preview saturation, default 1.0', '单独加白边成品(输出 _framed.jpg)': 'framed output with the object name (_framed.jpg)', '边框宽度, 占短边比例(默认 0.05)': 'border width as a fraction of the short side', '自动拉伸线性 TIFF': 'auto stretch a linear TIFF', '拉伸后饱和度': 'saturation after stretching', '光污染处理等级: auto/low/mid/high/manual': 'light pollution level: auto/low/mid/high/manual', '逐帧去光污染(每帧扣背景)': 'per-frame LP removal', '逐帧去光污染用除法': 'per-frame LP removal, divide mode', '网格背景提取(叠加后)': 'mesh background extraction after stacking', '背景地板分位数': 'background floor percentile', '网格背景 + 结构保护(保住星云/银河)': 'mesh background + structure protection', '二维多项式曲面(1=平面, 2~4=曲面)': 'polynomial surface (1=plane, 2..4=curved)', 'RBF 薄板样条背景(平滑量 0=关)': 'RBF thin-plate background (0=off)', '旧的后置背景平整': 'legacy post-stack flatten', '小波色噪去除(只处理色度)': 'wavelet chroma denoise (chrominance only)', '色噪小波层数(默认 3)': 'chroma wavelet scales (default 3)', '旧的色度高斯降噪 sigma(0=关)': 'legacy Gaussian chroma denoise sigma (0=off)', 'TIFF 输出时应用相机白平衡': 'apply camera white balance to the TIFF', '手动指定目标 (跳过视场检查)': 'set the object manually (skips the FOV check)'}


# 补充条目（避免直接改上面的 EN 字面量）
EN.update({
    "自动判断素材光污染，参数由程序定": "Light pollution graded automatically",
    "中文": "中文",
})


# 补充条目（避免直接改上面的 EN 字面量）
EN.update({
    "自动判断素材光污染，参数由程序定": "Light pollution graded automatically",
    "中文": "中文",
    "已保存预览图(仅拉伸, 未做色彩校准): %s": "Preview written (stretched, not colour-calibrated): %s",
    "已保存 16bit PNG 预览: %s": "16-bit PNG preview written: %s",
    "已保存拉伸 16bit TIFF(可直接用): %s": "Stretched 16-bit TIFF written (ready to use): %s",
    "识别结果已写入: %s": "Identification written: %s",
    "星点处理: %s (强度 %.2f, 掩膜覆盖 %.1f%%)":
        "Star handling: %s (strength %.2f, mask covers %.1f%%)",
    "已保存无星版: %s": "Starless version written: %s",
    "已保存星点层: %s": "Star layer written: %s",
    "已保存缩星版: %s": "Reduced-star version written: %s",
    "自动判断光污染等级: %s (背景中位 %.0f, 平面梯度 %.0f (相对 %.2f), 评分 %.2f)":
        "Light pollution level: %s (background median %.0f, plane gradient %.0f (relative %.2f), score %.2f)",
    "视场 %.1f° (%s), 可用星表覆盖 %.1f°~%.1f° -> 在范围内":
        "FOV %.1f deg (%s), catalogue coverage %.1f-%.1f deg -> in range",
    "视场超出星表范围, 不做按类型优化(可用'手动指定'强制启用)":
        "FOV outside catalogue range, skipping type tuning (use manual object to force)",
    "目标为用户手动指定, 跳过视场检查": "Object set manually, skipping FOV check",
    "叠加 %d 帧 (GPU)": "stacking %d frames (GPU)",
})


EN.update({
    '亮场 %d 张, 暗场 %d 张, 平场 %d 张': 'lights %d, darks %d, flats %d',
    '未提供暗场, 跳过暗场校正': 'no darks supplied, skipping dark calibration',
    '未提供平场, 跳过平场校正': 'no flats supplied, skipping flat calibration',
    '星点检测完成, 有效帧 %d/%d': 'star detection done, %d/%d frames usable',
    '配准完成: %d/%d 帧': 'registration done: %d/%d frames',
    '按公共覆盖范围裁剪 -> %d x %d': 'cropped to common coverage -> %d x %d',
    '已保存线性 16bit TIFF: %s': 'linear 16-bit TIFF saved: %s',
    '已保存预览图(仅拉伸, 未做色彩校准): %s': 'preview written (stretched, not colour-calibrated): %s',
    '识别结果已写入: %s': 'identification written: %s',
})

EN.update({
    "已生成: %s  (目标: %s)": "written: %s  (object: %s)",
    "已生成: %s": "written: %s",
})


def _lang_path():
    base = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "settings.json")


def load_lang():
    global LANG
    try:
        with open(_lang_path(), "r", encoding="utf-8-sig") as f:
            v = json.load(f).get("lang", "zh")
        LANG = "en" if str(v).lower().startswith("en") else "zh"
    except Exception:
        LANG = "zh"


def save_lang():
    try:
        with open(_lang_path(), "w", encoding="utf-8") as f:
            json.dump({"lang": LANG}, f)
    except Exception:
        pass


def set_lang(v):
    global LANG
    LANG = "en" if str(v).lower().startswith("en") else "zh"


def tr(s):
    if LANG == "zh":
        return s
    return EN.get(s, s)


_LANG_BINDINGS = []     # [(widget, 中文文本)]
_LANG_COMBOS = []       # [(widget, [中文值...])]


def lang_bind(root):
    """把当前所有控件的中文文本记下来，供切换语言时重写。"""
    del _LANG_BINDINGS[:]
    del _LANG_COMBOS[:]

    def walk(w):
        yield w
        for c in w.winfo_children():
            yield from walk(c)

    for w in walk(root):
        try:
            cls = w.winfo_class()
        except Exception:
            continue
        if cls == "TCombobox":
            try:
                _LANG_COMBOS.append((w, list(w.cget("values"))))
            except Exception:
                pass
            continue
        try:
            txt = w.cget("text")
        except Exception:
            continue
        if txt:
            _LANG_BINDINGS.append((w, txt))


def lang_apply(root):
    for w, zh in _LANG_BINDINGS:
        try:
            w.configure(text=tr(zh))
        except Exception:
            pass
    for w, vals in _LANG_COMBOS:
        try:
            cur = w.get()
            shown = [tr(v) for v in vals]
            idx = None
            for cand in (cur, tr(cur)):
                if cand in shown:
                    idx = shown.index(cand)
                    break
                if cand in vals:
                    idx = vals.index(cand)
                    break
            w.configure(values=shown)
            if idx is not None:
                w.set(shown[idx])
        except Exception:
            pass
    try:
        root.title(tr("深空堆栈工具  Deep-Sky Stacker"))
    except Exception:
        pass


def _warp_order(o):
    """重采样阶数：3=三次(Catmull-Rom/样条，默认)，1=双线性(快，略软)。"""
    try:
        return 1 if int(getattr(o, "warp_order", 3)) == 1 else 3
    except Exception:
        return 3


def decode(path):
    with rawpy.imread(str(path)) as raw:
        img = raw.raw_image.copy()
        wb = np.array(raw.camera_whitebalance, float)
        s = raw.sizes
        crop = (int(s.crop_top_margin), int(s.crop_left_margin),
                int(s.crop_height), int(s.crop_width))
    return img, dict(wb=wb, crop=crop)


def binned_luminance(a):
    h, w = a.shape
    h2, w2 = (h // 2) * 2, (w // 2) * 2
    return a[:h2, :w2].reshape(h2 // 2, 2, w2 // 2, 2).mean(axis=(1, 3))


def detect_stars(img, max_stars=400, nsig=5.0, border=24, min_sep=4.0, sat=13000.0, k=3):
    im = img.astype(np.float32, copy=False)
    bg = ndi.gaussian_filter(im, 12.0)
    hp = im - bg
    med = np.median(hp)
    noise = 1.4826 * np.median(np.abs(hp - med)) + 1e-6
    peaks = (hp == ndi.maximum_filter(hp, size=3)) & (hp > med + nsig * noise) & (im < sat)
    peaks[:border, :] = False
    peaks[-border:, :] = False
    peaks[:, :border] = False
    peaks[:, -border:] = False
    lab, ncomp = ndi.label(peaks)
    if ncomp == 0:
        return np.zeros((0, 2), np.float32), np.zeros((0,), np.float32)
    h, w = im.shape
    pos = np.asarray(ndi.center_of_mass(np.where(peaks, hp, 0.0), lab,
                                        np.arange(1, ncomp + 1)), np.float64).reshape(-1, 2)
    ys = np.clip(np.round(pos[:, 0]).astype(int), k, h - k - 1)
    xs = np.clip(np.round(pos[:, 1]).astype(int), k, w - k - 1)
    yy, xx = np.mgrid[-k:k + 1, -k:k + 1]
    yy = yy.ravel()
    xx = xx.ravel()
    patches = np.stack([hp[ys + dy, xs + dx] for dy in range(-k, k + 1) for dx in range(-k, k + 1)], axis=1)
    patches = np.where(patches > 0, patches, 0.0).astype(np.float64)
    flux = patches.sum(axis=1)
    ok = flux > 0
    cy = ys.astype(np.float64)
    cx = xs.astype(np.float64)
    cy[ok] = ys[ok] + (patches[ok] * yy).sum(axis=1) / flux[ok]
    cx[ok] = xs[ok] + (patches[ok] * xx).sum(axis=1) / flux[ok]
    order = np.argsort(-flux)
    acc = []
    cell = max(min_sep, 1.0)
    grid = {}
    for oi in order:
        if flux[oi] <= 0:
            continue
        px, py = float(cx[oi]), float(cy[oi])
        ix, iy = int(px // cell), int(py // cell)
        hit = False
        for gx in (ix - 1, ix, ix + 1):
            for gy in (iy - 1, iy, iy + 1):
                for (qx, qy) in grid.get((gx, gy), ()):
                    if (qx - px) ** 2 + (qy - py) ** 2 < min_sep ** 2:
                        hit = True
                        break
                if hit:
                    break
            if hit:
                break
        if hit:
            continue
        grid.setdefault((ix, iy), []).append((px, py))
        acc.append(int(oi))
        if len(acc) >= max_stars:
            break
    sel = np.asarray(acc, int)
    if len(sel) == 0:
        return np.zeros((0, 2), np.float32), np.zeros((0,), np.float32)
    return np.stack([cx[sel], cy[sel]], 1).astype(np.float32), flux[sel].astype(np.float32)


def detect_stars_narrow(lum, max_stars=200, sigma=2.0, filtsize=41):
    """窄视场专用星点提取。

    自家 detect_stars 是为叠加优化的(偏重速度/去噪), 星点少又密时质心不够准,
    盲解容易失败。窄视场(视场 < 10°)改用 tetra3 自带的质心算法, 它对
    小视场星敏感器这类场景调得更好。返回 (xy, flux)。
    """
    try:
        import tetra3
        cent = tetra3.get_centroids_from_image(
            np.asarray(lum, np.float32), sigma=float(sigma),
            filtsize=int(filtsize), max_returned=int(max_stars))
    except Exception:
        return detect_stars(lum, max_stars=max_stars)
    cent = np.asarray(cent, np.float32)
    if len(cent) == 0:
        return np.zeros((0, 2), np.float32), np.zeros((0,), np.float32)
    xy = np.stack([cent[:, 1], cent[:, 0]], 1)      # (y,x) -> (x,y)
    flux = np.arange(len(xy), 0, -1, dtype=np.float32)  # tetra3 已按亮度排序
    return xy, flux


def umeyama(src, dst):
    src = np.asarray(src, np.float64)
    dst = np.asarray(dst, np.float64)
    n = len(src)
    mu_s = src.mean(0)
    mu_d = dst.mean(0)
    s0 = src - mu_s
    d0 = dst - mu_d
    C = d0.T @ s0 / n
    U, D, Vt = np.linalg.svd(C)
    S = np.eye(2)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[1, 1] = -1
    R = U @ S @ Vt
    var_s = (s0 ** 2).sum() / n
    scale = (D * np.diag(S)).sum() / max(var_s, 1e-12)
    t = mu_d - scale * R @ mu_s
    return scale * R, t


def triangle_keys(xy, nbrs=6, min_ratio=1.08, min_unique=1.03):
    n = len(xy)
    if n < 8:
        return np.zeros((0, 2)), np.zeros((0, 3), int)
    tree = cKDTree(xy)
    k = min(nbrs + 1, n)
    _, idx = tree.query(xy, k=k)
    idx = np.atleast_2d(idx)
    tris = set()
    for i in range(n):
        nb = idx[i, 1:]
        for a in range(len(nb)):
            for b in range(a + 1, len(nb)):
                tris.add((i, int(nb[a]), int(nb[b])))
    keys = []
    tri_list = []
    for tri in tris:
        p = xy[list(tri)].astype(np.float64)
        d = np.array([np.linalg.norm(p[0] - p[1]), np.linalg.norm(p[1] - p[2]), np.linalg.norm(p[2] - p[0])])
        sd = np.sort(d)
        if sd[2] / max(sd[1], 1e-9) < min_unique:
            continue
        li = int(np.argmax(d))
        if li == 0:
            q, r, opp = 0, 1, 2
        elif li == 1:
            q, r, opp = 1, 2, 0
        else:
            q, r, opp = 2, 0, 1
        P, Q, R = p[q], p[r], p[opp]
        L = np.linalg.norm(P - Q)
        if L < 1e-6:
            continue
        cross = (Q[0] - P[0]) * (R[1] - P[1]) - (Q[1] - P[1]) * (R[0] - P[0])
        if cross < 0:
            P, Q = Q, P
            q, r = r, q
        a1 = np.linalg.norm(P - R) / L
        a2 = np.linalg.norm(Q - R) / L
        if min(a1, a2) < 1e-3:
            continue
        mx, mn = max(a1, a2), min(a1, a2)
        if mx / mn < min_ratio:
            continue
        keys.append((a1, a2))
        tri_list.append((int(tri[q]), int(tri[r]), int(tri[opp])))
    return np.asarray(keys, np.float64), np.asarray(tri_list, int)


def match_stars(ref_xy, tgt_xy, tol_inv=0.03, max_stars=200, min_inliers=12, ref_keys=None):
    refs = np.asarray(ref_xy[:max_stars], np.float64)
    tgts = np.asarray(tgt_xy[:max_stars], np.float64)
    if len(refs) < 6 or len(tgts) < 6:
        return None
    # 参考帧固定：三角键只算一次（每帧重算会多花约 40% 匹配时间）
    rk, rt = ref_keys if ref_keys is not None else triangle_keys(refs)
    tk, tt = triangle_keys(tgts)
    if len(rk) == 0 or len(tk) == 0:
        return None
    tree = cKDTree(tk)
    kq = min(2, len(tk))
    dist, jj = tree.query(rk, k=kq)
    if kq == 1:
        dist = dist[:, None]
        jj = jj[:, None]
    m = dist < tol_inv
    ii = np.nonzero(m)[0]
    kk = jj[m]
    if len(ii) == 0:
        return None
    src = refs[rt[ii]]
    dst = tgts[tt[kk]]
    asrc = (src[:, 1, 0] - src[:, 0, 0]) + 1j * (src[:, 1, 1] - src[:, 0, 1])
    bsrc = (src[:, 2, 0] - src[:, 0, 0]) + 1j * (src[:, 2, 1] - src[:, 0, 1])
    adst = (dst[:, 1, 0] - dst[:, 0, 0]) + 1j * (dst[:, 1, 1] - dst[:, 0, 1])
    bdst = (dst[:, 2, 0] - dst[:, 0, 0]) + 1j * (dst[:, 2, 1] - dst[:, 0, 1])
    den = np.abs(asrc) ** 2 + np.abs(bsrc) ** 2
    okden = den > 1e-6
    w = np.zeros(len(ii), complex)
    w[okden] = (np.conj(asrc[okden]) * adst[okden] + np.conj(bsrc[okden]) * bdst[okden]) / den[okden]
    cs = src.mean(axis=1)
    cd = dst.mean(axis=1)
    tx = cd[:, 0] - (w.real * cs[:, 0] - w.imag * cs[:, 1])
    ty = cd[:, 1] - (w.imag * cs[:, 0] + w.real * cs[:, 1])
    ang = np.angle(w)
    sc = np.abs(w)
    okc = okden & (sc > 0.9) & (sc < 1.1) & (np.abs(ang) < np.radians(30))
    if okc.sum() < 5:
        return None
    ang, sc, tx, ty, w = ang[okc], sc[okc], tx[okc], ty[okc], w[okc]
    q = np.stack([np.round(ang / np.radians(0.2)), np.round(sc / 0.002),
                  np.round(tx / 10.0), np.round(ty / 10.0)], axis=1).astype(np.int64)
    uq, inv, cnt = np.unique(q, axis=0, return_inverse=True, return_counts=True)
    tgt_tree = cKDTree(tgt_xy)

    def score(M, t, radius=2.0):
        s = np.hypot(M[0, 0], M[1, 0])
        if not (0.9 < s < 1.1):
            return -1, 1e9
        pred = refs @ M.T + t
        d, idx = tgt_tree.query(pred, k=1)
        good = d < radius
        if good.sum() == 0:
            return 0, 1e9
        nin = int(np.unique(idx[good]).size)
        if nin < 3:
            return nin, 1e9
        return nin, float(np.sqrt((d[good] ** 2).mean()))

    best = None
    for b in np.argsort(-cnt)[:15]:
        pick = np.nonzero(inv == b)[0][0]
        ww = w[pick]
        M = np.array([[ww.real, -ww.imag], [ww.imag, ww.real]])
        t = np.array([tx[pick], ty[pick]])
        for _ in range(5):
            nin, resid = score(M, t)
            if nin < min_inliers:
                break
            pred = refs @ M.T + t
            d, idx = tgt_tree.query(pred, k=1)
            good = d < 2.0
            M, t = umeyama(refs[good], tgt_xy[idx[good]])
        nin, resid = score(M, t)
        if nin >= min_inliers and (best is None or nin > best[2]):
            best = (M, t, nin, resid)
    return best


def refine_match(ref_xy, tgt_xy, M, t, radius=8.0, min_in=15, iters=4):
    tree = cKDTree(tgt_xy)
    pred = ref_xy @ M.T + t
    d, idx = tree.query(pred, k=1)
    good = d < radius
    if good.sum() < min_in:
        return None
    for _ in range(iters):
        M, t = umeyama(ref_xy[good], tgt_xy[idx[good]])
        if not (0.995 < np.hypot(M[0, 0], M[1, 0]) < 1.005):
            return None
        pred = ref_xy @ M.T + t
        d, idx = tree.query(pred, k=1)
        good = d < 2.0
        if good.sum() < min_in:
            return None
    return M, t, int(good.sum()), float(np.sqrt((d[good] ** 2).mean()))


def _read_exif(path):
    """解析 RAW(TIFF 结构) 的 IFD0 与 Exif 子 IFD, 返回 (ifd0, exif) 两个 tag 字典."""
    with open(path, "rb") as f:
        d = f.read(200000)
    if len(d) < 16:
        return {}, {}
    bo = "<" if d[:2] == b"II" else ">"
    SZ = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}
    FM = {1: "B", 3: "H", 4: "I", 5: "II", 6: "b", 8: "h", 9: "i", 10: "ii", 11: "f", 12: "d"}

    def rd(o):
        n = struct.unpack(bo + "H", d[o:o + 2])[0]
        t = {}
        for i in range(n):
            e = o + 2 + i * 12
            if e + 12 > len(d):
                break
            tag, typ, cnt = struct.unpack(bo + "HHI", d[e:e + 8])
            sz = SZ.get(typ, 1) * cnt
            if sz > 4:
                vo = struct.unpack(bo + "I", d[e + 8:e + 12])[0]
                raw = d[vo:vo + sz]
            else:
                raw = d[e + 8:e + 8 + sz]
            if typ == 2:
                t[tag] = raw.split(b"\x00")[0].decode("latin-1", "replace")
            elif typ in FM and len(raw) >= SZ.get(typ, 1) * cnt:
                v = struct.unpack(bo + FM[typ] * cnt, raw)
                t[tag] = v if len(v) > 1 else v[0]
        return t

    ifd = rd(struct.unpack(bo + "I", d[4:8])[0])
    ex = rd(ifd[0x8769]) if 0x8769 in ifd else {}
    return ifd, ex


def exif_time(path):
    try:
        ifd, ex = _read_exif(path)
        s = ex.get(0x9003) or ifd.get(0x132)
        return datetime.datetime.strptime(s, "%Y:%m:%d %H:%M:%S") if s else None
    except Exception:
        return None


def _ratio(v):
    try:
        if isinstance(v, tuple):
            return float(v[0]) / float(v[1]) if v[1] else 0.0
        return float(v)
    except Exception:
        return 0.0


def exif_fov(path):
    """从 EXIF 读焦距/等效焦距, 估算画面**对角视场**(度)。拿不到返回 None。

    RAW 里通常有 0xA405(35mm 等效焦距) 或 0x920A(实际焦距)+画幅信息。
    优先用等效焦距, 与传感器尺寸无关, 最稳。
    """
    try:
        ifd, ex = _read_exif(path)
    except Exception:
        return None
    f35 = ex.get(0xA405) or ifd.get(0xA405)
    try:
        f35 = float(f35) if f35 else 0.0
    except Exception:
        f35 = 0.0
    if f35 and 4.0 <= f35 <= 3000.0:
        v = math.degrees(2.0 * math.atan(43.267 / 2.0 / f35))
        return v if v > 0 else None
    fl = _ratio(ex.get(0x920A) or ifd.get(0x920A))
    if fl <= 0:
        return None
    # 没有等效焦距: 试着自己算传感器尺寸 —— FocalPlaneXResolution(0xA20E) 是"每单位像素数"
    # 配合 ResolutionUnit(0xA210: 2=英寸, 3=厘米) 可反推传感器宽度(毫米)
    try:
        fx = _ratio(ex.get(0xA20E) or ifd.get(0xA20E))
        unit = ex.get(0xA210) or ifd.get(0xA210) or 2
        W = ifd.get(0x100) or 0
        if fx > 0 and W > 0:
            per_mm = fx / (25.4 if int(unit) == 2 else 10.0)
            sensor_w = W / per_mm
            if 3.0 <= sensor_w <= 60.0:
                diag_mm = math.hypot(sensor_w, sensor_w * 2.0 / 3.0) / 2.0
                v = math.degrees(2.0 * math.atan(diag_mm / fl))
                if v > 0:
                    return v
    except Exception:
        pass
    # 最后兜底: 按 APS-C 画幅(23.5 x 15.6) + 焦距 估算对角视场
    diag_mm = math.hypot(23.5, 15.6) / 2.0
    v = math.degrees(2.0 * math.atan(diag_mm / fl))
    return v if v > 0 else None


# --------------------------------------------------------------------------
# 目标类型 -> 参数优化
# --------------------------------------------------------------------------
TYPE_CATEGORY = {
    "OCl": "cluster", "GCl": "cluster", "*": "cluster", "Cl+N": "nebula",
    "Neb": "nebula", "HII": "nebula", "RfN": "nebula", "SNR": "nebula",
    "PN": "planetary", "G": "galaxy",
}
CATEGORY_NAME = {"cluster": "星团", "nebula": "星云", "galaxy": "星系",
                 "planetary": "行星状星云"}

# 按类型覆盖参数(在光污染预设之后再覆盖)
TYPE_PRESETS = {
    # 星团: 全是点源, 没有大尺度结构要保护 -> 保护关掉、光害去得更干净
    "cluster":   dict(bg_protect=False, bg2d_q=45.0, chroma_nr=0.0, chroma_denoise_level=0.0),
    # 星云: 大尺度柔光最容易被当光害吃掉 -> 保护开、q 调高
    "nebula":    dict(bg_protect=True, bg2d_q=40.0, chroma_nr=0.0, chroma_denoise_level=0.35),
    # 星系: 暗弱外晕表面亮度低 -> 保护开, 不逐帧去光污染, 不做色度降噪
    "galaxy":    dict(bg_protect=True, bg2d_q=50.0, chroma_nr=0.0, chroma_denoise_level=0.0, lp_remove=False),
    # 行星状星云: 颜色是核心特征, 绝不降噪
    "planetary": dict(bg_protect=True, bg2d_q=50.0, chroma_nr=0.0, chroma_denoise_level=0.0),
}

TYPE_PRESET_TEXT = {
    "cluster": "结构保护关 + Background2D(q=45) + 不降噪",
    "nebula": "结构保护开 + Background2D(q=40) + 色噪去除 0.35",
    "galaxy": "结构保护开 + Background2D(q=50) + 关逐帧去光污染 + 不降噪",
    "planetary": "结构保护开 + Background2D(q=50) + 不降噪(保颜色)",
}


def catalog_fov_range():
    """**实际可用**星表覆盖的对角视场范围(度)。没有星表返回 None。"""
    cands = available_catalogs()
    if not cands:
        return None
    lo = min(c[2][0] for c in cands)
    hi = max(c[2][1] for c in cands)
    return lo, hi


def fov_in_catalog_range(fov_deg):
    """视场是否落在某个可用星表范围内; 视场未知或无星表返回 None。"""
    if not fov_deg or fov_deg <= 0:
        return None
    cands = available_catalogs()
    if not cands:
        return None
    for c in cands:
        lo, hi = c[2][0], c[2][1]
        if lo <= fov_deg <= hi:
            return True
    return False


def object_entry_by_label(label):
    """按显示名在目录里找条目(手动指定时用)."""
    if not label:
        return None
    for o in load_object_catalogue():
        if label_of(o) == label:
            return o
    return None


# --------------------------------------------------------------------------
# 目标识别: 内置星表盲解星场 + 内置深空天体目录
# --------------------------------------------------------------------------
def _fit_shape(a, shape):
    """把数组裁剪/补边到指定形状(背景面用)."""
    out = np.empty(shape, np.float32)
    sy = min(a.shape[0], shape[0]); sx = min(a.shape[1], shape[1])
    out[:sy, :sx] = a[:sy, :sx]
    if sy < shape[0]:
        out[sy:, :sx] = out[sy - 1:sy, :sx]
    if sx < shape[1]:
        out[:, sx:] = out[:, sx - 1:sx]
    return out


def mesh_background(plane_small, ny=20, nx=28, iters=4, clip=3.0):
    """用网格 + sigma 裁剪的中值, 再三次插值出平滑背景面 (参考 Siril 的背景提取思路).
    输入为降采样后的 2D 数组, 返回同尺寸的背景面."""
    h, w = plane_small.shape
    ys = np.linspace(0, h, ny + 1).astype(int)
    xs = np.linspace(0, w, nx + 1).astype(int)
    grid = np.zeros((ny, nx), np.float32)
    for i in range(ny):
        for j in range(nx):
            blk = plane_small[ys[i]:ys[i + 1], xs[j]:xs[j + 1]]
            if blk.size < 16:
                grid[i, j] = 0.0
                continue
            v = blk.ravel().astype(np.float32)
            for _ in range(iters):
                med = float(np.median(v))
                mad = float(np.median(np.abs(v - med))) + 1e-3
                keep = np.abs(v - med) < clip * 1.4826 * mad
                if keep.all() or keep.sum() < 16:
                    break
                v = v[keep]
            grid[i, j] = float(np.median(v))
    # 网格值做一次轻度中值平滑, 去掉个别异常网格
    from scipy import ndimage
    grid = ndimage.median_filter(grid, size=(3, 3), mode="nearest")
    surf = ndimage.zoom(grid, (h / float(ny), w / float(nx)), order=3)
    if surf.shape[0] < h or surf.shape[1] < w:
        pad = ((0, max(0, h - surf.shape[0])), (0, max(0, w - surf.shape[1])))
        surf = np.pad(surf, pad, mode="edge")
    return surf[:h, :w]


def remove_gradient(a, mode="sub", scale=8, ny=20, nx=28):
    """逐帧去光污染/渐晕: 对 4 个 CFA 平面各自估计背景并扣除(或相除), 原地修改."""
    from scipy import ndimage
    for (oy, ox) in ((0, 0), (0, 1), (1, 0), (1, 1)):
        pl = a[oy::2, ox::2]
        small = pl[::scale, ::scale].astype(np.float32)
        if small.shape[0] < 2 * ny or small.shape[1] < 2 * nx:
            continue
        surf_small = mesh_background(small, ny=ny, nx=nx)
        surf = ndimage.zoom(surf_small,
                            (pl.shape[0] / float(surf_small.shape[0]),
                             pl.shape[1] / float(surf_small.shape[1])), order=1)
        surf = _fit_shape(surf, pl.shape)
        if mode == "div":
            pl /= np.maximum(surf, 1e-6)
        else:
            pl -= surf
    return a


def rbf_background(img, ny=18, nx=24, iters=4, clip=3.0, smoothing=0.0):
    """RBF(薄板样条) 背景提取 —— 与 Siril 的 RBF 插值法同类.
    img: (H,W) 或 (H,W,3) float; 返回同形状背景面."""
    from scipy.interpolate import RBFInterpolator
    from scipy import ndimage
    single = (img.ndim == 2)
    chans = [img] if single else [img[:, :, c] for c in range(3)]
    h, w = chans[0].shape
    ys = np.linspace(0, h, ny + 1).astype(int)
    xs = np.linspace(0, w, nx + 1).astype(int)
    blocks = []
    coords = []
    for i in range(ny):
        for j in range(nx):
            y0, y1 = ys[i], ys[i + 1]
            x0, x1 = xs[j], xs[j + 1]
            if y1 - y0 < 4 or x1 - x0 < 4:
                continue
            blocks.append((y0, y1, x0, x1))
            coords.append(((y0 + y1) * 0.5 / float(h), (x0 + x1) * 0.5 / float(w)))
    coords = np.asarray(coords, np.float64)
    gy, gx = np.mgrid[0:h:16, 0:w:16]
    grid = np.stack([(gy / float(h)).ravel(), (gx / float(w)).ravel()], axis=1)
    out = []
    for ch in chans:
        vals = []
        for (y0, y1, x0, x1) in blocks:
            v = ch[y0:y1, x0:x1].ravel().astype(np.float32)
            for _ in range(iters):
                med = float(np.median(v))
                mad = float(np.median(np.abs(v - med))) + 1e-3
                keep = np.abs(v - med) < clip * 1.4826 * mad
                if keep.all() or keep.sum() < 16:
                    break
                v = v[keep]
            vals.append(float(np.median(v)))
        f = RBFInterpolator(coords, np.asarray(vals, np.float64),
                            kernel="thin_plate_spline", smoothing=float(smoothing))
        surf = f(grid).reshape(gy.shape).astype(np.float32)
        surf = ndimage.zoom(surf, (h / float(surf.shape[0]), w / float(surf.shape[1])), order=1)
        out.append(_fit_shape(surf, (h, w)))
    return out[0] if single else np.stack(out, axis=2)



def _block_percentile(plane, ny, nx, q, mask=None, step=3):
    """把平面切成 ny*nx 块，一次性算每块的 q 分位数（向量化）。

    比逐块 np.percentile 快 5~20 倍：块内按 step 抽样（分位数是稳健统计量，
    1/9 采样几乎不影响结果），全部块合并成一个三维数组一次算完。
    mask 为 True 的像素会被排除（用 nan 屏蔽）。
    """
    hh, ww = plane.shape
    ny = max(1, int(ny))
    nx = max(1, int(nx))
    by = max(1, hh // ny)
    bx = max(1, ww // nx)
    ny2, nx2 = hh // by, ww // bx
    a = plane[:ny2 * by, :nx2 * bx]
    if mask is not None:
        m = mask[:ny2 * by, :nx2 * bx]
        a = np.where(m, np.nan, a)
    b = a.reshape(ny2, by, nx2, bx).transpose(0, 2, 1, 3).reshape(ny2, nx2, by * bx)
    if step and int(step) > 1:
        b = b[:, :, ::int(step)]
    if mask is not None:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            v = np.nanpercentile(b, q, axis=2)
        bad = ~np.isfinite(v)
        if bad.any():
            raw = plane[:ny2 * by, :nx2 * bx].reshape(ny2, by, nx2, bx)
            raw = raw.transpose(0, 2, 1, 3).reshape(ny2, nx2, by * bx)
            if step and int(step) > 1:
                raw = raw[:, :, ::int(step)]
            v = np.where(bad, np.percentile(raw, q, axis=2), v)
    else:
        v = np.percentile(b, q, axis=2)
    # 尺寸不足时补齐到 ny*nx
    if v.shape != (ny, nx):
        out = np.empty((ny, nx), np.float32)
        out[:v.shape[0], :v.shape[1]] = v
        if v.shape[0] < ny:
            out[v.shape[0]:, :] = out[v.shape[0] - 1:v.shape[0], :]
        if v.shape[1] < nx:
            out[:, v.shape[1]:] = out[:, v.shape[1] - 1:v.shape[1]]
        v = out
    return v.astype(np.float32)



def _zoom_smooth(grid, hh, ww, mid=8):
    """把粗网格平滑放大到 (hh, ww)。

    直接 order=3 放大到 24MP 很慢(约 1.3s)；先 order=3 放大到 mid 倍(144x192,
    几乎不花时间)，再 order=1 放大到全尺寸(0.38s)——因为中间结果已经很密，
    双线性插值的误差可以忽略。等效平滑度，快 3 倍。
    """
    from scipy import ndimage
    ny, nx = grid.shape
    if ny * mid >= hh or nx * mid >= ww:
        return ndimage.zoom(grid, (hh / float(ny), ww / float(nx)), order=3)
    big = ndimage.zoom(grid, (ny * mid / float(ny), nx * mid / float(nx)), order=3)
    out = ndimage.zoom(big, (hh / float(big.shape[0]), ww / float(big.shape[1])), order=1)
    return out[:hh, :ww]


def _blur_large(a, sigma, scale=4):
    """大尺度高斯模糊：先在 1/scale 降采样上模糊，再放大回去(误差可忽略)。

    sigma=25 直接在全分辨率做要约 3.2s；降到 1/4 只要 0.4s。
    """
    from scipy import ndimage
    if sigma < scale * 2:
        return ndimage.gaussian_filter(a, sigma)
    small = a[::scale, ::scale]
    small = ndimage.gaussian_filter(small, sigma / float(scale))
    out = ndimage.zoom(small, (a.shape[0] / float(small.shape[0]),
                               a.shape[1] / float(small.shape[1])), order=1)
    return out[:a.shape[0], :a.shape[1]]


def bg2d_mesh(plane, box=None, filter_size=3, sigma=3.0, iters=5, exclude_pct=None, floor_q=35.0):
    """SExtractor 风格网格背景 (等价 photutils Background2D 的做法, 自实现避免依赖).
    网格 + sigma 裁剪中值 + 中值滤波 + 三次插值回全分辨率."""
    from scipy import ndimage
    h, w = plane.shape
    by = box[0] if box else max(48, h // 20)
    bx = box[1] if box else max(48, w // 26)
    ny = int(np.ceil(h / float(by)))
    nx = int(np.ceil(w / float(bx)))
    # 向量化: 一次算出所有网格的低分位数(块内地板), 比逐块 percentile 快 5~20 倍
    grid = _block_percentile(plane, ny, nx, floor_q, step=max(1, int(np.sqrt(iters))))
    if np.isnan(grid).any():
        grid = np.where(np.isnan(grid), float(np.nanmedian(grid)), grid)
    # 只信"偏暗"的网格(对应纯天空), 亮网格(银河/穹顶)不参与建模 -> 避免把银河一起减掉
    if exclude_pct is not None and 0 < exclude_pct < 100:
        cut = float(np.percentile(grid, exclude_pct))
        grid = np.where(grid > cut, np.nan, grid)
        if np.isnan(grid).all():
            grid = np.full_like(grid, cut)
        else:
            from scipy.interpolate import griddata
            gy, gx = np.indices(grid.shape)
            pts = np.argwhere(~np.isnan(grid))
            vals = grid[~np.isnan(grid)]
            try:
                interp = griddata(pts, vals, (gy, gx), method="cubic")
            except Exception:
                interp = None
            if interp is None or np.isnan(interp).all():
                interp = griddata(pts, vals, (gy, gx), method="linear")
            interp = np.where(np.isnan(interp), np.nanmedian(interp), interp)
            grid = interp.astype(np.float32)
    grid = ndimage.median_filter(grid, size=filter_size, mode="nearest")
    surf = _zoom_smooth(grid, h, w)
    return _fit_shape(surf, (h, w))


def bg2d_protect(plane, ny=18, nx=24, floor_q=40.0, iters=3, grow=8,
                 thresh_sigma=3.0, hp_sigma=25.0):
    """网格背景 + 结构保护.

    保护判据用**局部高频反差**(残差减大尺度模糊), 而不是"比模型亮"——
    这样星云、暗尘带这类有细节的结构会被保护, 而平缓的光害穹顶/月光梯度
    不会被误当成结构保留下来.
    """
    from scipy import ndimage
    hh, ww = plane.shape
    mask = np.zeros((hh, ww), bool)
    model = None
    for _ in range(max(1, iters)):
        grid = _block_percentile(plane, ny, nx, floor_q, mask=mask, step=3)
        grid = ndimage.median_filter(grid, size=3, mode="nearest")
        surf = _zoom_smooth(grid, hh, ww)
        model = _fit_shape(surf, (hh, ww))
        resid = plane - model
        hp = resid - _blur_large(resid, hp_sigma)
        sd = float(np.median(np.abs(hp - np.median(hp)))) * 1.4826 + 1e-3
        mask |= (hp > thresh_sigma * sd)
        if grow:
            # 用可分离的最大值滤波代替 N 次二值膨胀(等价于方形结构元, 快 3~5 倍)
            k = 2 * int(grow) + 1
            mask = ndimage.maximum_filter(mask.astype(np.uint8), size=k, mode="constant") > 0
    return model


def bg_poly(plane, degree=3, iters=3, grow=8, thresh_sigma=3.0, step=6):
    """二维多项式曲面背景(degree 1=平面, 越大越能贴合弯曲渐变) + 结构保护."""
    from scipy import ndimage
    hh, ww = plane.shape
    yy, xx = np.mgrid[0:hh:step, 0:ww:step]
    Y = (yy / float(hh) * 2 - 1).ravel()
    X = (xx / float(ww) * 2 - 1).ravel()
    A = np.stack([(X ** i) * (Y ** j) for i in range(degree + 1) for j in range(degree + 1 - i)], axis=1)
    Z = plane[::step, ::step]
    mask = np.zeros(Z.shape, bool)
    model = None
    for _ in range(max(1, iters)):
        ok = (~mask).ravel()
        if ok.sum() < A.shape[1] * 4:
            ok = np.ones(A.shape[0], bool)
        coef, *_ = np.linalg.lstsq(A[ok], Z.ravel()[ok], rcond=None)
        surf = (A @ coef).reshape(Z.shape)
        full = ndimage.zoom(surf, (hh / float(surf.shape[0]), ww / float(surf.shape[1])), order=1)
        model = _fit_shape(full, (hh, ww))
        resid = plane - model
        noise = float(np.median(np.abs(resid - np.median(resid)))) * 1.4826 + 1e-3
        m = (resid > thresh_sigma * noise)
        if grow:
            m = ndimage.binary_dilation(m, iterations=int(grow))
        mask = m[::step, ::step]
        if mask.shape != Z.shape:
            mask = np.zeros(Z.shape, bool)
    return model


def chroma_denoise(rgb, sigma=2.0, strength=1.0):
    """色度降噪: 只模糊色度(Cb/Cr), 保留亮度细节 —— 对付强光害区被放大的彩色噪点."""
    from scipy import ndimage
    x = rgb.astype(np.float32)
    y = 0.299 * x[:, :, 0] + 0.587 * x[:, :, 1] + 0.114 * x[:, :, 2]
    out = np.empty_like(x)
    # Cr = R-Y, Cb = B-Y, Cg = G-Y (三者线性相关, 这里用两组即可)
    cr = x[:, :, 0] - y
    cb = x[:, :, 2] - y
    cg = x[:, :, 1] - y
    bl = lambda a: ndimage.gaussian_filter(a, sigma)
    cr2 = cr * (1 - strength) + bl(cr) * strength
    cb2 = cb * (1 - strength) + bl(cb) * strength
    cg2 = cg * (1 - strength) + bl(cg) * strength
    out[:, :, 0] = y + cr2
    out[:, :, 1] = y + cg2
    out[:, :, 2] = y + cb2
    return out



def _atrous_blur(a, step):
    """à trous 小波的一层平滑: B3 样条核 [1,4,6,4,1]/16, 按 step 插零膨胀(可分离)."""
    from scipy import ndimage
    k = np.array([1.0, 4.0, 6.0, 4.0, 1.0], np.float64) / 16.0
    if step > 1:
        kk = np.zeros(4 * step + 1, np.float64)
        kk[::step] = k
        k = kk
    out = ndimage.convolve1d(a, k, axis=0, mode="reflect")
    out = ndimage.convolve1d(out, k, axis=1, mode="reflect")
    return out


def _mad_sd(a):
    """用 MAD 估计标准差(抗星点等大值干扰)."""
    m = np.median(a)
    return 1.4826 * float(np.median(np.abs(a - m))) + 1e-6


def _soft_shrink(x, t):
    """软阈值: 只削减小系数(噪声), 大系数(星点/星云边缘)基本不动."""
    if t <= 0:
        return x
    return np.sign(x) * np.maximum(np.abs(x) - t, 0.0)


def wavelet_denoise(rgb, strength=0.6, scales=4, k=3.0, per_channel=False):
    """à trous(starlet) 小波降噪 —— 天文摄影常用的 Starck 多尺度去噪.

    原理: 用 B3 样条做多尺度 "à trous" 分解, 噪声主要落在小尺度系数上;
    每层用 MAD 估噪声 σ, 软阈值 k*σ*strength 抑制小系数,
    星点、星云边缘这些大系数保留下来 —— 去噪但不糊星点。

    默认只处理亮度(噪声主要感知在亮度, 且快 3 倍), 色噪交给 chroma_denoise。
    per_channel=True 时三个通道各自处理(更彻底, 慢约 3 倍)。
    """
    x = np.asarray(rgb, np.float32)
    single = (x.ndim == 2)
    if single:
        x = x[:, :, None]
    use_luma = (not per_channel) and x.shape[2] >= 3
    out = x.copy()
    chans = [None] if use_luma else range(x.shape[2])
    for c in chans:
        img = (0.299 * x[:, :, 0] + 0.587 * x[:, :, 1] + 0.114 * x[:, :, 2]) if c is None else x[:, :, c]
        cj = img.astype(np.float32)
        ws = []
        for j in range(int(max(1, scales))):
            cprev = cj
            cj = _atrous_blur(cprev, 2 ** j).astype(np.float32)
            ws.append(cprev - cj)
        rec = cj.copy()
        for w in ws:
            # MAD 只在 1/4 抽样上估计：稳健统计量，结果几乎不变，快 16 倍
            t = k * _mad_sd(w[::4, ::4]) * float(strength)
            rec += _soft_shrink(w, t).astype(np.float32)
        if c is None:
            # 亮度替换：三通道加同一差值，色度不变
            diff = rec - img
            out[:, :, 0] += diff
            out[:, :, 1] += diff
            out[:, :, 2] += diff
        else:
            out[:, :, c] = rec
    return out[:, :, 0] if single else out



def chroma_wavelet(rgb, strength=0.5, scales=3, fast=True):
    """小波色噪去除：只处理色度(Cr/Cg/Cb)，亮度完全不动。

    做法：RGB -> Y + (R-Y, G-Y, B-Y)，对三个色差平面分别做 à trous 小波降噪
    （色噪是"斑块状"的大尺度误差，小波能按尺度压掉，而亮度通道不受影响），
    再合成回去。fast=True 时色度先在 1/2 分辨率上去噪再放大（快 4 倍，
    色噪本身就是低频的，几乎无损失）。
    """
    from scipy import ndimage
    x = np.asarray(rgb, np.float32)
    if x.ndim != 3 or x.shape[2] < 3:
        return x
    y = 0.299 * x[:, :, 0] + 0.587 * x[:, :, 1] + 0.114 * x[:, :, 2]
    out = x.copy()
    for c in range(3):
        d = x[:, :, c] - y
        if fast:
            d2 = d[::2, ::2]
            dn = wavelet_denoise(d2, strength=strength, scales=scales)
            dn = ndimage.zoom(dn, (d.shape[0] / float(dn.shape[0]),
                                   d.shape[1] / float(dn.shape[1])), order=1)
            dn = dn[:d.shape[0], :d.shape[1]]
        else:
            dn = wavelet_denoise(d, strength=strength, scales=scales)
        out[:, :, c] = y + dn
    return out


def write_png16(path, rgb01, level=3):
    """写 16bit RGB PNG (PIL 不支持 16bit RGB, 这里手写). rgb01: float 0..1 (H,W,3)."""
    import zlib, struct
    a = np.clip(np.asarray(rgb01, np.float32), 0, 1)
    a16 = (a * 65535.0 + 0.5).astype(">u2")          # (h,w,3) 大端
    h, w, _ = a16.shape
    rowbytes = w * 6                                  # 每像素 3 通道 × 2 字节
    raw = np.zeros((h, 1 + rowbytes), np.uint8)        # 每行开头 1 字节 filter=0
    raw[:, 1:] = a16.view(np.uint8).reshape(h, rowbytes)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 16, 2, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", zlib.compress(raw.tobytes(), level)))
        f.write(chunk(b"IEND", b""))


def _stretch_float(rgb16, sat=1.18, wb=(2.645, 1.0, 1.812), gain=64.0, asinh_k=30.0):
    """把线性 16bit 数组(0~65535)拉伸成可看的 0~1 浮点图。"""
    import math
    a = np.asarray(rgb16, np.float32)
    if a.ndim == 2:
        a = np.stack([a] * 3, axis=2)
    a = a[:, :, :3] / 65535.0
    x = np.clip(a * np.array(wb, np.float32)[None, None, :], 0, 1) * float(gain)
    for c in range(3):
        bg = float(np.percentile(x[:, :, c], 50.0))
        x[:, :, c] = np.maximum(x[:, :, c] - bg, 0.0)
    lum = x.mean(axis=2)
    hi = float(np.percentile(lum, 99.9)) or 1.0
    y = np.arcsinh(np.clip(x / hi, 0, None) * asinh_k) / math.asinh(asinh_k)
    y = np.clip(y, 0, 1)
    if sat and sat != 1.0:
        l = y.mean(axis=2, keepdims=True)
        y = np.clip(l + (y - l) * float(sat), 0, 1)
    return y



def _save_jpg(y, path, max_side=2600, quality=92, dither=True):
    """把浮点 0~1 图像写成 JPG：**先在浮点域降采样，再量化**。

    旧做法是 uint8 先量化再 resize(LANCZOS)：8bit 台阶被一起缩放，
    高光先被 clip，Lanczos 的负瓣还会在亮星周围出振铃。
    新做法：
      1) 浮点域用 LANCZOS 缩放(核按比例展宽，等效抗混叠平均)，不做 8bit 先量化；
      2) 量化前加三角分布抖动(±0.5 LSB)，消除 8bit 渐变色带；
      3) 最后才裁到 0~255。
    """
    import numpy as np
    from PIL import Image
    y = np.asarray(y, np.float32)
    if y.ndim == 2:
        y = np.stack([y] * 3, axis=2)
    y = np.clip(y[:, :, :3], 0.0, 1.0)
    h, w = y.shape[:2]
    scale = min(1.0, float(max_side) / float(max(h, w)))
    if scale < 0.999:
        th = max(1, int(round(h * scale)))
        tw = max(1, int(round(w * scale)))
        chans = []
        for c in range(3):
            im = Image.fromarray(np.ascontiguousarray(y[:, :, c], np.float32), mode="F")
            # 浮点域用 LANCZOS：PIL 会按缩小比例自动放大滤波核(等效面积平均)，
            # 因此在浮点下既抗混叠又不受 8bit 台阶影响。
            im = im.resize((tw, th), Image.LANCZOS)
            chans.append(np.asarray(im, np.float32))
        y = np.stack(chans, axis=2)
        h, w = y.shape[:2]
    if dither:
        rng = np.random.default_rng(12345)
        tri = (rng.random((h, w), np.float32) - rng.random((h, w), np.float32)) / 255.0
        y = y + tri[:, :, None]
    out = (np.clip(y, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    try:
        Image.fromarray(out).save(path, quality=int(quality), optimize=True,
                                  subsampling=2)      # 4:2:0，体积小
    except Exception:
        Image.fromarray(out).save(path, quality=int(quality))
    return path


def _write_stretched(y, tif_path, jpg=True, jpg_max=2600, jpg_quality=92):
    """把 0~1 浮点图写成 16bit TIFF + 缩小 JPG(可选)。"""
    import tifffile
    from PIL import Image
    tifffile.imwrite(tif_path, (np.clip(y, 0, 1) * 65535.0 + 0.5).astype(np.uint16),
                     photometric="rgb", compression="zlib")
    if jpg:
        try:
            _save_jpg(y, os.path.splitext(tif_path)[0] + ".jpg",
                      max_side=int(jpg_max), quality=int(jpg_quality))
        except Exception:
            im = Image.fromarray((np.clip(y, 0, 1) * 255 + 0.5).astype(np.uint8))
            im.save(os.path.splitext(tif_path)[0] + ".jpg", quality=92)
    return tif_path


def stretch_image(src, dst=None, sat=1.18, wb=(2.645, 1.0, 1.812), gain=64.0, asinh_k=30.0):
    """把线性未校准的堆栈 TIFF 自动拉伸成可看的图 (与预览图同一套算法, 但全精度 16bit 输出).
    返回 (tif_path, jpg_path).
    """
    import tifffile
    a = np.asarray(tifffile.imread(src))
    y = _stretch_float(a, sat=sat, wb=wb, gain=gain, asinh_k=asinh_k)
    base = os.path.splitext(src)[0]
    tif = dst or (base + "_stretched.tif")
    _write_stretched(y, tif, jpg=True)
    return tif, os.path.splitext(tif)[0] + ".jpg"



# --------------------------------------------------------------------------
# 去星 / 缩星
# --------------------------------------------------------------------------
LAST_STAR_COVERAGE = 0.0


class _SkipStars(Exception):
    pass


def star_mask(lum, sigma_small=3.0, k=6.0, grow=4, min_area=6, soft=1.2, max_area=3000):
    """从亮度图生成星点软掩膜(0~1)。

    多尺度高通(1.2/2.5/3/5 像素取最大)抓不同大小的星; 阈值用局部(64px)MAD,
    星云纹理强的区域门槛自动抬高; 面积过小(噪点)和过大(星云团块)的连通块丢掉;
    再按每颗星半径自适应膨胀, 最后软化。
    """
    sigmas = sorted(set([1.2, 2.5, max(3.0, float(sigma_small)), 5.0]))
    hp = None
    for sg in sigmas:
        d = lum - ndi.gaussian_filter(lum, sg)
        hp = d if hp is None else np.maximum(hp, d)
    med = float(np.median(hp))
    dev = np.abs(hp - med)
    # 64px 半径的高斯在原分辨率要 9s；MAD 面本身极平滑，降采样算再放大几乎无差别(0.7s)
    sd_map = _blur_large(dev, 64.0, scale=4) * 1.4826 + 1e-6
    m = hp > (med + k * sd_map)
    lab, n = ndi.label(m)
    if n:
        sizes = ndi.sum(m, lab, range(1, n + 1))
        keep = np.zeros(n + 1, bool)
        keep[1:] = (sizes >= min_area) & (sizes <= max_area)
        m = keep[lab]
    foot = ndi.gaussian_filter(m.astype(np.float32), 0.8)
    if m.any():
        lab2, n2 = ndi.label(m)
        sizes2 = ndi.sum(m, lab2, range(1, n2 + 1))
        radii = np.sqrt(sizes2 / np.pi)
        rmap = np.zeros(m.shape, np.float32)
        idx = lab2[m] - 1
        rmap[m] = radii[idx]
        rmap = ndi.grey_dilation(rmap, size=(31, 31))
        dist = ndi.distance_transform_edt(~m)
        need = np.maximum(float(grow), 1.7 * rmap)
        halo = dist <= need
    else:
        halo = m
    soft_mask = ndi.gaussian_filter(halo.astype(np.float32), soft)
    return np.clip(soft_mask, 0.0, 1.0), np.clip(foot, 0.0, 1.0)


def star_fill(rgb, mask, sigma=12.0):
    """归一化卷积: 用未遮挡的邻域估计星点下面被盖住的星云/背景。

    星点极密时掩膜覆盖大, 分母接近 0 会放大噪声, 所以: 分母下限 0.08,
    并按遮蔽程度混合一个 4 倍尺度的稳定估计。
    """
    w = 1.0 - mask
    den = ndi.gaussian_filter(w, float(sigma))
    den_big = ndi.gaussian_filter(w, float(sigma) * 4.0)
    out = np.empty_like(rgb, dtype=np.float32)
    for c in range(rgb.shape[2]):
        num = ndi.gaussian_filter(rgb[:, :, c] * w, float(sigma))
        num_big = ndi.gaussian_filter(rgb[:, :, c] * w, float(sigma) * 4.0)
        fine = num / np.maximum(den, 0.08)
        coarse = num_big / np.maximum(den_big, 0.08)
        out[:, :, c] = den * fine + (1.0 - den) * coarse
    return out


def process_stars(rgb, mode="remove", strength=0.9, sigma=10.0, k=3.5,
                  grow=5, sigma_small=3.0, min_area=2, max_area=3000):
    """去星(mode='remove') 或 缩星(mode='reduce')。返回 (结果图, 星点层)."""
    global LAST_STAR_COVERAGE
    rgb = rgb.astype(np.float32)
    lum = rgb.mean(axis=2)
    mask, foot = star_mask(lum, sigma_small=sigma_small, k=k, grow=grow,
                           min_area=min_area, max_area=max_area)
    LAST_STAR_COVERAGE = float((mask > 0.5).mean())
    under = star_fill(rgb, mask, sigma=sigma)

    if mode == "remove":
        a = float(np.clip(strength, 0.0, 1.0))
        out = rgb * (1.0 - mask[:, :, None] * a) + under * (mask[:, :, None] * a)
        return out, rgb - out

    halo = np.clip(mask - foot, 0.0, 1.0)
    a = float(np.clip(strength, 0.0, 1.0))
    out = rgb - (rgb - under) * halo[:, :, None] * a
    return out, rgb - out


def _display_stretch(rgb, wb=(2.645, 1.0, 1.812), gain=64.0, asinh_k=30.0, sat=1.15):
    """线性数据 -> 可看的 0~1 显示图(接受 0~65535 输入)。"""
    return _stretch_float(rgb, sat=sat, wb=wb, gain=gain, asinh_k=asinh_k)


def default_out_path():
    """默认输出: 程序同目录下 output 文件夹里的 YYMMDD_HHMM.tif (同名自动加 _2)."""
    base = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__)))
    outdir = os.path.join(base, "output")
    try:
        os.makedirs(outdir, exist_ok=True)
    except Exception:
        outdir = base
    stamp = datetime.datetime.now().strftime("%y%m%d_%H%M")
    path = os.path.join(outdir, stamp + ".tif")
    k = 2
    while os.path.exists(path):
        path = os.path.join(outdir, "%s_%d.tif" % (stamp, k))
        k += 1
    return path, outdir


def _res_path(name):
    """资源文件查找: 打包内目录 -> exe 同级目录 -> 脚本目录."""
    cands = []
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        cands.append(os.path.join(mei, name))
    if getattr(sys, "frozen", False):
        cands.append(os.path.join(os.path.dirname(sys.executable), name))
    cands.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), name))
    for p in cands:
        if os.path.exists(p):
            return p
    return cands[-1]


_OBJECTS = None
_SOLVERS = {}

# 内置星表: (文件名, 名称, 适用对角视场)
CATALOGS = [
    ("dsso_narrow.npz", "窄视场 4°~8°", (4.0, 8.0)),
    ("dsso_database.npz", "中等 10°~30°", (10.0, 30.0)),
    ("dsso_wide.npz", "宽视场 12°~60°", (12.0, 60.0)),
]
CATALOG_AUTO = "自动选择"

SENSORS = [
    ("全画幅 36×24", (36.0, 24.0)),
    ("APS-C 23.5×15.6", (23.5, 15.6)),
    ("APS-C(佳能) 22.3×14.9", (22.3, 14.9)),
    ("M4/3 17.3×13", (17.3, 13.0)),
    ("1 英寸 13.2×8.8", (13.2, 8.8)),
]
SENSOR_NONE = "不填(未知)"


def load_object_catalogue():
    global _OBJECTS
    if _OBJECTS is None:
        try:
            with open(_res_path("objects.json"), "r", encoding="utf-8") as f:
                _OBJECTS = json.load(f)
        except Exception:
            _OBJECTS = []
    return _OBJECTS


def fov_from_sensor(sensor_label, focal_mm, crop=None):
    """由画幅 + 焦距估算对角视场(度); 信息不全返回 None."""
    if not focal_mm or focal_mm <= 0:
        return None
    if crop:
        diag = 43.2666 / float(crop)
    else:
        diag = None
        for lab, wh in SENSORS:
            if lab == sensor_label:
                diag = math.hypot(wh[0], wh[1])
        if diag is None:
            return None
    return math.degrees(2.0 * math.atan(diag / (2.0 * float(focal_mm))))


def _tetra3_default_db():
    """tetra3 自带的 10°~30° 星表库（pip 装 tetra3 就有，不用另发）。

    我们的 dsso_database.npz 就是用它改名来的；找不到自己的副本时回退到它，
    这样只发窄视场库也能覆盖中视场。
    """
    try:
        import tetra3
        cand = os.path.join(os.path.dirname(os.path.abspath(tetra3.__file__)),
                            "data", "default_database.npz")
        if os.path.exists(cand):
            return cand
    except Exception:
        pass
    return None


def available_catalogs():
    out = []
    for fn, label, rng in CATALOGS:
        p = _res_path(fn)
        if not os.path.exists(p) and fn == "dsso_database.npz":
            p = _tetra3_default_db() or p
        if os.path.exists(p):
            out.append((fn, label, rng, p))
    return out


def get_solver(name=None):
    """按名字取解算器; name 为 None 时用第一个可用星表."""
    cands = available_catalogs()
    if not cands:
        return None
    p = cands[0][3]
    if name:
        for fn, label, rng, path in cands:
            if os.path.basename(fn) == os.path.basename(name) or label == name:
                p = path
                break
    if p in _SOLVERS:
        return _SOLVERS[p]
    try:
        import tetra3
        _SOLVERS[p] = tetra3.Tetra3(p)
    except Exception:
        return None
    return _SOLVERS[p]


def _pick_catalogs(fov_hint=None, catalog="auto"):
    cands = available_catalogs()
    if not cands:
        return []
    if catalog and catalog not in ("auto", CATALOG_AUTO, "全部尝试"):
        for c in cands:
            if catalog in (c[0], c[1]) or os.path.basename(c[0]) == os.path.basename(str(catalog)):
                return [c]
        return cands
    if catalog in ("全部尝试", "all"):
        return cands
    if fov_hint:
        def dist(c):
            lo, hi = c[2]
            if lo <= fov_hint <= hi:
                return 0.0
            return min(abs(fov_hint - lo), abs(fov_hint - hi))
        return sorted(cands, key=dist)
    return cands


def _solve_with(solver, cent_yx, width, height, fov_hint=None,
                pattern_stars=15, match_radius=0.02):
    kw = {}
    if fov_hint and fov_hint > 0:
        kw["fov_estimate"] = float(fov_hint)
        kw["fov_max_error"] = max(1.0, float(fov_hint) * 0.35)
    if len(cent_yx) >= 12:
        kw["pattern_checking_stars"] = int(pattern_stars)
        kw["match_radius"] = float(match_radius)
    try:
        r = solver.solve_from_centroids(cent_yx, (height, width),
                                        solve_timeout=12000, **kw)
    except Exception:
        return None
    if not r or r.get("RA") is None:
        return None
    return dict(ra=float(r["RA"]), dec=float(r["Dec"]), fov=float(r["FOV"]),
                roll=float(r.get("Roll", 0.0) or 0.0),
                matches=int(r.get("Matches", 0) or 0))


def solve_field(centroids_xy, width, height, fov_hint=None, catalog="auto"):
    """星场盲解: 按视场提示/用户指定挑选星表, 未指定则多星表依次尝试.

    对窄视场把星点坐标按比例放大后再解 —— 图案比例不变, 仍能匹配, 结果再还原尺度。
    """
    if len(centroids_xy) < 6:
        return None
    c = np.asarray(centroids_xy, np.float64)
    ctr = np.array([width / 2.0, height / 2.0])
    rel = c - ctr
    scales = [1.0]
    if fov_hint:
        # 目标: 放大到星表范围内(取中值)
        for _, _, rng, _ in available_catalogs():
            mid = 0.5 * (rng[0] + rng[1])
            if fov_hint < rng[0]:
                scales.append(max(1.0, mid / fov_hint))
    cands = _pick_catalogs(fov_hint, catalog)
    if fov_hint:
        # 视场提示明确落在某张库的范围内时，就别浪费时间试其它库了
        # （窄视场素材去试 10°~30° 的库，单次要跑一两分钟才失败）
        inside = [c for c in cands if c[2][0] * 0.85 <= fov_hint <= c[2][1] * 1.15]
        if inside:
            cands = inside
    for fn, label, rng, path in cands:
        solver = get_solver(path)
        if solver is None:
            continue
        for k in scales:
            cent = (rel * k + ctr)[:, ::-1]
            hint_k = (fov_hint / k) if fov_hint else None
            # 两种解法依次尝试：先用视场提示(快)，不行再用更多星组合、不带提示(稳)
            attempts = [dict(fov_hint=hint_k, pattern_stars=15, match_radius=0.02),
                        dict(fov_hint=None, pattern_stars=25, match_radius=0.01)]
            r = None
            for kw2 in attempts:
                r = _solve_with(solver, cent, width, height, **kw2)
                if r:
                    break
            if r:
                r["fov"] = r["fov"] / k
                r["catalog"] = label
                r["scale"] = k
                return r
    return None


def angular_sep(ra1, dec1, ra2, dec2):
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    v = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(r1 - r2)
    return math.degrees(math.acos(max(-1.0, min(1.0, v))))


def label_of(o):
    parts = [o["n"]]
    if o.get("zh"):
        parts.append(o["zh"])
    en = (o.get("en") or "").split(",")[0].strip()
    if en:
        parts.append("(" + en + ")")
    return " ".join(parts)


def identify_target(ra, dec, fov_w, fov_h, max_others=4):
    """返回 (主目标名称 或 None, 视场内其它目标名称列表)."""
    objs = load_object_catalogue()
    if not objs:
        return None, []
    half_diag = 0.5 * math.hypot(fov_w, fov_h)
    cands = []
    for o in objs:
        d = angular_sep(o["ra"], o["dec"], ra, dec)
        size_deg = (o.get("size") or 0.0) / 60.0
        inside = d <= half_diag + 0.5 * size_deg
        covers = size_deg >= 0.5 * max(fov_w, fov_h) and d <= 2.0 * half_diag
        if not (inside or covers):
            continue
        # 视场内多个目标时, 优先深空天体(恒星排在最后), 再按最亮星等(mag 越小越亮), 再看离中心远近
        mag = o.get("mag")
        mag_key = 99.0 if mag is None else float(mag)
        is_star = 1 if "*" in str(o.get("type") or "") else 0
        # 综合评分: 星等为主, 离画面中心越远扣分(边缘目标要亮很多才会被选中)
        size_bonus = 1.5 * math.log10(max(size_deg * 60.0, 1.0))   # 视面越大越像拍摄主体
        score = mag_key + 8.0 * min(d / max(half_diag, 1e-6), 1.0) - size_bonus
        cands.append((is_star, score, mag_key, d, o))
    if not cands:
        return None, []
    cands.sort(key=lambda x: (x[0], x[1], x[3]))
    return label_of(cands[0][4]), [label_of(c[4]) for c in cands[1:1 + max_others]]


def load_image_luminance(path):
    """读入 RAW 或普通图像, 返回 (亮度图, 是否普通图像)."""
    ext = os.path.splitext(path)[1].lower()
    if ext in RAW_EXT:
        img = decode(path)[0].astype(np.float32)
        return binned_luminance(img), False
    if ext in (".tif", ".tiff"):
        import tifffile
        a = tifffile.imread(path)
    else:
        from PIL import Image
        a = np.asarray(Image.open(path))
    a = np.asarray(a).astype(np.float32)
    if a.ndim == 3:
        a = a[:, :, :3].mean(axis=2) if a.shape[2] >= 3 else a[:, :, 0]
    h, w = a.shape
    step = max(1, int(math.ceil(max(h, w) / 3000.0)))
    if step > 1:
        h2, w2 = (h // step) * step, (w // step) * step
        a = a[:h2, :w2].reshape(h2 // step, step, w2 // step, step).mean(axis=(1, 3))
    return a, True


def identify_image_file(path, sensor=None, focal=None, crop=None, catalog="auto"):
    """独立识别: 单个 RAW/图像 -> 目标名称. 返回 dict.

    sensor/focal/crop 可选, 用于估算视场挑选星表; catalog 可指定星表或 'auto'.
    """
    try:
        lum, is_img = load_image_luminance(path)
    except Exception as e:
        return dict(ok=False, reason="读取失败: %r" % (e,))
    fov_hint = fov_from_sensor(sensor, focal, crop)
    if fov_hint and fov_hint < 10.0:
        xy, _ = detect_stars_narrow(lum, max_stars=200)
        if len(xy) < 10:
            xy, _ = detect_stars(lum, max_stars=400, sat=(float("inf") if is_img else 13000.0))
    else:
        xy, _ = detect_stars(lum, max_stars=400, sat=(float("inf") if is_img else 13000.0))
    if len(xy) < 6:
        return dict(ok=False, reason="星点太少(%d 颗), 无法识别" % len(xy))
    h, w = lum.shape
    sol = solve_field(xy, w, h, fov_hint=fov_hint, catalog=catalog)
    if not sol:
        hint_txt = "%.1f°" % fov_hint if fov_hint else "未知"
        return dict(ok=False,
                    reason="星场解算失败(估算对角视场 %s; 已尝试的星表不匹配, 或星点不够)" % hint_txt,
                    nstars=len(xy))
    ar = w / float(h)
    fov_w = sol["fov"] / math.sqrt(1.0 + 1.0 / (ar * ar))
    fov_h = fov_w / ar
    name, others = identify_target(sol["ra"], sol["dec"], fov_w, fov_h)
    return dict(ok=True, name=name or "未知", others=others, ra=sol["ra"], dec=sol["dec"],
                fov_w=fov_w, fov_h=fov_h, matches=sol["matches"], nstars=len(xy),
                roll=sol.get("roll", 0.0))


def identify_report(path, res):
    lines = ["文件: %s" % path, "识别结果: %s" % (res.get("name") or "未知")]
    if res.get("ok"):
        lines.append("星场中心: %s" % radec_text(res["ra"], res["dec"]))
        lines.append("视场: %.2f° x %.2f°" % (res["fov_w"], res["fov_h"]))
        lines.append("匹配星数: %d / 检测 %d 颗, 旋转 %.1f°" % (
            res["matches"], res["nstars"], res.get("roll", 0.0)))
        if res.get("catalog"):
            lines.append("使用星表: %s" % res["catalog"])
        if res.get("others"):
            lines.append("视场内其它目标: %s" % ", ".join(res["others"]))
    else:
        lines.append("原因: %s" % res.get("reason", ""))
    return "\n".join(lines)


def save_identify_report(path, res):
    out = os.path.splitext(path)[0] + "_object.txt"
    try:
        with open(out, "w", encoding="utf-8") as f:
            f.write(identify_report(path, res) + "\n")
    except Exception:
        return None
    return out


def catalog_choices():
    labels = [CATALOG_AUTO]
    for fn, label, rng in CATALOGS:
        if os.path.exists(_res_path(fn)):
            labels.append(label)
    labels.append("全部尝试")
    return labels


def ask_identify_options(parent):
    """弹出识别选项: 画幅 / 焦距 / 星表, 全部可留空. 取消返回 None."""
    import tkinter as tk
    from tkinter import ttk
    dlg = tk.Toplevel(parent)
    dlg.title("识别选项(都可以留空)")
    dlg.transient(parent)
    dlg.resizable(False, False)
    frm = ttk.Frame(dlg, padding=12)
    frm.pack(fill="both", expand=True)

    v_sensor = tk.StringVar(value=SENSOR_NONE)
    v_crop = tk.StringVar(value="")
    v_focal = tk.StringVar(value="")
    v_cat = tk.StringVar(value=CATALOG_AUTO)

    ttk.Label(frm, text="画幅").grid(row=0, column=0, sticky="w", pady=4)
    ttk.Combobox(frm, textvariable=v_sensor, width=24, state="readonly",
                 values=[SENSOR_NONE] + [lab for lab, _ in SENSORS]).grid(row=0, column=1, sticky="we", padx=6)
    ttk.Label(frm, text="裁切系数(可选)").grid(row=1, column=0, sticky="w", pady=4)
    ttk.Entry(frm, textvariable=v_crop, width=10).grid(row=1, column=1, sticky="w", padx=6)
    ttk.Label(frm, text="焦距 mm(可选)").grid(row=2, column=0, sticky="w", pady=4)
    ttk.Entry(frm, textvariable=v_focal, width=10).grid(row=2, column=1, sticky="w", padx=6)
    ttk.Label(frm, text="星表").grid(row=3, column=0, sticky="w", pady=4)
    ttk.Combobox(frm, textvariable=v_cat, width=24, state="readonly",
                 values=catalog_choices()).grid(row=3, column=1, sticky="we", padx=6)
    hint = ttk.Label(frm, text="填写画幅+焦距 可自动挑星表; 全留空则所有星表依次尝试",
                     foreground="#666666")
    hint.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 4))

    out = {}

    def ok():
        try:
            focal = float(v_focal.get()) if v_focal.get().strip() else None
        except ValueError:
            focal = None
        try:
            crop = float(v_crop.get()) if v_crop.get().strip() else None
        except ValueError:
            crop = None
        out.update(sensor=(None if v_sensor.get() == SENSOR_NONE else v_sensor.get()),
                   focal=focal, crop=crop, catalog=v_cat.get())
        dlg.destroy()

    def cancel():
        dlg.destroy()

    btns = ttk.Frame(frm)
    btns.grid(row=5, column=0, columnspan=2, sticky="e", pady=(10, 0))
    ttk.Button(btns, text="确定", command=ok).pack(side="left", padx=4)
    ttk.Button(btns, text="取消", command=cancel).pack(side="left")
    dlg.wait_visibility()
    dlg.grab_set()
    parent.wait_window(dlg)
    return out or None


FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyhl.ttc",
    "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simsun.ttc", "C:/Windows/Fonts/deng.ttf",
    "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/segoeui.ttf",
]


def _load_font(size):
    from PIL import ImageFont
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, max(8, int(size)))
            except Exception:
                continue
    return ImageFont.load_default()


def short_label(label):
    """去掉英文括注, 只留 '编号 中文名'."""
    if not label:
        return "未知"
    return label.split(" (")[0].strip()


def obj_display_name(name):
    """英文界面下把 "M42 猎户座大星云 (Great Orion Nebula)" 变成 "Great Orion Nebula"。"""
    if not name:
        return name
    if LANG != "en":
        return name
    m = re.search(r"\(([^)]+)\)", str(name))
    if m:
        return m.group(1).strip()
    return str(name)

def add_name_border(src, dst=None, name="未知", border_frac=0.05, jpeg_quality=95):
    """给照片加白色边框, 底部白色区域用黑字写天体名称."""
    from PIL import Image, ImageDraw
    ext = os.path.splitext(src)[1].lower()
    if ext in (".tif", ".tiff"):
        import tifffile
        a = tifffile.imread(src)
        a = np.asarray(a)
        if a.dtype != np.uint8:
            a = (np.clip(a.astype(np.float32) / (65535.0 if a.dtype == np.uint16 else max(a.max(), 1)), 0, 1) * 255).astype(np.uint8)
        if a.ndim == 2:
            a = np.stack([a] * 3, axis=2)
        img = Image.fromarray(a[:, :, :3])
    else:
        img = Image.open(src).convert("RGB")
    W, H = img.size
    b = max(12, int(round(min(W, H) * float(border_frac))))
    text_h = max(b, int(round(b * 1.5)))
    canvas = Image.new("RGB", (W + 2 * b, H + b + text_h), (255, 255, 255))
    canvas.paste(img, (b, b))
    draw = ImageDraw.Draw(canvas)
    txt = short_label(name)
    size = int(text_h * 0.62)
    while size > 8:
        font = _load_font(size)
        tw = draw.textlength(txt, font=font)
        if tw <= canvas.width - 2 * b - 10:
            break
        size = int(size * 0.92)
    font = _load_font(size)
    tw = draw.textlength(txt, font=font)
    try:
        bb = draw.textbbox((0, 0), txt, font=font)
        th = bb[3] - bb[1]
        ty = H + b + (text_h - th) / 2 - bb[1]
    except Exception:
        ty = H + b + text_h * 0.2
    draw.text(((canvas.width - tw) / 2, ty), txt, fill=(0, 0, 0), font=font)
    if dst is None:
        dst = os.path.splitext(src)[0] + "_framed.jpg"
    canvas.save(dst, quality=jpeg_quality, subsampling=0)
    return dst


def ask_frame_options(parent):
    """加白边成品对话框: 照片 / 目标(自动或手动) / 边框宽度."""
    import tkinter as tk
    from tkinter import ttk
    from tkinter import filedialog as fd
    dlg = tk.Toplevel(parent)
    dlg.title("生成带名称白边的成品")
    dlg.transient(parent)
    frm = ttk.Frame(dlg, padding=12)
    frm.pack(fill="both", expand=True)

    v_file = tk.StringVar()
    v_auto = tk.BooleanVar(value=True)
    v_obj = tk.StringVar(value=catalog_objects()[0] if catalog_objects() else "M42 猎户座大星云")
    v_border = tk.DoubleVar(value=5.0)

    ttk.Label(frm, text="照片").grid(row=0, column=0, sticky="w", pady=4)
    ttk.Entry(frm, textvariable=v_file, width=46).grid(row=0, column=1, sticky="we", padx=6)
    def pick():
        f = fd.askopenfilename(title="选择照片",
                               filetypes=[("图像/RAW", "*.tif *.tiff *.TIF *.png *.PNG *.jpg *.JPG *.jpeg *.arw *.ARW *.dng *.DNG *.cr2 *.CR2 *.nef *.NEF"), ("所有文件", "*.*")])
        if f:
            v_file.set(f)
    ttk.Button(frm, text="浏览…", width=7, command=pick).grid(row=0, column=2)

    ttk.Checkbutton(frm, text="自动识别目标", variable=v_auto).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
    ttk.Combobox(frm, textvariable=v_obj, values=catalog_objects(), width=44).grid(row=2, column=1, sticky="we", padx=6, pady=(4, 0))
    ttk.Label(frm, text="或手动选择").grid(row=2, column=0, sticky="w")

    ttk.Label(frm, text="白边宽度 %").grid(row=3, column=0, sticky="w", pady=(8, 0))
    ttk.Spinbox(frm, from_=1, to=15, increment=0.5, textvariable=v_border, width=8).grid(row=3, column=1, sticky="w", padx=6, pady=(8, 0))

    out = {}

    def ok():
        f = v_file.get().strip()
        if not f:
            from tkinter import messagebox
            messagebox.showwarning("提示", "请先选择照片")
            return
        out.update(path=f, auto=bool(v_auto.get()),
                   target=None if v_auto.get() else v_obj.get(),
                   border=float(v_border.get()) / 100.0)
        dlg.destroy()

    btns = ttk.Frame(frm)
    btns.grid(row=4, column=0, columnspan=3, sticky="e", pady=(12, 0))
    ttk.Button(btns, text="确定", command=ok).pack(side="left", padx=4)
    ttk.Button(btns, text="取消", command=dlg.destroy).pack(side="left")
    dlg.wait_visibility()
    dlg.grab_set()
    parent.wait_window(dlg)
    return out or None


def catalog_objects():
    objs = load_object_catalogue()
    out = []
    for o in sorted(objs, key=lambda d: d["n"]):
        lab = label_of(o)
        if lab not in out:
            out.append(lab)
    return out


STACK_MODE_LABELS = ["原版(两遍叠加)", "CPU 单遍优化", "GPU 加速"]
STACK_MODE_MAP = {"原版(两遍叠加)": "twopass", "CPU 单遍优化": "onepass", "GPU 加速": "gpu"}


def radec_text(ra, dec):
    rah = ra / 15.0
    h = int(rah)
    m = int((rah - h) * 60)
    s = (rah - h) * 3600 - m * 60
    sign = "+" if dec >= 0 else "-"
    ad = abs(dec)
    dd = int(ad)
    dm = int((ad - dd) * 60)
    ds = (ad - dd) * 3600 - dm * 60
    return "RA %02dh%02dm%04.1fs  Dec %s%02d°%02d'%04.1f\"" % (h, m, s, sign, dd, dm, ds)


# --------------------------------------------------------------------------
# 处理流程
# --------------------------------------------------------------------------
class Cancelled(Exception):
    pass


class Pipeline(object):
    """一次完整堆栈: 校暗/校平/配准/叠加/去马赛克/输出."""

    def __init__(self, opts, log=None, progress=None, cancel=None):
        self.o = opts
        self._log = log or (lambda m: None)
        self._prog = progress or (lambda frac, msg: None)
        self.cancel = cancel or threading.Event()
        self.stats = {}
        self._wb = None
        self._crop = (12, 12, 4000, 6000)
        self._raw_shape = (4024, 6048)
        self.object_name = None
        self.solve_info = None

    def log(self, msg):
        self._log(tr(msg))

    def prog(self, frac, msg=""):
        self._prog(float(frac), tr(msg) if msg else msg)

    def check(self):
        if self.cancel.is_set():
            raise Cancelled()

    # ---- 文件 ----
    @staticmethod
    def list_raw(folder, exclude_prefix=()):
        out = []
        if not folder or not os.path.isdir(folder):
            return out
        for p in sorted(glob.glob(os.path.join(folder, "*"))):
            if not os.path.isfile(p):
                continue
            if os.path.splitext(p)[1].lower() not in RAW_EXT:
                continue
            base = os.path.basename(p).lower()
            if any(base.startswith(x) for x in exclude_prefix):
                continue
            out.append(p)
        return out

    @staticmethod
    def natural_key(p):
        return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", os.path.basename(p))]

    # ---- 暗场/平场 ----
    def _combine(self, files, label, subtract_dark=None, frac0=0.0, frac1=0.1, sigma=4.0):
        n = len(files)
        if n == 0:
            return None
        acc = acc2 = None
        for i, p in enumerate(files):
            self.check()
            a = decode(p)[0].astype(np.float32)
            if subtract_dark is not None:
                a -= subtract_dark
            if acc is None:
                acc = np.zeros(a.shape, np.float64)
                acc2 = np.zeros(a.shape, np.float64)
            acc += a
            acc2 += a.astype(np.float64) ** 2
            if i % 5 == 0 or i == n - 1:
                self.prog(frac0 + (frac1 - frac0) * 0.5 * (i + 1) / n,
                          "%s: 统计 %d/%d" % (label, i + 1, n))
        mean = acc / n
        sd = np.sqrt(np.maximum(acc2 / n - mean ** 2, 0))
        acc.fill(0.0)
        acc2 = None
        cnt = np.zeros(mean.shape, np.float64)
        thr = sigma * np.maximum(sd, 1.0)
        for i, p in enumerate(files):
            self.check()
            a = decode(p)[0].astype(np.float32)
            if subtract_dark is not None:
                a -= subtract_dark
            good = np.abs(a - mean) < thr
            acc += np.where(good, a, 0.0)
            cnt += good
            if i % 5 == 0 or i == n - 1:
                self.prog(frac0 + (frac1 - frac0) * (0.5 + 0.5 * (i + 1) / n),
                          "%s: 合成 %d/%d" % (label, i + 1, n))
        return (acc / np.maximum(cnt, 1)).astype(np.float32)

    def _master_flat(self, files, dark, frac0, frac1):
        flat = self._combine(files, "平场", subtract_dark=dark, frac0=frac0, frac1=frac1)
        if flat is None:
            return None
        norm = np.zeros_like(flat)
        for oy in (0, 1):
            for ox in (0, 1):
                pl = flat[oy::2, ox::2]
                m = float(np.median(pl))
                norm[oy::2, ox::2] = np.clip(pl / max(m, 1.0), 0.15, 3.0)
        return norm

    # ---- 主流程 ----
    # ------------------------------------------------------------------
    # 叠加实现: 单遍(Welford 在线剔除) / GPU
    # ------------------------------------------------------------------
    def _stack_onepass(self, lights, Ms, ts, ok, idx, shapes, dark, flat, o, PLANES):
        """单遍叠加: 边累加边用在线均值/σ 剔除, 省掉第二遍解码+重采样."""
        nthreads = max(1, int(o.threads))
        chunks = [c for c in np.array_split(idx, nthreads)]
        accs = [dict(sum=[np.zeros(s_, np.float32) for s_ in shapes],
                     sq=[np.zeros(s_, np.float64) for s_ in shapes],
                     cnt=[np.zeros(s_, np.float32) for s_ in shapes]) for _ in range(nthreads)]
        pdone = [0]
        plock = threading.Lock()
        nframes = len(idx)
        warm = min(25, max(5, nframes // max(nthreads, 1)))

        warp_ord = _warp_order(o)

        def worker(ci):
            S = [np.zeros(s_, np.float32) for s_ in shapes]
            Q = [np.zeros(s_, np.float64) for s_ in shapes]
            C = [np.zeros(s_, np.float32) for s_ in shapes]
            msd = [None] * 4
            msd_k = [-999] * 4
            k = 0
            for pos in chunks[ci]:
                self.check()
                a = decode(lights[pos])[0].astype(np.float32)
                if dark is not None:
                    a -= dark
                if flat is not None:
                    a /= flat
                if getattr(o, "lp_remove", False):
                    a = remove_gradient(a.copy(), mode=getattr(o, "lp_mode", "sub"))
                Mxy = Ms[pos]
                Mrc = np.array([[Mxy[1, 1], Mxy[1, 0]], [Mxy[0, 1], Mxy[0, 0]]])
                trc = np.array([ts[pos][1], ts[pos][0]]) * 2.0
                k += 1
                for pi, (oy, ox) in enumerate(PLANES):
                    oo = np.array([oy, ox], np.float64)
                    off = (Mrc @ oo + trc - oo) * 0.5
                    pl = a[oy::2, ox::2]
                    w = ndi.affine_transform(pl, Mrc, offset=off, output_shape=pl.shape,
                                             order=warp_ord, mode='nearest',
                                             prefilter=(warp_ord > 1))
                    if k > warm:
                        # 均值/σ 每 8 帧刷新一次：在线统计变化很慢，对剔除结果影响
                        # 可忽略，但省掉每帧 4 个平面 × 6M 像素的除法/开方/临时数组
                        if msd[pi] is None or (k - msd_k[pi]) >= 8:
                            m = S[pi] / np.maximum(C[pi], 1.0)
                            var = Q[pi] / np.maximum(C[pi], 1.0) - m.astype(np.float64) ** 2
                            msd[pi] = (m, np.maximum(np.sqrt(np.maximum(var, 0)), 1e-3))
                            msd_k[pi] = k
                        m, sd = msd[pi]
                        gm = np.abs(w - m) <= o.kappa * sd
                        S[pi] += np.where(gm, w, 0.0)
                        C[pi] += gm
                        Q[pi] += np.where(gm, w, 0.0).astype(np.float64) ** 2
                    else:
                        S[pi] += w
                        C[pi] += 1.0
                        Q[pi] += w.astype(np.float64) ** 2
                with plock:
                    pdone[0] += 1
                    self.prog(0.48 + 0.46 * pdone[0] / nframes,
                              "叠加(单遍) %d/%d" % (pdone[0], nframes))
            for pi in range(4):
                accs[ci]["sum"][pi] = S[pi]
                accs[ci]["sq"][pi] = Q[pi]
                accs[ci]["cnt"][pi] = C[pi]

        self._run_threaded(worker, list(range(nthreads)))
        S = [np.zeros(s_, np.float32) for s_ in shapes]
        C = [np.zeros(s_, np.float32) for s_ in shapes]
        for a_ in accs:
            for pi in range(4):
                S[pi] += a_["sum"][pi]
                C[pi] += a_["cnt"][pi]
        return np.stack([S[pi] / np.maximum(C[pi], 1.0) for pi in range(4)]).astype(np.float32)

    def _gpu_warp(self, g, M, off, grids=None, order=3):
        """GPU 重采样: order=3 Catmull-Rom(4x4), order=1 双线性(2x2, 更快)."""
        import cupy as cp
        h, w = g.shape
        if grids is None:
            yy, xx = cp.mgrid[0:h, 0:w].astype(cp.float32)
        else:
            yy, xx = grids
        sy = (M[0, 0] * yy + M[0, 1] * xx) + float(off[0])
        sx = (M[1, 0] * yy + M[1, 1] * xx) + float(off[1])
        y0 = cp.floor(sy)
        x0 = cp.floor(sx)
        fy = sy - y0
        fx = sx - x0
        y0i = y0.astype(cp.int32)
        x0i = x0.astype(cp.int32)
        if int(order) == 1:
            out = None
            for j in (0, 1):
                yj = cp.clip(y0i + j, 0, h - 1)
                wy = (1.0 - fy) if j == 0 else fy
                row = None
                for i in (0, 1):
                    xi = cp.clip(x0i + i, 0, w - 1)
                    wx = (1.0 - fx) if i == 0 else fx
                    t = g[yj, xi] * (wx * wy)
                    row = t if row is None else row + t
                out = row if out is None else out + row
            return out
        f2 = fy * fy; f3 = f2 * fy
        g2 = fx * fx; g3 = g2 * fx
        wy = (-0.5 * fy + f2 - 0.5 * f3,
              1.0 - 2.5 * f2 + 1.5 * f3,
              0.5 * fy + 2.0 * f2 - 1.5 * f3,
              -0.5 * f2 + 0.5 * f3)
        wx = (-0.5 * fx + g2 - 0.5 * g3,
              1.0 - 2.5 * g2 + 1.5 * g3,
              0.5 * fx + 2.0 * g2 - 1.5 * g3,
              -0.5 * g2 + 0.5 * g3)
        out = None
        for j in range(4):
            yj = cp.clip(y0i + (j - 1), 0, h - 1)
            row = None
            for i in range(4):
                xi = cp.clip(x0i + (i - 1), 0, w - 1)
                t = g[yj, xi] * (wx[i] * wy[j])
                row = t if row is None else row + t
            out = row if out is None else out + row
        return out

    def _stack_gpu(self, lights, Ms, ts, ok, idx, shapes, dark, flat, o, PLANES):
        """GPU 单遍叠加: 多线程预取解码(含逐帧去光污染) -> GPU 重采样+累加."""
        import cupy as cp
        from concurrent.futures import ThreadPoolExecutor
        cp.cuda.Device(0).use()
        S = [cp.zeros(s_, cp.float32) for s_ in shapes]
        Q = [cp.zeros(s_, cp.float64) for s_ in shapes]
        C = [cp.zeros(s_, cp.float32) for s_ in shapes]
        nframes = len(idx)
        warm = min(25, max(5, nframes // 4))
        grids = {}
        for pi, (oy, ox) in enumerate(PLANES):
            shape = (self._raw_shape[0] // 2, self._raw_shape[1] // 2)
            grids[pi] = tuple(cp.mgrid[0:shape[0], 0:shape[1]].astype(cp.float32))

        def prepare(pos):
            a = decode(lights[pos])[0].astype(np.float32)
            if dark is not None:
                a -= dark
            if flat is not None:
                a /= flat
            if getattr(o, "lp_remove", False):
                a = remove_gradient(a.copy(), mode=getattr(o, "lp_mode", "sub"))
            return a

        warp_ord = _warp_order(o)
        nworker = max(2, min(6, int(o.threads)))
        k = 0
        with ThreadPoolExecutor(max_workers=nworker) as ex:
            it = iter(idx)
            pending = []
            for _ in range(nworker * 2):
                nxt = next(it, None)
                if nxt is None:
                    break
                pending.append((nxt, ex.submit(prepare, nxt)))
            while pending:
                self.check()
                pos, fut = pending.pop(0)
                a = fut.result()
                nxt = next(it, None)
                if nxt is not None:
                    pending.append((nxt, ex.submit(prepare, nxt)))
                Mxy = Ms[pos]
                Mrc = np.array([[Mxy[1, 1], Mxy[1, 0]], [Mxy[0, 1], Mxy[0, 0]]], np.float32)
                trc = np.array([ts[pos][1], ts[pos][0]], np.float32) * 2.0
                k += 1
                for pi, (oy, ox) in enumerate(PLANES):
                    oo = np.array([oy, ox], np.float32)
                    off = (Mrc @ oo + trc - oo) * 0.5
                    pl = np.ascontiguousarray(a[oy::2, ox::2])
                    g = cp.asarray(pl)
                    w = self._gpu_warp(g, Mrc, off, grids[pi], order=warp_ord)
                    if k > warm:
                        m = S[pi] / cp.maximum(C[pi], 1.0)
                        var = Q[pi] / cp.maximum(C[pi], 1.0) - m.astype(cp.float64) ** 2
                        sd = cp.sqrt(cp.maximum(var, 0)).astype(cp.float32)
                        gm = cp.abs(w - m) <= o.kappa * cp.maximum(sd, 1e-3)
                        S[pi] += cp.where(gm, w, 0.0)
                        C[pi] += gm
                        Q[pi] += cp.where(gm, w, 0.0).astype(cp.float64) ** 2
                    else:
                        S[pi] += w
                        C[pi] += 1.0
                        Q[pi] += w.astype(cp.float64) ** 2
                if k % 10 == 0:
                    self.prog(0.48 + 0.46 * k / nframes, "叠加(GPU) %d/%d" % (k, nframes))
        out = [cp.asnumpy(S[pi] / cp.maximum(C[pi], 1.0)) for pi in range(4)]
        return np.stack(out).astype(np.float32)

    def run(self):
        o = self.o
        t_start = time.time()
        if not getattr(o, "out_path", None):
            path, outdir = default_out_path()
            o.out_path = path
            self.log("输出目录: %s" % outdir)
        o.preview_sat = float(getattr(o, "preview_sat", 1.0))
        o.wb_out = bool(getattr(o, "wb_out", False))

        lights = self.list_raw(o.light_dir, exclude_prefix=("dark", "flat", "bias"))
        darks = self.list_raw(o.dark_dir, exclude_prefix=("light", "flat", "orion")) if o.dark_dir else []
        flats = self.list_raw(o.flat_dir, exclude_prefix=("light", "dark", "orion")) if o.flat_dir else []
        if not lights:
            raise RuntimeError("亮场文件夹中找不到 RAW 文件")
        self.log("亮场 %d 张, 暗场 %d 张, 平场 %d 张" % (len(lights), len(darks), len(flats)))

        # ---------- 光污染傻瓜模式: 等级 -> 具体参数 ----------
        lvl = str(getattr(o, "lp_level", "manual") or "manual").lower()
        if lvl != "manual":
            if lvl == "auto":
                auto_lvl, info = estimate_lp_level(lights)
                self.log("自动判断光污染等级: %s (%s)" % (auto_lvl, info))
                lvl = auto_lvl
            if lvl not in LP_PRESETS:
                lvl = "mid"
            if not flats and lvl == "low":
                lvl = "mid"
                self.log("未提供平场, 等级由 低 上调为 中")
            elif not flats and lvl == "mid":
                lvl = "high"
                self.log("未提供平场, 等级由 中 上调为 高")
            for k, v in LP_PRESETS[lvl].items():
                setattr(o, k, v)
            self.log("光污染等级 %s -> %s" % (lvl, LP_PRESET_TEXT[lvl]))

        times = {}
        for p in lights:
            times[p] = exif_time(p)
        if all(v is not None for v in times.values()):
            lights.sort(key=lambda p: (times[p], self.natural_key(p)))
            self.log("已按拍摄时间排序亮场")
        else:
            lights.sort(key=self.natural_key)

        dark = None
        if darks:
            dark = self._combine(darks, "暗场", frac0=0.00, frac1=0.06)
            self.log("主暗场完成 (均值 %.1f)" % float(dark.mean()))
        else:
            self.log("未提供暗场, 跳过暗场校正")
        self.prog(0.06, "主暗场完成")

        flat = None
        if flats:
            flat = self._master_flat(flats, dark, 0.06, 0.10)
            self.log("主平场完成 (归一化 0.1%%~99.9%%: %.2f~%.2f)" % (
                float(np.percentile(flat, 0.1)), float(np.percentile(flat, 99.9))))
        else:
            self.log("未提供平场, 跳过平场校正")
        self.prog(0.10, "主平场完成")

        # 星点检测
        n = len(lights)
        stars = np.full((n, 400, 2), np.nan, np.float32)
        lock = threading.Lock()
        done = [0]

        def work(i, path):
            img, meta = decode(path)
            if i == 0:
                self._wb = np.array(meta["wb"], float)
                self._crop = tuple(meta["crop"])
                self._raw_shape = img.shape
            a = img.astype(np.float32)
            del img
            if dark is not None:
                a -= dark
            if flat is not None:
                a /= flat
            xy, _ = detect_stars(binned_luminance(a), max_stars=400)
            stars[i, :len(xy)] = xy
            with lock:
                done[0] += 1
                self.prog(0.10 + 0.30 * done[0] / n, "星点检测 %d/%d" % (done[0], n))

        self._run_threaded(lambda it: work(*it), list(enumerate(lights)))
        good = np.array([np.isfinite(stars[i, :, 0]).sum() >= 20 for i in range(n)])
        self.log("星点检测完成, 有效帧 %d/%d" % (int(good.sum()), n))

        # ---- 目标识别(可选) ----
        self.object_name = None
        self.solve_info = None
        manual = getattr(o, "manual_object", None)
        if manual:
            self.object_name = manual
            self.log("手动指定目标: %s" % manual)
            self.prog(0.405, "目标: %s" % manual)
        elif getattr(o, "identify", True):
            self.prog(0.405, "识别拍摄目标 ...")
            self.log("正在识别拍摄目标(内置星表盲解) ...")
            try:
                # 视场提示: 优先 EXIF; 窄视场(<10°)改用手感更好的专用质心
                fov_hint = None
                try:
                    fov_hint = exif_fov(lights[0])
                except Exception:
                    fov_hint = None
                W2, H2 = self._raw_shape[1] // 2, self._raw_shape[0] // 2
                sol = None
                if fov_hint and fov_hint < 10.0:
                    # 窄视场: 单帧成功率不稳定, 依次试中间/首/尾三帧
                    cand_idx = []
                    for i in (n // 2, 0, n - 1):
                        if 0 <= i < n and i not in cand_idx:
                            cand_idx.append(i)
                    for ci in cand_idx:
                        try:
                            lum_ref, _ = load_image_luminance(lights[ci])
                            xy_n, _ = detect_stars_narrow(lum_ref, max_stars=200)
                        except Exception:
                            continue
                        if len(xy_n) < 10:
                            continue
                        sol = solve_field(np.asarray(xy_n, np.float64), W2, H2,
                                          fov_hint=fov_hint)
                        if sol:
                            self.log("  窄视场解算成功(第 %d 帧, %d 颗星)" % (ci + 1, len(xy_n)))
                            break
                if sol is None:
                    ref = stars[n // 2]
                    m = np.isfinite(np.asarray(ref, np.float64)[:, 0])
                    sol = solve_field(np.asarray(ref, np.float64)[m], W2, H2,
                                      fov_hint=fov_hint)
            except Exception as e:
                sol = None
                self.log("识别出错: %r" % (e,))
            if sol:
                diag = sol["fov"]
                W, H = self._raw_shape[1], self._raw_shape[0]
                fov_w = diag / math.sqrt(1.0 + (H / float(W)) ** 2)
                fov_h = fov_w * H / float(W)
                name, others = identify_target(sol["ra"], sol["dec"], fov_w, fov_h)
                self.solve_info = dict(sol, fov_w=fov_w, fov_h=fov_h, others=others)
                if name:
                    self.object_name = name
                    self.log("识别到目标: %s" % name)
                    if others:
                        self.log("  视场内其它目标: %s" % ", ".join(others))
                else:
                    self.object_name = "未知"
                    self.log("已解算星场(%s), 视场内没有已知天体 -> 未知" % radec_text(sol["ra"], sol["dec"]))
                self.log("  星场中心 %s, 视场 %.2f° x %.2f°, 匹配星 %d 颗" % (
                    radec_text(sol["ra"], sol["dec"]), fov_w, fov_h, sol["matches"]))
            else:
                self.object_name = "未知"
                self.log("星场解算失败, 目标名称: 未知")
            self.prog(0.42, "识别完成: %s" % self.object_name)

        # ---------- 按目标类型做参数优化 ----------
        if getattr(o, "type_opt", True):
            self._apply_type_preset(lights)

        # 配准
        ref_pos = n // 2
        ref_xy = stars[ref_pos].astype(np.float64)
        Ms = np.tile(np.eye(2), (n, 1, 1))
        ts = np.zeros((n, 2))
        ok = np.zeros(n, bool)
        ref_keys200 = None
        try:
            ref_keys200 = triangle_keys(ref_xy[:200])
        except Exception:
            ref_keys200 = None
        for pos in range(n):
            self.check()
            if not good[pos]:
                continue
            tgt = stars[pos].astype(np.float64)
            res = None
            prevs = [p for p in range(max(0, pos - 4), pos) if ok[p]]
            if prevs:
                p = prevs[-1]
                if len(prevs) >= 2:
                    q = prevs[-2]
                    dt = (pos - p) / max(1, (p - q))
                    Mp = Ms[p] + (Ms[p] - Ms[q]) * min(dt, 1.5)
                    tp = ts[p] + (ts[p] - ts[q]) * min(dt, 1.5)
                else:
                    Mp, tp = Ms[p], ts[p]
                res = refine_match(ref_xy, tgt, Mp, tp, radius=10.0)
            if res is None:
                r = match_stars(ref_xy, tgt, max_stars=200, min_inliers=15, ref_keys=ref_keys200)
                if r is not None:
                    res = refine_match(ref_xy, tgt, r[0], r[1], radius=4.0) or r
            if res is not None:
                M, tt, nin, rr = res
                if 0.99 < np.hypot(M[0, 0], M[1, 0]) < 1.01 and rr < 1.5:
                    Ms[pos], ts[pos], ok[pos] = M, tt, True
            if pos % 10 == 0:
                self.prog(0.40 + 0.08 * pos / n, "配准 %d/%d" % (pos + 1, n))
        for _ in range(3):
            bad = np.nonzero(good & ~ok)[0]
            if len(bad) == 0:
                break
            gp = np.nonzero(ok)[0]
            for pos in bad:
                self.check()
                tgt = stars[pos].astype(np.float64)
                near = gp[np.argmin(np.abs(gp - pos))]
                res = None
                for rad in (80.0, 50.0, 30.0, 15.0):
                    res = refine_match(ref_xy, tgt, Ms[near], ts[near], radius=rad)
                    if res is not None:
                        break
                if res is None:
                    src = stars[near].astype(np.float64)
                    r = match_stars(src, tgt, max_stars=200, min_inliers=15)
                    if r is not None:
                        res = refine_match(src, tgt, r[0], r[1], radius=4.0)
                        if res is not None:
                            M2, t2 = res[0], res[1]
                            res = refine_match(ref_xy, tgt, M2 @ Ms[near], M2 @ ts[near] + t2, radius=6.0)
                if res is not None:
                    M, tt, nin, rr = res
                    if 0.99 < np.hypot(M[0, 0], M[1, 0]) < 1.01 and rr < 1.5:
                        Ms[pos], ts[pos], ok[pos] = M, tt, True
        nok = int(ok.sum())
        self.log("配准完成: %d/%d 帧" % (nok, n))
        if nok < 3:
            raise RuntimeError("可用帧太少, 无法堆栈")
        self.prog(0.48, "配准完成")

        # 叠加
        idx = np.nonzero(ok)[0]
        nframes = len(idx)
        raw_h, raw_w = self._raw_shape
        PLANES = [(0, 0), (0, 1), (1, 0), (1, 1)]
        shapes = [(raw_h // 2, raw_w // 2)] * 4

        def stack_pass(clip, mean=None, sd=None):
            warp_ord = _warp_order(o)
            nthreads = max(1, int(o.threads))
            chunks = [c for c in np.array_split(idx, nthreads)]
            accs = [dict(sum=[np.zeros(s, np.float32) for s in shapes],
                         sq=[np.zeros(s, np.float64) for s in shapes],
                         cnt=[np.zeros(s, np.float32) for s in shapes]) for _ in range(nthreads)]
            pdone = [0]
            plock = threading.Lock()

            def worker(ci):
                for pos in chunks[ci]:
                    self.check()
                    a = decode(lights[pos])[0].astype(np.float32)
                    if dark is not None:
                        a -= dark
                    if flat is not None:
                        a /= flat
                    if getattr(o, "lp_remove", False):
                        a = remove_gradient(a.copy(), mode=getattr(o, "lp_mode", "sub"))
                    Mxy = Ms[pos]
                    Mrc = np.array([[Mxy[1, 1], Mxy[1, 0]], [Mxy[0, 1], Mxy[0, 0]]])
                    trc = np.array([ts[pos][1], ts[pos][0]]) * 2.0
                    for pi, (oy, ox) in enumerate(PLANES):
                        oo = np.array([oy, ox], np.float64)
                        off = (Mrc @ oo + trc - oo) * 0.5
                        pl = a[oy::2, ox::2]
                        w = ndi.affine_transform(pl, Mrc, offset=off, output_shape=pl.shape,
                                                 order=warp_ord, mode='nearest',
                                                 prefilter=(warp_ord > 1))
                        if clip:
                            gm = np.abs(w - mean[pi]) <= o.kappa * sd[pi]
                            accs[ci]["sum"][pi] += np.where(gm, w, 0.0)
                            accs[ci]["cnt"][pi] += gm
                        else:
                            accs[ci]["sum"][pi] += w
                            accs[ci]["sq"][pi] += w.astype(np.float64) ** 2
                    with plock:
                        pdone[0] += 1
                        f0 = 0.48 if not clip else 0.71
                        f1 = 0.71 if not clip else 0.94
                        self.prog(f0 + (f1 - f0) * pdone[0] / nframes,
                                  ("叠加(σ剔除) " if clip else "叠加 ") + "%d/%d" % (pdone[0], nframes))

            self._run_threaded(worker, list(range(nthreads)))
            S = [np.zeros(s, np.float32) for s in shapes]
            C = [np.zeros(s, np.float32) for s in shapes]
            Q = [np.zeros(s, np.float64) for s in shapes]
            for a_ in accs:
                for pi in range(4):
                    S[pi] += a_["sum"][pi]
                    C[pi] += a_["cnt"][pi]
                    Q[pi] += a_["sq"][pi]
            if clip:
                return np.stack([S[pi] / np.maximum(C[pi], 1.0) for pi in range(4)]).astype(np.float32)
            mean_v = np.stack([S[pi] / nframes for pi in range(4)]).astype(np.float32)
            var = np.stack([np.maximum(Q[pi] / nframes - (S[pi] / nframes).astype(np.float64) ** 2, 0)
                            for pi in range(4)])
            return mean_v, np.sqrt(var).astype(np.float32)

        mode = _resolve_mode(getattr(o, "stack_mode", DEFAULT_STACK_MODE))
        if mode == "gpu":
            try:
                self.log("GPU 单遍叠加 (重采样+累加在显卡上) ...")
                stacked = self._stack_gpu(lights, Ms, ts, ok, idx, shapes, dark, flat, o, PLANES)
            except Exception as e:
                self.log("GPU 叠加失败(%r), 回退 CPU 单遍" % (e,))
                stacked = self._stack_onepass(lights, Ms, ts, ok, idx, shapes, dark, flat, o, PLANES)
        elif mode == "onepass":
            self.log("CPU 单遍叠加 (在线 κσ 剔除) ...")
            stacked = self._stack_onepass(lights, Ms, ts, ok, idx, shapes, dark, flat, o, PLANES)
        else:
            self.log("第一遍叠加 (统计均值与噪声) ...")
            mean, sd = stack_pass(False)
            self.log("第二遍叠加 (κ=%.1f σ 剔除) ..." % o.kappa)
            stacked = stack_pass(True, mean=mean, sd=sd)
            del mean, sd
        self.prog(0.94, "叠加完成")

        self.log("去马赛克 ...")
        rgb = self._demosaic(stacked)
        del stacked
        self.prog(0.97, "去马赛克完成")

        crop = self._auto_crop(Ms, ts, ok, rgb.shape[1], rgb.shape[0], o.crop)
        if crop != (0, rgb.shape[0], 0, rgb.shape[1]):
            rgb = rgb[crop[0]:crop[1], crop[2]:crop[3]]
            self.log("按公共覆盖范围裁剪 -> %d x %d" % (rgb.shape[1], rgb.shape[0]))

        poly = int(getattr(o, "bg_poly", 0) or 0)
        protect = bool(getattr(o, "bg_protect", False))
        # bg_poly / bg_protect 单独给出时也应触发去背景（以前只有 --bg2d 才生效，属于 bug）
        if getattr(o, "bg2d", 0) or poly > 0 or protect:
            if poly > 0:
                self.log("多项式去背景(degree=%d) ..." % poly)
            elif protect:
                self.log("Background2D 去背景(网格+结构保护) ...")
            else:
                self.log("Background2D 去背景(网格+sigma裁剪+中值+三次插值) ...")
            try:
                out = np.empty(rgb.shape, np.float32)
                q = float(getattr(o, "bg2d_q", 40.0))
                for c in range(3):
                    plane = np.asarray(rgb[:, :, c], np.float32)
                    if poly > 0:
                        out[:, :, c] = plane - bg_poly(plane, degree=poly)
                    elif protect:
                        out[:, :, c] = plane - bg2d_protect(plane, floor_q=q)
                    else:
                        out[:, :, c] = plane - bg2d_mesh(plane, floor_q=q)
                rgb = out
                self.log("Background2D 完成")
            except Exception as e:
                self.log("Background2D 失败: %r" % (e,))
        if getattr(o, "rbf", 0):
            if getattr(o, "bg2d", 0):
                self.log("已使用 Background2D, 跳过 RBF(避免重复去背景)")
            else:
                self.log("RBF 背景提取(薄板样条) ...")
                try:
                    bg = rbf_background(rgb.astype(np.float32), smoothing=float(o.rbf))
                    rgb = rgb.astype(np.float32) - bg
                except Exception as e:
                    self.log("RBF 失败: %r" % (e,))
        if getattr(o, "flatten", False):
            self.log("背景平整(去光害渐变) ...")
            rgb = self._flatten_bg(rgb)
        if getattr(o, "denoise", 0):
            self.log("小波降噪 (强度 %.2f, %d 层) ..." % (
                float(o.denoise), int(getattr(o, "denoise_scales", 4))))
            try:
                rgb = wavelet_denoise(rgb, strength=float(o.denoise),
                                      scales=int(getattr(o, "denoise_scales", 4)))
            except Exception as e:
                self.log("降噪失败: %r" % (e,))

        if getattr(o, "chroma_denoise_level", 0):
            self.log("小波色噪去除 (强度 %.2f, %d 层) ..." % (
                float(o.chroma_denoise_level), int(getattr(o, "chroma_scales", 3))))
            try:
                rgb = chroma_wavelet(rgb, strength=float(o.chroma_denoise_level),
                                     scales=int(getattr(o, "chroma_scales", 3)))
            except Exception as e:
                self.log("色噪去除失败: %r" % (e,))
        elif getattr(o, "chroma_nr", 0):
            self.log("色度降噪 (高斯 sigma=%.1f, 旧算法) ..." % float(o.chroma_nr))
            try:
                rgb = chroma_denoise(rgb, sigma=float(o.chroma_nr))
            except Exception as e:
                self.log("色度降噪失败: %r" % (e,))
        out = o.out_path
        kind = str(getattr(o, "out_kind", "both") or "both").lower()
        linear_arr = None
        if kind in ("both", "linear"):
            linear_arr = self._save_tiff(rgb, out)
            self.log("已保存线性 16bit TIFF: %s" % out)
            try:
                preview = os.path.splitext(out)[0] + "_preview.jpg"
                self._save_preview(rgb, preview)
                self.log("已保存预览图(仅拉伸, 未做色彩校准): %s" % preview)
            except Exception as e:
                self.log("预览图生成失败: %r" % e)
        if kind in ("both", "stretch"):
            try:
                self.prog(0.99, "生成拉伸图")
                if linear_arr is None:
                    linear_arr = self._prepare_linear(rgb)
                y = _stretch_float(linear_arr, sat=float(getattr(o, "stretch_sat", 1.18)))
                st_tif = os.path.splitext(out)[0] + "_stretched.tif"
                _write_stretched(y, st_tif, jpg=True,
                                 jpg_max=int(getattr(o, "jpg_max", 2600)),
                                 jpg_quality=int(getattr(o, "jpg_quality", 92)))
                self.log("已保存拉伸 16bit TIFF(可直接用): %s" % st_tif)
            except Exception as e:
                self.log("拉伸图生成失败: %r" % (e,))

        # ---------- 叠加后的星点处理（缩星 / 去星）----------
        smode = str(getattr(o, "star_mode", "off") or "off").lower()
        if smode in ("reduce", "remove"):
            try:
                self.prog(0.995, "星点处理")
                arr = linear_arr if linear_arr is not None else self._prepare_linear(rgb)
                res, stars = process_stars(arr.astype(np.float32), mode=smode,
                                           strength=float(getattr(o, "star_strength", 0.85)))
                cov = LAST_STAR_COVERAGE
                if cov > 0.35:
                    # 掩膜覆盖超过 1/3 说明把噪声/背景当成星点了（常见于帧数极少、噪声极高）
                    self.log("星点掩膜覆盖 %.0f%%(过大), 判定为误检, 跳过星点处理" % (cov * 100))
                    raise _SkipStars()
                self.log("星点处理: %s (强度 %.2f, 掩膜覆盖 %.1f%%)" % (
                    "去星" if smode == "remove" else "缩星",
                    float(getattr(o, "star_strength", 0.85)), cov * 100))
                if smode == "remove" and cov > 0.12:
                    self.log("提示: 星场较密, 去星可能带走部分漫射光, 可改缩星或降低强度")
                import tifffile
                tag = "_starless" if smode == "remove" else "_starred"
                sp = os.path.splitext(out)[0] + tag + ".tif"
                tifffile.imwrite(sp, np.clip(res, 0, 65535).astype(np.uint16),
                                 photometric="rgb", compression="zlib")
                self.log("已保存%s: %s" % ("无星版" if smode == "remove" else "缩星版", sp))
                if smode == "remove":
                    sp2 = os.path.splitext(out)[0] + "_starless_stars.tif"
                    tifffile.imwrite(sp2, np.clip(stars + 2000.0, 0, 65535).astype(np.uint16),
                                     photometric="rgb", compression="zlib")
                    self.log("已保存星点层: %s" % sp2)
                try:
                    y = _stretch_float(np.clip(res, 0, 65535),
                                       sat=float(getattr(o, "stretch_sat", 1.18)))
                    _write_stretched(y, os.path.splitext(sp)[0] + "_stretched.tif", jpg=True,
                                     jpg_max=int(getattr(o, "jpg_max", 2600)),
                                     jpg_quality=int(getattr(o, "jpg_quality", 92)))
                except Exception as e:
                    self.log("星点版拉伸图失败: %r" % (e,))
            except _SkipStars:
                pass
            except Exception as e:
                self.log("星点处理失败: %r" % (e,))

        # 目标识别结果落盘
        try:
            obj_path = os.path.splitext(out)[0] + "_object.txt"
            with open(obj_path, "w", encoding="utf-8") as f:
                name_txt = self.object_name or ("未启用识别" if not getattr(o, "identify", True) else "未知")
                f.write((tr("识别结果: %s") if LANG == "en" else "识别结果: %s") % obj_display_name(name_txt) + "\n")
                if self.solve_info:
                    si = self.solve_info
                    f.write("星场中心: %s\n" % radec_text(si["ra"], si["dec"]))
                    f.write("视场: %.2f° x %.2f° (对角 %.2f°)\n" % (si["fov_w"], si["fov_h"], si["fov"]))
                    f.write("匹配星数: %d, 旋转: %.1f°\n" % (si["matches"], si.get("roll", 0.0)))
                    if si.get("others"):
                        f.write("视场内其它目标: %s\n" % ", ".join(si["others"]))
                elif not getattr(o, "manual_object", None):
                    f.write("(星场解算失败, 或该视场超出内置星表适用范围)\n")
            self.log("识别结果已写入: %s" % obj_path)
        except Exception as e:
            self.log("识别结果写入失败: %r" % e)
        self.prog(1.0, "完成")
        self.log("总耗时 %.1f 分钟, 叠加 %d 帧, 目标: %s" % (
            (time.time() - t_start) / 60.0, nframes, self.object_name or "未识别"))

    def _run_threaded(self, fn, items):
        q = queue.Queue()
        for it in items:
            q.put(it)
        err = []

        def runner():
            while True:
                try:
                    it = q.get_nowait()
                except queue.Empty:
                    return
                if self.cancel.is_set():
                    return
                try:
                    fn(it)
                except Cancelled:
                    return
                except Exception as e:  # noqa
                    err.append(e)
                    return

        nthreads = max(1, int(self.o.threads))
        threads = [threading.Thread(target=runner, daemon=True) for _ in range(nthreads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.check()
        if err:
            raise err[0]

    # ---- 去马赛克 ----
    @staticmethod
    def _bilinear_2x(plane, oy, ox, H, W):
        out = np.zeros((H, W), np.float32)
        out[oy::2, ox::2] = plane
        c1 = 1 - ox
        samp = out[oy::2, ox::2]
        if ox == 1:
            samp = np.concatenate([samp[:, :1], samp], axis=1)
        else:
            samp = np.concatenate([samp, samp[:, -1:]], axis=1)
        out[oy::2, c1::2] = 0.5 * (samp[:, :-1] + samp[:, 1:])
        up = out[oy::2, :].copy()
        if oy == 1:
            up = np.concatenate([up[:1, :], up], axis=0)
        else:
            up = np.concatenate([up, up[-1:, :]], axis=0)
        out[1 - oy::2, :] = 0.5 * (up[:-1, :] + up[1:, :])
        return out

    def _demosaic(self, st):
        y0, x0, hh, ww = self._crop
        pr, pc = hh // 2, ww // 2
        ry, rx = y0 // 2, x0 // 2
        planes = [st[i][ry:ry + pr, rx:rx + pc] for i in range(4)]
        H, W = pr * 2, pc * 2
        G = 0.5 * (self._bilinear_2x(planes[1], 0, 1, H, W) + self._bilinear_2x(planes[2], 1, 0, H, W))
        Rf = self._bilinear_2x(planes[0], 0, 0, H, W)
        Bf = self._bilinear_2x(planes[3], 1, 1, H, W)
        return np.stack([Rf, G, Bf], axis=2)

    def _auto_crop(self, Ms, ts, ok, W, H, mode):
        if not mode:
            return (0, H, 0, W)
        pos = np.nonzero(ok)[0]
        step = 8
        ys = np.arange(0, H, step)
        xs = np.arange(0, W, step)
        gx, gy = np.meshgrid(xs, ys)
        y0, x0 = self._crop[0], self._crop[1]
        px = (gx + x0) / 2.0
        py = (gy + y0) / 2.0
        lo = 8.0
        rmax = self._raw_shape[0] / 2.0 - lo
        cmax = self._raw_shape[1] / 2.0 - lo
        valid = np.ones(gx.shape, bool)
        for p in pos:
            M = Ms[p]
            qx = M[0, 0] * px + M[0, 1] * py + float(ts[p][0])
            qy = M[1, 0] * px + M[1, 1] * py + float(ts[p][1])
            valid &= (qx > lo) & (qx < cmax) & (qy > lo) & (qy < rmax)
        L = np.full(valid.shape[0], -1, int)
        R = np.full(valid.shape[0], -1, int)
        for i in range(valid.shape[0]):
            ix = np.flatnonzero(valid[i])
            if len(ix):
                L[i] = ix[0]
                R[i] = ix[-1]
        best = (0, 0, 0, 0, 0)
        for r0 in range(valid.shape[0]):
            if L[r0] < 0:
                continue
            lmax, rmin = L[r0], R[r0]
            for r1 in range(r0, valid.shape[0]):
                if L[r1] < 0:
                    break
                lmax = max(lmax, L[r1])
                rmin = min(rmin, R[r1])
                if rmin <= lmax:
                    break
                area = (xs[rmin] - xs[lmax]) * (ys[r1] - ys[r0])
                if area > best[0]:
                    best = (area, r0, r1, lmax, rmin)
        if best[0] == 0:
            return (0, H, 0, W)
        _, r0, r1, lmax, rmin = best
        return (int(ys[r0]), int(ys[r1]), int(xs[lmax]), int(xs[rmin]))

    # ---- 输出 ----
    def _flatten_bg(self, rgb):
        """去光害渐变: 逐通道估计大尺度背景并减掉 (保留银河这类中等尺度结构)."""
        from scipy import ndimage
        a = rgb.astype(np.float32)
        h, w, _ = a.shape
        # 1/4 采样
        hs, ws = h // 4 * 4, w // 4 * 4
        small = a[:hs, :ws].reshape(hs // 4, 4, ws // 4, 4, 3).mean(axis=(1, 3))
        # 网格 + sigma 裁剪中值 + 三次插值(比模糊更能保留银河结构)
        chans = []
        for c in range(3):
            chans.append(mesh_background(small[:, :, c], ny=10, nx=14))
        bg = np.stack(chans, axis=2)
        bg = ndimage.zoom(bg, (h / bg.shape[0], w / bg.shape[1], 1), order=1)
        bg = bg[:h, :w]
        out = a - bg
        # 加回一个很小的底, 避免大片纯 0
        floor = float(np.percentile(bg, 10)) * 0.02
        return np.clip(out + floor, 0, None)

    def _prepare_linear(self, rgb):
        """把浮点线性数据转成写盘用的 uint16(含白平衡增益与 pedestal), 不写文件."""
        x = rgb.astype(np.float32)
        if getattr(self.o, "wb_out", False):
            if self._wb is not None and len(self._wb) >= 3 and self._wb[1] > 0:
                g = self._wb[:3] / self._wb[1]
                x = x * g[None, None, :]
        v = x * (65535.0 / 16383.0)
        lo = float(np.percentile(v, 0.01))
        if lo < 0:
            v = v - lo
        return np.clip(v, 0, 65535).astype(np.uint16)

    def _save_tiff(self, rgb, path):
        import tifffile
        x = rgb.astype(np.float32)
        if getattr(self.o, "wb_out", False):
            # 只做相机白平衡增益(不套色彩矩阵, 避免偏色/溢出), 输出仍是线性数据
            if self._wb is not None and len(self._wb) >= 3 and self._wb[1] > 0:
                g = self._wb[:3] / self._wb[1]
                x = x * g[None, None, :]
        v = x * (65535.0 / 16383.0)
        lo = float(np.percentile(v, 0.01))
        if lo < 0:
            # 保留负值对应的暗部信息: 整体抬一个基底, 而不是把负值裁成 0
            v = v - lo
            self.log("已加基底 %.0f (保留暗部/负噪声信息)" % (-lo))
        big = np.clip(v, 0, 65535).astype(np.uint16)
        tifffile.imwrite(path, big, photometric="rgb", compression="zlib")
        return big

    def _apply_type_preset(self, lights):
        """识别出目标后, 按类型覆盖去背景参数。

        视场门控规则:
          · 手动指定目标 -> 直接优化(用户已经明确告诉程序目标是谁)
          · 自动识别     -> 用 EXIF 焦距算视场; 没有 EXIF 就用星场解算结果;
                            视场超出可用星表覆盖范围时不做优化(避免瞎猜)
        """
        o = self.o
        name = getattr(self, "object_name", None)
        if not name or name in ("未知", "未启用识别"):
            self.log("未识别出具体目标, 跳过按类型优化")
            return
        entry = object_entry_by_label(name)
        if entry is None:
            self.log("目标不在内置目录里, 跳过按类型优化")
            return

        manual = bool(getattr(o, "manual_object", None))
        if manual:
            self.log("目标为用户手动指定, 跳过视场检查")
        else:
            fov, src = None, ""
            try:
                fov = exif_fov(lights[0]) if lights else None
                if fov:
                    src = "EXIF"
            except Exception:
                fov = None
            if not fov and self.solve_info:
                fov = float(self.solve_info.get("fov") or 0.0) or None
                src = "星场解算"
            rng = catalog_fov_range()
            if fov:
                inside = fov_in_catalog_range(fov)
                if rng:
                    self.log("视场 %.1f° (%s), 可用星表覆盖 %.1f°~%.1f° -> %s" % (
                        fov, src, rng[0], rng[1], "在范围内" if inside else "超出范围"))
                else:
                    self.log("视场 %.1f° (%s), 但没有可用星表" % (fov, src))
                if inside is False:
                    self.log("视场超出星表范围, 不做按类型优化(可用'手动指定'强制启用)")
                    return
            else:
                self.log("未取到视场信息(EXIF 无焦距且未解算), 照常按类型优化")

        t = str(entry.get("type") or "")
        cat = TYPE_CATEGORY.get(t)
        if not cat:
            self.log("目标类型 %r 没有对应预设, 跳过" % t)
            return
        lvl_now = str(getattr(o, "lp_level", "manual") or "manual").lower()
        for k, v in TYPE_PRESETS.get(cat, {}).items():
            if k == "bg2d_q" and lvl_now == "high":
                continue    # 强光害下以去渐变为先, 不抬高 q
            setattr(o, k, v)
        self.log("按目标类型优化: %s(%s) -> %s" % (
            CATEGORY_NAME.get(cat, cat), entry.get("n"), TYPE_PRESET_TEXT.get(cat, "")))

    def _save_preview(self, rgb, path):
        x = rgb.astype(np.float32)
        if self._wb is not None and len(self._wb) >= 3 and np.all(np.isfinite(self._wb[:3])) and self._wb[1] > 0:
            g = self._wb[:3] / self._wb[1]
            x = x * g[None, None, :]
        # 预览专用的天空扣除 + 拉伸(不写入 TIFF, 仅为了看得见)
        bg = np.array([np.percentile(x[:, :, c], 50.0) for c in range(3)], np.float32)
        x = x - bg[None, None, :]
        lum = x.mean(axis=2)
        hi = float(np.percentile(lum, 99.9)) or 1.0
        y = np.arcsinh(np.clip(x / hi, 0, None) * 30.0) / math.asinh(30.0)
        y = np.clip(y, 0, 1)
        if getattr(self.o, "preview_sat", 1.0) and self.o.preview_sat != 1.0:
            l = y.mean(axis=2, keepdims=True)
            y = np.clip(l + (y - l) * float(self.o.preview_sat), 0, 1)
        _save_jpg(y, path,
                  max_side=min(2200, int(getattr(self.o, "jpg_max", 2600))),
                  quality=min(90, int(getattr(self.o, "jpg_quality", 92))))
        if getattr(self.o, "png_preview", False):
            try:
                png = os.path.splitext(path)[0] + ".png"
                write_png16(png, y)
                self.log("已保存 16bit PNG 预览: %s" % png)
            except Exception as e:
                self.log("PNG 预览保存失败: %r" % (e,))


# --------------------------------------------------------------------------
# 命令行
# --------------------------------------------------------------------------
def run_cli(argv):
    import argparse
    load_lang()
    for _i, _a in enumerate(argv):
        if _a == "--lang" and _i + 1 < len(argv):
            set_lang(argv[_i + 1])
        elif _a.startswith("--lang="):
            set_lang(_a.split("=", 1)[1])
    ap = argparse.ArgumentParser(description=tr("RAW 亮场/暗场/平场 配准堆栈"))
    ap.add_argument("--lang", default=None, choices=["zh", "en"],
                    help=tr("界面语言: zh(中文) / en(English)"))
    ap.add_argument("--lights", default=None)
    ap.add_argument("--darks", default=None)
    ap.add_argument("--flats", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--kappa", type=float, default=3.0)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help=tr("只处理前 N 张亮场(调试用)"))
    ap.add_argument("--no-crop", action="store_true")
    ap.add_argument("--no-identify", action="store_true", help=tr("不做目标识别"))
    ap.add_argument("--object", default=None, help=tr("手动指定目标名称, 例如 M42"))
    ap.add_argument("--identify", default=None, help=tr("单独识别图片/RAW 文件, 不做堆栈"))
    ap.add_argument("--sensor", default=None, help=tr("画幅, 如 APS-C / 全画幅 / M4/3"))
    ap.add_argument("--focal", type=float, default=None, help=tr("焦距 mm"))
    ap.add_argument("--crop", type=float, default=None, help=tr("裁切系数, 覆盖 --sensor"))
    ap.add_argument("--catalog", default="auto", help=tr("星表: auto / 窄视场 / 中等 / 宽视场 / 全部尝试"))
    ap.add_argument("--wb", action="store_true", help=tr("TIFF 输出时应用相机白平衡+色彩矩阵(线性 sRGB)"))
    ap.add_argument("--preview-sat", type=float, default=1.0, help=tr("预览饱和度倍数, 默认 1.0"))
    ap.add_argument("--png", action="store_true", help=tr("额外输出 16bit PNG 彩色预览图"))
    ap.add_argument("--out-kind", default="both", choices=["both", "linear", "stretch"],
                    help=tr("输出内容: both=线性+拉伸(默认) / linear=只线性 / stretch=只拉伸"))
    ap.add_argument("--no-stretch-out", action="store_true",
                    help=tr("等同于 --out-kind linear (兼容旧用法)"))
    ap.add_argument("--stretch-sat", type=float, default=1.18, help=tr("拉伸图饱和度倍数"))
    ap.add_argument("--flatten", action="store_true", help=tr("背景平整(叠加后): 去大尺度渐变"))
    ap.add_argument("--lp", action="store_true", help=tr("逐帧去光污染(适合重度光害/无跟踪)"))
    ap.add_argument("--fast-warp", action="store_true",
                    help=tr("重采样用双线性(更快, 星点略软); 默认三次插值"))
    ap.add_argument("--denoise", default="off",
                    choices=["off", "light", "medium", "strong"],
                    help=tr("小波降噪强度: off/light(0.30)/medium(0.50)/strong(0.70)"))
    ap.add_argument("--denoise-scales", type=int, default=4, help=tr("小波层数(默认 4)"))
    ap.add_argument("--jpg-max", type=int, default=2600, help=tr("JPG 长边像素上限(默认 2600)"))
    ap.add_argument("--jpg-quality", type=int, default=92, help=tr("JPG 质量(默认 92)"))
    ap.add_argument("--star-mode", default="off", choices=["off", "reduce", "remove"],
                    help=tr("叠加后的星点处理: off / reduce(缩星) / remove(去星)"))
    ap.add_argument("--star-strength", type=float, default=0.85, help=tr("星点处理强度 0~1"))
    ap.add_argument("--no-type-opt", action="store_true",
                    help=tr("关闭按目标类型自动优化参数"))
    ap.add_argument("--lp-level", default="manual",
                    choices=["manual", "auto", "low", "mid", "high"],
                    help=tr("光污染傻瓜模式: auto=自动判断 / low / mid / high(覆盖去背景各项参数)"))
    ap.add_argument("--rbf", type=float, nargs="?", const=2.0, default=0.0,
                    help=tr("叠加后 RBF 背景提取(薄板样条), 可给平滑量, 默认 2.0"))
    ap.add_argument("--bg2d", action="store_true", help=tr("网格背景提取(强光害推荐, 无需模型)"))
    ap.add_argument("--bg2d-q", type=float, default=40.0, help=tr("背景地板分位数(默认40; 越小越激进去光害, 越大越保守)"))
    ap.add_argument("--bg-protect", action="store_true", help=tr("网格背景 + 结构保护(保住星云/银河)"))
    ap.add_argument("--bg-poly", type=int, default=0, help=tr("二维多项式曲面去背景(1=平面, 2~4=曲面)"))
    ap.add_argument("--chroma-nr", type=float, default=0.0,
                    help=tr("旧的高斯色度降噪 sigma(0=关, 2~4 常用); 新算法用 --chroma-denoise"))
    ap.add_argument("--chroma-denoise", default="off",
                    choices=["off", "light", "medium", "strong"],
                    help=tr("小波色噪去除: off / light(0.35) / medium(0.55) / strong(0.75)"))
    ap.add_argument("--chroma-scales", type=int, default=3, help=tr("色噪小波层数(默认 3)"))
    ap.add_argument("--stack-mode", default=DEFAULT_STACK_MODE,
                    choices=["auto", "twopass", "onepass", "gpu"],
                    help=tr("叠加方式: auto(有 GPU 用 GPU) / twopass / onepass / gpu"))
    ap.add_argument("--lp-div", action="store_true", help=tr("逐帧去光污染用除法(默认减法)"))
    ap.add_argument("--stretch", default=None, help=tr("自动拉伸线性 TIFF(输入图片路径)"))
    ap.add_argument("--sat", type=float, default=1.18, help=tr("拉伸后饱和度倍数, 默认 1.18"))
    ap.add_argument("--frame", default=None, help=tr("给照片加白色名称边框(输入图片路径)"))
    ap.add_argument("--target", default=None, help=tr("加边框时手动指定的目标名称"))
    ap.add_argument("--border", type=float, default=0.05, help=tr("白边宽度(占短边比例, 默认 0.05)"))
    a = ap.parse_args(argv)


    if a.stretch:
        tif, jpg = stretch_image(a.stretch, a.out, sat=a.sat)
        print("已生成: %s" % tif, flush=True)
        print("已生成: %s" % jpg, flush=True)
        return 0

    if a.frame:
        name = a.target
        if not name:
            res = identify_image_file(a.frame, sensor=a.sensor, focal=a.focal,
                                      crop=a.crop, catalog=a.catalog)
            name = res.get("name") or "未知"
            for line in identify_report(a.frame, res).split("\n"):
                print(line, flush=True)
        out = a.out or (os.path.splitext(a.frame)[0] + "_framed.jpg")
        add_name_border(a.frame, out, obj_display_name(name), a.border)
        print("已生成: %s  (目标: %s)" % (out, short_label(name)), flush=True)
        return 0

    if a.identify:
        try:
            fh = open(os.path.splitext(a.identify)[0] + ".identify.log", "a", encoding="utf-8")
        except Exception:
            fh = None
        def say(m):
            line = "[%s] %s" % (datetime.datetime.now().strftime("%H:%M:%S"), m)
            if fh:
                fh.write(line + "\n"); fh.flush()
            try:
                if sys.stdout is not None:
                    print(line, flush=True)
            except Exception:
                pass
        say("识别: %s" % a.identify)
        res = identify_image_file(a.identify, sensor=a.sensor, focal=a.focal,
                                  crop=a.crop, catalog=a.catalog)
        txt = identify_report(a.identify, res)
        for line in txt.split("\n"):
            say(line)
        saved = save_identify_report(a.identify, res)
        if saved:
            say("结果已写入: %s" % saved)
        if fh:
            fh.close()
        return 0 if res.get("ok") else 2

    if not a.lights:
        print("错误: 需要 --lights 目录, 或用 --identify 单独识别")
        return 1
    o = type("Opts", (), {})()
    o.light_dir, o.dark_dir, o.flat_dir = a.lights, a.darks, a.flats
    o.kappa, o.threads, o.crop = a.kappa, a.threads, (not a.no_crop)
    o.identify = not a.no_identify
    o.manual_object = a.object
    o.out_path = a.out or default_out_path()[0]
    o.preview_sat = a.preview_sat
    o.png_preview = bool(a.png)
    o.out_kind = "linear" if a.no_stretch_out else a.out_kind
    o.stretch_sat = float(a.stretch_sat)
    o.flatten = bool(a.flatten)
    o.lp_remove = bool(a.lp)
    o.lp_level = a.lp_level
    o.type_opt = not bool(a.no_type_opt)
    o.warp_order = 1 if a.fast_warp else 3
    o.denoise = {"off": 0.0, "light": 0.30, "medium": 0.50, "strong": 0.70}.get(a.denoise, 0.0)
    o.denoise_scales = int(a.denoise_scales)
    o.jpg_max = int(a.jpg_max)
    o.jpg_quality = int(a.jpg_quality)
    o.star_mode = a.star_mode
    o.star_strength = float(a.star_strength)
    o.rbf = float(a.rbf or 0.0)
    o.bg2d = bool(a.bg2d)
    o.bg2d_q = float(a.bg2d_q)
    o.bg_protect = bool(a.bg_protect)
    o.bg_poly = int(a.bg_poly)
    o.chroma_nr = float(a.chroma_nr)
    o.chroma_denoise_level = {"off": 0.0, "light": 0.35, "medium": 0.55,
                              "strong": 0.75}.get(a.chroma_denoise, 0.0)
    o.chroma_scales = int(a.chroma_scales)
    o.stack_mode = a.stack_mode
    o.lp_mode = "div" if a.lp_div else "sub"
    o.wb_out = bool(a.wb)

    logfile = os.path.splitext(o.out_path)[0] + ".log"
    fh = open(logfile, "w", encoding="utf-8")

    def say(msg):
        line = "[%s] %s" % (datetime.datetime.now().strftime("%H:%M:%S"), msg)
        fh.write(line + "\n")
        fh.flush()
        try:
            if sys.stdout is not None:
                print(line, flush=True)
        except Exception:
            pass

    p = Pipeline(o, log=say, progress=lambda f, m: None)
    if a.limit:
        orig = Pipeline.list_raw

        def limited(folder, exclude_prefix=()):
            return orig(folder, exclude_prefix)[:a.limit]
        p.list_raw = limited
    try:
        p.run()
    finally:
        if fh:
            fh.close()
    return 0


DENOISE_LABELS = ["关", "轻", "中", "强"]
DENOISE_MAP = {"关": 0.0, "轻": 0.30, "中": 0.50, "强": 0.70}
CHROMA_LABELS = ["关", "轻", "中", "强"]
CHROMA_MAP = {"关": 0.0, "轻": 0.35, "中": 0.55, "强": 0.75}
STAR_MODE_LABELS = ["不处理", "缩星", "去星"]
STAR_MODE_MAP = {"不处理": "off", "缩星": "reduce", "去星": "remove"}

OUT_KIND_LABELS = ["线性 + 拉伸（都生成）", "只生成线性 TIFF", "只生成拉伸 TIFF"]
OUT_KIND_MAP = {"线性 + 拉伸（都生成）": "both",
                "只生成线性 TIFF": "linear",
                "只生成拉伸 TIFF": "stretch"}


# --------------------------------------------------------------------------
# 光污染"傻瓜模式": 低/中/高 三档预设 + 自动判断
# --------------------------------------------------------------------------
LP_LEVEL_LABELS = ["自动判断（推荐）", "低（郊区/暗夜）", "中（城郊）", "高（城市）", "手动设置"]
LP_LEVEL_MAP = {"自动判断（推荐）": "auto", "低（郊区/暗夜）": "low",
                "中（城郊）": "mid", "高（城市）": "high", "手动设置": "manual"}

LP_PRESETS = {
    "low":  dict(lp_remove=False, lp_mode="sub", bg2d=True, bg_protect=True,
                 bg2d_q=40.0, chroma_nr=0.0, chroma_denoise_level=0.0, denoise=0.0, rbf=0.0, bg_poly=0,
                 flatten=False),
    "mid":  dict(lp_remove=False, lp_mode="sub", bg2d=True, bg_protect=True,
                 bg2d_q=35.0, chroma_nr=0.0, chroma_denoise_level=0.35, denoise=0.30, rbf=0.0, bg_poly=0,
                 flatten=False),
    "high": dict(lp_remove=True, lp_mode="sub", bg2d=True, bg_protect=True,
                 bg2d_q=30.0, chroma_nr=0.0, chroma_denoise_level=0.55, denoise=0.45, rbf=0.0, bg_poly=0,
                 flatten=False),
}

LP_PRESET_TEXT = {
    "low": "Background2D 保守(q=40) + 结构保护，不逐帧处理",
    "mid": "Background2D(q=35) + 结构保护 + 小波降噪 0.30 + 小波色噪去除 0.35",
    "high": "逐帧去光污染 + Background2D 激进(q=30) + 结构保护 + 小波降噪 0.45 + 小波色噪去除 0.55",
}


def estimate_lp_level(files, sample=3):
    """采样几帧估计光污染等级。返回 (level, 说明文本)。"""
    if not files:
        return "mid", "无可用帧, 默认中级"
    picks = files[:max(1, int(sample))]
    meds, rels = [], []
    last_grad = 0.0
    for f in picks:
        try:
            a = decode(f)[0].astype(np.float32)
        except Exception:
            continue
        sm = a[::8, ::8]
        med = float(np.median(sm))
        h, w = sm.shape
        Y, X = np.mgrid[0:h, 0:w]
        A = np.c_[X.ravel() / max(w, 1), Y.ravel() / max(h, 1), np.ones(h * w)]
        coef, *_ = np.linalg.lstsq(A, sm.ravel(), rcond=None)
        plane = (A @ coef).reshape(h, w)
        grad = float(plane.max() - plane.min())
        last_grad = grad
        if med > 0:
            meds.append(med)
            rels.append(grad / med)
    if not meds:
        return "mid", "采样失败, 默认中级"
    med = float(np.median(meds))
    rel = float(np.median(rels))
    score = med / 1000.0 + rel
    if score < 0.8:
        lvl = "low"
    elif score < 1.8:
        lvl = "mid"
    else:
        lvl = "high"
    return lvl, "背景中位 %.0f, 平面梯度 %.0f (相对 %.2f), 评分 %.2f" % (med, last_grad, rel, score)


MANUAL_AUTO = "（自动识别）"


def object_choices():
    """GUI 下拉框用的目标列表."""
    objs = load_object_catalogue()
    labels = [MANUAL_AUTO]
    for o in sorted(objs, key=lambda d: d["n"]):
        lab = label_of(o)
        if lab not in labels:
            labels.append(lab)
    return labels


# --------------------------------------------------------------------------
# 图形界面
# --------------------------------------------------------------------------

# 双语：按显示标签查表的映射补上英文键
def _alias_map(m):
    for k, v in list(m.items()):
        ek = EN.get(k)
        if ek and ek not in m:
            m[ek] = v


for _m in (STACK_MODE_MAP, DENOISE_MAP, CHROMA_MAP, STAR_MODE_MAP,
           OUT_KIND_MAP, LP_LEVEL_MAP):
    _alias_map(_m)
SENSORS = SENSORS + [(EN[lab], wh) for lab, wh in list(SENSORS) if lab in EN]
CATALOGS = CATALOGS + [(fn, EN[lab], rng) for fn, lab, rng in list(CATALOGS) if lab in EN]
if CATALOG_AUTO in EN:
    CATALOG_AUTO = EN[CATALOG_AUTO]
if SENSOR_NONE in EN:
    SENSOR_NONE = EN[SENSOR_NONE]


class _I18n(object):
    def __init__(self):
        self.items = []
        self.combos = []

    def bind_text(self, widget, zh):
        self.items.append((widget, zh))

    def bind_combo(self, widget, zh_values):
        self.combos.append((widget, list(zh_values)))

    def apply(self, root):
        for w, zh in self.items:
            try:
                w.configure(text=tr(zh))
            except Exception:
                pass
        for w, vals in self.combos:
            try:
                cur = w.get()
                shown = [tr(v) for v in vals]
                idx = None
                for cand in (cur, tr(cur)):
                    if cand in shown:
                        idx = shown.index(cand)
                        break
                    if cand in vals:
                        idx = vals.index(cand)
                        break
                w.configure(values=shown)
                if idx is not None:
                    w.set(shown[idx])
            except Exception:
                pass
        try:
            root.title(tr("深空堆栈工具  Deep-Sky Stacker"))
        except Exception:
            pass


I18N = _I18n()


def run_gui():
    load_lang()
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, scrolledtext

    root = tk.Tk()
    root.title("深空堆栈工具  Deep-Sky Stacker")
    root.geometry("960x800")
    root.minsize(880, 720)

    # ---- 语言选择（放最上面，切换后即时生效）----
    lang_bar = ttk.Frame(root)
    lang_bar.pack(fill="x", padx=10, pady=(6, 0))
    tk.Label(lang_bar, text="语言 / Language:").pack(side="left")
    lang_var = tk.StringVar(value="English" if LANG == "en" else "中文")
    w_lang = ttk.Combobox(lang_bar, textvariable=lang_var, width=10, state="readonly",
                          values=["中文", "English"])
    w_lang.pack(side="left", padx=(4, 0))

    def _switch_lang(*_):
        set_lang("en" if lang_var.get().startswith("English") else "zh")
        save_lang()
        lang_apply(root)
        root.event_generate("<<LangChanged>>")

    w_lang.bind("<<ComboboxSelected>>", _switch_lang)

    v_light = tk.StringVar()
    v_dark = tk.StringVar()
    v_flat = tk.StringVar()
    v_out = tk.StringVar()
    v_kappa = tk.DoubleVar(value=3.0)
    v_threads = tk.IntVar(value=max(2, min(8, (os.cpu_count() or 4) // 2)))
    v_crop = tk.BooleanVar(value=True)
    v_ident = tk.BooleanVar(value=True)
    v_wb = tk.BooleanVar(value=False)
    v_png = tk.BooleanVar(value=False)
    v_out_kind = tk.StringVar(value="线性 + 拉伸（都生成）")
    v_type_opt = tk.BooleanVar(value=True)
    v_lp_level = tk.StringVar(value="自动判断（推荐）")
    v_star_mode = tk.StringVar(value="不处理")
    v_star_strength = tk.DoubleVar(value=0.85)
    v_fast_warp = tk.BooleanVar(value=False)
    v_lp_mode = tk.StringVar(value="减法")
    v_bg2d_q = tk.DoubleVar(value=40.0)
    v_chroma_mode = tk.StringVar(value="关")
    v_denoise = tk.StringVar(value="关")
    v_poly = tk.IntVar(value=0)
    v_rbf_s = tk.DoubleVar(value=0.0)
    v_flatten = tk.BooleanVar(value=False)
    v_lp = tk.BooleanVar(value=False)
    v_rbf = tk.BooleanVar(value=False)
    v_bg2d = tk.BooleanVar(value=True)
    v_prot = tk.BooleanVar(value=True)
    _gpu_ok = _gpu_available()
    v_stack = tk.StringVar(value=("GPU 加速" if _gpu_ok else "CPU 单遍优化"))

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill="both", expand=True)

    def pick_dir(var):
        d = filedialog.askdirectory(title="选择文件夹")
        if d:
            var.set(d)

    def pick_out():
        f = filedialog.asksaveasfilename(
            title="输出 TIFF", defaultextension=".tif",
            filetypes=[("TIFF 16bit", "*.tif"), ("All files", "*.*")],
            initialfile="stacked_%s.tif" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        if f:
            v_out.set(f)

    def row(label, var, cb, r):
        ttk.Label(frm, text=label, width=11).grid(row=r, column=0, sticky="w", pady=3)
        ttk.Entry(frm, textvariable=var).grid(row=r, column=1, sticky="we", padx=4)
        ttk.Button(frm, text="浏览…", width=7, command=cb).grid(row=r, column=2)

    row("亮场文件夹", v_light, lambda: pick_dir(v_light), 0)
    row("暗场文件夹", v_dark, lambda: pick_dir(v_dark), 1)
    row("平场文件夹", v_flat, lambda: pick_dir(v_flat), 2)
    row("输出文件", v_out, pick_out, 3)

    opt = ttk.LabelFrame(frm, text="选项", padding=8)
    opt.grid(row=4, column=0, columnspan=3, sticky="we", pady=(8, 4))
    ttk.Label(opt, text="σ 剔除倍数").grid(row=0, column=0, sticky="w")
    ttk.Spinbox(opt, from_=1.5, to=6.0, increment=0.5, textvariable=v_kappa, width=6).grid(row=0, column=1, padx=(4, 18))
    ttk.Label(opt, text="线程数").grid(row=0, column=2, sticky="w")
    ttk.Spinbox(opt, from_=1, to=32, textvariable=v_threads, width=6).grid(row=0, column=3, padx=(4, 18))
    # ---- 第 1 行: 叠加方式 ----
    ttk.Label(opt, text="叠加方式").grid(row=1, column=0, sticky="w", pady=(8, 2))
    _stack_box = ttk.Combobox(opt, textvariable=v_stack, width=18, state="readonly",
                              values=STACK_MODE_LABELS if _gpu_ok else
                              [l for l in STACK_MODE_LABELS if "GPU" not in l])
    _stack_box.grid(row=1, column=1, columnspan=2, sticky="w", padx=(4, 8), pady=(8, 2))
    ttk.Label(opt, text=("已检测到可用 GPU" if _gpu_ok else "未检测到 GPU（已禁用 GPU 选项）"),
              foreground=("#2a7" if _gpu_ok else "#a55")).grid(
        row=1, column=3, columnspan=3, sticky="w", pady=(8, 2))

    # ---- 第 2 行: 手动指定目标 ----
    ttk.Label(opt, text="或手动指定").grid(row=2, column=0, sticky="w", pady=2)
    v_obj = tk.StringVar(value=MANUAL_AUTO)
    obj_combo = ttk.Combobox(opt, textvariable=v_obj, values=object_choices(),
                             width=34, state="readonly")
    obj_combo.grid(row=2, column=1, columnspan=5, sticky="we", padx=(4, 0), pady=2)

    # ---- 第 3 行: 输出内容 ----
    ttk.Label(opt, text="输出内容").grid(row=3, column=0, sticky="w", pady=(8, 2))
    ttk.Combobox(opt, textvariable=v_out_kind, width=22, state="readonly",
                 values=OUT_KIND_LABELS).grid(row=3, column=1, columnspan=2,
                                              sticky="w", padx=(4, 0), pady=(8, 2))

    # ---- 第 4 行: 去光污染（傻瓜模式） ----
    ttk.Label(opt, text="去光污染").grid(row=4, column=0, sticky="w", pady=(8, 2))
    lp_box = ttk.Combobox(opt, textvariable=v_lp_level, width=18, state="readonly",
                          values=LP_LEVEL_LABELS)
    lp_box.grid(row=4, column=1, sticky="w", padx=(4, 0), pady=(8, 2))
    lp_hint = ttk.Label(opt, text="自动按素材判断", foreground="#2a7")
    lp_hint.grid(row=4, column=2, columnspan=4, sticky="w", padx=(8, 0), pady=(8, 2))

    # ---- 第 5~7 行: 手动参数(仅"手动设置"时可用) ----
    manual_widgets = []
    ttk.Label(opt, text="逐帧去光污染").grid(row=5, column=0, sticky="w", pady=2)
    w_lp = ttk.Checkbutton(opt, text="开", variable=v_lp)
    w_lp.grid(row=5, column=1, sticky="w", padx=(4, 0), pady=2)
    w_lpmode = ttk.Combobox(opt, textvariable=v_lp_mode, width=9, state="readonly",
                            values=["减法", "除法"])
    w_lpmode.grid(row=5, column=2, sticky="w", padx=(4, 8), pady=2)
    w_bg2d = ttk.Checkbutton(opt, text="Background2D", variable=v_bg2d)
    w_bg2d.grid(row=5, column=3, sticky="w", pady=2)
    ttk.Label(opt, text="q").grid(row=5, column=4, sticky="e")
    w_q = ttk.Spinbox(opt, from_=15, to=70, increment=5, textvariable=v_bg2d_q, width=5)
    w_q.grid(row=5, column=5, sticky="w", padx=(2, 0), pady=2)
    manual_widgets += [w_lp, w_lpmode, w_bg2d, w_q]

    w_prot = ttk.Checkbutton(opt, text="结构保护", variable=v_prot)
    w_prot.grid(row=6, column=0, columnspan=2, sticky="w", pady=2)
    ttk.Label(opt, text="色噪去除").grid(row=6, column=2, sticky="e")
    w_chroma = ttk.Combobox(opt, textvariable=v_chroma_mode, width=5, state="readonly",
                            values=CHROMA_LABELS)
    w_chroma.grid(row=6, column=3, sticky="w", padx=(2, 8), pady=2)
    ttk.Label(opt, text="多项式阶").grid(row=6, column=4, sticky="e")
    w_poly = ttk.Spinbox(opt, from_=0, to=4, textvariable=v_poly, width=5)
    w_poly.grid(row=6, column=5, sticky="w", padx=(2, 0), pady=2)
    manual_widgets += [w_prot, w_chroma, w_poly]

    ttk.Label(opt, text="RBF 平滑").grid(row=7, column=0, sticky="w", pady=2)
    w_rbf = ttk.Spinbox(opt, from_=0, to=10, increment=0.5, textvariable=v_rbf_s, width=5)
    w_rbf.grid(row=7, column=1, sticky="w", padx=(4, 8), pady=2)
    ttk.Label(opt, text="小波降噪").grid(row=7, column=2, sticky="e")
    w_dn = ttk.Combobox(opt, textvariable=v_denoise, width=5, state="readonly",
                        values=DENOISE_LABELS)
    w_dn.grid(row=7, column=3, sticky="w", padx=(2, 8), pady=2)
    ttk.Label(opt, text="（层数 4，只处理亮度）", foreground="#666").grid(
        row=7, column=4, columnspan=2, sticky="w")
    manual_widgets += [w_rbf, w_dn]

    # ---- 第 8 行: 星点处理（堆栈后自动做）----
    ttk.Label(opt, text="星点处理").grid(row=10, column=0, sticky="w", pady=(8, 2))
    ttk.Combobox(opt, textvariable=v_star_mode, width=10, state="readonly",
                 values=STAR_MODE_LABELS).grid(row=10, column=1, sticky="w",
                                               padx=(4, 8), pady=(8, 2))
    ttk.Label(opt, text="强度").grid(row=10, column=2, sticky="e")
    ttk.Spinbox(opt, from_=0.2, to=1.0, increment=0.05, textvariable=v_star_strength,
                width=5).grid(row=10, column=3, sticky="w", padx=(2, 8), pady=(8, 2))
    ttk.Checkbutton(opt, text="快速重采样（双线性，略软·更快）",
                    variable=v_fast_warp).grid(row=10, column=4, columnspan=2,
                                               sticky="w", pady=(8, 2))

    # ---- 第 9~10 行: 其它开关 ----
    ttk.Checkbutton(opt, text="自动裁剪到公共覆盖区域", variable=v_crop).grid(
        row=8, column=0, columnspan=2, sticky="w", pady=(8, 2))
    ttk.Checkbutton(opt, text="自动识别目标", variable=v_ident).grid(
        row=8, column=2, columnspan=2, sticky="w", pady=(8, 2))
    ttk.Checkbutton(opt, text="按目标类型优化", variable=v_type_opt).grid(
        row=13, column=0, columnspan=3, sticky="w", pady=2)
    ttk.Checkbutton(opt, text="TIFF 白平衡版", variable=v_wb).grid(
        row=8, column=4, columnspan=2, sticky="w", pady=(8, 2))
    ttk.Checkbutton(opt, text="额外输出 16bit PNG", variable=v_png).grid(
        row=9, column=0, columnspan=2, sticky="w", pady=2)
    ttk.Checkbutton(opt, text="背景平整(旧算法)", variable=v_flatten).grid(
        row=9, column=2, columnspan=2, sticky="w", pady=2)

    def _lp_level_changed(*_a):
        manual = LP_LEVEL_MAP.get(v_lp_level.get(), "auto") == "manual"
        state = "normal" if manual else "disabled"
        for w in manual_widgets:
            try:
                w.configure(state=state)
            except Exception:
                pass
        if manual:
            lp_hint.configure(text=tr("请手动选择下面各项"), foreground="#a55")
        else:
            lvl = LP_LEVEL_MAP.get(v_lp_level.get(), "auto")
            if lvl == "auto":
                lp_hint.configure(text=tr("自动判断素材光污染，参数由程序定"), foreground="#2a7")
            else:
                lp_hint.configure(text=tr(LP_PRESET_TEXT.get(lvl, "")), foreground="#2a7")
    v_lp_level.trace_add("write", _lp_level_changed)
    _lp_level_changed()

    bar = ttk.Progressbar(frm, mode="determinate", maximum=1000)
    bar.grid(row=5, column=0, columnspan=3, sticky="we", pady=(8, 2))
    status = ttk.Label(frm, text="就绪", anchor="w")
    status.grid(row=6, column=0, columnspan=3, sticky="we")

    logbox = scrolledtext.ScrolledText(frm, height=15, state="disabled", wrap="word")
    logbox.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=(6, 0))
    frm.rowconfigure(7, weight=1)
    frm.columnconfigure(1, weight=1)

    btns = ttk.Frame(frm)
    btns.grid(row=8, column=0, columnspan=3, sticky="we", pady=(8, 0))
    btn_start = ttk.Button(btns, text="开始堆栈")
    btn_start.pack(side="left")
    btn_cancel = ttk.Button(btns, text="取消", state="disabled")
    btn_cancel.pack(side="left", padx=8)
    btn_ident = ttk.Button(btns, text="单独识别星空…")
    btn_ident.pack(side="left", padx=(24, 0))
    btn_frame = ttk.Button(btns, text="加白边成品…")
    btn_frame.pack(side="left", padx=(8, 0))
    btn_stretch = ttk.Button(btns, text="自动拉伸…")
    btn_stretch.pack(side="left", padx=(8, 0))
    ident_info = ttk.Label(btns, text="", foreground="#0060a0")
    ident_info.pack(side="left", padx=10)

    q = queue.Queue()
    cancel = threading.Event()

    def log(msg):
        q.put(("log", msg))

    def prog(frac, msg=""):
        q.put(("prog", (frac, msg)))

    def drain():
        try:
            while True:
                kind, payload = q.get_nowait()
                if kind == "log":
                    logbox.configure(state="normal")
                    logbox.insert("end", payload + "\n")
                    logbox.see("end")
                    logbox.configure(state="disabled")
                elif kind == "prog":
                    frac, msg = payload
                    bar.configure(value=int(frac * 1000))
                    if msg:
                        status.configure(text="%s   (%.0f%%)" % (msg, frac * 100))
                elif kind == "ident":
                    messagebox.showinfo("识别结果", payload)
                elif kind == "done":
                    btn_start.configure(state="normal")
                    btn_cancel.configure(state="disabled")
                    status.configure(text=tr("完成"))
                    bar.configure(value=1000)
                    messagebox.showinfo("完成", payload)
                elif kind == "fail":
                    btn_start.configure(state="normal")
                    btn_cancel.configure(state="disabled")
                    status.configure(text=tr("已停止"))
                    messagebox.showerror("出错", payload)
        except queue.Empty:
            pass
        root.after(120, drain)

    def start():
        try:
            _start_impl()
        except Exception as e:
            import traceback
            messagebox.showerror("无法开始堆栈", "%r\n\n%s" % (e, traceback.format_exc()[-1500:]))

    def _start_impl():
        if not v_light.get().strip():
            messagebox.showwarning("提示", "请先选择亮场文件夹")
            return
        out = v_out.get().strip() or None
        o = type("Opts", (), {})()
        o.light_dir = v_light.get().strip()
        o.dark_dir = v_dark.get().strip() or None
        o.flat_dir = v_flat.get().strip() or None
        o.out_path = out
        o.wb_out = bool(v_wb.get())
        o.png_preview = bool(v_png.get())
        o.out_kind = OUT_KIND_MAP.get(v_out_kind.get(), "both")
        o.flatten = bool(v_flatten.get())
        o.type_opt = bool(v_type_opt.get())
        o.star_mode = STAR_MODE_MAP.get(v_star_mode.get(), "off")
        o.star_strength = float(v_star_strength.get())
        o.warp_order = 1 if v_fast_warp.get() else 3
        o.lp_level = LP_LEVEL_MAP.get(v_lp_level.get(), "auto")
        o.lp_remove = bool(v_lp.get())
        o.lp_mode = "div" if v_lp_mode.get() == "除法" else "sub"
        o.bg2d_q = float(v_bg2d_q.get())
        o.chroma_nr = 0.0
        o.chroma_denoise_level = CHROMA_MAP.get(v_chroma_mode.get(), 0.0)
        o.denoise = DENOISE_MAP.get(v_denoise.get(), 0.0)
        o.bg_poly = int(v_poly.get())
        o.rbf = float(v_rbf_s.get())
        o.rbf = 2.0 if v_rbf.get() else 0.0
        o.bg2d = bool(v_bg2d.get())
        o.bg_protect = bool(v_prot.get())
        o.preview_sat = 1.0
        o.kappa = float(v_kappa.get())
        o.threads = int(v_threads.get())
        o.stack_mode = STACK_MODE_MAP.get(v_stack.get(), "onepass")
        o.crop = bool(v_crop.get())
        o.identify = bool(v_ident.get())
        sel = v_obj.get()
        o.manual_object = None if (not sel or sel == MANUAL_AUTO) else sel

        cancel.clear()
        btn_start.configure(state="disabled")
        btn_cancel.configure(state="normal")
        logbox.configure(state="normal")
        logbox.delete("1.0", "end")
        logbox.configure(state="disabled")
        bar.configure(value=0)
        status.configure(text=tr("准备中…"))

        def job():
            try:
                pp = Pipeline(o, log=log, progress=prog, cancel=cancel)
                pp.run()
                q.put(("done", "堆栈完成\n\n识别目标: %s\n\n输出:\n%s" % (
                    pp.object_name or "未知", pp.o.out_path)))
            except Cancelled:
                q.put(("fail", "已取消"))
            except Exception as e:
                q.put(("fail", "%s\n\n%s" % (e, traceback.format_exc()[-1200:])))

        threading.Thread(target=job, daemon=True).start()

    def ident_worker(path, opts=None):
        try:
            btn_ident.configure(state="disabled")
            ident_info.configure(text=tr("识别中…"))
            log("[识别] 正在处理: %s" % path)
            if opts:
                log("[识别] 画幅=%s 焦距=%s 星表=%s" % (opts.get("sensor") or "未填",
                                                     opts.get("focal") or "未填",
                                                     opts.get("catalog")))
            res = identify_image_file(path, **(opts or {}))
            txt = identify_report(path, res)
            saved = save_identify_report(path, res)
            for line in txt.split("\n"):
                log("[识别] " + line)
            if saved:
                log("[识别] 结果已写入: %s" % saved)
            ident_info.configure(text=tr("识别结果: %s") % (res.get("name") or "未知"))
            q.put(("ident", txt + ("\n\n已保存:\n%s" % saved if saved else "")))
        except Exception as e:
            q.put(("fail", "识别失败: %r" % (e,)))
        finally:
            btn_ident.configure(state="normal")

    def ident_start():
        opts = ask_identify_options(root)
        if opts is None:
            return
        path = filedialog.askopenfilename(
            title="选择要识别的图片或 RAW 文件",
            filetypes=[("RAW 或图像", "*.arw *.ARW *.srf *.SRF *.dng *.DNG *.cr2 *.CR2 *.nef *.NEF *.tif *.tiff *.TIF *.png *.PNG *.jpg *.JPG"),
                       ("所有文件", "*.*")])
        if not path:
            return
        threading.Thread(target=ident_worker, args=(path, opts), daemon=True).start()

    btn_ident.configure(command=ident_start)

    def frame_worker(opts):
        try:
            btn_frame.configure(state="disabled")
            path = opts["path"]
            log("[加边框] 处理: %s" % path)
            if opts["auto"]:
                res = identify_image_file(path)
                name = res.get("name") or "未知"
                log("[加边框] 自动识别: %s" % name)
            else:
                name = opts["target"] or "未知"
                log("[加边框] 手动指定: %s" % name)
            out = add_name_border(path, None, obj_display_name(name), opts["border"])
            log("[加边框] 已保存: %s" % out)
            q.put(("ident", "已生成带名称白边的成品\n\n目标: %s\n输出: %s" % (short_label(name), out)))
        except Exception as e:
            q.put(("fail", "加边框失败: %r" % (e,)))
        finally:
            btn_frame.configure(state="normal")

    def frame_start():
        opts = ask_frame_options(root)
        if not opts:
            return
        threading.Thread(target=frame_worker, args=(opts,), daemon=True).start()

    btn_frame.configure(command=frame_start)

    def stretch_worker(path):
        try:
            btn_stretch.configure(state="disabled")
            log("[拉伸] 处理: %s" % path)
            tif, jpg = stretch_image(path)
            log("[拉伸] 已保存: %s" % tif)
            log("[拉伸] 已保存: %s" % jpg)
            q.put(("ident", "拉伸完成\n\nTIFF: %s\nJPG: %s" % (tif, jpg)))
        except Exception as e:
            q.put(("fail", "拉伸失败: %r" % (e,)))
        finally:
            btn_stretch.configure(state="normal")

    def stretch_start():
        path = filedialog.askopenfilename(
            title="选择要拉伸的线性 TIFF",
            filetypes=[("TIFF", "*.tif *.tiff *.TIF *.TIFF"), ("所有文件", "*.*")])
        if not path:
            return
        threading.Thread(target=stretch_worker, args=(path,), daemon=True).start()

    btn_stretch.configure(command=stretch_start)

    btn_start.configure(command=start)
    btn_cancel.configure(command=lambda: (cancel.set(), status.configure(text=tr("正在取消…"))))

    def _on_lang_changed(_e=None):
        try:
            _lp_level_changed()
        except Exception:
            pass
        try:
            status.configure(text=tr("就绪"))
        except Exception:
            pass

    root.bind("<<LangChanged>>", _on_lang_changed)
    lang_bind(root)
    lang_apply(root)
    lang_var.set("English" if LANG == "en" else "中文")

    root.after(120, drain)
    root.mainloop()


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass
        for _s in (sys.stdout, sys.stderr):
            try:
                if _s is not None:
                    _s.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    if "--selftest" in sys.argv:
        # 自检: 构建界面但不进入事件循环
        import tkinter as tk
        orig = tk.Tk.mainloop

        def fake(self, *a, **k):
            self.update_idletasks()
            self.update()
            self.after(200, self.destroy)
            orig(self)

        tk.Tk.mainloop = fake
        run_gui()
        print("GUI selftest OK")
        sys.exit(0)
    if any(x in sys.argv for x in ("--cli", "--identify", "--frame", "--target",
                                 "--stretch", "--help", "-h")):
        sys.exit(run_cli([a for a in sys.argv[1:] if a != "--cli"]))
    run_gui()
