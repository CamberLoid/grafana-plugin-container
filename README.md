# Grafana Plugin Container

将根目录一个或多个 `xxx.list` 定义的指定 Grafana 插件打包成 Busybox 容器，并发布到 GHCR 或以 `tar.gz` 形式发布到 Releases。纯 Github Actions 实现。

产出一个或多个容器镜像。插件放置在镜像内的 `/opt/plugins` 路径下。

默认交付 `linux-amd64`。

## 使用方法

1. 将本仓库设为 **Template repository**，使用 **Use this template** 创建自己的仓库。
2. 复制或修改根目录的 `example.list`，例如命名为 `production.list`；不需要示例镜像时可删除 `example.list`。
3. 将改动提交到默认分支。Actions 会发布对应列表的镜像，也可以通过 **Actions → Build plugin bundles → Run workflow** 手动重建全部列表。

如果无需 GHCR 发布，则在根目录下创建一个空的 `.no-ghcr`；如果无需 Release 发布，则在根目录下创建一个空的 `.no-release`

暂不支持修改交付架构功能。

## 产物

- 容器镜像：`<list-name>:YYYY-MM-DD`、`<list-name>:YYYY-MM-DD-<hash>`；发布在 GHCR 或 GHE Cloud Packages
- 容器镜像 Tarball：`<list-name>-YYYY-MM-DD.tar.gz`、`<list-name>-YYYY-MM-DD-<hash>.tar.gz`；发布在 Release `YYYY-MM-DD-<hash>` 下

日期使用 UTC，`<hash>` 为构建源码提交 SHA 的前 7 位。完整镜像名为 `<registry>/<owner>/<repo>/<list-name>:<tag>`；GitHub.com 使用 `ghcr.io`，GHE Cloud 数据驻留实例及 GHES 使用 `containers.<实例域名>`。

## 列表格式

- 以 `#` 开头的注释
- Grafana 插件ID：`grafana-github-datasource` 或 `grafana-github-datasource 2.9.4`
- Grafana 插件地址：`https://grafana.com/grafana/plugins/grafana-github-datasource/`
- Grafana 插件 ZIP / TAR（含 `.tar.gz`）地址，以 HTTP(S) Schema 提供

可查阅 example.list

插件 ID 和页面地址优先获取 `linux-amd64` 包；

## 备注

### 空列表行为

如果列表解析为空，则会在 `/opt/plugins` 下生成一个 `.empty-plugins` 文件

### CI/CD 行为

- 默认分支提交只重建变更的根目录列表；修改 Dockerfile、脚本、workflow 或增删发布开关时重建全部列表；手动触发也重建全部。删除列表不删除历史产物。
- 默认同时发布 GHCR 与 Release；
- 所有选中列表先完成本地构建，再发布。Release 只包含本次选中的列表；需要完整交付时手动运行。GHCR 推送失败仍会尝试发布已构建的 Release 归档，工作流保持失败状态。
- Release 首次创建为草稿，附件全部上传成功后再发布；失败后可重跑，重用同名 Release 并覆盖同名附件。
- GHE Cloud 默认使用托管 runner，GHES 默认使用 Linux self-hosted runner；可用仓库变量 `RUNNER_LABELS`（JSON 数组）覆盖。Runner 需有 Git、Python 3、curl、Docker、gzip，以及启用 Release 时所需的 `gh`，并能访问插件来源及 BusyBox 镜像源。发布使用当前实例的 `GITHUB_TOKEN`；GHES 需已启用 Container Registry（仅发布 Release 时不需要）。

### tests

完全由 LLM 生成，未经审阅。

## Disclaimer

本仓库使用 OpenAI Codex 生成，并经过维护者审阅。
