# Ebookmaker

  <p align="center"><img src="https://raw.githubusercontent.com/WerWolv/EdiZon-Rewrite/master/icon.jpg"><br />
      <a href="https://github.com/zdm65477730/Ebookmaker/releases/latest"><img src="https://img.shields.io/github/downloads/WerWolv/EdiZon-Rewrite/total.svg" alt="Latest Release" /></a>
  </p>

自动爬取小说，并生成ePub格式，最后转换成Kindle可用的电子书格式。

## 如何使用

  1. 将Ebookmaker存储库克隆到您的计算机。<pre><code>git clone https://github.com/zdm65477730/Ebookmaker</code></pre>
  2. 修改configs目录下的`setting.json`来配置爬取的页面和书籍相关信息。
  3. 进入Ebookmaker目录执行：<pre><code>python3 book.py</code></pre>

## setting.json详细说明

  json配置文件里已经支持xbooktxt和xbiquge网站的内容抓取，其他网站，需要自行添加爬取的正则。
  如果要爬取小说，需要配置settings.json配置文件，以下为示例说明：
  <pre><code>
  {
    "book_publisher": "Ebookmaker，书籍发行商",
    "book_rights": "Created by Ebookmaker v1.0，书籍版权信息",
    "book_language": "zh-CN，书籍语言",
    "ebooks_labrary_path": "ebooks，制作书籍的临时存储目录",
    "book_url": "https://www.xbiquge.la/66/66747/，书籍目录页",
    "book_host": "www.xbiquge.la，书籍网站主页",
    "book_referer": "https://www.xbiquge.la/66/66747/26547971.html，从哪个页面链接过来",
    "book_cookie": "请求的cookie信息，可以为空",
    "book_chapter_file_suffic": ".html，存储的章节后缀名",
    "book_fetch_retry_count": 10, /*书籍章节爬取失败重试次数，也用于代理IP获取重试*/
    "book_fetch_delay": 5, /*书籍章节爬取失败重试间隔*/
    "book_fetch_max_thread_num": 10,  /*书籍章节爬取最大线程数，如果为0，则自动根据设置为筛选的代码IP数*/
    "book_name_re": "书籍名称正则",
    "book_author_re": "书籍作者正则",
    "book_description_re": "书籍描述正则",
    "book_subject_re": "书籍类别正则",
    "book_date_re": "书籍时间正则",
    "book_cover_url_re": "书籍封面正则",
    "book_chapter_list_re": "书籍章节名正则",
    "book_chapter_content_re": "书籍章节正文正则",
    "daili_url_base": "代理IP提供页地址",
    "daili_host": "代理IP提供网址",
    "daili_cookie": "获取代理IP使用的cookie",
    "daili_re": "获取代理IP的正则",
    "daili_web_num": 20,  /*代理IP获取最大页面数*/
    "proxy_pool_url": "验证代理IP的主页",
    "proxy_pool_host": "验证代理IP的主页",
    "tools_base_path": "kindlegen等工具的目录",
    "kindlegen_linux": "kindlegen Liunux版本名称",
    "kindlegen_mac": "kindlegen MAC版本名称",
    "kindlegen_win": "kindlegen Windows版本名称",
    "kindlegen_book_compression_level": "kindlegen压缩机别，例如：1"
  }
  </code></pre>
