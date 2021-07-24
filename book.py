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
import argparse
import json
from urllib3.exceptions import InsecureRequestWarning
from urllib import error
#from bs4 import BeautifulSoup
urllib3.disable_warnings(InsecureRequestWarning)

class MarkdownHelper(object):
    def __init__(self):
        self.former_summary_list = []
        self.chapter_name_suffix = '.md'
        self.overwrite = True
        self.append = False
        self.kindlegen_linux = 'kindlegen'
        self.kindlegen_mac = 'kindlegen-darwin'
        self.kindlegen_win = 'kindlegen.exe'
        self.book_json = {
            'title': 'MyBook',
            'author': 'GitBook',
            'description': '由GitBook制作',
            'language': 'zh-hans'
        }

    def readTitle(self, dirPath):
        try:
            f = open(dirPath+'/book.json') 
            book = json.load(f)
            return book['title']
        except:
            return 'book' 

    def mdfile_in_dir(self, dire):
        """判断目录中是否有MD文件
        """
        for root, dirs, files in os.walk(dire):
            for filename in files:
                if re.search('.md$|.markdown$', filename):
                    return True
        return False

    def is_markdown_file(self, filename):
        """ 判断文件名是.Markdown
        i: filename
        o: filename without '.md' or '.markdown'
        """
        match = re.search('.md$|.markdown$', filename)
        if not match:
            return False
        elif len(match.group()) is len('.md'):
            return filename[:-3]
        elif len(match.group()) is len('.markdown'):
            return filename[:-9]

    def createRead0(self,dir_input, filename):
        #create 0-README.md
        readmeFile = open(os.path.join(dir_input, filename), 'w')
        readmeFile.close()

    def sort_dir_file(self, listdir, dire):
        # sort dirs and files, first files a-z, then dirs a-z
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
            if ('章' not in f or os.path.isdir(f)):
                filename_to_append.insert(0, f)
        list_of_file = [x for x in list_of_file if x not in filename_to_append]
        if list_of_file:
            list_of_file.sort(key=lambda x: int(x.split('章')[0][1:]))
        for f in filename_to_append:
            list_of_file.insert(0, f)

        return list_of_file

    def write_md_filename(self, filename, append):
        """ write markdown filename
        i: filename and append
        p: if append: find former list name and return
        else: write filename
        """
        if append:
            for line in self.former_summary_list:
                if re.search(filename, line):
                    s = re.search('\[.*\]\(', line)
                    return s.group()[1:-2]
            else:
                return self.is_markdown_file(filename)
        else:
            return self.is_markdown_file(filename)

    def output_markdown(self, dire, base_dir, output_file, append, iter_depth=0):
        """Main iterator for get information from every file/folder
        i: directory, base directory(to calulate relative path), 
        output file name, iter depth.
        p: Judge is directory or is file, then process .md/.markdown files.
        o: write .md information (with identation) to output_file.
        """
        ignores = ['_book', 'docs', 'images', 'node_modules', 'dict', '.git']

        for filename in self.sort_dir_file(os.listdir(dire), base_dir):
            # add list and sort
            if filename in ignores:
                #print('continue ', filename)  # output log
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
                    self.output_markdown(file_or_path, base_dir, output_file, append,
                                    iter_depth + 1)  # iteration
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
                                self.write_md_filename(filename, append),
                                os.path.join(
                                    os.path.relpath(dire, base_dir), filename)))
                        # iter depth for indent, relpath and join to write link.

    def create_gitbook_summary(self,dire,overwrite=False,append=False):
        # print information
        print('GitBook auto summary:', dire)
        if overwrite:
            print('--overwrite')
        if append and os.path.exists(os.path.join(dire, 'SUMMARY.md')):
            #append: read former SUMMARY.md
            print('--append')
            with open(os.path.join(dire, 'SUMMARY.md')) as f:
                self.former_summary_list = f.readlines()
                f.close()
        # output to flie
        if (overwrite == False and os.path.exists(os.path.join(dire, 'SUMMARY.md'))):
            # overwrite logic
            filename = 'SUMMARY-GitBook-auto-summary.md'
        else:
            filename = 'SUMMARY.md'
        output = open(os.path.join(dire, filename), 'w')
        output.write('# 目录\n\n')
        output.write('* [简介](./README.md)\n')
        self.output_markdown(dire, dire, output, append)
        output.close()
        print('GitBook auto summary文件生成成功！')

    def create_gitbook_book_json(self,dire,title,author,description,language):
        self.book_json['title'] = title
        self.book_json['author'] = author
        self.book_json['description'] = description
        self.book_json['language'] = language
        json_data = json.dumps(self.book_json,ensure_ascii=False)

        with open(os.path.join(dire, 'book.json'), 'w') as f:
            f.write(json_data)
            f.close()
        print('GitBook book.json生成成功！')

    def convert_by_kindlegen(self, dire):
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
            title = self.readTitle(dire)
            gitbook_command = 'gitbook epub {} {}'.format(dire, dire + '/docs/' + title + '.epub')
            ret = subprocess.run(gitbook_command,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding="utf-8",timeout=1200)
            if ret == 0:
                print('*************************************************************')
                print('gitBook创建epub成功:', dire)
                print('*************************************************************')
            else:
                print('gitBook创建epub失败:', gitbook_command)
            kindlegen_command = os.path.join('.', kindlegen_tool) + ' ' + dire + '/docs/' + title + '.epub'
            ret = subprocess.run(kindlegen_command,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding="utf-8",timeout=600)
            if ret.returncode != 0:
                print('kindlegen命令操作失败：', kindlegen_command)
            else:
                print('gitBook转换mobi成功：', dire)

class Ebookmaker(object):
    def __init__(self):
        #self.book_url = 'https://www.xbiquge.la/66/66747/'
        #self.book_host = 'www.xbiquge.la'
        #self.book_referer = 'https://www.xbiquge.la/66/66747/26547971.html'
        #self.cookie = '_abcde_qweasd=0; Hm_lvt_169609146ffe5972484b0957bd1b46d6=1626520436,1626585865; Hm_lpvt_169609146ffe5972484b0957bd1b46d6=1626597513'
        #self.book_name_re = re.compile(r'<meta property="og:name" content="(.*?)"/>')
        #self.book_description_re = re.compile(r'<meta property="og:description" content="(.*?)"/>')
        #self.book_author_re = re.compile(r'<meta property="og:novel:author" content="(.*?)"/>')
        # <dd><a href='/66/66747/26547971.html' >第1章 重生</a></dd>
        #list_reg = re.compile(r'<dd><a href=\'/66/66747/([0-9]{8}\.html)\' >(.*?)</a></dd>')
        # <br />&nbsp;&nbsp;&nbsp;&nbsp;武神历2216年。
        # <br />
        #self.chapter_content_reg = re.compile(r'<br />&nbsp;&nbsp;&nbsp;&nbsp;.*?\r<br />', re.S)
        ######################################################################################
        self.book_url = 'https://www.xbooktxt.net/2_2588/'
        self.book_host = 'www.xbooktxt.net'
        self.book_referer = 'https://www.xbooktxt.net/2_2588/685752.html'
        self.cookie = 'UM_distinctid=17ac9cdf4d0d3f-09ee6521cf9cfd-6373264-384000-17ac9cdf4d1146c; CNZZDATA1266846634=2004344946-1626881060-https%3A%2F%2Fwww.baidu.com%2F|1626881060; hitbookid=2588; PPad_id_PP=5; hitme=2'
        self.user_agent_list=[
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
            'User-Agent':random.choice(self.user_agent_list),
            #'Cookie':cookie,
            #'Host':host,
            #'Referer':referer
        }
        self.book_name_re = re.compile(r'<meta property="og:novel:book_name" content="(.*?)"/>')
        self.book_description_re = re.compile(r'<meta property="og:description" content="(.*?)"/>')
        self.book_author_re = re.compile(r'<meta property="og:novel:author" content="(.*?)"/>')
        self.list_reg = re.compile(r'<dd><a href="/2_2588/([0-9]{5,6}\.html)"  >(.*?)</a></dd>')
        self.chapter_content_reg = re.compile(r'&nbsp;&nbsp;&nbsp;&nbsp;(.*?)<br><br>', re.S)
        self.chapter_dict = {}
        ######################################################################################
        # For Calibre
        self.chapter_name_format_begin = "# "
        self.chapter_name_format_end = " #"
        self.chapter_name_suffix = ".md"
        # For kaf-cli
        #self.chapter_name_format_begin = ""
        #self.chapter_name_format_end = ""
        #self.chapter_name_suffix = ".txt"
        ######################################################################################
        self.daili_url_base = 'https://ip.jiangxianli.com/?page='
        self.daili_host = 'ip.jiangxianli.com'
        self.daili_cookie = 'UM_distinctid=17abfa06f89dc5-0f97a150c82592-6373264-384000-17abfa06f8ad3c; Hm_lvt_b72418f3b1d81bbcf8f99e6eb5d4e0c3=1626712600,1626886778,1626886791,1626886800; Hm_lpvt_b72418f3b1d81bbcf8f99e6eb5d4e0c3=1626886832'
        self.daili_re = re.compile(r'data-url="http://(\d+\.\d+\.\d+\.\d+:\d+)"')
        self.proxy_pool_url = 'http://httpbin.org/ip'
        self.proxy_pool_host = 'httpbin.org'
        self.book_name = 'MyBook'
        self.book_author = 'Ebookmaker'
        self.book_description = 'Made by Ebookmaker!'
        self.book_default_output_name = 'outfile' + self.chapter_name_suffix
        self.book_default_kafcli_bottom = '1'
        ######################################################################################
        self.thread_num = 5
        self.ip_pool_web_num = 20
        self.semaphore = threading.BoundedSemaphore(self.thread_num)
        self.sem = threading.Semaphore()
        self.IP = []
        self.proxyPool = []
        self.missing_urls = []
        ######################################################################################
        self.kafcli_linux = 'kaf-cli-linux'
        self.kafcli_mac = 'kaf-cli-darwin'
        self.kafcli_win = 'kaf-cli.exe'

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
                    #print(e)
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
        daili_data = self.loadData(self.daili_url_base + str(idx+1), host=self.daili_host, referer=self.daili_url_base + str(idx), cookie=self.daili_cookie)
        if daili_data != 'ERROR':
            # data-url="http://119.167.66.22:8081"
            for ip in re.findall(self.daili_re, daili_data):
                self.sem.acquire()
                self.IP.append(ip)
                self.sem.release()
        self.semaphore.release()

    def proxy_pool(self,ip):
        self.semaphore.acquire()
        proxies = { "http" : "http://" + ip}
        proxy_pool_data = self.loadData(self.proxy_pool_url, host=self.proxy_pool_host, proxy_pool=proxies)
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
            if idx%self.thread_num == 0:
                time.sleep(3)
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
            if idx%self.thread_num == 0:
                time.sleep(3)
        for t in proxy_pool_threads:
            t.join()
        print('筛选后的代理池大小为{}'.format(len(self.proxyPool)))

    def get_book_info(self):
        res = self.loadData(self.book_url, referer=self.book_referer, host=self.book_host)
        if res == 'ERROR':
            print("访问失败: {:<64}".format(self.book_url))
            return list()
        self.book_name = self.book_name_re.findall(res)
        self.book_description = self.book_description_re.findall(res)
        self.book_author = self.book_author_re.findall(res)
        urls = self.list_reg.findall(res)
        print("获取书籍信息：\n{}\n{}\n{}\n".format(self.book_name[0],self.book_author[0],self.book_description[0]))
        return urls

    def work(self,base_path,index,urls,cookie=None,proxy_pool=None):
        self.semaphore.acquire()
        write_path = os.path.join(base_path, urls[index][1] + self.chapter_name_suffix)
        self.chapter_dict[str(index+1)] = write_path
        if os.path.isfile(write_path):
            os.remove(write_path)
        with open(write_path, 'a+') as f:
            f.write(self.chapter_name_format_begin + urls[index][1] + self.chapter_name_format_end + '\n\n')
            chapter_html = self.loadData(self.book_url + urls[index][0], host=self.book_host, referer=self.book_url, cookie=cookie, proxy_pool=proxy_pool)
            if chapter_html == 'ERROR':
                print("访问失败: {:<64}".format(urls[index][1]))
                self.sem.acquire()
                self.missing_urls.append(urls[index])
                self.sem.release()
                self.semaphore.release()
                return
            chapter_content = re.findall(self.chapter_content_reg, chapter_html)
            for content in chapter_content:
                #content = content.replace("&nbsp;&nbsp;&nbsp;&nbsp;", md_chapter_content_format_begin)
                #content = content.replace('<br><br>', md_chapter_content_format_begin)
                f.write(content + '\n')
            f.write('\n')
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
            if idx%self.thread_num == 0:
                time.sleep(3)
        for t in work_threads:
            t.join()

    def merge_chapters(self,dir):
        print('合并所有章节...')
        res = ""
        for k in sorted(self.chapter_dict):
        #files.sort(key=lambda x: int(x.split('章')[0][1:] + x.split(self.chapter_name_suffix)[0][:1]))
        #for file in files:
            file = self.chapter_dict[k]
            if file.endswith(self.chapter_name_suffix):
                path = os.path.join(dir,file)
                with open(path, 'r', encoding='utf-8') as file:
                    content = file.read()
                    file.close()
                res += content
        path = os.path.join(dir,self.book_default_output_name)
        with open(path, 'w', encoding='utf-8') as outFile:
            outFile.write(res)
            outFile.close()

    def convert_by_kafcli(self,dir,book_name,book_author,book_bottom='1',book_cover='cover.png'):
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
            kafcli_command = os.path.join(dir, kafcli_tool) + ' -filename ' + book_name + '/' + self.book_default_output_name + ' -bookname ' + book_name + ' -author ' + book_author + ' -cover ' + book_cover + ' -bottom ' + book_bottom
            ret = subprocess.run(kafcli_command,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding="utf-8",timeout=300)
            if ret.returncode != 0:
                print('kaf-cli操作失败!',ret)
            else:
                print('所有操作都已经完成!!!')

def main():
    em = Ebookmaker()
    em.get_ip_pool()
    em.get_proxy_pool()
    urls = em.get_book_info()
    if not urls:
        return
    book_path = os.path.join('ebooks', em.book_name[0])
    em.create_book_store_dir(book_path)

    print('拷贝封面cover.jpg文件到当前目录...')
    if os.path.exists('cover.jpg') and os.path.exists('cover_small.jpg'):
        shutil.copy('cover.jpg', book_path)
        shutil.copy('cover_small.jpg', book_path)
    else:
        print('封面cover.jpg和cover_small.jpg文件不存在，如果需要生成封面，请把书对应的cover.jpg和cover_small.jpg放到脚本同一目录下。')

    print('现在开始将所有章节存入文件...')
    em.fetch_and_store_urls(book_path, urls)
    print('现在重新处理写入失败的章节...')
    em.fetch_and_store_urls(book_path, em.missing_urls)

    # Use kaf-cli to convert ePub book
    #em.merge_chapters(book_path)
    #em.convert_by_kafcli('.', em.book_name[0], em.book_author[0], em.book_default_kafcli_bottom)

    # Use gitbook to build mobi book
    mh = MarkdownHelper()
    if mh.overwrite:
        print('覆盖SUMMARY文件：', book_path + '/SUMMARY.md')
    else:
        print('创建SUMMARY文件：', book_path + '/SUMMARY-GitBook-auto-summary.md')
    mh.create_gitbook_summary(book_path, overwrite=mh.overwrite, append=mh.append)

    print('gitBook正在创建mobi文件...')
    if not os.path.exists(book_path + '/docs'):
        os.makedirs(book_path + '/docs')
    readmeFile = open(os.path.join(book_path, 'README.md'), 'w')
    readmeFile.write('# {} #\n\n'.format('简介'))
    readmeFile.write('{}\n'.format(em.book_description[0]))
    readmeFile.close()
    mh.create_gitbook_book_json(book_path,em.book_name[0],em.book_author[0],em.book_description[0],'zh-hans')
    mh.convert_by_kindlegen(book_path)

    print('gitBook生成mobi文件完成！')

if __name__ == '__main__':
    main()
