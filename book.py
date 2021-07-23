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
from urllib3.exceptions import InsecureRequestWarning
from urllib import error
#from bs4 import BeautifulSoup
urllib3.disable_warnings(InsecureRequestWarning)

class Ebookmaker(object):
    def __init__(self):
        #self.book_url = 'https://www.xbiquge.la/66/66747/'
        #self.book_host = 'www.xbiquge.la'
        #self.book_referer = 'https://www.xbiquge.la/66/66747/26547971.html'
        #self.cookie = '_abcde_qweasd=0; Hm_lvt_169609146ffe5972484b0957bd1b46d6=1626520436,1626585865; Hm_lpvt_169609146ffe5972484b0957bd1b46d6=1626597513'
        #self.book_title_re = re.compile(r'<meta property="og:title" content="(.*?)"/>')
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
        self.book_title_re = re.compile(r'<meta property="og:novel:book_name" content="(.*?)"/>')
        self.book_description_re = re.compile(r'<meta property="og:description" content="(.*?)"/>')
        self.book_author_re = re.compile(r'<meta property="og:novel:author" content="(.*?)"/>')
        self.list_reg = re.compile(r'<dd><a href="/2_2588/([0-9]{5,6}\.html)"  >(.*?)</a></dd>')
        self.chapter_content_reg = re.compile(r'&nbsp;&nbsp;&nbsp;&nbsp;(.*?)<br><br>', re.S)
        ######################################################################################
        self.daili_url_base = 'https://ip.jiangxianli.com/?page='
        self.daili_host = 'ip.jiangxianli.com'
        self.daili_cookie = 'UM_distinctid=17abfa06f89dc5-0f97a150c82592-6373264-384000-17abfa06f8ad3c; Hm_lvt_b72418f3b1d81bbcf8f99e6eb5d4e0c3=1626712600,1626886778,1626886791,1626886800; Hm_lpvt_b72418f3b1d81bbcf8f99e6eb5d4e0c3=1626886832'
        self.daili_re = re.compile(r'data-url="http://(\d+\.\d+\.\d+\.\d+:\d+)"')
        self.proxy_pool_url = 'http://httpbin.org/ip'
        self.proxy_pool_host = 'httpbin.org'
        ######################################################################################
        # For Calibre
        #self.chapter_title_format_begin = "# "
        #self.chapter_title_format_end = " #"
        # For kaf-cli
        self.chapter_title_format_begin = ""
        self.chapter_title_format_end = ""
        ######################################################################################
        self.thread_num = 5
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

    def work(self,base_path,index,urls,cookie=None,proxy_pool=None):
        self.semaphore.acquire()
        write_path = os.path.join(base_path, str(index+1) + '.txt')
        if os.path.isfile(write_path):
            os.remove(write_path)
        with open(write_path, 'a+') as f:
            f.write(self.chapter_title_format_begin + urls[index][1] + self.chapter_title_format_end + '\r\n\r\n')
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
                f.write(content + '\r\n')
            f.write('\r\n')
            print("写入成功: {:<64}".format(urls[index][1]))
        self.semaphore.release()

def main():
    em = Ebookmaker()
    ip_threads = []
    for idx in range(20):
        t = threading.Thread(target=em.ip_pool,args=(idx,))
        t.start()
        ip_threads.append(t)
        if idx%em.thread_num == 0:
            time.sleep(3)
    for t in ip_threads:
        t.join()
    new_list = list(set(em.IP))
    new_list.sort(key=em.IP.index)
    em.IP = new_list
    print('代理IP池大小为{}'.format(len(em.IP)))

    proxy_pool_threads = []
    for idx in range(len(em.IP)):
        t = threading.Thread(target=em.proxy_pool,args=(em.IP[idx],))
        t.start()
        proxy_pool_threads.append(t)
        if idx%em.thread_num == 0:
            time.sleep(3)
    for t in proxy_pool_threads:
        t.join()
    print('筛选后的代理池大小为{}'.format(len(em.proxyPool)))

    res = em.loadData(em.book_url, referer=em.book_referer, host=em.book_host)
    if res == 'ERROR':
        print("访问失败: {:<64}".format(em.book_url))
        return
    book_title = em.book_title_re.findall(res)
    book_description = em.book_description_re.findall(res)
    book_author = em.book_author_re.findall(res)
    urls = em.list_reg.findall(res)
    print("获取书籍信息：\n{}\n{}\n{}\n".format(book_title[0],book_author[0],book_description[0]))

    print('开始创建书籍存档目录：%s...' %book_title[0])
    if not os.path.exists(book_title[0]):
        os.makedirs(book_title[0])

    print('现在开始将所有章节存入文件...')
    work_threads = []
    em.thread_num = 50
    em.semaphore = threading.BoundedSemaphore(em.thread_num)
    chapter_len = len(urls)
    for idx in range(chapter_len):
        t = threading.Thread(target=em.work,args=(book_title[0],idx,urls,None,em.proxyPool[random.randint(0,len(em.proxyPool)-1)]))
        t.start()
        work_threads.append(t)
        if idx%em.thread_num == 0:
            time.sleep(3)
    for t in work_threads:
        t.join()
    work_threads = []

    print('现在重新处理写入失败的章节...')
    chapter_len = len(em.missing_urls)
    for idx in range(chapter_len):
        t = threading.Thread(target=em.work,args=(book_title[0],idx,em.missing_urls,None,em.proxyPool[random.randint(0,len(em.proxyPool)-1)]))
        t.start()
        work_threads.append(t)
        if idx%em.thread_num == 0:
            time.sleep(3)
    for t in work_threads:
        t.join()

    print('合并所有章节...')
    res = ""
    files = os.listdir(book_title[0])
    files.sort(key=lambda x: int(x.split('.txt')[0]))
    for file in files:
        if file.endswith('.txt'):
            path = os.path.join(book_title[0],file)
            with open(path, 'r', encoding='utf-8') as file:
                content = file.read()
                file.close()
            res += content
    with open(book_title[0] + '/outfile.txt', 'w', encoding='utf-8') as outFile:
        outFile.write(res)
        outFile.close()

    print('转换为Kindle电子书格式...')
    sysstr = platform.system()
    if (sysstr == "Windows"):
        kafcli_tool = em.kafcli_win
    elif (sysstr == "Linux"):
        kafcli_tool = em.kafcli_linux
    elif (sysstr == "Mac"):
        kafcli_tool = em.kafcli_mac
    if not os.path.isfile(kafcli_tool):
        print('kaf-cli工具不存在脚本所在文件夹！请放入后重试！')
    else:
        kafcli_command = os.path.join('.', kafcli_tool) + ' -filename ' + book_title[0] + '/outfile.txt' + ' -bookname ' + book_title[0] + ' -author ' + book_author[0] + ' -cover cover.png'
        ret = subprocess.run(kafcli_command,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding="utf-8",timeout=300)
        if ret.returncode != 0:
            print('kaf-cli操作失败!',ret)
        else:
            print('所有操作都已经完成!!!')

if __name__ == '__main__':
    main()
