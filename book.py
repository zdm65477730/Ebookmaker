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
urllib3.disable_warnings(InsecureRequestWarning)

'''
To get free proxy website, check:
http://t.zoukankan.com/whnba-p-11878802.html

www.kuaidaili.com/free:
    "daili_url_base": "https://www.kuaidaili.com/free/inha/",
    "daili_host": "ip.jiangxianli.com",
    "daili_cookie": "",
    "daili_re": "<td data-title=\"IP\">(\\d+\\.\\d+\\.\\d+\\.\\d+)</td>\n                    <td data-title=\"PORT\">(\\d+)</td>",

www.89ip.cn:
    "daili_url_base": "https://www.89ip.cn/index_",
    "daili_host": "www.89ip.cn",
    "daili_cookie": "",
    "daili_re": "<tr>\n\t\t<td>\n\t\t\t(\\d+\\.\\d+\\.\\d+\\.\\d+)\t\t</td>\n\t\t<td>\n\t\t\t(\\d+)\t\t</td>",

'''

class Ebookmaker(object):
    def __init__(self, basic_info):
        self.basic_info = basic_info
        self.basic_info['book_name'] = "MyBook"
        self.basic_info['book_author'] = "Ebookmaker"
        self.basic_info['book_date'] = time.strftime("%Y/%m/%d", time.localtime())
        self.basic_info['book_subject'] = "其他"
        self.basic_info['book_description'] = "Made by Ebookmaker!"
        if not self.basic_info['book_chapter_url']:
            self.basic_info['book_chapter_url'] = self.basic_info['book_url']
        if not self.basic_info['book_fetch_retry_count']:
            self.basic_info['book_fetch_retry_count'] = 1
        if not self.basic_info['book_fetch_delay']:
            self.basic_info['book_fetch_delay'] = 3
        if not self.basic_info['daili_fetch_retry_count']:
            self.basic_info['daili_fetch_retry_count'] = 5
        if not self.basic_info['daili_fetch_delay']:
            self.basic_info['daili_fetch_delay'] = 1
        if not self.basic_info['daili_fetch_max_num']:
            self.basic_info['daili_fetch_max_num'] = 50
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
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.5060.53 Safari/537.36 Edg/103.0.1264.37'
        ]
        self.headers = { 
            'accept':'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'accept-encoding':'gzip,deflate,br',
            'accept-language':'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'connection':'keep-alive',
            'cache-Control':'max-age=0',
            'sec-ch-ua':'" Not;A Brand";v="99", "Microsoft Edge";v="103", "Chromium";v="103"',
            'sec-ch-ua-mobile':'?0',
            'sec-fetch-dest':'document',
            'sec-fetch-mode':'navigate',
            'sec-fetch-site':'none',
            'sec-fetch-user':'?1',
            'upgrade-insecure-requests':'1',
            'user-agent':random.choice(user_agent_list),
            'cookie':self.basic_info['book_cookie'],
            'host':self.basic_info['book_host'],
            'referer':self.basic_info['book_referer']
        }
        self.basic_info['work_thread_num'] = self.basic_info['daili_web_num']
        self.semaphore = threading.BoundedSemaphore(self.basic_info['work_thread_num'])
        self.IP = []
        self.proxyPool = []
        self.book_chapter_urls = []
        self.missing_urls = []

    def loadData(self,url,host=None,referer=None,cookie=None,proxy_pool=None,stream_mode=False):
        if host == None:
            host = ''
        if referer == None:
            referer = ''
        if cookie == None:
            cookie = ''
        self.headers.update({'cookie': cookie})
        self.headers.update({'host': host})
        self.headers.update({'referer': referer})
        try:
            if proxy_pool == None:
                response = requests.get(url, headers=self.headers, verify=False, stream=stream_mode, timeout=(10,10))
            elif len(proxy_pool) == 1:
                response = requests.get(url, headers=self.headers, proxies=proxy_pool, verify=False, stream=stream_mode,timeout=(10,10))
            else:
                proxy = random.choice(proxy_pool)
                response = requests.get(url, headers=self.headers, proxies=proxy, verify=False, stream=stream_mode,timeout=(10,10))
            response.raise_for_status()
        except requests.RequestException as e:
            return 'ERROR'
        if stream_mode == True:
            return response.content
        elif response.encoding:
            if response.encoding == 'ISO-8859-1' or response.encoding == 'iso-8859-1':
                encodings = requests.utils.get_encodings_from_content(response.text)
                if encodings:
                    encoding = encodings[0]
                else:
                    encoding = response.apparent_encoding
                if response.encoding == 'gb2312' or response.encoding == 'GB2312':
                    encoding = 'gbk'
            else:
                encoding = response.encoding
        else:
            encoding = 'utf-8'
        encode_content = response.content.decode(encoding, 'ignore')
        #print('##########')
        #print(url)
        #print(encode_content)
        #print('##########')
        return encode_content

    def ip_pool(self,idx):
        self.semaphore.acquire()
        daili_data = self.loadData(self.basic_info['daili_url_base'] + str(idx) + '.html', host=self.basic_info['daili_host'], referer=self.basic_info['daili_url_base'] + str(idx), cookie=self.basic_info['daili_cookie'])
        if daili_data != 'ERROR':
            for ip in re.findall(re.compile(self.basic_info['daili_re']), daili_data):
                ip_port = ip[0] + ':' + ip[1]
                if self.IP.count(ip_port) == 0:
                    self.IP.append(ip_port)
        self.semaphore.release()

    def proxy_pool(self,idx):
        self.semaphore.acquire()
        proxies = { "http" : "http://" + self.IP[idx]}
        proxy_pool_data = self.loadData(self.basic_info['proxy_pool_url'], host=self.basic_info['proxy_pool_host'], proxy_pool=proxies)
        if proxy_pool_data != 'ERROR':
            if self.proxyPool.count(proxies) == 0:
                self.proxyPool.append(proxies)
        self.semaphore.release()

    def get_ip_pool(self):
        print('抓取代理IP池...')
        time_start = datetime.datetime.now()
        retry = self.basic_info['daili_fetch_retry_count']
        while retry:
            ip_threads = []
            for idx in range(self.basic_info['daili_web_num']):
                t = threading.Thread(target=self.ip_pool,args=(idx+1,))
                t.start()
                ip_threads.append(t)
            wait_all_child_task_done(ip_threads)
            if len(self.IP) < self.basic_info['daili_fetch_max_num']:
                retry -= 1
                print('抓取的IP地址池大小：{} < {}，尝试重新获取代理IP池，剩余{}次...'.format(len(self.IP), self.basic_info['daili_fetch_max_num'], retry))
                if self.basic_info['daili_fetch_delay'] != 0:
                    time.sleep(self.basic_info['daili_fetch_delay'])
            else:
                break
        time_end = datetime.datetime.now()
        print('代理IP池大小为{}，耗时：{}'.format(len(self.IP), time_end - time_start))

    def get_proxy_pool(self):
        print('筛选代理IP池...')
        self.basic_info['work_thread_num'] = len(self.IP)
        print('线程数设置为：{}'.format(self.basic_info['work_thread_num']))
        self.semaphore = threading.BoundedSemaphore(self.basic_info['work_thread_num'])
        time_start = datetime.datetime.now()
        retry = self.basic_info['daili_fetch_retry_count']
        while retry:
            proxy_pool_threads = []
            for idx in range(len(self.IP)):
                t = threading.Thread(target=self.proxy_pool,args=(idx,))
                t.start()
                proxy_pool_threads.append(t)
            wait_all_child_task_done(proxy_pool_threads)
            if len(self.proxyPool) < len(self.IP):
                retry -= 1
                if self.basic_info['daili_fetch_delay'] != 0:
                    time.sleep(self.basic_info['daili_fetch_delay'])
                print('筛选的IP地址池大小：{} < {}，尝试重新获取代理IP池，剩余{}次...'.format(len(self.proxyPool), len(self.IP), retry))
            else:
                break
        time_end = datetime.datetime.now()
        print('筛选后的代理池大小为{}，耗时：{}'.format(len(self.proxyPool), time_end - time_start))

    def get_book_info(self,dir):
        print('获取书籍信息...')
        time_start = datetime.datetime.now()
        retry = self.basic_info['book_fetch_retry_count']
        while retry:
            res = self.loadData(self.basic_info['book_url'], host=self.basic_info['book_host'], referer=self.basic_info['book_referer'], cookie=self.basic_info['book_cookie'], proxy_pool=self.proxyPool[random.randint(0,len(self.proxyPool)-1)])
            if res == 'ERROR':
                retry -= 1
                print('尝试重新获取书籍信息，剩余{}次...'.format(retry))
                time.sleep(self.basic_info['book_fetch_delay'])
            else:
                break
        if retry == 0:
            print("访问失败: {:<64}".format(self.basic_info['book_url']))
            return
        self.basic_info['book_name'] = re.compile(self.basic_info['book_name_re']).findall(res)[0]
        self.basic_info['book_author'] = re.compile(self.basic_info['book_author_re']).findall(res)[0]
        self.basic_info['book_date'] = re.compile(self.basic_info['book_date_re']).findall(res)[0]
        self.basic_info['book_subject'] = re.compile(self.basic_info['book_subject_re']).findall(res)[0]
        self.basic_info['book_description'] = re.compile(self.basic_info['book_description_re']).findall(res)[0]
        self.basic_info['book_cover_url'] = re.compile(self.basic_info['book_cover_url_re']).findall(res)[0]
        self.book_chapter_urls = re.compile(self.basic_info['book_chapter_list_re']).findall(res)
        self.book_chapter_urls.sort(key=lambda x: int(re.compile(r'(?<=第)(?:[\s]*)(\d+?)(?:[\s]*)(?=章)').findall(x[1])[0]))
        for idx in range(len(self.book_chapter_urls) - 1, -1, -1):
            if len(re.compile(r'(第[\s]+\d+?[\s]+章)').findall(self.book_chapter_urls[idx][1])) > 0:
                self.book_chapter_urls.remove(self.book_chapter_urls[idx])
        book_chapter_number = []
        [book_chapter_number.append(int(re.compile(r'第(\d+?)章').findall(item[1])[0])) for item in self.book_chapter_urls]
        for idx in range(len(self.book_chapter_urls) - 1, -1, -1):
            if book_chapter_number.count(book_chapter_number[idx]) > 1:
                book_chapter_number.remove(book_chapter_number[idx])
                self.book_chapter_urls.remove(self.book_chapter_urls[idx])
        # self.book_chapter_urls.insert(3030, ('745991.html', '第3031章 尊者秘闻'))
        print('开始创建书籍存档目录：%s...' %dir)
        book_store_path = os.path.join(dir, self.basic_info['book_name'])
        if not os.path.exists(book_store_path):
            os.makedirs(book_store_path)
        print('下载书籍封面图片...')
        image_path = os.path.join(dir, self.basic_info['book_name'], 'cover.pic')
        res = self.loadData('https://' + self.basic_info['book_host'] + self.basic_info['book_cover_url'], host=self.basic_info['book_host'], referer=self.basic_info['book_referer'], cookie=self.basic_info['book_cookie'], proxy_pool=self.proxyPool[random.randint(0,len(self.proxyPool)-1)], stream_mode=True)
        if res == 'ERROR':
            print("访问失败: {:<64}".format(self.basic_info['book_cover_url']))
        else:
            with open(image_path, 'wb') as f:
                f.write(res)
        time_end = datetime.datetime.now()
        print("完成！耗时：{}\n书名：{}\n作者：{}\n类型：{}\n最后更新时间：{}\n简介：{}\n".format(time_end - time_start, self.basic_info['book_name'], self.basic_info['book_author'], self.basic_info['book_subject'], self.basic_info['book_date'], self.basic_info['book_description']))

    def book_text_correction(self,index,content_list):
        contents = ""
        for content in content_list:
            contents += content + '\n'
        if self.basic_info['book_chapter_content_replace_re_group']:
            for book_chapter_content_replace_re in self.basic_info['book_chapter_content_replace_re_group']:
                if book_chapter_content_replace_re['chapterIndex'] == str(index+1) or book_chapter_content_replace_re['chapterIndex'] == '*':
                    contents = re.sub(book_chapter_content_replace_re['pattern'], book_chapter_content_replace_re['repl'], contents, flags=re.M)
        return re.split(r'\n', contents)

    def work(self,dir,index,cookie=None,proxy_pool=None):
        self.semaphore.acquire()
        write_path = os.path.join(dir, 'chapter' + str(index+1) + '.html')
        if os.path.isfile(write_path):
            if os.path.getsize(write_path):
                print("文件已缓存: {:<64}".format(write_path))
                self.semaphore.release()
                return
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
        html_body_h2.nodeValue = self.book_chapter_urls[index][1]
        retry = self.basic_info['book_fetch_retry_count']
        while retry:
            chapter_html = self.loadData(self.basic_info['book_chapter_url'] + self.book_chapter_urls[index][0], host=self.basic_info['book_host'], referer=self.basic_info['book_referer'], cookie=cookie, proxy_pool=proxy_pool)
            if chapter_html == 'ERROR':
                retry -= 1
                with open(write_path, 'w+', encoding='utf-8') as f:
                    f.seek(0)
                    f.truncate()
                time.sleep(self.basic_info['book_fetch_delay'])
            else:
                break
        if retry == 0:
            print("访问失败: {:<64}".format(write_path))
            if self.missing_urls.count(self.book_chapter_urls[index]) == 0:
                self.missing_urls.append(self.book_chapter_urls[index])
            self.semaphore.release()
            return
        content_list = self.book_text_correction(index, re.findall(re.compile(self.basic_info['book_chapter_content_re']), chapter_html))
        for content in content_list:
            html_body_p = xml.createElement('p')
            html_body.appendChild(html_body_p)
            html_body_p_text = xml.createTextNode(content)
            html_body_p.appendChild(html_body_p_text)
            html_body_p.setAttribute('class', 'a')
        with open(write_path, 'w+', encoding='utf-8') as f:
            xml.writexml(f, newl = '\n', addindent = '\t', encoding='utf-8')
            xml.unlink()
            print("写入成功: {}".format(write_path))
        self.semaphore.release()

    def fetch_and_store_urls(self,dir):
        print('开始抓取所有章节并存入文件...')
        book_chapters_path = os.path.join(dir, 'OEBPS')
        self.basic_info['work_thread_num'] = len(self.proxyPool) * 3
        if self.basic_info['book_fetch_max_thread_num'] and self.basic_info['book_fetch_max_thread_num'] > 0:
            self.basic_info['work_thread_num'] = self.basic_info['book_fetch_max_thread_num']
        print('线程数设置为：{}'.format(self.basic_info['work_thread_num']))
        self.semaphore = threading.BoundedSemaphore(self.basic_info['work_thread_num'])
        time_start = datetime.datetime.now()
        work_threads = []
        for idx in range(len(self.book_chapter_urls)):
            t = threading.Thread(target=self.work,args=(book_chapters_path,idx,self.basic_info['book_cookie'],self.proxyPool[random.randint(0,len(self.proxyPool)-1)]))
            t.start()
            work_threads.append(t)
        wait_all_child_task_done(work_threads, print_char='')
        os.remove(os.path.join(book_chapters_path, 'chapter0.html'))
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
        for chapter_url in self.book_chapter_urls:
            chapter_item = xml.createElement('item')
            manifest.appendChild(chapter_item)
            chapter_item.setAttribute('id', 'chapter' + str(self.book_chapter_urls.index(chapter_url) + 1))
            chapter_item.setAttribute('href', 'chapter' + str(self.book_chapter_urls.index(chapter_url) + 1) + '.html')
            chapter_item.setAttribute('media-type', 'application/xhtml+xml')
        spine = package.getElementsByTagName('spine')[0]
        for chapter_url in self.book_chapter_urls:
            chapter_item = xml.createElement('itemref')
            spine.appendChild(chapter_item)
            chapter_item.setAttribute('idref', 'chapter' + str(self.book_chapter_urls.index(chapter_url) + 1))
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
        for chapter_url in self.book_chapter_urls:
            navPoint = xml.createElement('navPoint')
            navMap.appendChild(navPoint)
            navPoint.setAttribute('id', 'chapter' + str(self.book_chapter_urls.index(chapter_url) + 1))
            navPoint.setAttribute('playOrder', str(self.book_chapter_urls.index(chapter_url) + 1))
            navPoint_navLabel = xml.createElement('navLabel')
            navPoint.appendChild(navPoint_navLabel)
            navPoint_navLabel_text = xml.createElement('text')
            navPoint_navLabel.appendChild(navPoint_navLabel_text)
            navPoint_navLabel_text_title = xml.createTextNode(chapter_url[1])
            navPoint_navLabel_text.appendChild(navPoint_navLabel_text_title)
            navPoint_content = xml.createElement('content')
            navPoint.appendChild(navPoint_content)
            navPoint_content.setAttribute('src', 'chapter' + str(self.book_chapter_urls.index(chapter_url) + 1) + '.html')
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
        for chapter_url in self.book_chapter_urls:
            html_body_div_dl_dt = xml.createElement('dt')
            html_body_div_dl.appendChild(html_body_div_dl_dt)
            html_body_div_dl_dt.setAttribute('class', 'tocl2')
            html_body_div_dl_dt_a = xml.createElement('a')
            html_body_div_dl_dt.appendChild(html_body_div_dl_dt_a)
            html_body_div_dl_dt_a_text = xml.createTextNode(chapter_url[1])
            html_body_div_dl_dt_a.appendChild(html_body_div_dl_dt_a_text)
            html_body_div_dl_dt_a.setAttribute('href', 'chapter' + str(self.book_chapter_urls.index(chapter_url) + 1) + '.html')
        with open(xml_path, 'w', encoding='utf-8') as f:
            xml.writexml(f, newl = '\n', addindent = '\t',encoding='utf-8')
        time_end = datetime.datetime.now()
        print('完成！耗时：{}'.format(time_end - time_start))

    def create_epub(self,dir):
        print('生成epub文件...')
        time_start = datetime.datetime.now()
        current_path = os.getcwd()
        os.chdir(dir)
        if not os.path.exists('META-INF') or not os.path.exists('OEBPS') or not os.path.exists('mimetype'):
            print("创建ePub失败！META-INF, OEBPS或mimetype不存在。")
            return
        zfile = zipfile.ZipFile(self.basic_info['book_name'] + '.epub', 'w', zipfile.ZIP_DEFLATED)
        for epubdir in ['META-INF', 'OEBPS']:
            for dirpath, dirs, files in os.walk(epubdir):
                for file in files:
                    zfile.write(os.path.join(dirpath, file))
        zfile.write('mimetype')
        zfile.close()
        os.chdir(current_path)
        time_end = datetime.datetime.now()
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
        if not kindlegen_tool:
            print('kindlegen工具路径未配置！请先安装配置后重试！')
            return -1
        elif not os.path.isfile(kindlegen_tool):
            print('kindlegen工具不存在于脚本同目录下tools所在文件夹！请放入后重试！')
            return -2
        else:
            lang = self.basic_info['book_language']
            if lang == 'zh-CN':
                lang = 'zh'
            epub_path = os.path.join(dir, self.basic_info['book_name'] + '.epub')
            output_path = self.basic_info['book_name'] + '.mobi'
            kindlegen_command = kindlegen_tool + ' ' + epub_path + ' -dont_append_source -verbose -c' + self.basic_info['kindlegen_book_compression_level'] + ' -locale ' + lang + ' -o ' + output_path
            proc = subprocess.Popen(kindlegen_command,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding="utf-8")
            while proc.poll() is None:
                line = proc.stdout.readline()
                if line and line != '' and line != '\n':
                    print(line, end='')
            time_end = datetime.datetime.now()
            if proc.returncode != 0 and proc.returncode != 1:
                print('失败! 耗时：{} 返回值：{}\n'.format(time_end - time_start, proc.returncode))
                return proc.returncode
            else:
                print('完成！耗时：{}'.format(time_end - time_start))
                return 0 

    def convert_by_ebook_convert(self,dir):
        print('转换为azw3电子书格式...')
        time_start = datetime.datetime.now()
        sysstr = platform.system()
        if (sysstr == "Windows"):
            ebook_convert_tool = self.basic_info['ebook_convert_win']
        elif (sysstr == "Linux"):
            ebook_convert_tool = self.basic_info['ebook_convert_linux']
        elif (sysstr == "Mac"):
            ebook_convert_tool = self.basic_info['ebook_convert_mac']
        if not ebook_convert_tool:
            print('ebook-convert工具路径未配置！请先安装配置后重试！')
        elif not os.path.isfile(ebook_convert_tool):
            print('ebook-convert工具 {} 不存在！请先安装后重试！'.format(ebook_convert_tool))
            print('下载页面：http://calibre-ebook.com/download')
            print('Mac OS下载安装: curl -O --insecure https://download.calibre-ebook.com/5.24.0/calibre-5.24.0.dmg')
            print('Linux安装命令: sudo -v && wget -nv -O- https://download.calibre-ebook.com/linux-installer.sh | sudo sh /dev/stdin')
            print('Windows下载安装: https://download.calibre-ebook.com/5.24.0/calibre-5.24.0.msi')
        else:
            lang = self.basic_info['book_language']
            if lang == 'zh-CN':
                lang = 'zh'
            ebook_convert_path = '\"' + ebook_convert_tool + '\" '
            epub_path = os.path.join(dir, self.basic_info['book_name'] + '.epub')
            output_path = os.path.join(dir, self.basic_info['book_name'] + '.azw3')
            ebook_convert_command = ebook_convert_path + epub_path + ' ' + output_path + ' --language=' + lang + ' --input-profile=kindle --output-profile=kindle_pw3 --expand-css --remove-paragraph-spacing-indent-size=2 --remove-first-image --chapter-mark=pagebreak --max-toc-links=0 --use-auto-toc --mobi-toc-at-start --pretty-print --prefer-metadata-cover --insert-metadata'
            proc = subprocess.Popen(ebook_convert_command,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding="utf-8")
            while proc.poll() is None:
                line = proc.stdout.readline()
                if line and line != '' and line != '\n':
                    print(line, end='')
            time_end = datetime.datetime.now()
            if proc.returncode != 0:
                print('失败! 耗时：{} 返回值：{}\n'.format(time_end - time_start, proc.returncode))
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
            if print_char != '':
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
    with open(os.path.join('configs', 'settings.json'), 'r', encoding='utf-8') as f:
        basic_info = json.load(f)
    print('配置参数：\n{}'.format(json.dumps(basic_info, sort_keys=True, indent=4, separators=(', ', ': '))))

    em = Ebookmaker(basic_info)
    em.get_ip_pool()
    if len(em.IP) == 0:
        print('代理IP池大小为0！请重新获取！')
        return

    em.get_proxy_pool()
    if len(em.proxyPool) == 0:
        print('可用的IP代理池大小为0！请重新获取！')
        return

    em.get_book_info(em.basic_info['ebooks_labrary_path'])
    if not em.book_chapter_urls:
        print('获取书籍信息失败，请重试！')
        return

    print('拷贝模板文件到书籍生成目录...')
    book_path = os.path.join(em.basic_info['ebooks_labrary_path'], em.basic_info['book_name'])
    copy_dir('template', book_path)
    print('拷贝封面图片到书籍生成目录...')
    book_cover_path = os.path.join(book_path, 'OEBPS', 'cover.jpg')
    if os.path.exists(os.path.join(book_path, 'cover.pic')):
        shutil.move(os.path.join(book_path, 'cover.pic'), book_cover_path)
    chapter_template_file = os.path.join(book_path, 'OEBPS', 'chapter0.html')
    if not os.path.exists(chapter_template_file):
        print('章节模板文件不存在！请检查后重试。')
        return

    em.fetch_and_store_urls(book_path)
    if len(em.missing_urls):
        print('仍然存在获取失败的章节！请重试！')
        return

    em.write_content_opf(book_path)
    em.write_toc_ncx(book_path)
    em.write_cover_html(book_path)
    em.write_book_toc_html(book_path)
    em.create_epub(book_path)
    rc = em.convert_by_kindlegen(book_path)
    if rc == 0:
        em.convert_by_ebook_convert(book_path)

if __name__ == '__main__':
    main()
