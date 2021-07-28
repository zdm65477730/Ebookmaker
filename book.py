#!/usr/bin/python3
# -*- coding:utf-8 -*-

import re
import os
import time
import random
import requests
import platform
import urllib3
import threading
import subprocess
import shutil
import json
from urllib3.exceptions import InsecureRequestWarning
from urllib import error
#from bs4 import BeautifulSoup
urllib3.disable_warnings(InsecureRequestWarning)

class GitbookHelper(object):
    def __init__(self, book_path, book_title='GitbookHelper', book_author='GitbookHelper', book_description='Made by GitbookHelper', book_language='zh-hans', book_summary_file_overwrite=True, book_summary_file_append=False):
        self.book_path = book_path
        self.book_title = book_title
        self.book_author = book_author
        self.book_description = book_description
        self.book_language = book_language  #en, ar, bn, cs, de, en, es, fa, fi, fr, he, it, ja, ko, no, pl, pt, ro, ru, sv, uk, vi, zh-hans, zh-tw
        self.book_json = {
            'title': self.book_title,
            'author': self.book_author,
            'description': self.book_description,
            'language': self.book_language
        }
        self.book_summary_file_overwrite = book_summary_file_overwrite
        self.book_summary_file_append = book_summary_file_append
        self.kindlegen_linux = 'kindlegen'
        self.kindlegen_mac = 'kindlegen-darwin'
        self.kindlegen_win = 'kindlegen.exe'
        self.book_former_summary_list = []

    def readTitle(self, dire):
        try:
            f = open(os.path.join(dire, 'book.json')) 
            book = json.load(f)
            return book['title']
        except:
            return 'book' 

    def mdfile_in_dir(self, dire):
        for root, dirs, files in os.walk(dire):
            for filename in files:
                if re.search('.md$|.markdown$', filename):
                    return True
        return False

    def is_markdown_file(self, filename):
        match = re.search('.md$|.markdown$', filename)
        if not match:
            return False
        elif len(match.group()) is len('.md'):
            return filename[:-3]
        elif len(match.group()) is len('.markdown'):
            return filename[:-9]

    def createRead0(self, dir_input, filename):
        #create 0-README.md
        readmeFile = open(os.path.join(dir_input, filename), 'w')
        readmeFile.close()

    def sort_dir_file(self, listdir, dire):
        list_of_file = []
        list_of_dir = []
        for filename in listdir:
            if os.path.isdir(os.path.join(dire, filename)):
                list_of_dir.append(filename)
            else:
                list_of_file.append(filename)
        for dire in list_of_dir:
            list_of_file.append(dire)
        filename_to_append = list()
        for f in list_of_file:
            if (u'\u7AE0' not in f or os.path.isdir(f)):
                filename_to_append.insert(0, f)
        list_of_file = [x for x in list_of_file if x not in filename_to_append]
        if list_of_file:
            list_of_file.sort(key=lambda x: int(x.split(u'\u7AE0')[0][1:]))
        for f in filename_to_append:
            list_of_file.insert(0, f)
        return list_of_file

    def write_md_filename(self, filename):
        if self.book_summary_file_append:
            for line in self.book_former_summary_list:
                if re.search(filename, line):
                    s = re.search('\[.*\]\(', line)
                    return s.group()[1:-2]
            else:
                return self.is_markdown_file(filename)
        else:
            return self.is_markdown_file(filename)

    def output_markdown(self, dire, base_dir, output_file, iter_depth=0):
        ignores = ['_book', 'docs', 'images', 'node_modules', 'dict', '.git']
        for filename in self.sort_dir_file(os.listdir(dire), base_dir):
            # add list and sort
            if filename in ignores:
                continue
            #print('Processing ', filename)  # output log
            file_or_path = os.path.join(dire, filename)
            if os.path.isdir(file_or_path):  #is dir
                if self.mdfile_in_dir(file_or_path):
                    # if there is .md files in the folder, output folder name
                    # output_file.write('  ' * iter_depth + '* ' + filename + '\n')
                    self.createRead0(file_or_path, '0-README.md')
                    output_file.write('  ' * iter_depth + '* [{}]({}/{})\n'.format(
                        filename, filename, '0-README.md'))
                    self.output_markdown(file_or_path, base_dir, output_file, iter_depth + 1)  # iteration
            else:  # is file
                if self.is_markdown_file(filename):
                    # re to find target markdown files, $ for matching end of filename
                    if (filename not in [
                            'SUMMARY.md', 'SUMMARY-GitBook-auto-summary.md',
                            '0-README.md', 'README.md'
                    ]):
                        #or iter_depth != 0): # escape SUMMARY.md at base directory
                        output_file.write(
                            '  ' * iter_depth + '* [{}]({})\n'.format(
                                self.write_md_filename(filename),
                                os.path.join(os.path.relpath(dire, base_dir), filename)))
                        # iter depth for indent, relpath and join to write link.

    def create_gitbook_summary(self, dire):
        # print information
        print('GitBook auto summary:', dire)
        if self.book_summary_file_overwrite:
            print('--overwrite')
        if self.book_summary_file_append and os.path.exists(os.path.join(dire, 'SUMMARY.md')):
            #append: read former SUMMARY.md
            print('--append')
            with open(os.path.join(dire, 'SUMMARY.md')) as f:
                self.book_former_summary_list = f.readlines()
                f.close()
        # output to flie
        if (self.book_summary_file_overwrite == False and os.path.exists(os.path.join(dire, 'SUMMARY.md'))):
            # overwrite logic
            filename = 'SUMMARY-GitBook-auto-summary.md'
        else:
            filename = 'SUMMARY.md'
        output = open(os.path.join(dire, filename), 'w')
        output.write('# 目录\n\n')
        output.write('* [简介](./README.md)\n')
        self.output_markdown(dire, dire, output)
        output.close()
        print('GitBook auto summary文件生成成功！')

    def create_gitbook_book_json(self, dire):
        json_data = json.dumps(self.book_json, ensure_ascii=False)
        with open(os.path.join(dire, 'book.json'), 'w') as f:
            f.write(json_data)
            f.close()
        print('GitBook book.json生成成功！')

    def build_epub(self, dire, epub_path):
        print('转换为Kindle电子书格式...')
        gitbook_command = 'gitbook epub --debug --log=debug {} {}'.format(dire, epub_path + '.epub')
        ret = subprocess.run(gitbook_command,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding="utf-8",timeout=1200)
        if ret == 0:
            print('*************************************************************')
            print('gitBook创建epub成功:', gitbook_command)
            print('*************************************************************')
        else:
            print('gitBook创建epub失败:', gitbook_command)

    def build_mobi(self, epub_path):
        print('转换为Kindle电子书格式...')
        sysstr = platform.system()
        if (sysstr == "Windows"):
            kindlegen_tool = self.kindlegen_win
        elif (sysstr == "Linux"):
            kindlegen_tool = self.kindlegen_linux
        elif (sysstr == "Mac"):
            kindlegen_tool = self.kindlegen_mac
        if not os.path.isfile(kindlegen_tool):
            print('kindlegen工具不存在脚本所在文件夹！请放入后重试！')
        else:
            #kindlegen [filename.opf/.htm/.html/.epub/.zip or directory] [-c0 or -c1 or c2] [-verbose] [-western] [-o <file name>]
            lang = self.book_language
            if lang == 'zh-hans' or lang == 'zh-tw':
                lang = 'zh'
            kindlegen_command = os.path.join('.', kindlegen_tool) + ' ' + epub_path + '.epub' + ' -c1 -verbose -locale ' + lang + ' -o ' + epub_path + '.mobi'
            ret = subprocess.run(kindlegen_command,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding="utf-8",timeout=600)
            if ret.returncode != 0:
                print('kindlegen命令操作失败：', kindlegen_command)
            else:
                print('kindlegen转换mobi成功：', kindlegen_command)

    def convert(self, dire):
        # Use gitbook to build mobi book
        if self.book_summary_file_overwrite:
            print('覆盖SUMMARY文件：', self.book_path + '/SUMMARY.md')
        else:
            print('创建SUMMARY文件：', self.book_path + '/SUMMARY-GitBook-auto-summary.md')
        self.create_gitbook_summary(self.book_path)
        print('gitBook正在创建mobi文件...')
        docs_path = os.path.join(self.book_path, 'docs')
        if not os.path.exists(docs_path):
            os.makedirs(docs_path)
        readmeFile = open(os.path.join(self.book_path, 'README.md'), 'w')
        readmeFile.write('# {}\n\n'.format('简介'))
        readmeFile.write('{}\n'.format(self.book_description))
        readmeFile.close()
        self.create_gitbook_book_json(self.book_path)
        epub_path = os.path.join(dire, 'docs', self.readTitle(dire))
        self.build_epub(dire, epub_path)
        self.build_mobi(epub_path)

class Ebookmaker(object):
    def __init__(self, book_info):
        user_agent_list = [
            'Mozilla/5.0 (Windows; U; MSIE 9.0; Windows NT 9.0; en-US',
            'Mozilla/5.0 (compatible; MSIE 10.0; Macintosh; Intel Mac OS X 10_7_3; Trident/6.0',
            'Mozilla/5.0 (compatible; MSIE 8.0; Windows NT 6.1; Trident/4.0; GTB7.4; InfoPath.2; SV1; .NET CLR 3.3.69573; WOW64; en-US',
            'Opera/9.80 (X11; Linux i686; U; ru) Presto/2.8.131 Version/11.11',
            'Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.2 (KHTML, like Gecko) Chrome/22.0.1216.0 Safari/537.2',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_7_4) AppleWebKit/537.13 (KHTML, like Gecko) Chrome/24.0.1290.1 Safari/537.13',
            'Mozilla/5.0 (X11; CrOS i686 2268.111.0) AppleWebKit/536.11 (KHTML, like Gecko) Chrome/20.0.1132.57 Safari/536.11',
            'Mozilla/5.0 (Windows NT 6.2; Win64; x64; rv:16.0.1) Gecko/20121011 Firefox/16.0.1',
            'Mozilla/5.0 (X11; Ubuntu; Linux i686; rv:15.0) Gecko/20100101 Firefox/15.0.1',
            'Mozilla/5.0 (iPad; CPU OS 6_0 like Mac OS X) AppleWebKit/536.26 (KHTML, like Gecko) Version/6.0 Mobile/10A5355d Safari/8536.2',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        ]
        self.book_info = book_info
        self.headers = { 
            'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Accept-encoding':'gzip,deflate,br',
            'Accept-Language':'zh-CN,zh;q=0.9',
            'Connection':'keep-alive',
            'Cache-Control':'max-age=0',
            'sec-ch-ua':'" Not;A Brand";v="99", "Google Chrome";v="91", "Chromium";v="91"',
            'sec-ch-ua-mobile':'?0',
            'Sec-Fetch-Dest':'document',
            'Sec-Fetch-Mode':'navigate',
            'Sec-Fetch-Site':'same-origin',
            'Sec-Fetch-User':'?1',
            'Upgrade-Insecure-Requests':'1',
            'User-Agent':random.choice(user_agent_list),
            'Cookie':self.book_info['book_cookie'],
            'Host':self.book_info['book_host'],
            'Referer':self.book_info['book_referer']
        }
        ######################################################################################
        self.kafcli_linux = 'kaf-cli-linux'
        self.kafcli_mac = 'kaf-cli-darwin'
        self.kafcli_win = 'kaf-cli.exe'
        self.kafcli_book_bottom = '1'
        self.kafcli_book_cover = 'cover.png'
        self.kafcli_tool_base_path = '.'
        ######################################################################################
        self.thread_num = 20
        self.ip_pool_web_num = 20
        self.semaphore = threading.BoundedSemaphore(self.thread_num)
        self.sem = threading.Semaphore()
        self.IP = []
        self.proxyPool = []
        self.book_chapter_urls = {}
        self.missing_urls = []
        self.book_chapter_dict = {}
        ######################################################################################

    def loadData(self,url,host=None,referer=None,cookie=None,proxy_pool=None):
        if host == None:
            host = ''
        if referer == None:
            referer = ''
        if cookie == None:
            cookie = ''
        self.headers.update({'Cookie': cookie})
        self.headers.update({'Host': host})
        self.headers.update({'Referer': referer})
        try_agin_count = 3
        while try_agin_count > 0:
            try:
                try_agin_count = try_agin_count - 1
                if proxy_pool == None:
                    response = requests.get(url, headers=self.headers, verify=False, timeout=(10,10))
                elif len(proxy_pool) == 1:
                    response = requests.get(url, headers=self.headers, proxies=proxy_pool, verify=False, timeout=(10,10))
                else:
                    proxy = random.choice(proxy_pool)
                    response = requests.get(url, headers=self.headers, proxies=proxy, verify=False, timeout=(10,10))
                response.raise_for_status()
            except requests.RequestException as e:
                if try_agin_count == 0:
                    return 'ERROR'
                time.sleep(3)
            else:
                break
        if response.encoding:
            if response.encoding == 'ISO-8859-1':
                encodings = requests.utils.get_encodings_from_content(response.text)
                if encodings:
                    encoding = encodings[0]
                else:
                    encoding = response.apparent_encoding
            else:
                encoding = response.encoding
        else:
            encoding = 'utf-8'
        encode_content = response.content.decode(encoding, 'ignore')
        return encode_content

    def ip_pool(self,idx):
        self.semaphore.acquire()
        daili_data = self.loadData(self.book_info['daili_url_base'] + str(idx+1), host=self.book_info['daili_host'], referer=self.book_info['daili_url_base'] + str(idx), cookie=self.book_info['daili_cookie'])
        if daili_data != 'ERROR':
            # data-url="http://119.167.66.22:8081"
            for ip in re.findall(self.book_info['daili_re'], daili_data):
                self.sem.acquire()
                self.IP.append(ip)
                self.sem.release()
        self.semaphore.release()

    def proxy_pool(self,ip):
        self.semaphore.acquire()
        proxies = { "http" : "http://" + ip}
        proxy_pool_data = self.loadData(self.book_info['proxy_pool_url'], host=self.book_info['proxy_pool_host'], proxy_pool=proxies)
        if proxy_pool_data != 'ERROR':
            self.sem.acquire()
            self.proxyPool.append(proxies)
            self.sem.release()
        self.semaphore.release()

    def get_ip_pool(self):
        ip_threads = []
        for idx in range(self.ip_pool_web_num):
            t = threading.Thread(target=self.ip_pool,args=(idx,))
            t.start()
            ip_threads.append(t)
            #if idx%self.thread_num == 0:
            #    time.sleep(1)
        for t in ip_threads:
            t.join()
        new_list = list(set(self.IP))
        new_list.sort(key=self.IP.index)
        self.IP = new_list
        print('代理IP池大小为{}'.format(len(self.IP)))

    def get_proxy_pool(self):
        proxy_pool_threads = []
        for idx in range(len(self.IP)):
            t = threading.Thread(target=self.proxy_pool,args=(self.IP[idx],))
            t.start()
            proxy_pool_threads.append(t)
        for t in proxy_pool_threads:
            t.join()
        print('筛选后的代理池大小为{}'.format(len(self.proxyPool)))

    def get_book_info(self):
        res = self.loadData(self.book_info['book_url'], referer=self.book_info['book_referer'], host=self.book_info['book_host'])
        if res == 'ERROR':
            print("访问失败: {:<64}".format(self.book_info['book_url']))
            return list()
        self.book_info['book_name'] = self.book_info['book_name_re'].findall(res)[0]
        self.book_info['book_description'] = self.book_info['book_description_re'].findall(res)[0]
        self.book_info['book_author'] = self.book_info['book_author_re'].findall(res)[0]
        self.book_info['book_output_name'] = self.book_info['book_name'] + self.book_info['book_chapter_file_suffic']
        self.book_chapter_urls = self.book_info['book_chapter_list_reg'].findall(res)
        print("获取书籍信息：\n{}\n{}\n{}\n".format(self.book_info['book_name'],self.book_info['book_author'],self.book_info['book_description']))

    def work(self,base_path,index,urls,cookie=None,proxy_pool=None):
        self.semaphore.acquire()
        write_path = os.path.join(base_path, urls[index][1] + self.book_info['book_chapter_file_suffic'])
        self.sem.acquire()
        self.book_chapter_dict[index+1] = urls[index][1] + self.book_info['book_chapter_file_suffic']
        self.sem.release()
        if os.path.isfile(write_path):
            if os.path.getsize(write_path):
                print("文件已缓存: {:<64}".format(urls[index][1]))
                self.semaphore.release()
                return
        with open(write_path, 'w+') as f:
            f.write(self.book_info['book_chapter_name_format_begin'] + urls[index][1] + '\n\n')
            f.write('--------------------\n\n')
            chapter_html = self.loadData(self.book_info['book_url'] + urls[index][0], host=self.book_info['book_host'], referer=self.book_info['book_url'], cookie=cookie, proxy_pool=proxy_pool)
            if chapter_html == 'ERROR':
                f.seek(0)
                f.truncate()
                print("访问失败: {:<64}".format(urls[index][1]))
                self.sem.acquire()
                self.missing_urls.append(urls[index])
                self.sem.release()
                self.semaphore.release()
                return
            for content in re.findall(self.book_info['book_chapter_content_reg'], chapter_html):
                f.write(content + self.book_info['book_chapter_name_format_end'] + '\n\n')
            print("写入成功: {:<64}".format(urls[index][1]))
        self.semaphore.release()

    def create_book_store_dir(self,dir):
        print('开始创建书籍存档目录：%s...' %dir)
        if not os.path.exists(dir):
            os.makedirs(dir)

    def fetch_and_store_urls(self,dir,urls):
        work_threads = []
        self.thread_num = 50
        self.semaphore = threading.BoundedSemaphore(self.thread_num)
        chapter_len = len(urls)
        for idx in range(chapter_len):
            t = threading.Thread(target=self.work,args=(dir,idx,urls,None,self.proxyPool[random.randint(0,len(self.proxyPool)-1)]))
            t.start()
            work_threads.append(t)
        for t in work_threads:
            t.join()

    def write_md_title(self,dir):
        print('写入标题和目录...')
        path = os.path.join(dir, self.book_info['book_output_name'])
        with open(path, 'w+') as f:
            f.write('# 目录 \n\n')
            f.write('--------------------\n\n')
            for k in sorted(self.book_chapter_dict):
                chapter_title = self.book_chapter_dict[k].split(self.book_info['book_chapter_file_suffic'])[0]
                f.write('  - [' + chapter_title + '](#' + re.sub(' ', '-', chapter_title) + ')\n')
            f.write('\n')

    def write_md_chapters(self,dir):
        print('写入所有章节...')
        res = ""
        for k in sorted(self.book_chapter_dict):
            file = self.book_chapter_dict[k]
            if file.endswith(self.book_info['book_chapter_file_suffic']):
                path = os.path.join(dir,file)
                with open(path, 'r', encoding='utf-8') as file:
                    content = file.read()
                res += content
        path = os.path.join(dir,self.book_info['book_output_name'])
        with open(path, 'a+', encoding='utf-8') as f:
            f.write(res)

    def convert_by_pandoc(self,dir):
        '''
        pandoc -D markdown > modified.markdown
        pandoc --template modified.markdown <... rest of your command ...>
        pandoc -s --table-of-contents --toc-depth=4 --metadata title="武神主宰" 1.md -o 1.epub
            --top-level-division=chapter \
            --variable=toc-title='目录' \
            --table-of-contents \
            --toc-depth=3 \
            --metadata-file=metadata.yml \
        pandoc --from=markdown --to=markdown --standalone --table-of-contents --toc-depth=3 --variable=lang=zh_CN --metadata title="目录" 1.md -o 1_new.md
        pandoc \
            --from=markdown \
            --to=epub3 \
            --atx-headers \
            --variable=lang=zh_CN \
            --standalone \
            --wrap=preserve \
            --verbose \
            --template=epub.template \
            --metadata title="武神主宰" \
            --metadata author="暗魔师" \
            --metadata description="天武大陆一代传奇秦尘，因好友背叛意外陨落武域。" \
            --metadata css=epub.css \
            --metadata cover-image=cover.jpg \
            --output=1.epub \
            output.md
        '''
        print('转换为epub电子书格式...')
        epub_output_path = os.path.join(dir, self.book_info['book_name'] + '.epub')
        css_path = os.path.join(dir, 'epub.css')
        cover_path = os.path.join(dir, 'cover.jpg')
        templater_path = os.path.join(dir, 'epub.template')
        pandoc_command = 'pandoc --from=markdown --to=epub3 --atx-headers --variable=lang=zh_CN --standalone --wrap=preserve --verbose ' + ' --template=' + templater_path + ' --metadata title=' + self.book_info['book_name'] + ' --metadata author=' + self.book_info['book_author'] + ' --metadata description=' + self.book_info['book_description'] + ' --metadata css=' + css_path + ' --metadata cover-image=' + cover_path + ' --output=' + epub_output_path + ' ' + os.path.join(dir, self.book_info['book_name'] + '.md')
        ret = subprocess.run(pandoc_command,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding="utf-8",timeout=1200)
        if ret.returncode != 0:
            print('pandoc操作失败!',ret)
        else:
            print('epub转换完成!!!')

    def convert_by_ebook_convert(self,dir):
        '''
        TBD: use ebook-convert cmdline to convert markdown file to mobi/azw3
        #fmt.Print(fmt.Sprintf("ebook-convert %s %s --authors %s --comments '%s' --level1-toc '//h:h1' --level2-toc '//h:h2' --language '%s'\n", Tmp, Mobi, Author, Comment, Lang))
        ebook-convert 1.epub 1.mobi 
            --authors "暗魔师" --input-profile=kindle --output-profile=kindle_pw3 --extra-css=default.css 
            --expand-css --remove-paragraph-spacing-indent-size=2 --remove-first-image --chapter-mark=pagebreak 
            --prefer-metadata-cover --insert-metadata --level1-toc=//h:h1 --level2-toc=//h:h2 --level3-toc=//h:h3
            --max-toc-links=0 --use-auto-toc --formatting-type=markdown --mobi-toc-at-start
            --title=""
            --authors=""
            --cover=cover.jpg
            --comments=""
            --publisher=""
            --tags=""
            --book-producer=""
            --language=zh
        '''
        print('转换为azw3/mobi电子书格式...')
        ebook_convert_command = 'ebook-convert ' + os.path.join(dir, self.book_info['book_name'] + '.epub') + ' ' + os.path.join(dir, self.book_info['book_name'] + '.azw3')
        ret = subprocess.run(ebook_convert_command,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding="utf-8",timeout=1200)
        if ret.returncode != 0:
            print('ebook_convert操作失败!',ret)
        else:
            print('azw3/mobi转换完成!!!')

    def convert_by_kafcli(self):
        print('转换为Kindle电子书格式...')
        sysstr = platform.system()
        if (sysstr == "Windows"):
            kafcli_tool = self.kafcli_win
        elif (sysstr == "Linux"):
            kafcli_tool = self.kafcli_linux
        elif (sysstr == "Mac"):
            kafcli_tool = self.kafcli_mac
        if not os.path.isfile(kafcli_tool):
            print('kaf-cli工具不存在脚本所在文件夹！请放入后重试！')
        else:
            kafcli_command = os.path.join(self.kafcli_tool_base_path, kafcli_tool) + ' -filename ' + os.path.join(self.book_info['ebooks_labrary_path'], self.book_info['book_name'], self.book_info['book_output_name']) + ' -bookname ' + self.book_info['book_name'] + ' -author ' + self.book_info['book_author'] + ' -cover ' + self.kafcli_book_cover + ' -bottom ' + self.kafcli_book_bottom
            ret = subprocess.run(kafcli_command,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding="utf-8",timeout=600)
            if ret.returncode != 0:
                print('kaf-cli操作失败!',ret)
            else:
                print('所有操作都已经完成!!!')

def main():
    book_info = {
        'book_name': 'MyBook',
        'book_author': 'Ebookmaker',
        'book_description': 'Made by Ebookmaker!',
        'ebooks_labrary_path': os.path.join('.', 'ebooks'),
        'book_url': 'https://www.xbooktxt.net/2_2588/',                #https://www.xbiquge.la/66/66747/
        'book_host': 'www.xbooktxt.net',                               #www.xbiquge.la
        'book_referer': 'https://www.xbooktxt.net/2_2588/685752.html', #https://www.xbiquge.la/66/66747/26547971.html
        'book_cookie': 'UM_distinctid=17ac9cdf4d0d3f-09ee6521cf9cfd-6373264-384000-17ac9cdf4d1146c; CNZZDATA1266846634=2004344946-1626881060-https%3A%2F%2Fwww.baidu.com%2F|1626881060; hitbookid=2588; PPad_id_PP=5; hitme=2', #_abcde_qweasd=0; Hm_lvt_169609146ffe5972484b0957bd1b46d6=1626520436,1626585865; Hm_lpvt_169609146ffe5972484b0957bd1b46d6=1626597513
        'book_chapter_name_format_begin': '## ',
        'book_chapter_name_format_end': '  ',
        'book_chapter_file_suffic': '.md',
        'book_output_name': 'outfile.md',
        #'book_chapter_name_format_begin': '',
        #'book_chapter_name_format_end': '',
        #'book_chapter_file_suffic': '.txt',
        #'book_output_name': 'outfile.txt',
        'book_name_re':re.compile(r'<meta property="og:novel:book_name" content="(.*?)"/>'),                           #re.compile(r'<meta property="og:name" content="(.*?)"/>')
        'book_description_re':re.compile(r'<meta property="og:description" content="(.*?)"/>'),                        #re.compile(r'<meta property="og:description" content="(.*?)"/>')
        'book_author_re':re.compile(r'<meta property="og:novel:author" content="(.*?)"/>'),                            #re.compile(r'<meta property="og:novel:author" content="(.*?)"/>')
        'book_chapter_list_reg':re.compile(r'<dd><a href="/2_2588/([0-9]{5,6}\.html)"  >(.*?)</a></dd>'), #re.compile(r'<dd><a href=\'/66/66747/([0-9]{8}\.html)\' >(.*?)</a></dd>')
        'book_chapter_content_reg':re.compile(r'&nbsp;&nbsp;&nbsp;&nbsp;(.*?)<br><br>', re.S),                         #re.compile(r'<br />&nbsp;&nbsp;&nbsp;&nbsp;.*?\r<br />', re.S)
        'daili_url_base': 'https://ip.jiangxianli.com/?page=',
        'daili_host': 'ip.jiangxianli.com',
        'daili_cookie': 'UM_distinctid=17abfa06f89dc5-0f97a150c82592-6373264-384000-17abfa06f8ad3c; Hm_lvt_b72418f3b1d81bbcf8f99e6eb5d4e0c3=1626712600,1626886778,1626886791,1626886800; Hm_lpvt_b72418f3b1d81bbcf8f99e6eb5d4e0c3=1626886832',
        'daili_re': re.compile(r'data-url="http://(\d+\.\d+\.\d+\.\d+:\d+)"'),
        'proxy_pool_url': 'http://httpbin.org/ip',
        'proxy_pool_host': 'httpbin.org'
    }

    em = Ebookmaker(book_info)
    em.get_ip_pool()
    em.get_proxy_pool()
    em.get_book_info()
    if not em.book_chapter_urls:
        return
    book_path = os.path.join(em.book_info['ebooks_labrary_path'], em.book_info['book_name'])
    em.create_book_store_dir(book_path)

    print('拷贝封面文件到书籍生成目录...')
    pandoc_cover_jpg = os.path.join('pandoc', 'cover.jpg')
    pandoc_cover_png = os.path.join('pandoc', 'cover.png')
    if os.path.exists(pandoc_cover_jpg) and os.path.exists(pandoc_cover_png):
        try:
            shutil.copy(pandoc_cover_jpg, book_path)
            shutil.copy(pandoc_cover_png, book_path)
        except Exception as e:
            print(e)
    else:
        print('封面cover.png与cover.jpg文件不存在，如果需要生成封面，请把书对应的封面文件放到脚本同一目录下。')

    print('拷贝ePub样式文件到书籍生成目录...')
    pandoc_css = os.path.join('pandoc', 'epub.css')
    if os.path.exists(pandoc_css):
        try:
            shutil.copy(pandoc_css, book_path)
        except Exception as e:
            print(e)
    else:
        print('ePub样式文件epub.css不存在，请把该文件放到脚本同一目录下的pandoc目录下。')
        return
    
    print('拷贝ePub模板文件到书籍生成目录...')
    pandoc_template = os.path.join('pandoc', 'epub.template')
    if os.path.exists(pandoc_template):
        try:
            shutil.copy(pandoc_template, book_path)
        except Exception as e:
            print(e)
    else:
        print('ePub模板文件epub.template不存在，请把该文件放到脚本同一目录下的pandoc目录下。')
        return

    print('现在开始将所有章节存入文件...')
    em.fetch_and_store_urls(book_path, em.book_chapter_urls)
    print('现在尝试重新处理写入失败的章节...')
    em.fetch_and_store_urls(book_path, em.missing_urls)

    # Use kaf-cli to convert ePub book
    '''
    TBD: vs code reg need to do after merge chapters:
        ”([^\n]).*? => "\n$1
        (“.*?[^”]$)\n$ => $1"\n
        " => ”
        'i' => ''
        &nbsp => ''
    '''
    em.write_md_title(book_path)
    em.write_md_chapters(book_path)
    #em.convert_by_kafcli()
    em.convert_by_pandoc(book_path)
    em.convert_by_ebook_convert(book_path)

    # Use gitbook to build mobi book
    #gh = GitbookHelper(book_path, em.book_info['book_name'], em.book_info['book_author'], em.book_info['book_description'])
    #gh.convert(book_path)、

if __name__ == '__main__':
    main()
