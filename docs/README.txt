深空堆栈工具 使用说明
================================

目录
----
<安装目录>\
├─ DeepSkyStacker.exe        图形界面版
├─ DeepSkyStacker_CLI.exe    命令行版
├─ gpu_runtime\              GPU 加速所需的 CuPy + CUDA 运行库（2.7 GB，可删）
├─ dsso_database.npz         星表（目标识别用）
├─ objects.json              深空天体目录（278 个 Messier/NGC/IC）
└─ src\astro_stack_gui.py    源码

叠加方式
--------
一个程序内置三种叠加方式，界面里选，命令行也能指定（--stack-mode）。

  界面位置：选项区 → "叠加方式" 下拉框
      · 两遍叠加(twopass)  第一遍统计均值/σ，第二遍按 κσ 剔除；最慢、最保守
      · 单遍叠加(onepass)  边累加边在线剔除，省一遍解码+重采样；比两遍快约 1.5 倍
      · GPU 加速(gpu)      单遍 + 显卡做重采样/累加；比两遍快 2~4 倍
  默认值：检测到 gpu_runtime\ 时自动选 "GPU 加速"，否则 "CPU 单遍优化"。

  命令行：
      --stack-mode auto       自动（有 GPU 就用 GPU）—— 默认
      --stack-mode gpu        GPU 加速
      --stack-mode onepass    CPU 单遍优化
      --stack-mode twopass    两遍叠加

  三种叠加方式的成像质量实测等价（星点面积、星点数、噪声在误差内一致），
  差别只在速度和极微小的高频平滑。

实测速度（同参数、6 线程）
--------------------------
                      ISO400 500 帧          猎户座 1050 帧
  两遍叠加            886 s                  1773 s
  单遍叠加            602 s（1.47x）          1263 s（1.40x）
  GPU 加速            435 s（2.04x）           780 s（2.27x）
  其中叠加段加速：ISO400 2.55x，猎户座 4.27x

GPU 说明
--------
gpu_runtime\ 里放的是 CuPy 和 CUDA 运行库，约 2.7 GB。这些是 NVIDIA 的专有库，
不随程序再分发，需要自己准备：

  1. pip install cupy-cuda12x
  2. 把 cupy 安装目录下的 .pyd / .dll 与 CUDA 的 cudart64_*.dll、nvrtc64_*.dll
     拷进 gpu_runtime\，目录结构照搬 site-packages
  3. 启动程序，叠加方式里出现"GPU 加速"就说明认到了

显存建议 8 GB 以上（24 MP 的图像每帧要占几百 MB）。显存不够会自动退回 CPU 叠加，
日志里能看到原因。程序放在含中文的路径下时，CUDA 的运行时编译可能失败，
**建议放在全英文路径**。

输出目录
--------
默认写在程序目录下的 output\。文件名用堆栈开始时刻，形如 261117_0330.tif，重名自动加 _2、_3。

同时生成：
    261117_0330.tif                线性 16bit，未拉伸
    261117_0330_stretched.tif      已拉伸的 16bit（可选）
    261117_0330_stretched.jpg      拉伸后的 JPG（长边 2600 px）
    261117_0330_preview.jpg        预览图
    261117_0330_preview.png        16bit PNG 预览（可选）
    261117_0330_object.txt         识别结果（认出目标时）
    261117_0330.log                完整日志

用 --out 指定路径时，以上文件都跟着 --out 的名字走。

启动方式
--------
  图形界面：双击 DeepSkyStacker.exe

  命令行：
      DeepSkyStacker_CLI.exe --cli --lights "D:\photos\light" ^
          --darks "D:\photos\dark" --flats "D:\photos\flat" --out out.tif

  只拉伸一张已堆好的 TIFF：
      DeepSkyStacker_CLI.exe --cli --stretch in.tif

  全部参数：
      DeepSkyStacker_CLI.exe --help

常见错误
--------
1) 提示"亮场文件夹中找不到 RAW 文件"
   检查扩展名是否被识别（ARW / CR2 / NEF / DNG / TIFF），以及文件名里是否含
   dark / flat / bias（被当成校准帧排除了）。

2) GPU 叠加失败，回退 CPU
   多数是路径含中文，或 gpu_runtime\ 不完整。日志里有具体原因。

3) 成片一边死黑
   旧版本把负值裁成 0。现版本自动加基底，用最新版重新堆一次即可。
