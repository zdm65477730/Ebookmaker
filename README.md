# Ebookmaker

  <p align="center"><img src="https://raw.githubusercontent.com/WerWolv/EdiZon-Rewrite/master/icon.jpg"><br />
      <a href="https://github.com/zdm65477730/Ebookmaker/releases/latest"><img src="https://img.shields.io/github/downloads/WerWolv/EdiZon-Rewrite/total.svg" alt="Latest Release" /></a>
  </p>

自动爬取小说，并整合成一个txt文件，最后转换成Kindle可用的电子书格式。

## 如何编译

  1. 使用 `git clone https://github.com/zdm65477730/Ebookmaker` 将Ebookmaker存储库克隆到您的计算机。
  2. 下载kaf-cli可执行文件，与kindlegen放置到book.py同目录下。
  3. 直接命令行python3 book.py编译即可。

## 用法

  由于目前只支持xbooktxt网站的内容抓取，只要是这个网站的小说，修改book.py里__init__函数里：
    self.book_url = 'https://www.xbooktxt.net/2_2588/'
  为您自己的小说目录页地址即可。
