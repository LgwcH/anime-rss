# 打包与发布

AniRSS 使用 PyInstaller 生成桌面目录包。`AniRSS.spec` 会收集应用资源和许可证；只有构建脚本
显式设置 BT 构建标志时才会收集 `libtorrent`，不会因为当前虚拟环境碰巧装过它而改变产物。
spec 还会排除程序未使用的 Qt PDF、QML、Quick 和 Virtual Keyboard 模块；发布检查必须确认这些
文件没有重新进入产物。构建脚本会把快速开始、发布说明、项目许可证、第三方声明及许可证目录
复制到 `AniRSS.exe` 同级，便于收件人直接查阅；运行时资源中也保留一份。

## 独立启动器

PyInstaller 的分析入口是 `scripts/anirss_launcher.py`，而不是把包内的 `app.py` 或 `__main__.py`
当成独立脚本执行。这个极小启动器只从已收集的 `anirss` 包导入 `anirss.app.main`，从而在冻结
产物中保留源码运行时相同的包上下文和相对导入语义。`AniRSS.spec` 同时把 `src/` 加入分析路径，
并显式保留 `anirss.app`；这不增加第二套启动逻辑，命令行解析和单实例保护仍由正式应用入口负责。

## 本地构建

在项目根目录建立干净的 Python 3.11+ 虚拟环境，然后运行：

```powershell
python -m pip install -e ".[packaging]"
.\scripts\build.ps1 -Clean
```

需要内嵌 BT 引擎时使用：

```powershell
.\scripts\build.ps1 -Clean -WithTorrent
```

上述命令只生成未签名的本地开发包，不得直接作为正式 Windows 发行版。正式构建必须在安装了
Windows SDK Signing Tools 的受控环境中使用可信 Authenticode 证书：

```powershell
.\scripts\build.ps1 -Clean -WithTorrent -RequireSignature `
  -SigningCertificateThumbprint $env:ANIRSS_SIGNING_CERT_THUMBPRINT
```

脚本会使用 SHA-256 和时间戳服务签名 `AniRSS.exe`，随后再次验证签名；缺少证书、`signtool.exe`
或有效签名时，`-RequireSignature` 构建会失败。不要通过关闭 Defender、改壳、混淆或添加全局排除
项来绕过检测。若 Defender 将干净构建误判为恶意软件，应先停止分发，并通过微软 Security
Intelligence 样本提交入口以“Software developer”身份请求复核。

Linux/macOS 使用 `./scripts/build.sh --clean [--with-torrent]`。脚本只构建当前操作系统和 CPU 架构
的产物，不支持交叉打包。输出目录为 `dist/AniRSS/`；macOS 还会生成应用包结构。

`-WithTorrent`/`--with-torrent` 会安装可选依赖并向 spec 传入显式标志。某些 Python/平台组合
没有预编译 wheel，此时构建应失败并显示原因，而不是悄悄发布缺少 BT 的“完整”安装包。未传
该选项时，即使环境中已经安装 `libtorrent`，也会明确排除它。

## 发布检查表

1. 从带签名标签的干净提交构建，确认工作区没有真实订阅、数据库、日志或媒体。
2. 分别在目标 Windows、macOS 和 Linux 环境构建；不要复制其他系统的 libtorrent 动态库。
3. 在未安装 Python 的干净用户环境中验证启动、HTTP 下载、暂停/恢复、路径清理和卸载。
4. 验证重复启动同一数据目录时第二个进程退出，而使用不同 `--data-dir` 时可以独立运行。
5. 用本地可控 HTTP 服务验证断点恢复仅接受起点和长度均匹配的 `Content-Range`。
6. BT 版本额外验证模块实际加载、磁力元数据、完成后停止、端口与上传限速。
7. 检查浅色/深色、高 DPI、托盘、通知和当前用户级自启动；应用不得请求管理员权限。
8. 收集 Qt、libtorrent、Python 以及其他随包分发组件的许可证和必要声明。
9. Windows 正式包必须通过 Authenticode 验证，再对最终归档生成 SHA-256 校验值；不能以哈希值
   代替发布者签名或杀毒复核。
10. 发布说明列出是否包含 BT、支持的平台/架构、已知限制和 `CHANGELOG.md` 对应版本。

## 资源与图标

仓库提供原创的 `resources/icons/anirss.ico` 与 `anirss.png`，Windows 构建会把 ICO 写入 EXE。
macOS 尚未提供 `anirss.icns`，因此正式发布 macOS 包前应补齐对应资源。替换图标前需确认原创或
许可兼容，并把来源与许可证记录在 `resources/licenses/`。

## 可复现性与供应链

`pyproject.toml` 使用兼容版本范围，便于用户安装安全更新；正式 Release 构建应另外记录解析后的
完整依赖版本、Python 版本和构建系统镜像。不要把开发者机器上的随机 DLL 或未注明来源的 wheel
复制进包。发布自动化应固定受信任源、缓存哈希并输出软件物料清单（SBOM）。

PyInstaller 只是打包工具，不会改变第三方组件的许可。特别是 Qt/PySide6 的部署需满足其适用
许可条款；发布者应根据实际链接模块和发布方式自行核对，而不能只依赖本说明。
