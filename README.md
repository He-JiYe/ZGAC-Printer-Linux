# ZGCA Linux 打印驱动

**为学院师生提供 PDF 与浏览器刷卡打印支持, 非官方项目。** · **v1.0.1** · [MIT](LICENCE)

## 项目简介

连接学院现有打印服务，使用自己的账号提交任务，然后到打印机刷卡取件。支持：

- 客户端手动添加 PDF；
- 浏览器按 Ctrl+P 选择打印队列。

## 安装方法

### 普通用户

1. 在 [Releases](https://github.com/He-JiYe/ZGAC-Printer-Linux/releases) 下载 `zgcaprint_1.0.1_all.deb`。

2. 在下载目录执行以下命令，系统会自动安装依赖：

   ```sh
   sudo apt install ./zgcaprint_1.0.1_all.deb
   ```

3. 从应用菜单打开 **ZGCA Linux 打印驱动**，保持连接校园内网，等待首次配置完成。

> [!TIP]
> 无需手动下载 Mac 驱动，也无需逐项安装 Python 依赖。
> 首次运行自动从学校下载、校验并读取配置，不执行原厂程序。

- **安装时**：需要访问 Ubuntu 软件源，以自动安装依赖。

- **首次打开时**：需要连接校园内网，完成配置后进入登录界面。

- **以后使用**：保留已有配置与本机缓存；未知的官方新版本不会自动覆盖配置。

<details>
<summary><strong>开发者：源码安装、测试与构建</strong></summary>

#### 环境要求

- **运行环境**：Python 3.10+、CUPS 2.x、Tk。
- **桌面集成**：GI/libsecret、Ayatana 托盘、pkexec、xdg-utils。
- **协议兼容**：libgcrypt。

源码位于 `src/zgcaprint/`，按职责划分模块。首次配置与普通安装包相同。

#### 1. 源码安装与启动

在项目目录执行：

```sh
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m zgcaprint gui --allow-http
```

#### 2. 回归测试

运行常规测试：

```sh
.venv/bin/python -m pytest -q
```

安装 `xvfb` 后，可在独立虚拟屏幕中运行含界面检查的完整测试：

```sh
xvfb-run -a env ZGCAPRINT_TEST_UI=1 .venv/bin/python -m pytest -q
```

测试使用合成数据和模拟服务，不访问校园打印服务。

#### 3. 构建发布包

```sh
.venv/bin/python tools/build_release.py
.venv/bin/python tools/build_deb.py
```

产物位于 `dist/`：前者生成白名单源码 ZIP，后者生成 `.deb` 安装包。

GitHub 工作流会先运行回归测试；尚无对应 Release 的新版本会自动构建发布，已有版本不会覆盖。

#### 可选：PyInstaller 目录版

```sh
.venv/bin/python -m pip install '.[build]'
.venv/bin/python tools/build_binary.py
```

运行时保留程序与 `_internal` 在同一目录。此方式仍依赖系统桌面组件，并受构建系统的 glibc 版本限制。

</details>

## 使用方法

1. **登录**：点击齿轮设置，输入自己的打印账号。

2. **打印 PDF**：添加文件，设置参数，点击“提交任务”并确认。

3. **浏览器打印**：设置中点击“更新打印机”，完成系统授权；按 Ctrl+P 选择 **ZGCAxZGCIprinter**，设置份数、颜色及单双面。

4. **取件**：在学校网页核对任务，再到打印机刷卡取件。

| 设置 | 作用 |
| --- | --- |
| 记住密码 | 将密码保存在系统钥匙串 |
| 自动登录 | 打开客户端后自动使用已保存密码登录 |
| 自动启动 | 登录 Ubuntu 桌面后自动运行客户端 |
| 自动提交任务 | 自动提交当前运行中新收到的浏览器任务 |

- 手动添加和启动前积压的任务，仍需手动确认。

- 关闭窗口后继续常驻；右键菜单提供 **打开 / 设置 / 注销 / 退出**。

- 注销会结束当前登录；需要删除已保存密码时，取消选中“记住密码”。

本地已提交任务会默认保留 **24 小时**，可在设置中调整；不与网页同步。

提交成功后删除客户端 PDF 副本，保留原始文件；未完成任务不会被定时清理。

### 测试打印

附带 [两页 A4 测试 PDF](examples/print-test.pdf)，不含个人信息：

- **首次测试**：第 1 页、1 份、黑白、单面。网页核对后，检查出纸是否乱码、缺页或裁切。

- **双面测试**：打印两页，选择长边翻转；第 2 页箭头应朝上。

- **尺寸与颜色**：100% 缩放时标尺约为 100 mm；彩色测试按学校对应规则计费。

安装后的测试文件位于 `/usr/share/doc/zgcaprint/examples/print-test.pdf`。

## 卸载方法

1. 在客户端设置中关闭“自动启动”，取消选中“记住密码”，然后从右键菜单选择“退出”。仅“注销”不会删除已保存密码。

2. 确认没有未完成的本机打印任务后，在 Ubuntu 系统打印设置中删除 **ZGCAxZGCIprinter** 队列。

3. 卸载程序：

   ```sh
   sudo apt remove zgcaprint
   ```

4. 清理本工具创建的个人启动项和应用菜单快捷方式：

   ```sh
   rm -f \
     "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/org.zgcaprint.Client.desktop" \
     "${XDG_DATA_HOME:-$HOME/.local/share}/applications/org.zgcaprint.Client.desktop"
   ```

卸载不会撤销学校服务器已接受的任务，也不会自动删除本地配置与记录。默认数据目录为 `~/.local/share/zgcaprint`，旧开发环境可能使用项目内的 `.local`；需要删除时，请先核对或备份未完成的 PDF。

<details>
<summary>可选：清理独立安装的打印后端</summary>

“更新打印机”生成的 CUPS 后端不由 `apt` 管理。删除队列后，可请管理员确认以下路径属于本工具，再清理：

- `/usr/lib/cups/backend/zgcaprint`
- `/usr/local/lib/zgcaprint-cups`
- `/etc/zgcaprint-cups.json`

系统暂存目录 `/var/spool/zgcaprint/你的UID` 也可能保留未完成的 PDF，请先核对；不要删除其他用户的目录。

</details>

## 注意事项

- **适配范围**：固定适配 Mac 5.1.3.12 配置，已在 Ubuntu 26.04.1 x86_64 验证。安装包使用系统 Python，避免冻结程序的 glibc 限制；Ubuntu 22.04 / 24.04 及其他架构尚未完成整机测试。20.04 默认环境不满足要求。

- **打印限制**：A3/A4/A5/Letter/Legal，1–99 份，黑白或彩色，单面或双面；每个 PDF 不超过 100 MiB、2000 页。不支持加密 PDF、混合纸张和装订。

- **使用规范**：仅使用本人有权使用的账号和校园服务，遵守学校认证、计费与刷卡规则。队列不共享；客户端使用普通用户运行，仅安装和更新打印机需要管理员授权。

- **网络与隐私**：学校当前使用 HTTP / FTP 明文传输，仅在可信校园网络使用。本项目无个人中转或统计服务。不要公开私有数据目录、配置、密码或生成的 CUPS 安装包。

- **异常处理**：状态不明确时先核对网页，避免重复提交；“已提交”仅是本地回执，不代表当前仍待打印。“仅回执”任务没有本地 PDF，无法预览。

- **许可与维护**：原创代码采用 [MIT](LICENCE)，不涵盖原厂文件或学校接入授权。公开安装包不捆绑原厂安装包或认证配置；开源和免费不能保证免责。官方提供可用 Linux 驱动后建议迁移；收到学校或权利人的下架要求时，会配合核实并停止自己控制渠道的分发。

## 欢迎提 Issue

欢迎在 [Issues](https://github.com/He-JiYe/ZGAC-Printer-Linux/issues) 反馈问题、适配结果或改进建议。

建议提供：

- Ubuntu 版本、客户端版本与安装方式；
- 复现步骤、预期结果和实际结果；
- 脱敏后的错误信息或截图。

**请勿上传账号密码、Cookie、个人配置或真实打印文档。**

**有问题可以联系邮箱**：[s-wmw26@bza.edu.cn](mailto:s-wmw26@bza.edu.cn)
