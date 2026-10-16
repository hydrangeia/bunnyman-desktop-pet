# DST 兔人桌宠

让《饥荒联机版》的兔人住在桌面一角。它会认得轻点、喂食、拖动和靠近，也会自己活动或打个短盹；没有文字气泡，平时看它的动作就好。

**解压 → 启动 → 放在桌面一角 → 轻点、喂食或拖动 → 看兔人回应**

## 下载与启动

下载 [Windows x64 完整包 v0.1.1](https://github.com/hydrangeia/bunnyman-desktop-pet/releases/latest/download/BunnymanDesktopPet-windows-x64.zip)，解压整个文件夹，再运行 `BunnymanDesktopPet.exe`。它不需要另装 Python；请保留 ZIP 解压后的 `_internal` 文件夹和 `manifest.json`、图片资源目录。

如果你已经安装了完整的 v0.1.0，可以下载 [v0.1.0 → v0.1.1 更新包](https://github.com/hydrangeia/bunnyman-desktop-pet/releases/download/v0.1.1/BunnymanDesktopPet-v0.1.0-to-v0.1.1-update.zip)。先退出兔人，把更新包解压到已有的 `BunnymanDesktopPet` 程序文件夹，确认覆盖同名文件后再启动。更新包只适用于完整的 v0.1.0；更早或不完整的安装请使用完整包。更新包不会删除程序目录里的其他文件。历史版本见 [GitHub Releases](https://github.com/hydrangeia/bunnyman-desktop-pet/releases)。

桌宠默认是睡帽兔人，会贴近屏幕底部，脚底按身体实际轮廓落地。它是透明无边框的小窗，保持在普通窗口上方；可吸附到屏幕、任务栏和普通窗口的边缘，并随窗口移动。右键菜单里可以喂食、切换陪伴节奏和自动活动、开关吸附、调整外观和大小，或退出。

## 和兔人互动

- 轻点不同部位、双击会触发不一样的互动，继续玩能发现更多小惊喜。
- 按 `F` 或用右键菜单喂胡萝卜。兔人会实际吃胡萝卜；喂食有冷却，兔人忙着做动作时会等当前流程结束再吃。
- 按住左键拖动兔人，松开会回应放下；停在兔人身上一会儿，它也会注意到你。
- 滚轮能触发冰冻和解冻互动。
- 右键菜单可以关闭自动活动，或切换为“安静陪伴”。默认“活泼亲人”会在待机时偶尔做小动作；无人互动一阵子后会短暂打盹。手动选择睡觉后需要手动叫醒。
- 睡觉会先躺下，离开睡眠时会醒来；钻地会再钻出来，跳跃会完整落地。走路和跑步目前只播放动画，不会带着桌宠移动。

想自己挑动作或朝向，可以打开右键菜单里的“开发预览”，那里有完整动作和原始片段。大多数时候不用打开它。

<details>
<summary>想看隐藏互动提示</summary>

两秒内轻点四次会触发受击火花；向下滚轮三格会冻结四秒再碎冰解冻，向上滚轮可提前解冻。拖动时来回甩动再松手会触发特别回应。双击会从跳舞开始，继续探索可以遇到跳跃、枕头互动和钻地。自动活动只在待机时触发，不会打断动作、拖动或打开的菜单。

</details>

## 用 OBS 或直播姬单独采集

在桌宠右键菜单勾选“直播采集窗口”，会打开一个普通 Windows 窗口，标题为“兔人桌宠 · 直播采集”。它始终使用固定 620×616 画布显示与主桌宠同步的动作和特效，不受主桌宠大小或屏幕位置影响。右键采集窗，或使用主菜单里的“采集背景”，可以在绿、蓝、品红之间切换；选一种不会和场景内容混在一起的颜色，再在直播软件里用色度键抠除。采集窗可以放到其他窗口后面，但要保持打开且不要最小化；最小化可能让捕获画面停住或变黑。

### OBS

1. 打开采集窗，在 OBS 场景的来源中添加“窗口捕获”，选择“兔人桌宠 · 直播采集”。如果带入了标题栏，选择仅捕获客户区，或在来源中裁掉边框。
2. 打开该来源的滤镜，添加 Chroma Key（色度键）并选择与采集窗相同的颜色。调节相似度、平滑度和溢色抑制，让背景消失，同时保留兔人边缘。

### 哔哩哔哩直播姬

1. 在场景中添加窗口捕获来源，选择“兔人桌宠 · 直播采集”。
2. 如果当前版本提供色度抠图或绿幕效果，给这个来源选择与采集窗相同的颜色，再检查预览。如果没有合适的滤镜，可以在 OBS 中完成抠色和场景合成，再由 OBS 推流到 B 站。

已通过 Windows 原生窗口枚举和客户端捕获检查，OBS、直播姬中的完整采集和抠色仍待实机试用。可参考 [OBS 窗口捕获说明](https://obsproject.com/kb/window-capture-sources)、[OBS Chroma Key 滤镜说明](https://obsproject.com/kb/chroma-key-filter) 和 [B站官方开播指南](https://live.bilibili.com/blackboard/era/u4EPvXpDYUMv7hYJ.html)。

## 从源码构建

仓库包含桌宠代码和构建脚本，不包含游戏衍生图片、渲染帧或本机 `manifest.json`。如果你已有匹配的 v2 清单和帧图，可以跳过导出。`build_release.py` 只复制清单明确引用的 PNG/WebP 帧、道具和特效图片，并会从发布副本移除本机游戏目录和绝对路径；它不会打包游戏动画 ZIP。便携包还会保留 Qt/Python 和其他运行依赖的第三方许可证文本。

在 Windows x64、Python 3.13 环境中运行：

```powershell
py -3.13 -m venv .build-venv
.\.build-venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.build-venv\Scripts\python.exe export_pet.py --game "C:\Program Files (x86)\Steam\steamapps\common\Don't Starve Together"
.\.build-venv\Scripts\python.exe -m pytest -q
.\.build-venv\Scripts\python.exe build_release.py --dry-run
.\.build-venv\Scripts\python.exe build_release.py
```

构建结果写入 `dist\BunnymanDesktopPet` 和 `dist\BunnymanDesktopPet-windows-x64.zip`。解压后可以用下面的命令检查资源和动作流程；窗口版会把结果写进 JSON 文件，不依赖控制台：

```powershell
.\dist\BunnymanDesktopPet\BunnymanDesktopPet.exe --smoke-test --test-report .\smoke-report.json
```

## 许可与素材

这是免费、非商业的同人桌面应用，与 Klei Entertainment 无关，也未获其背书。兔人角色、游戏图像、动画帧和其他《饥荒联机版》素材归 Klei 所有。仓库中的 MIT 许可只适用于本项目编写的代码，不授予游戏素材的许可。请阅读 [Klei 玩家创作指南](https://support.klei.com/hc/en-us/articles/360029880791-Player-Creation-Guidelines) 和 [第三方声明](THIRD_PARTY_NOTICES.md)。
