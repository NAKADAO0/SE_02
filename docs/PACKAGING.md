# 源码交付包

要求 Python 3.11+。打包和离线测试只使用标准库，无须联网或提供 API 密钥。

## 构建和校验（PowerShell）

在项目根目录运行：

```powershell
python scripts/build_release.py
Get-Content dist/SE_02-source.zip.sha256
(Get-FileHash dist/SE_02-source.zip -Algorithm SHA256).Hash.ToLower()
```

默认生成 `dist/SE_02-source.zip` 和 `dist/SE_02-source.zip.sha256`。两条哈希必须相同。可以使用 `--project-root PATH --output PATH` 指定输入项目和明确的输出文件；相对输出路径以当前工作目录为基准。重建覆盖这两个明确文件，不递归删除目录。未改变输入文件、Python/zlib 环境时，连续构建 ZIP 字节相同；跨压缩库版本不承诺压缩字节一致。

ZIP 内路径直接从源码根目录开始。`MANIFEST.json` 记录项目版本、清单格式版本和每个文件的字节大小及 SHA256，不含时间、机器路径或身份信息；manifest 本身由外部 ZIP SHA256 覆盖。文件按路径排序、固定 ZIP 时间与权限。未压缩总量及最终 ZIP 均必须小于 200 MiB。

## 白名单和敏感文件

根目录只接纳 `README.md`、`Design.md`、`pyproject.toml`、`.gitignore` 和存在时的 `config.example.toml`；脚本仅接纳 `scripts/build_release.py`。目录 `src/`、`tests/`、`examples/`、`docs/`、`release/` 仅接纳 `.py`、`.md`、`.toml`、`.json`、`.txt`，未知扩展和未知顶层文件不会进入包。`release/` 可放脱敏验收证据。

任意层的 `.env` 变体、private、runs、缓存、虚拟环境、Git 元数据、构建产物及凭据命名文件排除；旧 ZIP 不在扩展白名单中。指向根目录外的符号链接或 junction 会令构建失败，内部链接跳过。脚本检测常见 API key、AWS key 和私钥内容，发现后中止而不打印密钥。模式检测不能辨别任意字符串是否为真实凭据，交付前仍须确认白名单文件只有示例配置和脱敏证据，真实密钥仅通过运行环境提供。

## 解压与完全离线验收

使用尚不存在的目标目录，避免混入旧文件：

```powershell
Expand-Archive dist/SE_02-source.zip -DestinationPath ./delivery-check
Set-Location ./delivery-check
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -m unittest discover -s tests -v
python -m se02 --help
python examples/workflow_demo.py --scenario direct_pass
```

`PYTHONPATH` 方式无需安装、构建工具或网络。若需要虚拟环境的 editable 安装，先准备本地 wheelhouse，包含 pip、setuptools>=68 和 wheel 的兼容 wheel；然后：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-index --find-links ../wheelhouse "setuptools>=68" wheel
.\.venv\Scripts\python.exe -m pip install --no-index --no-build-isolation --no-deps -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

源码包不携带第三方 wheel、虚拟环境、私密 runs 或真实服务密钥；仅包含 release 下人工检查过的公开任务运行证据。Mock 验收无需外部服务；HTTP 模式需另行配置环境凭据。

最终交付另存于 `deliverables/SE_02-source.zip` 及 `.sha256` 并随 Git 发布，重建命令为 `python scripts/build_release.py --output deliverables/SE_02-source.zip`；该目录不在打包白名单内，因此不会把旧 ZIP 再放进新 ZIP。

2026-10-23 文档更新：额外允许 docs/screenshots 下的 PNG，使 README 运行截图在解压后仍可查看。其他目录的图片仍不进入白名单。新回归测试覆盖此限制。
