# 安全策略（Security Policy）

## 支持的版本

| 版本 | 是否接受安全修复 |
|---|---|
| 最新 Release / main | ✅ |
| 更早的版本 | ❌（请先升级） |

## 报告漏洞

**请不要在公开 Issue 里贴漏洞细节。**

请通过 GitHub 的 [私密漏洞报告](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability)
（仓库 → Security → Report a vulnerability）提交，或直接联系维护者。

请尽量提供：

- 受影响的版本、操作系统
- 复现步骤或最小输入（能触发问题的 RAW/TIFF 可只描述特征）
- 影响范围（崩溃 / 内存越界 / 任意代码执行 / 信息泄露 …）

## 处理流程

1. 48 小时内确认收到
2. 评估后给出修复计划与预计时间
3. 修复发布后，在 Release Notes 中致谢（除非你要求匿名）

## 本项目的主要攻击面

| 面 | 说明 |
|---|---|
| RAW 解析 | 走 LibRaw（`raw_r.dll`），恶意构造的 RAW 可能导致崩溃；请保持 libraw 为最新 |
| TIFF / PNG 读取 | `tifffile` / Pillow，处理他人提供的文件时注意版本 |
| 星表文件 | `*.npz` 用 `np.load`，恶意 pickle 可执行代码——本项目的 npz 均为 `allow_pickle=False` 的纯数组 |
| 命令行参数 | 仅接受路径与数值；路径会做存在性检查 |
| 打包产物 | PyInstaller onefile 会在临时目录解压，注意目标目录权限 |

## 不在范围内

- 因用户素材本身损坏导致的崩溃（请附样例，我们尽量做成友好报错）
- 第三方依赖自身的漏洞（请向其上游报告；我们会尽快跟进升级）
