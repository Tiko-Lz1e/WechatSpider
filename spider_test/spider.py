# -*- coding: utf-8 -*-
from lxml import etree
import os
from bs4 import BeautifulSoup
from pymongo import *
import time
import json
import requests
import re
import random
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# 加载配置项到settings（字典）中
with open('setting_default.json', encoding='utf-8') as f:
    setting_str = f.read()
    settings = json.loads(setting_str)
    f.close()

# 连接mongodb
db_ip = settings['db_ip']
db_port = settings['db_port']
client = MongoClient(db_ip, db_port)  # 腾讯云
db = client.WeChat.test  # 数据库名称，此代码中生成的数据库名为"test.水网火安"

# 设置chromedriver
chrome_options = Options()
chrome_options.add_argument("--headless")  # define headless
# driver = webdriver.Chrome(options=chrome_options)  # 不弹出Chrome窗口
driver = webdriver.Chrome()  # 弹出Chrome窗口

# 公众号账户信息
user = settings['WeChat_user']
password = settings['WeChat_pwd']

target_list = settings['targets']  # 目标公众号，默认抓取全部文章
path_cookies = settings['path_cookies']  # cookie文件储存位置，当不存在时触发登录逻辑，存在直接使用，需定时删除


# 扫码登录
def weChat_login():
    # dic: 一个空的字典，用于存放cookies内容
    dic = {}

    # 打开chrome，进行登录
    print("【启动浏览器，登录微信公众号】")
    driver.get('https://mp.weixin.qq.com/')
    # 模拟人类操作，在操作间进行等待
    time.sleep(5)
    print("【正在自动输入微信公众号登录账号和密码】")
    # 清空账号框中的内容
    driver.find_element_by_name("account").clear()
    # 自动填入登录用户名
    driver.find_element_by_name("account").send_keys(user)
    # 清空密码框中的内容
    driver.find_element_by_name("password").clear()
    # 自动填入登录密码
    driver.find_element_by_name("password").send_keys(password)

    # 在自动输完密码之后需要手动点一下记住我
    print("【请手动点击'记住账号'后等待本程序自动登录】")
    time.sleep(10)
    # 自动点击登录按钮
    driver.find_element_by_class_name("btn_login").click()

    print("【请在20秒内扫描二维码登录公众号】")
    time.sleep(20)
    print("【完成登录过程，正在检测登录结果并保存cookie】")
    try:
        # 重新载入公众号登录页，从返回内容中获取cookies信息
        driver.get('https://mp.weixin.qq.com/')
        cookie_items = driver.get_cookies()

        # 根据cookie长度初步判断登录结果
        if len(cookie_items) > 6:
            # 将cookies转成json形式并存入本地名为cookie.txt的文本中
            for cookie_item in cookie_items:
                dic[cookie_item['name']] = cookie_item['value']
            cookie_str = json.dumps(dic)
            with open(path_cookies, 'w+', encoding='utf-8') as f:
                f.write(cookie_str)
            print("【登录成功，cookies信息已保存到本地】")
        else:
            print("【登录失败，请检查登录过程】")
            driver.close()
    except Exception as e:
        print(e)
        driver.close()
        return 1


# 爬取微信公众号文章，并存在mongodb中
def get_articles(query):
    # query为要爬取的公众号名称，保存在target_list中
    # 参数设置
    url = 'https://mp.weixin.qq.com'
    header = {
        "HOST": "mp.weixin.qq.com",
        "User-Agent": "Mozilla/5.0 (Windows NT 6.2) AppleWebKit/536.3 (KHTML, like Gecko) Chrome/19.0.1062.0 Safari/536.3",
        'Connection': 'close'
    }

    # 读取cookies
    with open(path_cookies, 'r', encoding='utf-8') as f:
        cookie = f.read()
    cookies = json.loads(cookie)

    # 登录之后的微信公众号首页url变化为：https://mp.weixin.qq.com/cgi-bin/home?t=home/index&lang=zh_CN&token=1849751598，从这里获取token信息
    response = requests.get(url=url, cookies=cookies)
    token = re.findall(r'token=(\d+)', str(response.url))[0]

    # 搜索微信公众号的接口地址
    search_url = 'https://mp.weixin.qq.com/cgi-bin/searchbiz?'
    # 搜索微信公众号接口需要传入的参数，有三个变量：微信公众号token、随机数random、搜索的微信公众号名字
    query_id = {
        'action': 'search_biz',
        'token': token,
        'lang': 'zh_CN',
        'f': 'json',
        'ajax': '1',
        'random': random.random(),
        'query': query,
        'begin': '0',
        'count': '5'
    }
    # 打开搜索微信公众号接口地址，需要传入相关参数信息如：cookies、params、headers
    search_response = requests.get(search_url, cookies=cookies, headers=header, params=query_id)
    # 取搜索结果中的第一个公众号
    lists = search_response.json().get('list')[0]
    # 获取这个公众号的fakeid，后面爬取公众号文章需要此字段
    fakeid = lists.get('fakeid')

    # 微信公众号文章接口地址
    appmsg_url = 'https://mp.weixin.qq.com/cgi-bin/appmsg?'
    # 搜索文章需要传入几个参数：登录的公众号token、要爬取文章的公众号fakeid、随机数random
    query_id_data = {
        'token': token,
        'lang': 'zh_CN',
        'f': 'json',
        'ajax': '1',
        'random': random.random(),
        'action': 'list_ex',
        'begin': '0',  # 不同页，此参数变化，变化规则为每页加5
        'count': '5',
        'query': '',
        'fakeid': fakeid,
        'type': '9'
    }
    # 打开搜索的微信公众号文章列表页
    appmsg_response = requests.get(appmsg_url, cookies=cookies, headers=header, params=query_id_data)
    # 获取文章总数
    max_num = appmsg_response.json().get('app_msg_cnt')
    # print('【文章总数】 ', max_num)
    # 每页至少有5条，获取文章总的页数，爬取时需要分页爬
    num = int(int(max_num) / 5)
    print('【文章总页数】 ', num)
    # 起始页begin参数，往后每页加5
    begin = 0
    while num + 1 > 0:
        query_id_data = {
            'token': token,
            'lang': 'zh_CN',
            'f': 'json',
            'ajax': '1',
            'random': random.random(),
            'action': 'list_ex',
            'begin': '{}'.format(str(begin)),
            'count': '5',
            'query': '',
            'fakeid': fakeid,
            'type': '9'
        }
        print('【正在翻页】--------------', begin)

        # 获取每一页文章的标题和链接地址，并写入本地文本中
        query_fakeid_response = requests.get(appmsg_url, cookies=cookies, headers=header, params=query_id_data)

        fakeid_list = query_fakeid_response.json().get('app_msg_list')
        print(fakeid_list)
        for item in fakeid_list:

            # 判断一条数据是否已经存在，以link作为依据
            exist = db[query].find_one({'url': item.get('link')})
            if exist:
                print('【已存在，去重】')
            else:
                article_dict = {}
                content_link = item.get('link')
                content_title = item.get('title')
                timeStamp = item.get('update_time')
                timeArray = time.localtime(timeStamp)
                date = time.strftime("%Y-%m-%d %H:%M:%S", timeArray)
                content_date = date

                article_dict['title'] = content_title
                article_dict['url'] = content_link
                article_dict['date'] = content_date
                article_dict['content'] = get_content(content_link)
                article_dict['name'] = query

                try:
                    # 过滤已被删除文章
                    if article_dict['content'] != 1:
                        db[query].insert_one(article_dict)

                except Exception as e:
                    print(e)

                # print(article_dict)
                print("【添加一条新数据】")
        num -= 1
        begin = int(begin)
        begin += 5
        time.sleep(2)
        print('【begin】======', begin)

        # 仅抓取最新的两页
        # if begin == 10:
            # break


def get_content(url):
    # 调用chrome
    # 打开公众号单篇文章页面
    driver.get(url)
    # 等待5秒钟
    time.sleep(5)
    # 拿到渲染后的页面
    html = driver.page_source
    try:
        # 转换页面格式
        selector = etree.HTML(html)
        # 用xpath取出需要的页面部分
        result = selector.xpath('//*[@id="js_content"]')[0]
        # 转为html
        content = etree.tostring(result, method='html')
        # 获取bs4对象
        soup = BeautifulSoup(content, 'html.parser', from_encoding='utf-8')
        new_list = []

        # 通过标签来获取内容
        ls = soup.find_all(["p", "img"])
        print(ls)
        for table in ls:
            res = {}

            data = table.get_text()
            if data:
                # 去除空字符和特殊字符
                new_data = "".join(data.split())
                new_data = new_data.replace(u'\ufeff', '')
                if new_data != "":
                    res["text"] = new_data
                    new_list.append(res)

            link = table.get('data-src')
            if link:
                res["img"] = link
                new_list.append(res)

        print(new_list)
        return new_list
    except Exception as e:
        print(e)
        return 1


# 爬虫逻辑

if __name__ == '__main__':
    start_time = time.time()
    print('【开始时间】 ', time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_time)))
    try:

        # 登录微信公众号，获取登录之后的cookies信息，并保存到本地文本中
        if os.path.exists(path_cookies):
            print('【cookie已存在】')
        else:
            weChat_login()

        # 登录之后，通过微信公众号后台提供的微信公众号文章接口爬取文章
        if os.path.exists(path_cookies):
            for query in target_list:
                # 爬取微信公众号文章，并存在mongo中
                print("【开始爬取公众号】 " + query)
                get_articles(query)

            print("【爬取完成】")
            end_time = time.time()
            print('【结束时间】 ', time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end_time)))
            use_time = end_time - start_time
            print('【此次爬取时间】 ', use_time)
    except Exception as e:
        print(str(e))
        driver.quit()

