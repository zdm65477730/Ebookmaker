#!/usr/bin/python3
# -*- coding:utf-8 -*-

import re
import os
import datetime
import random
import hashlib
import requests
import platform
import urllib3
import threading
import subprocess
import shutil
import json
import time
import zipfile
from xml.dom import minidom
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
        self.basic_info['kindlegen_linux'] = 'kindlegen'
        self.basic_info['kindlegen_mac'] = 'kindlegen-darwin'
        self.basic_info['kindlegen_win'] = 'kindlegen.exe'
        self.book_former_summary_list = []

    def readTitle(self, dire):
        try:
            f = open(os.path.join(dire, 'book.json'), encoding='utf-8') 
            book = json.load(f)
            return book['title']
        except:
            return 'book' 

    def mdfile_in_dir(self, dire):
        for dirpath, dirs, files in os.walk(dire):
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
        readmeFile = open(os.path.join(dir_input, filename), 'w', encoding='utf-8')
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
            with open(os.path.join(dire, 'SUMMARY.md'), encoding='utf-8') as f:
                self.book_former_summary_list = f.readlines()
                f.close()
        # output to flie
        if (self.book_summary_file_overwrite == False and os.path.exists(os.path.join(dire, 'SUMMARY.md'))):
            # overwrite logic
            filename = 'SUMMARY-GitBook-auto-summary.md'
        else:
            filename = 'SUMMARY.md'
        with open(os.path.join(dire, filename), 'w', encoding='utf-8') as output:
            output.write('# 目录\n\n')
            output.write('* [简介](./README.md)\n')
            self.output_markdown(dire, dire, output)
        print('GitBook auto summary文件生成成功！')

    def create_gitbook_book_json(self, dire):
        json_data = json.dumps(self.book_json, ensure_ascii=False)
        with open(os.path.join(dire, 'book.json'), 'w', encoding='utf-8') as f:
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
            kindlegen_tool = self.basic_info['kindlegen_win']
        elif (sysstr == "Linux"):
            kindlegen_tool = self.basic_info['kindlegen_linux']
        elif (sysstr == "Mac"):
            kindlegen_tool = self.basic_info['kindlegen_mac']
        if not os.path.isfile(kindlegen_tool):
            print('kindlegen工具不存在脚本所在文件夹！请放入后重试！')
        else:
            #kindlegen [filename.opf/.htm/.html/.epub/.zip or directory] [-c0 or -c1 or c2] [-verbose] [-western] [-o <file name>]
            lang = self.book_language
            if lang == 'zh-hans' or lang == 'zh-tw':
                lang = 'zh'
            kindlegen_command = os.path.join('tools', kindlegen_tool) + ' ' + epub_path + '.epub' + ' -dont_append_source -c1 -verbose -locale ' + lang + ' -o ' + epub_path + '.mobi'
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
        with open(os.path.join(self.book_path, 'README.md'), 'w', encoding='utf-8') as readmeFile:
            readmeFile.write('# {}\n\n'.format('简介'))
            readmeFile.write('{}\n'.format(self.book_description))
        self.create_gitbook_book_json(self.book_path)
        epub_path = os.path.join(dire, 'docs', self.readTitle(dire))
        self.build_epub(dire, epub_path)
        self.build_mobi(epub_path)

class Ebookmaker(object):
    def __init__(self, basic_info):
        self.basic_info = basic_info
        self.basic_info['book_name'] = "MyBook"
        self.basic_info['book_author'] = "Ebookmaker"
        self.basic_info['book_date'] = "2021/07/31"
        self.basic_info['book_subject'] = "其他"
        self.basic_info['book_description'] = "Made by Ebookmaker!"
        if self.basic_info['book_chapter_file_suffic'] == ".md":
            self.basic_info['book_chapter_title_format_begin'] = '## '
            self.basic_info['book_chapter_title_format_end'] = '  '
            self.basic_info['book_chapter_text_format_begin'] = ''
            self.basic_info['book_chapter_text_format_end'] = ''
        elif self.basic_info['book_chapter_file_suffic'] == ".txt":
            self.basic_info['book_chapter_title_format_begin'] = ''
            self.basic_info['book_chapter_title_format_end'] = ''
            self.basic_info['book_chapter_text_format_begin'] = ''
            self.basic_info['book_chapter_text_format_end'] = ''
        #####################################################################################
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
            'Cookie':self.basic_info['book_cookie'],
            'Host':self.basic_info['book_host'],
            'Referer':self.basic_info['book_referer']
        }
        self.basic_info['work_thread_num'] = self.basic_info['ip_pool_web_num']
        self.semaphore = threading.BoundedSemaphore(self.basic_info['work_thread_num'])
        self.sem = threading.Semaphore()
        self.IP = []
        self.proxyPool = []
        self.book_chapter_urls = {}
        self.missing_urls = []
        self.book_chapter_dict = {}
        ######################################################################################
        self.kafcli_linux = 'kaf-cli-linux'
        self.kafcli_mac = 'kaf-cli-darwin'
        self.kafcli_win = 'kaf-cli.exe'
        self.kafcli_book_bottom = '1'
        self.kafcli_book_cover = 'cover.png'
        ######################################################################################

    def loadData(self,url,host=None,referer=None,cookie=None,proxy_pool=None,stream_mode=False):
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
                    response = requests.get(url, headers=self.headers, verify=False, stream=stream_mode, timeout=(10,10))
                elif len(proxy_pool) == 1:
                    response = requests.get(url, headers=self.headers, proxies=proxy_pool, verify=False, stream=stream_mode,timeout=(10,10))
                else:
                    proxy = random.choice(proxy_pool)
                    response = requests.get(url, headers=self.headers, proxies=proxy, verify=False, stream=stream_mode,timeout=(10,10))
                response.raise_for_status()
            except requests.RequestException as e:
                if try_agin_count == 0:
                    return 'ERROR'
                time.sleep(3)
            else:
                break
        if stream_mode == True:
            return response.content
        elif response.encoding:
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
        daili_data = self.loadData(self.basic_info['daili_url_base'] + str(idx+1), host=self.basic_info['daili_host'], referer=self.basic_info['daili_url_base'] + str(idx), cookie=self.basic_info['daili_cookie'])
        if daili_data != 'ERROR':
            # data-url="http://119.167.66.22:8081"
            for ip in re.findall(re.compile(self.basic_info['daili_re']), daili_data):
                self.sem.acquire()
                self.IP.append(ip)
                self.sem.release()
        if idx%50 != 0:
            print("*", end='')
        self.semaphore.release()

    def proxy_pool(self,idx):
        self.semaphore.acquire()
        self.sem.acquire()
        proxies = { "http" : "http://" + self.IP[idx]}
        self.sem.release()
        proxy_pool_data = self.loadData(self.basic_info['proxy_pool_url'], host=self.basic_info['proxy_pool_host'], proxy_pool=proxies)
        if proxy_pool_data != 'ERROR':
            self.sem.acquire()
            self.proxyPool.append(proxies)
            self.sem.release()
        if idx%50 != 0:
            print("*", end='')
        self.semaphore.release()

    def get_ip_pool(self):
        print('抓取代理IP池...')
        time_start = datetime.datetime.now()
        ip_threads = []
        for idx in range(self.basic_info['ip_pool_web_num']):
            t = threading.Thread(target=self.ip_pool,args=(idx,))
            t.start()
            ip_threads.append(t)
        wait_all_child_task_done(ip_threads)
        new_list = list(set(self.IP))
        new_list.sort(key=self.IP.index)
        self.IP = new_list
        time_end = datetime.datetime.now()
        print('代理IP池大小为{}，耗时：{}'.format(len(self.IP), time_end - time_start))

    def get_proxy_pool(self):
        time_start = datetime.datetime.now()
        proxy_pool_threads = []
        self.basic_info['work_thread_num'] = len(self.IP)
        print('线程数设置为：{}'.format(self.basic_info['work_thread_num']))
        self.semaphore = threading.BoundedSemaphore(self.basic_info['work_thread_num'])
        for idx in range(len(self.IP)):
            t = threading.Thread(target=self.proxy_pool,args=(idx,))
            t.start()
            proxy_pool_threads.append(t)
        wait_all_child_task_done(proxy_pool_threads)
        time_end = datetime.datetime.now()
        print('筛选后的代理池大小为{}，耗时：{}'.format(len(self.proxyPool), time_end - time_start))

    def get_book_info(self,dir):
        print('获取书籍信息...')
        time_start = datetime.datetime.now()
        res = self.loadData(self.basic_info['book_url'], host=self.basic_info['book_host'], referer=self.basic_info['book_referer'], cookie=self.basic_info['book_cookie'], proxy_pool=self.proxyPool[random.randint(0,len(self.proxyPool)-1)])
        if res == 'ERROR':
            print("访问失败: {:<64}".format(self.basic_info['book_url']))
            return list()
        self.basic_info['book_name'] = re.compile(self.basic_info['book_name_re']).findall(res)[0]
        self.basic_info['book_author'] = re.compile(self.basic_info['book_author_re']).findall(res)[0]
        self.basic_info['book_date'] = re.compile(self.basic_info['book_date_re']).findall(res)[0]
        self.basic_info['book_subject'] = re.compile(self.basic_info['book_subject_re']).findall(res)[0]
        self.basic_info['book_description'] = re.compile(self.basic_info['book_description_re']).findall(res)[0]
        self.basic_info['book_cover_url'] = re.compile(self.basic_info['book_cover_url_re']).findall(res)[0]
        self.book_chapter_urls = re.compile(self.basic_info['book_chapter_list_re']).findall(res)
        self.create_book_store_dir(os.path.join(dir, self.basic_info['book_name']))
        print('下载书籍封面图片...')
        image_path = os.path.join(dir, self.basic_info['book_name'], 'cover.pic')
        res = self.loadData(self.basic_info['book_cover_url'], host=self.basic_info['book_host'], referer=self.basic_info['book_referer'], cookie=self.basic_info['book_cookie'], proxy_pool=self.proxyPool[random.randint(0,len(self.proxyPool)-1)], stream_mode=True)
        if res == 'ERROR':
            print("访问失败: {:<64}".format(self.basic_info['book_cover_url']))
        else:
            with open(image_path, 'wb') as f:
                f.write(res)
        time_end = datetime.datetime.now()
        print("完成！耗时：{}\n书名：{}\n作者：{}\n类型：{}\n最后更新时间：{}\n简介：{}\n".format(time_end - time_start, self.basic_info['book_name'], self.basic_info['book_author'], self.basic_info['book_subject'], self.basic_info['book_date'], self.basic_info['book_description']))

    def work(self,dir,index,urls,cookie=None,proxy_pool=None):
        self.semaphore.acquire()
        write_path = os.path.join(dir, 'chapter' + str(index+1) + self.basic_info['book_chapter_file_suffic'])
        self.sem.acquire()
        self.book_chapter_dict[index+1] = urls[index][1]
        self.sem.release()
        if os.path.isfile(write_path):
            if os.path.getsize(write_path):
                print("文件已缓存: {:<64}".format(urls[index][1]))
                self.semaphore.release()
                return
        if self.basic_info['book_chapter_file_suffic'] == ".html":
            xml_path = os.path.join(dir, 'chapter0.html')
            xml = minidom.parse(xml_path)
            html = xml.documentElement
            html.setAttribute('xml:lang', self.basic_info['book_language'])
            html_head = html.getElementsByTagName('head')[0]
            html_head_metas = html_head.getElementsByTagName('meta')
            for meta in html_head_metas:
                if meta.hasAttribute('name'):
                    meta.setAttribute('content', self.basic_info['book_rights'])
            html_head_title = html_head.getElementsByTagName('title')[0].childNodes[0]
            html_head_title.nodeValue = 'chapter ' + str(index+1) + ' - 0'
            html_body = html.getElementsByTagName('body')[0]
            html_body_h2 = html_body.getElementsByTagName('h2')[0].childNodes[0]
            html_body_h2.nodeValue = urls[index][1]
        elif self.basic_info['book_chapter_file_suffic'] == ".txt" or self.basic_info['book_chapter_file_suffic'] == ".md":
            chapter_content = ""
            chapter_content += self.basic_info['book_chapter_title_format_begin'] + urls[index][1] + self.basic_info['book_chapter_title_format_end']
            chapter_content += '\n\n'
            if self.basic_info['book_chapter_file_suffic'] == ".md":
                chapter_content += '\n\n'
        chapter_html = self.loadData(self.basic_info['book_url'] + urls[index][0], host=self.basic_info['book_host'], referer=self.basic_info['book_url'], cookie=cookie, proxy_pool=proxy_pool)
        if chapter_html == 'ERROR':
            with open(write_path, 'w+', encoding='utf-8') as f:
                f.seek(0)
                f.truncate()
            print("访问失败: {:<64}".format(urls[index][1]))
            self.sem.acquire()
            self.missing_urls.append(urls[index])
            self.sem.release()
            self.semaphore.release()
            return
        for content in re.findall(re.compile(self.basic_info['book_chapter_content_re']), chapter_html):
            if self.basic_info['book_chapter_file_suffic'] == ".html":
                html_body_p = xml.createElement('p')
                html_body.appendChild(html_body_p)
                html_body_p_text = xml.createTextNode(content)
                html_body_p.appendChild(html_body_p_text)
                html_body_p.setAttribute('class', 'a')
            elif self.basic_info['book_chapter_file_suffic'] == ".txt" or self.basic_info['book_chapter_file_suffic'] == ".md":
                chapter_content += self.basic_info['book_chapter_text_format_begin'] + content + self.basic_info['book_chapter_text_format_end']
                if self.basic_info['book_chapter_file_suffic'] == ".md":
                    chapter_content += '\n\n'
                elif self.basic_info['book_chapter_file_suffic'] == ".txt":
                    chapter_content += '\n'
        with open(write_path, 'w+', encoding='utf-8') as f:
            if self.basic_info['book_chapter_file_suffic'] == ".html":
                xml.writexml(f, newl = '\n', addindent = '\t', encoding='utf-8')
                xml.unlink()
            elif self.basic_info['book_chapter_file_suffic'] == ".txt" or self.basic_info['book_chapter_file_suffic'] == ".md":
                f.write(chapter_content)
            print("写入成功: {:<64}".format(urls[index][1]))
        self.semaphore.release()

    def create_book_store_dir(self,dir):
        print('开始创建书籍存档目录：%s...' %dir)
        if not os.path.exists(dir):
            os.makedirs(dir)

    def fetch_and_store_urls(self,dir,urls):
        print('开始抓取并存入文件...')
        time_start = datetime.datetime.now()
        work_threads = []
        self.basic_info['work_thread_num'] = len(self.proxyPool) * 10
        print('线程数设置为：{}'.format(self.basic_info['work_thread_num']))
        self.semaphore = threading.BoundedSemaphore(self.basic_info['work_thread_num'])
        chapter_len = len(urls)
        for idx in range(chapter_len):
            t = threading.Thread(target=self.work,args=(dir,idx,urls,self.basic_info['book_cookie'],self.proxyPool[random.randint(0,len(self.proxyPool)-1)]))
            t.start()
            work_threads.append(t)
        wait_all_child_task_done(work_threads, print_char='')
        time_end = datetime.datetime.now()
        print('完成！耗时：{}'.format(time_end - time_start))

    def write_content_opf(self,dir):
        print('写入content.opf...')
        time_start = datetime.datetime.now()
        xml_path = os.path.join(dir, 'OEBPS', 'content.opf')
        xml = minidom.parse(xml_path)
        package = xml.documentElement
        metadata = package.getElementsByTagName('metadata')[0]
        metadata.getElementsByTagName('dc:identifier')[0].firstChild.data = 'Ebookmaker-' + hashlib.md5(self.basic_info['book_name'].encode(encoding='UTF-8')).hexdigest()[0:7]
        metadata.getElementsByTagName('dc:title')[0].firstChild.data = self.basic_info['book_name']
        metadata.getElementsByTagName('dc:creator')[0].firstChild.data = self.basic_info['book_author']
        metadata.getElementsByTagName('dc:date')[0].firstChild.data = self.basic_info['book_date']
        metadata.getElementsByTagName('dc:publisher')[0].firstChild.data = self.basic_info['book_publisher']
        metadata.getElementsByTagName('dc:rights')[0].firstChild.data = self.basic_info['book_rights']
        metadata.getElementsByTagName('dc:language')[0].firstChild.data = self.basic_info['book_language']
        metadata.getElementsByTagName('dc:subject')[0].firstChild.data = self.basic_info['book_subject']
        metadata.getElementsByTagName('dc:description')[0].firstChild.data = self.basic_info['book_description']
        manifest = package.getElementsByTagName('manifest')[0]
        for chapter_index in sorted(self.book_chapter_dict):
            chapter_item = xml.createElement('item')
            manifest.appendChild(chapter_item)
            chapter_item.setAttribute('id', 'chapter' + str(chapter_index))
            chapter_item.setAttribute('href', 'chapter' + str(chapter_index) + '.html')
            chapter_item.setAttribute('media-type', 'application/xhtml+xml')
        spine = package.getElementsByTagName('spine')[0]
        for chapter_index in sorted(self.book_chapter_dict):
            chapter_item = xml.createElement('itemref')
            spine.appendChild(chapter_item)
            chapter_item.setAttribute('idref', 'chapter' + str(chapter_index))
            chapter_item.setAttribute('linear', 'yes')
        with open(xml_path, 'w', encoding='utf-8') as f:
            xml.writexml(f, newl = '\n', addindent = '\t',encoding='utf-8')
        time_end = datetime.datetime.now()
        print('完成！耗时：{}'.format(time_end - time_start))

    def write_toc_ncx(self,dir):
        print('写入toc.ncx...')
        time_start = datetime.datetime.now()
        xml_path = os.path.join(dir, 'OEBPS', 'toc.ncx')
        xml = minidom.parse(xml_path)
        ncx = xml.documentElement
        head = ncx.getElementsByTagName('head')[0]
        metas = head.getElementsByTagName('meta')
        for meta in metas:
            if meta.getAttribute('name') == 'dtb:uid':
                meta.setAttribute('content', 'Ebookmaker-' + hashlib.md5(self.basic_info['book_name'].encode(encoding='UTF-8')).hexdigest()[0:7])
        docTitle = ncx.getElementsByTagName('docTitle')[0]
        docTitle_text = docTitle.getElementsByTagName('text')[0]
        docTitle_text.data = self.basic_info['book_name']
        docAuthor = ncx.getElementsByTagName('docAuthor')[0]
        docAuthor_text = docAuthor.getElementsByTagName('text')[0]
        docAuthor_text.data = self.basic_info['book_author']

        navMap = ncx.getElementsByTagName('navMap')[0]
        for chapter_index in sorted(self.book_chapter_dict):
            navPoint = xml.createElement('navPoint')
            navMap.appendChild(navPoint)
            navPoint.setAttribute('id', 'chapter' + str(chapter_index))
            navPoint.setAttribute('playOrder', str(chapter_index))
            navPoint_navLabel = xml.createElement('navLabel')
            navPoint.appendChild(navPoint_navLabel)
            navPoint_navLabel_text = xml.createElement('text')
            navPoint_navLabel.appendChild(navPoint_navLabel_text)
            navPoint_navLabel_text_title = xml.createTextNode(self.book_chapter_dict[chapter_index])
            navPoint_navLabel_text.appendChild(navPoint_navLabel_text_title)
            navPoint_content = xml.createElement('content')
            navPoint.appendChild(navPoint_content)
            navPoint_content.setAttribute('src', 'chapter' + str(chapter_index) + '.html')
        with open(xml_path, 'w', encoding='utf-8') as f:
            xml.writexml(f, newl = '\n', addindent = '\t',encoding='utf-8')
        time_end = datetime.datetime.now()
        print('完成！耗时：{}'.format(time_end - time_start))

    def write_cover_html(self,dir):
        print('写入cover.html...')
        time_start = datetime.datetime.now()
        xml_path = os.path.join(dir, 'OEBPS', 'cover.html')
        xml = minidom.parse(xml_path)
        html = xml.documentElement
        body = html.getElementsByTagName('body')[0]
        divs = body.getElementsByTagName('div')
        for div in divs:
            if div.getAttribute('class') == 'container':
                table = div.getElementsByTagName('table')[0]
                tr = table.getElementsByTagName('tr')[0]
                td = tr.getElementsByTagName('td')[0]
                img = td.getElementsByTagName('img')[0]
                img.setAttribute('alt', self.basic_info['book_name'])
        with open(xml_path, 'w', encoding='utf-8') as f:
            xml.writexml(f, newl = '\n', addindent = '\t',encoding='utf-8')
        time_end = datetime.datetime.now()
        print('完成！耗时：{}'.format(time_end - time_start))

    def write_book_toc_html(self,dir):
        print('写入book-toc.html...')
        time_start = datetime.datetime.now()
        xml_path = os.path.join(dir, 'OEBPS', 'book-toc.html')
        xml = minidom.parse(xml_path)
        html = xml.documentElement
        html.setAttribute('xml:lang', self.basic_info['book_language'])
        html_head = html.getElementsByTagName('head')[0]
        html_head_metas = html_head.getElementsByTagName('meta')
        for meta in html_head_metas:
            if meta.hasAttribute('name'):
                meta.setAttribute('content', self.basic_info['book_rights'])
        html_body = html.getElementsByTagName('body')[0]
        html_body_div = html_body.getElementsByTagName('div')[0]
        html_body_div_dl = html_body_div.getElementsByTagName('dl')[0]
        for chapter_index in sorted(self.book_chapter_dict):
            html_body_div_dl_dt = xml.createElement('dt')
            html_body_div_dl.appendChild(html_body_div_dl_dt)
            html_body_div_dl_dt.setAttribute('class', 'tocl2')
            html_body_div_dl_dt_a = xml.createElement('a')
            html_body_div_dl_dt.appendChild(html_body_div_dl_dt_a)
            html_body_div_dl_dt_a_text = xml.createTextNode(self.book_chapter_dict[chapter_index])
            html_body_div_dl_dt_a.appendChild(html_body_div_dl_dt_a_text)
            html_body_div_dl_dt_a.setAttribute('href', 'chapter' + str(chapter_index) + '.html')
        with open(xml_path, 'w', encoding='utf-8') as f:
            xml.writexml(f, newl = '\n', addindent = '\t',encoding='utf-8')
        time_end = datetime.datetime.now()
        print('完成！耗时：{}'.format(time_end - time_start))

    def create_epub(self,dir):
        print('生成epub文件...')
        time_start = datetime.datetime.now()
        meta_inf_path = os.path.join(dir, 'META-INF')
        oebps_path = os.path.join(dir, 'OEBPS')
        mimetype_path = os.path.join(dir, 'mimetype')
        epub_path = os.path.join(dir, self.basic_info['book_name'] + '.epub')
        if not os.path.exists(meta_inf_path) or not os.path.exists(oebps_path) or not os.path.exists(mimetype_path):
            print("创建ePub失败！META-INF, OEBPS或mimetype不存在。")
            return
        time_start = datetime.datetime.now()
        zfile = zipfile.ZipFile(epub_path, 'w', zipfile.ZIP_DEFLATED)
        for epubdir in [meta_inf_path, oebps_path]:
            for dirpath, dirs, files in os.walk(epubdir):
                for file in files:
                    zfile.write(os.path.join(dirpath, file))
        zfile.write(mimetype_path)
        zfile.close()
        time_end = datetime.datetime.now()
        print('完成！耗时：{}'.format(time_end - time_start))

    def write_md_title(self,dir):
        print('写入标题和目录...')
        time_start = datetime.datetime.now()
        path = os.path.join(dir, self.basic_info['book_name'] + self.basic_info['book_chapter_file_suffic'])
        with open(path, 'w+', encoding='utf-8') as f:
            f.write('# 目录 \n\n')
            f.write('--------------------\n\n')
            for chapter_index in sorted(self.book_chapter_dict):
                chapter_title = self.book_chapter_dict[chapter_index]
                f.write('  - [' + chapter_title + '](#' + re.sub(' |？|，|！|……', '-', chapter_title) + ')\n')
            f.write('\n')
        time_end = datetime.datetime.now()
        print('完成！耗时：{}'.format(time_end - time_start))

    def write_chapters(self,dir):
        print('写入所有章节...')
        time_start = datetime.datetime.now()
        res = ""
        for chapter_index in sorted(self.book_chapter_dict):
            file = self.book_chapter_dict[chapter_index] + self.basic_info['book_chapter_file_suffic']
            path = os.path.join(dir, file)
            with open(path, 'r', encoding='utf-8') as file:
                content = file.read()
            res += content
        path = os.path.join(dir, self.basic_info['book_name'] + self.basic_info['book_chapter_file_suffic'])
        with open(path, 'a+', encoding='utf-8') as f:
            f.write(res)
        time_end = datetime.datetime.now()
        print('完成！耗时：{}'.format(time_end - time_start))

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
            --to=epub \
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
        time_start = datetime.datetime.now()
        epub_output_path = os.path.join(dir, self.basic_info['book_name'] + '.epub')
        css_path = os.path.join(dir, 'epub.css')
        cover_path = os.path.join(dir, 'cover.jpg')
        templater_path = os.path.join(dir, 'epub.template')
        pandoc_command = 'pandoc --from=markdown --to=epub3 --atx-headers --variable=lang=zh_CN --standalone --wrap=preserve --verbose ' + ' --template=' + templater_path + ' --metadata title=' + self.basic_info['book_name'] + ' --metadata author=' + self.basic_info['book_author'] + ' --metadata description=' + self.basic_info['book_description'] + ' --metadata css=' + css_path + ' --metadata cover-image=' + cover_path + ' --output=' + epub_output_path + ' ' + os.path.join(dir, self.basic_info['book_name'] + '.md')
        ret = subprocess.Popen(pandoc_command,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding="utf-8")
        while True:
            r = ret.stdout.readline()
            if not r:
                break
            else:
                print(r.strip())
        time_end = datetime.datetime.now()
        if ret.returncode != None:
            print('失败! 耗时：{}\n{}\n'.format(time_end - time_start, ret.returncode))
        else:
            print('完成！耗时：{}'.format(time_end - time_start))

    def convert_by_ebook_convert(self,dir):
        '''
        TBD: use ebook-convert cmdline to convert markdown file to mobi/azw3
        #fmt.Print(fmt.Sprintf("ebook-convert %s %s --authors %s --comments '%s' --level1-toc '//h:h1' --level2-toc '//h:h2' --language '%s'\n", Tmp, Mobi, Author, Comment, Lang))
        ebook-convert 1.epub 1.mobi \
            --input-profile=kindle --output-profile=kindle_pw3 --extra-css=epub.css \
            --expand-css --remove-paragraph-spacing-indent-size=2 --remove-first-image --chapter-mark=pagebreak \
            --prefer-metadata-cover --insert-metadata --level1-toc=//h:h1 --level2-toc=//h:h2 --level3-toc=//h:h3 \
            --max-toc-links=0 --use-auto-toc --mobi-toc-at-start --pretty-print \
            --title="武神主宰" \
            --authors="暗魔师" \
            --cover=cover.jpg \
            --comments="天武大陆一代传奇秦尘，因好友背叛意外陨落武域。三百年后，他转生在一个受尽欺凌的王府私生子身上，利用前世造诣，凝神功、炼神丹，逆天而上，强势崛起，从此踏上一段震惊大陆的惊世之旅。" \
            --publisher="ireader" \
            --tags="小说" \
            --book-producer="越光" \
            --language=zh
        '''
        print('转换为azw3/mobi电子书格式...')
        time_start = datetime.datetime.now()
        ebook_convert_command = 'ebook-convert ' + os.path.join(dir, self.basic_info['book_name'] + '.epub') + ' ' + os.path.join(dir, self.basic_info['book_name'] + '.azw3')
        ret = subprocess.Popen(ebook_convert_command,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding="utf-8")
        while True:
            r = ret.stdout.readline()
            if not r:
                break
            else:
                print(r.strip())
        time_end = datetime.datetime.now()
        if ret.returncode != None:
            print('失败! 耗时：{}\n{}\n'.format(time_end - time_start, ret.returncode))
        else:
            print('完成！耗时：{}'.format(time_end - time_start))

    def convert_by_kafcli(dir,self):
        print('转换为Kindle电子书格式...')
        time_start = datetime.datetime.now()
        sysstr = platform.system()
        if (sysstr == "Windows"):
            kafcli_tool = self.kafcli_win
        elif (sysstr == "Linux"):
            kafcli_tool = self.kafcli_linux
        elif (sysstr == "Mac"):
            kafcli_tool = self.kafcli_mac
        kafcli_tool = os.path.join(self.basic_info['tools_base_path'], kafcli_tool)
        if not os.path.isfile(kafcli_tool):
            print('kaf-cli工具不存在脚本同目录下tools所在文件夹！请放入后重试！')
        else:
            kafcli_command = kafcli_tool + ' -filename ' + os.path.join(dir, self.basic_info['book_name'] + self.basic_info['book_chapter_file_suffic']) + ' -bookname ' + self.basic_info['book_name'] + ' -author ' + self.basic_info['book_author'] + ' -cover ' + self.kafcli_book_cover + ' -bottom ' + self.kafcli_book_bottom
            ret = subprocess.Popen(kafcli_command,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding="utf-8")
            while True:
                r = ret.stdout.readline()
                if not r:
                    break
                else:
                    print(r.strip())
            time_end = datetime.datetime.now()
            if ret.returncode != None:
                print('失败! 耗时：{}\n{}\n'.format(time_end - time_start, ret.returncode))
            else:
                print('完成！耗时：{}'.format(time_end - time_start))

    def convert_by_kindlegen(self,dir):
        print('转换为Kindle电子书格式...')
        time_start = datetime.datetime.now()
        sysstr = platform.system()
        if (sysstr == "Windows"):
            kindlegen_tool = self.basic_info['kindlegen_win']
        elif (sysstr == "Linux"):
            kindlegen_tool = self.basic_info['kindlegen_linux']
        elif (sysstr == "Mac"):
            kindlegen_tool = self.basic_info['kindlegen_mac']
        kindlegen_tool = os.path.join(self.basic_info['tools_base_path'], kindlegen_tool)
        if not os.path.isfile(kindlegen_tool):
            print('kindlegen工具不存在脚本同目录下tools所在文件夹！请放入后重试！')
        else:
            lang = self.basic_info['book_language']
            if lang == 'zh-CN':
                lang = 'zh'
            epub_path = os.path.join(dir, self.basic_info['book_name'] + '.epub')
            output_path = self.basic_info['book_name'] + '.mobi'
            kindlegen_command = kindlegen_tool + ' ' + epub_path + ' -dont_append_source -verbose -c' + self.basic_info['kindlegen_book_compression_level'] + ' -locale ' + lang + ' -o ' + output_path
            ret = subprocess.Popen(kindlegen_command,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding="utf-8")
            while True:
                r = ret.stdout.readline()
                if not r:
                    break
                else:
                    print(r.strip())
            time_end = datetime.datetime.now()
            if ret.returncode != None:
                print('失败! 耗时：{}\n{}\n'.format(time_end - time_start, ret.returncode))
            else:
                print('完成！耗时：{}'.format(time_end - time_start))

def wait_all_child_task_done(thread_list, print_char='*'):
    cnt = 0
    while True:
        cnt += 1
        for t in thread_list:
            if not t.is_alive():
                thread_list.remove(t)
        if len(thread_list) == 0:
            print('')
            break
        else:
            print(print_char, end='', flush=True)
            if cnt%50 == 0:
                print('')
            time.sleep(0.5)

def copy_dir(src_path, dest_path):
    if src_path == dest_path:
        return
    if os.path.isfile(src_path):
        if os.path.exists(dest_path):
            os.remove(dest_path)
        shutil.copy(src_path, dest_path)
    elif os.path.isdir(src_path):
        if not os.path.exists(dest_path):
            os.makedirs(dest_path)
        for file in os.listdir(src_path):
            copy_dir(os.path.join(src_path, file), os.path.join(dest_path, file))

def main():
    """
    basic_info = {
        'book_name': 'MyBook',
        'book_author': 'Ebookmaker',
        'book_date': '2021/07/31',
        'book_publisher': 'Ebookmaker',
        'book_rights': 'Created with Ebookmaker v1.0',
        'book_language': 'zh-CN',
        'book_subject': '小说',
        'book_description': 'Made by Ebookmaker!',
        'ebooks_labrary_path': os.path.join('.', 'ebooks'),
        'book_url': 'https://www.xbooktxt.net/2_2588/',                #https://www.xbiquge.la/66/66747/
        'book_host': 'www.xbooktxt.net',                               #www.xbiquge.la
        'book_referer': 'https://www.xbooktxt.net/2_2588/685752.html', #https://www.xbiquge.la/66/66747/26547971.html
        'book_cookie': 'UM_distinctid=17ac9cdf4d0d3f-09ee6521cf9cfd-6373264-384000-17ac9cdf4d1146c; CNZZDATA1266846634=2004344946-1626881060-https%3A%2F%2Fwww.baidu.com%2F|1626881060; hitbookid=2588; PPad_id_PP=5; hitme=2', #_abcde_qweasd=0; Hm_lvt_169609146ffe5972484b0957bd1b46d6=1626520436,1626585865; Hm_lpvt_169609146ffe5972484b0957bd1b46d6=1626597513
        'book_chapter_file_suffic': '.html',
        'book_name_re':re.compile(r'<meta property="og:novel:book_name" content="(.*?)"/>'),                           #re.compile(r'<meta property="og:name" content="(.*?)"/>')
        'book_description_re':re.compile(r'<meta property="og:description" content="(.*?)"/>'),                        #re.compile(r'<meta property="og:description" content="(.*?)"/>')
        'book_date_re':re.compile(r'<meta property="og:novel:update_time" content="(2\d{3}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"/>'),
        'book_subject_re':re.compile(r'<meta property="og:novel:category" content="(.*?)"/>'),
        'book_author_re':re.compile(r'<meta property="og:novel:author" content="(.*?)"/>'),                            #re.compile(r'<meta property="og:novel:author" content="(.*?)"/>')
        'book_cover_url_re':re.compile(r'<meta property="og:image" content="(https:\/\/www.*?jpg)"/>')
        'book_chapter_list_re':re.compile(r'<dd><a href="/2_2588/([0-9]{5,6}\.html)"  >(.*?)</a></dd>'), #re.compile(r'<dd><a href=\'/66/66747/([0-9]{8}\.html)\' >(.*?)</a></dd>')
        'book_chapter_content_re':re.compile(r'&nbsp;&nbsp;&nbsp;&nbsp;(.*?)<br><br>', re.S),                         #re.compile(r'<br />&nbsp;&nbsp;&nbsp;&nbsp;.*?\r<br />', re.S)
        'daili_url_base': 'https://ip.jiangxianli.com/?page=',
        'daili_host': 'ip.jiangxianli.com',
        'daili_cookie': 'UM_distinctid=17abfa06f89dc5-0f97a150c82592-6373264-384000-17abfa06f8ad3c; Hm_lvt_b72418f3b1d81bbcf8f99e6eb5d4e0c3=1626712600,1626886778,1626886791,1626886800; Hm_lpvt_b72418f3b1d81bbcf8f99e6eb5d4e0c3=1626886832',
        'daili_re': re.compile(r'data-url="http://(\d+\.\d+\.\d+\.\d+:\d+)"'),
        'proxy_pool_url': 'http://httpbin.org/ip',
        'proxy_pool_host': 'httpbin.org'
    }
    """
    with open(os.path.join('configs', 'settings.json'), 'r', encoding='utf-8') as f:
        basic_info = json.load(f)
    print('配置参数：\n{}'.format(json.dumps(basic_info, sort_keys=True, indent=4, separators=(', ', ': '))))

    em = Ebookmaker(basic_info)    
    em.get_ip_pool()
    if len(em.IP) == 0:
        print('IP代理池大小为0！请重新获取！')
        return
    em.get_proxy_pool()
    if len(em.proxyPool) == 0:
        print('可用的IP代理池大小为0！请重新获取！')
        return
    em.get_book_info(os.path.join(em.basic_info['ebooks_labrary_path']))
    if not em.book_chapter_urls:
        return

    book_path = os.path.join(em.basic_info['ebooks_labrary_path'], em.basic_info['book_name'])
    print('拷贝模板文件到书籍生成目录...')
    copy_dir('template', book_path)

    print('拷贝封面图片到书籍生成目录...')
    book_cover_path = os.path.join(book_path, 'cover.jpg')
    if em.basic_info['book_chapter_file_suffic'] == ".html":
        book_cover_path = os.path.join(book_path, 'OEBPS', 'cover.jpg')
    if os.path.exists(os.path.join(book_path, 'cover.pic')):
        shutil.move(os.path.join(book_path, 'cover.pic'), book_cover_path)

    print('将所有章节存入文件...')
    book_chapters_path = book_path
    if em.basic_info['book_chapter_file_suffic'] == ".html":
        book_chapters_path = os.path.join(book_path, 'OEBPS')
        chapter_template_file = os.path.join(book_chapters_path, 'chapter0.html')
        if not os.path.exists(chapter_template_file):
            print('章节模板文件不存在！请检查后重试。')
            return
    em.fetch_and_store_urls(book_chapters_path, em.book_chapter_urls)
    if em.basic_info['book_chapter_file_suffic'] == ".html":
        os.remove(chapter_template_file)

    retry_count = em.basic_info['book_chapter_retry_count']
    while retry_count:
        if len(em.missing_urls):
            retry_count -= 1
            print('尝试重新处理写入失败的章节，剩余{}次...'.format(retry_count))
            em.fetch_and_store_urls(book_chapters_path, em.missing_urls)
        else:
            break

    # Use kaf-cli to convert ePub book
    '''
    TBD: vs code reg need to do after merge chapters:
        ”([^\n]).*? => "\n$1
        (“.*?[^”]$)\n$ => $1"\n
        " => ”
        'i' => ''
        ，; => '，'
        ”\n， => ”，
        &nbsp => ''
    '''
    if em.basic_info['book_chapter_file_suffic'] == ".md":
        em.write_md_title(book_path)
        em.write_chapters(book_path)
        #em.convert_by_kafcli(book_path)
        em.convert_by_pandoc(book_path)
        em.convert_by_ebook_convert(book_path)
    elif em.basic_info['book_chapter_file_suffic'] == ".txt":
        em.write_chapters(book_path)
        #em.convert_by_kafcli(book_path)
    elif em.basic_info['book_chapter_file_suffic'] == ".html":
        em.write_content_opf(book_path)
        em.write_toc_ncx(book_path)
        em.write_cover_html(book_path)
        em.write_book_toc_html(book_path)
        em.create_epub(book_path)
        em.convert_by_kindlegen(book_path)

    # Use gitbook to build mobi book
    #gh = GitbookHelper(book_path, em.basic_info['book_name'], em.basic_info['book_author'], em.basic_info['book_description'])
    #gh.convert(book_path)

if __name__ == '__main__':
    main()
