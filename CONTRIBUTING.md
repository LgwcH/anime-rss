# 参与 AniRSS

感谢你愿意改进 AniRSS。无论是错误报告、界面建议、文档修订还是代码贡献都很受欢迎。
参与前请先阅读本文件以及 [安全政策](SECURITY.md)。

## 行为与合规边界

- 保持友善、具体且尊重他人。
- 只使用你有权访问的 RSS 源和下载内容。请勿在 issue、测试、文档或示例中提交盗版源、
  未授权种子、密钥、Cookie 或个人订阅地址。
- 不接受绕过 DRM、访问控制、付费墙或平台限制的功能。
- 示例数据应使用 `example.invalid`、自建测试服务，或明确许可公开再分发的内容。

## 建立开发环境

需要 Python 3.11 或更高版本。建议为项目建立独立虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

Linux/macOS 激活命令为 `source .venv/bin/activate`。如果需要测试 BT 引擎，并且当前平台有
兼容的 libtorrent Python 绑定，可另行运行 `python -m pip install -e ".[torrent]"`。

## 本地检查

提交前请运行：

```text
ruff check .
ruff format --check .
pytest
mypy
```

仅修改文档时可以省略与代码无关的检查，但请确认所有相对链接仍然有效。界面改动应在至少
一个支持的平台上手工验证常见窗口尺寸、浅色/深色主题和高 DPI 缩放。

## 提交与拉取请求

1. 为一个清晰的问题创建短分支，避免混入无关格式化或重构。
2. 为行为变化添加或更新测试，并同步用户文档与 `CHANGELOG.md` 的 `Unreleased` 部分。
3. 提交信息使用简短祈使句，例如 `fix: prevent duplicate RSS downloads`。
4. 拉取请求中说明动机、用户可见变化、验证方法和可能风险；界面变化请附截图。
5. 不要提交本地数据库、真实订阅 URL、下载记录、日志或媒体文件。

维护者可能要求拆分范围过大的变更。合并前需通过自动检查并解决所有评审意见。

## 报告问题

错误报告应包含：AniRSS 版本、操作系统、Python 版本、复现步骤、预期/实际结果，以及移除
URL、Token、Cookie、路径用户名和内容标题后的日志。涉及漏洞时不要创建公开 issue，请按照
[SECURITY.md](SECURITY.md) 私下报告。
