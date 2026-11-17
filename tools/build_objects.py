# Copyright (c) 2026 MRZH
# SPDX-License-Identifier: MIT
#
# 本文件是「深空堆栈工具」的一部分，按 MIT 许可发布，详见仓库根目录 LICENSE。
"""从 OpenNGC 生成 data/objects.json（278 个热门深空天体 + 中文名）。

用法:
    # 1. 先下载 OpenNGC 的 NGC.csv
    #    https://github.com/mattiaverga/OpenNGC/blob/master/database_files/NGC.csv
    #    存成 data/_ngc.csv（或设 OPENNGC_CSV 环境变量指向它）
    # 2. 运行
    python tools/build_objects.py

许可: OpenNGC 为 CC BY-SA 4.0，生成的 objects.json 同样以 CC BY-SA 4.0 提供。
"""

import csv
import json
import os


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.environ.get("OPENNGC_CSV", os.path.join(ROOT, "data", "_ngc.csv"))
OUT = os.path.join(ROOT, "data", "objects.json")

# 中文名(常用) —— Messier 与人气 NGC/IC 天体
ZH = {
    "M1": "蟹状星云", "M2": "球状星团", "M3": "球状星团", "M4": "球状星团", "M5": "球状星团",
    "M6": "蝴蝶星团", "M7": "托勒密星团", "M8": "礁湖星云", "M9": "球状星团", "M10": "球状星团",
    "M11": "野鸭星团", "M12": "球状星团", "M13": "武仙座大球状星团", "M14": "球状星团", "M15": "球状星团",
    "M16": "鹰状星云", "M17": "Ω星云", "M18": "疏散星团", "M19": "球状星团", "M20": "三叶星云",
    "M21": "疏散星团", "M22": "球状星团", "M23": "疏散星团", "M24": "人马座星云", "M25": "疏散星团",
    "M26": "疏散星团", "M27": "哑铃星云", "M28": "球状星团", "M29": "疏散星团", "M30": "球状星团",
    "M31": "仙女座大星系", "M32": "仙女座伴星系", "M33": "三角座星系", "M34": "疏散星团", "M35": "疏散星团",
    "M36": "疏散星团", "M37": "疏散星团", "M38": "疏散星团", "M39": "疏散星团", "M40": "双星",
    "M41": "疏散星团", "M42": "猎户座大星云", "M43": "猎户座星云(M42的一部分)", "M44": "蜂巢星团",
    "M45": "昴星团(七姐妹星团)", "M46": "疏散星团", "M47": "疏散星团", "M48": "疏散星团", "M49": "椭圆星系",
    "M50": "疏散星团", "M51": "涡状星系", "M52": "疏散星团", "M53": "球状星团", "M54": "球状星团",
    "M55": "球状星团", "M56": "球状星团", "M57": "环状星云", "M58": "棒旋星系", "M59": "椭圆星系",
    "M60": "椭圆星系", "M61": "旋涡星系", "M62": "球状星团", "M63": "向日葵星系", "M64": "黑眼星系",
    "M65": "狮子座旋涡星系", "M66": "狮子座旋涡星系", "M67": "疏散星团", "M68": "球状星团", "M69": "球状星团",
    "M70": "球状星团", "M71": "球状星团", "M72": "球状星团", "M73": "星群", "M74": "旋涡星系",
    "M75": "球状星团", "M76": "小哑铃星云", "M77": "旋涡星系", "M78": "反射星云", "M79": "球状星团",
    "M80": "球状星团", "M81": "波德星系", "M82": "雪茄星系", "M83": "南风车星系", "M84": "椭圆星系",
    "M85": "椭圆星系", "M86": "椭圆星系", "M87": "室女座A星系", "M88": "旋涡星系", "M89": "椭圆星系",
    "M90": "旋涡星系", "M91": "棒旋星系", "M92": "球状星团", "M93": "疏散星团", "M94": "旋涡星系",
    "M95": "棒旋星系", "M96": "旋涡星系", "M97": "猫头鹰星云", "M98": "旋涡星系", "M99": "旋涡星系",
    "M100": "旋涡星系", "M101": "风车星系", "M102": "透镜星系", "M103": "疏散星团", "M104": "草帽星系",
    "M105": "椭圆星系", "M106": "旋涡星系", "M107": "球状星团", "M108": "棒旋星系", "M109": "棒旋星系",
    "M110": "仙女座伴星系",
    "NGC7000": "北美洲星云", "NGC6960": "面纱星云(西)", "NGC6992": "面纱星云(东)", "NGC2024": "火焰星云",
    "IC434": "马头星云", "IC1396": "象鼻星云", "NGC869": "英仙座双星团", "NGC884": "英仙座双星团",
    "NGC2237": "玫瑰星云", "NGC2264": "圣诞树星团/锥状星云", "NGC281": "吃豆人星云", "NGC6888": "新月星云",
    "NGC7635": "气泡星云", "NGC891": "侧向旋涡星系", "NGC4565": "针状星系", "NGC6543": "猫眼星云",
    "NGC7293": "螺旋星云", "NGC253": "玉夫座星系", "NGC5128": "半人马座A", "NGC5139": "半人马座ω球状星团",
    "NGC1976": "猎户座大星云", "NGC1977": "奔跑者星云", "NGC2174": "猴头星云", "NGC2359": "雷神头盔",
    "NGC3372": "船底座大星云", "NGC6334": "猫爪星云", "NGC6357": "龙虾星云", "NGC1499": "加州星云",
    "IC5070": "鹈鹕星云", "IC1805": "心脏星云", "IC1848": "灵魂星云", "IC405": "火焰星星云",
    "IC410": "蝌蚪星云", "IC5146": "茧星云", "Sh2-155": "洞穴星云",
}


def parse_ra(s):
    h, m, sec = s.split(":")
    return (float(h) + float(m) / 60 + float(sec) / 3600) * 15.0


def parse_dec(s):
    sign = -1 if s.strip().startswith("-") else 1
    s = s.strip().lstrip("+-")
    d, m, sec = s.split(":")
    return sign * (float(d) + float(m) / 60 + float(sec) / 3600)


def fnum(x):
    try:
        return float(x)
    except Exception:
        return None


rows = []
if not os.path.isfile(SRC):
    raise SystemExit(
        "找不到 OpenNGC 的 NGC.csv：%s\n"
        "请先下载 https://github.com/mattiaverga/OpenNGC/blob/master/database_files/NGC.csv\n"
        "放到 data/_ngc.csv，或用环境变量 OPENNGC_CSV 指定路径。" % SRC)
with open(SRC, newline="", encoding="utf-8") as f:
    rd = csv.DictReader(f, delimiter=";")
    for r in rd:
        name = r["Name"]
        messier = (r.get("M") or "").strip()
        common = (r.get("Common names") or "").strip()
        maj = fnum(r.get("MajAx"))
        vmag = fnum(r.get("V-Mag"))
        typ = (r.get("Type") or "").strip()
        keep = bool(messier) or bool(common) or (maj is not None and maj >= 15 and (vmag is None or vmag <= 11))
        if not keep:
            continue
        try:
            ra = parse_ra(r["RA"])
            dec = parse_dec(r["Dec"])
        except Exception:
            continue
        ids = []
        if messier:
            ids.append("M%d" % int(messier))
        ids.append(name)
        extra = (r.get("Identifiers") or "").strip()
        if extra:
            for t in extra.split(","):
                t = t.strip()
                if t.startswith(("NGC", "IC", "Sh2")):
                    ids.append(t)
        label = ids[0]
        zh = ""
        for cand in ids:
            key = cand.replace(" ", "")
            if key in ZH:
                zh = ZH[key]
                break
        mag = fnum(r.get("V-Mag"))
        if mag is None:
            mag = fnum(r.get("B-Mag"))
        rows.append(dict(
            n=label,
            mag=(round(mag, 2) if mag is not None else None),
            ids=ids[:4],
            zh=zh,
            en=common,
            ra=round(ra, 4),
            dec=round(dec, 4),
            size=round(maj or 0.0, 2),
            type=typ,
        ))

rows.sort(key=lambda d: (-(d["size"] or 0)))
json.dump(rows, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print("objects:", len(rows), "size KB:", os.path.getsize(OUT) // 1024)
for d in rows[:5]:
    print(" ", d)
m42 = [d for d in rows if "M42" in d["ids"] or d["n"] == "M42"]
print("M42 entry:", m42)
