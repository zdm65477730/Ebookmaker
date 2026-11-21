# Ebookmaker

自动爬取小说站点正文与书籍信息，净化页面广告/乱码/干扰内容，按章节目录排版生成 EPUB，并转换为 Kindle 支持的 MOBI / AZW3 格式。

v2.0 重构为模块化 Python 包 `ebookmaker`，设计上参考了
[FictionDown](https://github.com/ma6254/FictionDown)（断点续爬/广告过滤/多线程）、
[espc](https://github.com/kiddinick/espc)（站点规则配置化）、
[novel-downloader](https://gitcode.com/gh_mirrors/no/novel-downloader)（站点适配器注册表）与
[trafilatura](https://github.com/adbar/trafilatura)（通用正文抽取兜底）等开源项目。

## 架构

```
爬取 URL ──► 站点适配层 sites/ ──► 净化管线 cleaner.py ──► 工作区 store（books/<书名>/，JSON）
                                                              │
                          builders/epub.py ◄── 跨章节广告行二次过滤（junk_lines.json）
                                     │
                          builders/convert.py ──► .epub / .mobi / .azw3
```

- **爬虫与制书解耦**：章节先净化落盘为 JSON 工作区，EPUB/MOBI/AZW3 完全由本地数据生成；支持断点续爬、失败补爬、离线重新制书
- **sites/ 自动适配**：未命中已有规则时自动采样章节学习站点结构（[auto.py](ebookmaker/auto.py)），生成描述符落盘工程根 `sites/<host>.yaml` 并在后续爬取中直接复用；未学习成功时走 `generic` 启发式（og meta + 链接密度目录 + trafilatura/正文密度）。同时自动处理三类真实站点难题：**目录混入跨站镜像链接**（同域过滤）、**目录分页**（`xxx_5/` 兄弟页逐页展开合并全部章节，`<a>` 与 `<select>` 页码条都识别）、**章节分页拼接**。不再内置手写站点适配器，如需人工兜底可手写 YAML 描述符（见“站点适配”一节）
- **加密字体自动解密**：首章探测 PUA 码位占比，命中则自动下载 @font-face 字体、按 glyph 命名还原字符映射（需 fonttools，woff2 加 brotli），解密表沉淀进工作区供离线重建复用；无法解密时保留原码位且不触发无效补爬
- **章节分页自动拼接**：自动识别 `xxx_2.html` / `xxx/2/` 等同系列分页并合并，带重复守护，不会误拼下一章内容
- **cleaner**：全部为内建通用逻辑，**不存在任何净化规则文件**：零宽字符/符号水印/拼音乱码清除、内置广告行黑名单、引号排版内建规则、跨章节高频广告行统计剔除、正文重复标题剔除、章节质量检查（过短/乱码率自动标记补爬）
- **反爬（AIMD 自适应）**：现代 UA 池轮换 + 浏览器请求头指纹、Referer/Cookie 注入、域名级令牌桶限速 + 随机抖动、指数退避重试、连接被重置时重建 TCP/TLS 会话并禁用 keep-alive；核心是拥塞控制式自适应速率：命中 429/403/验证页自动减半速率并尊重站点 Retry-After（首次仅短冷却，屡犯递增），连续成功逐步回升至上限——无需手动调参即可自动找到各站安全速度；代理池（免费列表源/API/本地文件，连通性校验 + 成功率评分 + 失效拉黑补充）
- **多线程与实时进度**：固定 `ThreadPoolExecutor` 线程池（不再是每章一线程），失败队列多轮降速补爬；TTY 下单行实时进度条（百分比/速率/ETA），重定向或非交互终端自动退回定期日志

## 环境准备

```bash
sudo apt install python3 python3-pip
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com  # requests/beautifulsoup4/lxml/PyYAML/charset-normalizer
pip install trafilatura -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com          # 可选：通用站点正文抽取兜底
pip install fonttools brotli -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com      # 可选：加密字体站点自动解密
# azw3/部分 mobi 转换需要 calibre（推荐）：
sudo -v && wget -nv -O- https://download.calibre-ebook.com/linux-installer.sh | sudo sh /dev/stdin
```

`tools/` 目录内置三平台 kindlegen 二进制，作为无 calibre 环境的回退方案（Amazon 已停止维护，仅能产出 MOBI；AZW3 请安装 calibre）。

## 使用

一步端到端（输入书籍网址 → 直接产出最终电子书）：

```bash
python3 -m ebookmaker https://www.xbiquge.la/66/66747/
```

等价于 `run --url <URL>`：自动完成 适配/学习站点 → 多线程爬取 → 净化 → 断点续跑与补爬 → EPUB（封面+扉页+目录+章节）→ MOBI/AZW3。

单步命令（均保留，可单独执行）：

```bash
# 仅爬取+净化落盘（中断后重复执行即续跑）
python3 -m ebookmaker crawl --url <目录页URL> --threads 16

# 仅从本地工作区重新制书（不联网；调整净化规则后反复验证）
python3 -m ebookmaker build books/武神主宰 --formats epub,mobi,azw3

# 仅格式转换
python3 -m ebookmaker convert books/武神主宰.epub --formats mobi,azw3

# 清理输出目录
python3 -m ebookmaker clean                      # 清所有缓存（工作区），保留成品书
python3 -m ebookmaker clean --all                # 全删：缓存+成品书+books/ 目录本身
python3 -m ebookmaker clean --dry-run            # 预演：只展示将删什么
```

清理规则（就两档）：**裸 `clean` 清缓存留成品**——删除 workdir 内全部书籍工作区目录及杂项文件，保留成品书 `.epub/.mobi/.azw3`；**`clean --all` 全删**——连成品书一起清空，workdir 也移除（下次出书自动重建）。指定 targets 只处理对应工作区。`run`/`build` 的 `--clean` 与 `cleanup.auto` 等效裸 clean（针对该书工作区）。工程根 `sites/` 学习规则不在 workdir 内，不受清理影响。

常用参数：`--site 适配器名`、`--cookie`、`--proxy-source none|list|api|file`、`--proxy-api/--proxy-file`、`--rules-dir`（额外规则目录，可多次）、`--force`（忽略缓存全部重爬）、`-c config.yaml`。

全局默认值在 [config.yaml](config.yaml) 中配置（线程数、限速、代理、净化阈值、转换器路径等），命令行参数优先。

## 站点适配（全自动）

**无需任何接入操作**：直接 `python3 -m ebookmaker <目录页URL>`，系统自动学习站点结构并在工程根 `sites/` 沉淀规则，第二次起直接复用。若学习失败（JS 渲染、字体加密等站点）会退回通用启发式抽取并给出提示。

仅当学习结果不准时，可手写 YAML 站点描述符人工兜底（放任意目录配合 `--rules-dir`，同名描述符优先于自动学习产物）。描述符只描述页面结构，**不携带任何清洗规则**：

```yaml
name: mysite
type: site
hosts: [www.mysite.com]
toc:
  selector: "dl dd a"          # 或 regex: '<dd><a href="([^"]+)">(.*?)</a></dd>'
content:
  selector: "#chapter-body"    # 或 regex: '<div id="chapter-body">([\s\S]*?)</div>'
```

内容净化（去广告/乱码/干扰文本/排版修复）全部内置在 [cleaner.py](ebookmaker/cleaner.py)，按通用特征与跨章节统计算法工作，无需也不支持任何规则文件。

## 输出

```
books/
├── <书名>/                 # 工作区：meta.json / toc.json / cover.jpg / chapters/*.json
├── <书名>.epub
├── <书名>.mobi             # kindlegen 或 calibre 产出
└── <书名>.azw3             # calibre 产出
```

EPUB 符合 EPUB 3 规范（兼带 NCX 目录兼容旧 Kindle），成品必含**封面页、扉页、目录页、全部章节**：站点封面缺失时自动使用内置默认封面。内嵌排版样式：章前分页、段首两字符缩进、双目录（NCX + EPUB3 nav）。

## 测试

```bash
pip install pytest
python3 -m pytest tests/ -q
```

测试全部离线运行：`tests/fixtures/raw/` 为各站点页面结构夹具，`tests/fixtures/legacy_output/` 为 v1 真实产物（用于验证净化不会误伤正文）。

## 法律提示

本项目仅用于个人备份已获授权阅读的内容与技术学习，请勿爬取、传播盗版或用于商业用途。
