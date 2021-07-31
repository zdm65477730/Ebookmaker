# Ebookmaker

  <p align="center"><img src="https://raw.githubusercontent.com/WerWolv/EdiZon-Rewrite/master/icon.jpg"><br />
      <a href="https://github.com/zdm65477730/Ebookmaker/releases/latest"><img src="https://img.shields.io/github/downloads/WerWolv/EdiZon-Rewrite/total.svg" alt="Latest Release" /></a>
  </p>

自动爬取小说，并生成ePub格式，最后转换成Kindle可用的电子书格式。

## 如何编译运行

  1. 使用 `git clone https://github.com/zdm65477730/Ebookmaker` 将Ebookmaker存储库克隆到您的计算机。
  2. 修改configs目录下的setting.json来配置爬取的页面和书籍相关信息。
  3. 进入Ebookmaker目录执行：<pre><code>python3 book.py</code></pre>

## 用法

  json配置文件里已经支持xbooktxt网站的内容抓取，其他网站，需要自行添加爬取的正则。
  如果要爬取xbooktxt网站里其他小说，仅需要修改json配置文件里以下项：
  <pre><code>self.book_url = 'https://www.xbooktxt.net/2_2588/'</code></pre>
  为您自己的小说目录页地址即可。
