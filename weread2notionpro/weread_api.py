import hashlib
import json
import logging
import os
import re
import uuid
from datetime import datetime
from time import perf_counter
from typing import Any, Dict, Optional

import requests
from requests.utils import cookiejar_from_dict
from retrying import retry
from urllib.parse import quote
from dotenv import load_dotenv

# 配置日志 - 同时输出到控制台和文件
log_dir = "logs"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

log_filename = os.path.join(log_dir, f"weread_sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

# 创建logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 创建formatter
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# 创建控制台handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)

# 创建文件handler
file_handler = logging.FileHandler(log_filename, encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)

# 添加handlers到logger
logger.addHandler(console_handler)
logger.addHandler(file_handler)

# 避免重复日志
logger.propagate = False

logger.info(f"日志文件已创建: {log_filename}")

load_dotenv()
WEREAD_URL = "https://weread.qq.com"
WEREAD_NOTEBOOKS_URL = "https://weread.qq.com/api/user/notebook"
WEREAD_BOOKMARKLIST_URL = "https://weread.qq.com/web/book/bookmarklist"
WEREAD_CHAPTER_INFO = "https://weread.qq.com/web/book/chapterInfos"
WEREAD_READ_INFO_URL = "https://weread.qq.com/web/book/getProgress"
WEREAD_REVIEW_LIST_URL = "https://weread.qq.com/web/review/list"
WEREAD_BOOK_INFO = "https://weread.qq.com/web/book/info"
WEREAD_READDATA_DETAIL = "https://weread.qq.com/web/readdata/detail"
WEREAD_HISTORY_URL = "https://weread.qq.com/web/readdata/summary?synckey=0"


class WeReadApi:
    REQUEST_LOG_PREVIEW = 800

    def __init__(self):
        self.cookie = self.get_cookie()
        self.session = requests.Session()
        self.session.cookies = self.parse_cookie_string()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.103 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json'
        })
        self._request_meta: Dict[str, Dict[str, Any]] = {}

    def try_get_cloud_cookie(self, url, id, password):
        if url.endswith("/"):
            url = url[:-1]
        req_url = f"{url}/get/{id}"
        data = {"password": password}
        result = None
        response = requests.post(req_url, data=data)
        if response.status_code == 200:
            data = response.json()
            cookie_data = data.get("cookie_data")
            if cookie_data and "weread.qq.com" in cookie_data:
                cookies = cookie_data["weread.qq.com"]
                cookie_str = "; ".join(
                    [f"{cookie['name']}={cookie['value']}" for cookie in cookies]
                )
                result = cookie_str
        return result

    def get_cookie(self):
        url = os.getenv("CC_URL")
        if not url:
            url = "https://cookiecloud.malinkang.com/"
        id = os.getenv("CC_ID")
        password = os.getenv("CC_PASSWORD")
        cookie = os.getenv("WEREAD_COOKIE")
        if url and id and password:
            cookie = self.try_get_cloud_cookie(url, id, password)
        if not cookie or not cookie.strip():
            raise Exception("没有找到cookie，请按照文档填写cookie")
        return cookie

    def parse_cookie_string(self):
        cookies_dict = {}

        # 使用正则表达式解析 cookie 字符串
        pattern = re.compile(r'([^=]+)=([^;]+);?\s*')
        matches = pattern.findall(self.cookie)

        for key, value in matches:
            cookies_dict[key] = value.encode('unicode_escape').decode('ascii')
        # 直接使用 cookies_dict 创建 cookiejar
        cookiejar = cookiejar_from_dict(cookies_dict)

        return cookiejar

    def _truncate_string(self, value: Optional[str]) -> str:
        if value is None:
            return "None"
        if len(value) > self.REQUEST_LOG_PREVIEW:
            return f"{value[:self.REQUEST_LOG_PREVIEW]}... (截断, 原长度 {len(value)})"
        return value

    def _serialize_for_log(self, payload: Any) -> str:
        if payload is None:
            return "None"
        try:
            if isinstance(payload, (dict, list)):
                text = json.dumps(payload, ensure_ascii=False, default=str)
            else:
                text = str(payload)
        except Exception:
            text = repr(payload)
        return self._truncate_string(text)

    def _safe_response_preview(self, response: requests.Response) -> str:
        try:
            content_type = response.headers.get('Content-Type', '')
        except Exception:
            content_type = ''

        try:
            if content_type and 'application/json' in content_type:
                payload = response.json()
                text = json.dumps(payload, ensure_ascii=False, default=str)
            else:
                text = response.text or ''
        except Exception:
            try:
                text = response.text or ''
            except Exception:
                text = '<无法读取响应内容>'
        return self._truncate_string(text)

    def _start_request_log(self, name: str, method: str, url: str, **kwargs) -> str:
        suffix = uuid.uuid4().hex[:8]
        request_id = f"{name}-{suffix}" if name else suffix
        start_time = perf_counter()
        self._request_meta[request_id] = {
            'start': start_time,
            'name': name or method,
        }
        current_time = datetime.now().isoformat()
        logger.info(f"[{request_id}] {name or method} - 开始 {method.upper()} 请求: {url}")
        logger.info(f"[{request_id}] 请求发起时间: {current_time}")

        params = kwargs.get('params')
        if params:
            logger.info(f"[{request_id}] 请求params: {self._serialize_for_log(params)}")

        data = kwargs.get('data')
        if data:
            logger.info(f"[{request_id}] 请求data: {self._serialize_for_log(data)}")

        json_body = kwargs.get('json')
        if json_body:
            logger.info(f"[{request_id}] 请求json: {self._serialize_for_log(json_body)}")

        headers = kwargs.get('headers')
        if headers:
            logger.debug(f"[{request_id}] 请求头: {self._serialize_for_log(headers)}")

        cookies = kwargs.get('cookies')
        if cookies:
            try:
                if hasattr(cookies, 'get_dict'):
                    cookies_repr = cookies.get_dict()
                else:
                    cookies_repr = dict(cookies)
            except Exception:
                cookies_repr = str(cookies)
            logger.debug(f"[{request_id}] 请求cookies: {self._serialize_for_log(cookies_repr)}")

        timeout = kwargs.get('timeout')
        if timeout:
            logger.debug(f"[{request_id}] 请求timeout: {timeout}")

        return request_id

    def _finish_request_log(self, request_id: str, response: Optional[requests.Response] = None, error: Optional[Exception] = None) -> None:
        meta = self._request_meta.pop(request_id, {})
        start_time = meta.get('start')
        duration = perf_counter() - start_time if start_time is not None else None
        end_time = datetime.now().isoformat()
        name = meta.get('name', request_id)

        if response is not None:
            logger.info(f"[{request_id}] {name} - 响应状态: {response.status_code}")
            logger.info(f"[{request_id}] 响应接收时间: {end_time}")
            if duration is not None:
                logger.info(f"[{request_id}] 请求耗时: {duration:.3f} 秒")
            try:
                headers_repr = dict(response.headers)
            except Exception:
                headers_repr = '<无法读取响应头>'
            logger.debug(f"[{request_id}] 响应头: {self._serialize_for_log(headers_repr)}")
            logger.info(f"[{request_id}] 响应内容: {self._safe_response_preview(response)}")
        elif error is not None:
            logger.error(f"[{request_id}] {name} - 请求异常: {str(error)}")
            logger.error(f"[{request_id}] 异常时间: {end_time}")
            if duration is not None:
                logger.error(f"[{request_id}] 请求耗时: {duration:.3f} 秒")

    def _send_request(self, name: str, method: str, url: str, *, use_session: bool = True, **kwargs) -> requests.Response:
        method_upper = method.upper()
        request_id = self._start_request_log(name, method_upper, url, **kwargs)
        caller = self.session.request if use_session else requests.request
        try:
            response = caller(method_upper, url, **kwargs)
        except Exception as exc:
            self._finish_request_log(request_id, error=exc)
            raise
        self._finish_request_log(request_id, response=response)
        return response

    def get_bookshelf(self, retry_count=0):
        """获取书架信息"""
        logger.info("正在获取书架信息...")
        try:
            url = "https://weread.qq.com/web/shelf/sync"
            headers = dict(self.session.headers)
            self._send_request("BOOKSHELF_PREFLIGHT", "GET", WEREAD_URL)
            r = self._send_request("BOOKSHELF", "GET", url, headers=headers)
            
            if r.ok:
                data = r.json()
                logger.info(f"书架API响应成功，数据键: {list(data.keys()) if data else 'None'}")
                logger.debug(f"完整响应数据: {data}")
                
                # 检查是否有错误码
                if data.get('errCode') and data.get('errCode') != 0:
                    logger.warning(f"API返回错误: {data.get('errMsg', '未知错误')} (错误码: {data.get('errCode')})")
                    if data.get('errCode') == -2012 and retry_count == 0:  # 登录超时，尝试刷新Cookie
                        logger.info(f"获取书架信息 - 登录超时，尝试刷新Cookie后重试")
                        if self.refresh_cookie():
                            logger.info(f"获取书架信息 - Cookie刷新成功，重新请求")
                            return self.get_bookshelf(retry_count + 1)
                        else:
                            logger.warning(f"获取书架信息 - Cookie刷新失败")
                            return {"books": []}
                    elif data.get('errCode') == -2012:
                        logger.warning(f"获取书架信息 - 重试后仍登录超时")
                        return {"books": []}
                    self.handle_errcode(data.get('errCode', 0))
                    return {"books": []}
                
                # 根据实际响应结构获取书籍数据
                books = data.get("books", [])
                if not books and 'info' in data:
                    # 如果books为空，尝试从info中获取
                    info = data.get('info', {})
                    books = info.get('books', []) if isinstance(info, dict) else []
                
                logger.info(f"获取到书架信息，包含 {len(books)} 本书")
                if books:
                    logger.debug(f"第一本书示例: {books[0] if books else 'None'}")
                    # 记录前几本书的基本信息
                    for i, book in enumerate(books[:5]):  # 只记录前5本书的信息
                        book_title = book.get('title', '未知书名')
                        book_id = book.get('bookId', '未知ID')
                        book_author = book.get('author', '未知作者')
                        logger.info(f"  书架书籍 {i+1}: 《{book_title}》 作者: {book_author} (bookId: {book_id})")
                    if len(books) > 5:
                        logger.info(f"  ... 还有 {len(books) - 5} 本书")
                return {"books": books}
            else:
                logger.error(f"书架API响应失败: {r.status_code} - {r.text}")
                logger.debug(f"错误响应内容: {r.text}")
                errcode = r.json().get("errcode", 0) if r.text else 0
                self.handle_errcode(errcode)
                return {"books": []}
        except Exception as e:
            logger.error(f"获取书架信息时出错: {str(e)}")
            import traceback
            traceback.print_exc()
            raise
        
    def handle_errcode(self,errcode):
        if( errcode== -2012 or errcode==-2010):
            logger.error(f"::error::微信读书Cookie过期了，请参考文档重新设置。https://mp.weixin.qq.com/s/B_mqLUZv7M1rmXRsMlBf7A")

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_notebooklist(self, retry_count=0):
        """获取笔记本列表"""
        logger.info("正在获取笔记本列表...")
        try:
            headers = dict(self.session.headers)
            self._send_request("NOTEBOOK_PREFLIGHT", "GET", WEREAD_URL)
            r = self._send_request("GET_NOTEBOOK_LIST", "GET", WEREAD_NOTEBOOKS_URL, headers=headers)
            
            if r.ok:
                data = r.json()
                logger.info(f"笔记本API响应数据键: {list(data.keys()) if data else 'None'}")
                logger.debug(f"完整响应数据: {data}")
                
                # 检查是否有错误码
                if data.get('errCode') and data.get('errCode') != 0:
                    logger.warning(f"API返回错误: {data.get('errMsg', '未知错误')} (错误码: {data.get('errCode')})")
                    if data.get('errCode') == -2012 and retry_count == 0:  # 登录超时，尝试刷新Cookie
                        logger.info(f"获取笔记本列表 - 登录超时，尝试刷新Cookie后重试")
                        if self.refresh_cookie():
                            logger.info(f"获取笔记本列表 - Cookie刷新成功，重新请求")
                            return self.get_notebooklist(retry_count + 1)
                        else:
                            logger.warning(f"获取笔记本列表 - Cookie刷新失败")
                            return []
                    elif data.get('errCode') == -2012:
                        logger.warning(f"获取笔记本列表 - 重试后仍登录超时")
                        return []
                    self.handle_errcode(data.get('errCode', 0))
                    return []
                
                books = data.get("books")
                if books:
                    books.sort(key=lambda x: x["sort"])
                    logger.info(f"获取到 {len(books)} 本有笔记的书")
                    logger.debug(f"第一本有笔记的书示例: {books[0] if books else 'None'}")
                    
                    # 为了保持与原有书架API的兼容性，将笔记本数据转换为书架格式
                    # 提取book字段作为主要书籍信息，保持原有的数据结构
                    formatted_books = []
                    for notebook in books:
                        if 'book' in notebook:
                            book_info = notebook['book'].copy()
                            # 保留笔记本特有的信息
                            book_info['noteCount'] = notebook.get('noteCount', 0)
                            book_info['reviewCount'] = notebook.get('reviewCount', 0)
                            book_info['sort'] = notebook.get('sort', 0)
                            formatted_books.append(book_info)
                    
                    logger.debug(f"转换后的书籍格式示例: {formatted_books[0] if formatted_books else 'None'}")
                    return formatted_books
                else:
                    logger.warning("未获取到笔记本数据")
                    return []
            else:
                logger.error(f"笔记本API响应失败: {r.status_code} - {r.text}")
                logger.debug(f"错误响应内容: {r.text}")
                errcode = r.json().get("errcode", 0) if r.text else 0
                self.handle_errcode(errcode)
                return []
        except Exception as e:
            logger.error(f"获取笔记本列表时出错: {str(e)}")
            import traceback
            traceback.print_exc()
            raise

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_bookinfo(self, bookId, retry_count=0):
        """获取书的详情"""
        headers = dict(self.session.headers)
        params = dict(bookId=bookId)
        self._send_request("BOOKINFO_PREFLIGHT", "GET", WEREAD_URL)
        r = self._send_request("GET_BOOK_INFO", "GET", WEREAD_BOOK_INFO, params=params, headers=headers)

        if r.ok:
            data = r.json()
            logger.info(f"获取书籍信息 - 完整原始响应: {data}")
            
            # 检查是否有错误码
            if data.get('errCode') and data.get('errCode') != 0:
                logger.warning(f"获取书籍信息 - API返回错误: {data.get('errMsg', '未知错误')} (错误码: {data.get('errCode')})")
                if data.get('errCode') == -2012 and retry_count == 0:  # 登录超时，尝试刷新Cookie
                    logger.info(f"获取书籍信息 - 登录超时，尝试刷新Cookie后重试")
                    if self.refresh_cookie():
                        logger.info(f"获取书籍信息 - Cookie刷新成功，重新请求")
                        return self.get_bookinfo(bookId, retry_count + 1)
                    else:
                        logger.warning(f"获取书籍信息 - Cookie刷新失败，跳过书籍 {bookId}")
                        return None
                elif data.get('errCode') == -2012:
                    logger.warning(f"获取书籍信息 - 重试后仍登录超时，跳过书籍 {bookId}")
                    return None
                self.handle_errcode(data.get('errCode', 0))
                return None
            
            # 记录获取到的书籍详细信息
            book_title = data.get('title', '未知书名')
            book_author = data.get('author', '未知作者')
            logger.info(f"获取书籍信息 - 成功获取书籍: 《{book_title}》 作者: {book_author} (bookId: {bookId})")
            logger.debug(f"获取书籍信息 - 书籍详细信息: title={book_title}, author={book_author}, cover={data.get('cover', 'None')}, isbn={data.get('isbn', 'None')}")
            
            return data
        else:
            logger.error(f"获取书籍信息 - 请求失败: {r.status_code} - {r.text}")
            errcode = r.json().get("errcode", 0) if r.text else 0
            self.handle_errcode(errcode)
            return None


    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_bookmark_list(self, bookId, retry_count=0):
        headers = dict(self.session.headers)
        self._send_request("BOOKMARK_PREFLIGHT", "GET", WEREAD_URL)
        params = dict(bookId=bookId)
        r = self._send_request("GET_BOOKMARK_LIST", "GET", WEREAD_BOOKMARKLIST_URL, params=params, headers=headers)
        
        if r.ok:
            data = r.json()
            logger.info(f"获取标注列表 - 响应数据键: {list(data.keys()) if data else 'None'}")
            logger.debug(f"获取标注列表 - 完整响应: {data}")
            
            # 检查是否有错误码
            if data.get('errCode') and data.get('errCode') != 0:
                logger.warning(f"获取标注列表 - API返回错误: {data.get('errMsg', '未知错误')} (错误码: {data.get('errCode')})")
                if data.get('errCode') == -2012 and retry_count == 0:  # 登录超时，尝试刷新Cookie
                    logger.info(f"获取标注列表 - 登录超时，尝试刷新Cookie后重试")
                    if self.refresh_cookie():
                        logger.info(f"获取标注列表 - Cookie刷新成功，重新请求")
                        return self.get_bookmark_list(bookId, retry_count + 1)
                    else:
                        logger.warning(f"获取标注列表 - Cookie刷新失败，跳过书籍 {bookId}")
                        return []
                elif data.get('errCode') == -2012:
                    logger.warning(f"获取标注列表 - 重试后仍登录超时，跳过书籍 {bookId}")
                    return []
                self.handle_errcode(data.get('errCode', 0))
                return []
            
            bookmarks = data.get("updated", [])
            logger.info(f"获取到 {len(bookmarks)} 个标注")
            return bookmarks
        else:
            logger.error(f"获取标注列表 - 请求失败: {r.status_code} - {r.text}")
            errcode = r.json().get("errcode", 0) if r.text else 0
            self.handle_errcode(errcode)
            return []

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_read_info(self, bookId, retry_count=0):
        # 构建请求头，模仿TypeScript版本的实现
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.103 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json',
        }
        
        logger.info(f"获取阅读信息 - 正在查询书籍 {bookId} 的阅读详情")

        try:
            params = {'bookId': bookId}
            try:
                cookie_count = len(list(self.session.cookies))
                logger.debug(f"获取阅读信息 - 当前cookies数量: {cookie_count}")
            except Exception as e:
                logger.debug(f"获取阅读信息 - 无法获取cookies信息: {str(e)}")

            r = self._send_request(
                "GET_READ_INFO",
                "GET",
                WEREAD_READ_INFO_URL,
                use_session=False,
                params=params,
                headers=headers,
                cookies=self.session.cookies,
                timeout=30,
            )
            
            if r.ok:
                data = r.json()
                logger.info(f"获取阅读信息 - 完整原始响应: {data}")
                
                # 检查是否有错误码
                if data.get('errCode') and data.get('errCode') != 0:
                    logger.warning(f"获取阅读信息 - API返回错误: {data.get('errMsg', '未知错误')} (错误码: {data.get('errCode')})")
                    if data.get('errCode') == -2012 and retry_count == 0:  # 登录超时，尝试刷新Cookie
                        logger.info(f"获取阅读信息 - 登录超时，尝试刷新Cookie后重试")
                        # 避免Cookie冲突，只记录Cookie数量
                        try:
                            cookie_count = len(list(self.session.cookies))
                            logger.debug(f"获取阅读信息 - 当前cookies数量: {cookie_count}")
                        except Exception as e:
                            logger.debug(f"获取阅读信息 - 无法获取当前cookies信息: {str(e)}")
                        
                        if self.refresh_cookie():
                            logger.info(f"获取阅读信息 - Cookie刷新成功，重新请求")
                            try:
                                cookie_count = len(list(self.session.cookies))
                                logger.debug(f"获取阅读信息 - 刷新后cookies数量: {cookie_count}")
                            except Exception as e:
                                logger.debug(f"获取阅读信息 - 无法获取刷新后cookies信息: {str(e)}")
                            return self.get_read_info(bookId, retry_count + 1)
                        else:
                            logger.warning(f"获取阅读信息 - Cookie刷新失败，跳过书籍 {bookId}")
                            return None
                    elif data.get('errCode') == -2012:
                        logger.warning(f"获取阅读信息 - 重试后仍登录超时，跳过书籍 {bookId}")
                        return None
                    self.handle_errcode(data.get('errCode', 0))
                    return None
                
                # 根据book.py中实际使用的字段进行适配
                result = {}
                
                # 基础标识字段
                result['bookId'] = bookId
                result['canFreeRead'] = data.get('canFreeRead')
                result['timestamp'] = data.get('timestamp')
                
                # book.py中实际使用的核心字段
                result['readingTime'] = data.get('readingTime', 0)  # 阅读时长（秒）- 用于计算"阅读时长"和"阅读状态"
                result['progress'] = data.get('progress', 0)  # 阅读进度（0-100）
                result['readingProgress'] = data.get('progress', 0)  # 兼容字段，用于计算"阅读进度"
                
                # book.py中期望但API可能不返回的字段（设置默认值）
                result['markedStatus'] = data.get('markedStatus', 1)  # 阅读状态标记：1-想读，4-读完，其他-在读
                result['totalReadDay'] = data.get('totalReadDay', 0)  # 阅读天数
                result['newRating'] = data.get('newRating')  # 评分
                result['newRatingDetail'] = data.get('newRatingDetail')  # 评分详情
                
                # 获取嵌套的book对象数据
                book_data = data.get('book', {})
                
                # 时间相关字段（优先从book对象中获取，然后从顶级对象获取）
                result['finishedDate'] = book_data.get('finishedDate') or data.get('finishedDate')  # 完成日期
                result['lastReadingDate'] = book_data.get('lastReadingDate') or data.get('lastReadingDate')  # 最后阅读日期
                result['readingBookDate'] = book_data.get('readingBookDate') or data.get('readingBookDate')  # 阅读书籍日期
                result['beginReadingDate'] = book_data.get('beginReadingDate') or data.get('beginReadingDate')  # 开始阅读日期
                result['startReadingTime'] = book_data.get('startReadingTime') or data.get('startReadingTime')  # 开始阅读时间戳
                result['finishTime'] = book_data.get('finishTime') or data.get('finishTime')  # 完成时间戳
                result['updateTime'] = book_data.get('updateTime') or data.get('updateTime')  # 更新时间
                
                # 从book对象中提取其他重要字段
                if book_data:
                    # 覆盖之前设置的字段，使用book对象中的实际数据
                    result['readingTime'] = book_data.get('readingTime', result.get('readingTime', 0))
                    result['progress'] = book_data.get('progress', result.get('progress', 0))
                    result['readingProgress'] = book_data.get('progress', result.get('readingProgress', 0))
                    result['chapterUid'] = book_data.get('chapterUid')
                    result['chapterOffset'] = book_data.get('chapterOffset')
                    result['chapterIdx'] = book_data.get('chapterIdx')
                    result['isStartReading'] = book_data.get('isStartReading')
                
                # 阅读详情数据（用于插入阅读时间数据）
                result['readDetail'] = data.get('readDetail', {})
                
                # 书籍信息（可能包含额外的书籍元数据）
                result['bookInfo'] = data.get('bookInfo', {})
                
                # 保留原始数据以保持完整性和向后兼容
                result['book'] = book_data
                
                # 记录获取到的阅读信息详情
                reading_time = result.get('readingTime', 0)
                progress = result.get('progress', 0)
                start_reading_time = result.get('startReadingTime')
                update_time = result.get('updateTime')
                
                # 获取书籍名称用于日志显示
                book_title = book_data.get('title') or data.get('title')
                book_author = book_data.get('author') or data.get('author')
                
                # 如果阅读信息API没有返回书名，尝试从书籍详情API获取
                if not book_title or not book_author:
                    logger.debug(f"获取阅读信息 - 阅读信息API未返回书名，尝试从书籍详情API获取 (bookId: {bookId})")
                    try:
                        book_info = self.get_bookinfo(bookId)
                        if book_info:
                            book_title = book_title or book_info.get('title', '未知书名')
                            book_author = book_author or book_info.get('author', '未知作者')
                            logger.debug(f"获取阅读信息 - 从书籍详情API获取到书名: {book_title}, 作者: {book_author}")
                        else:
                            book_title = book_title or '未知书名'
                            book_author = book_author or '未知作者'
                            logger.warning(f"获取阅读信息 - 无法从书籍详情API获取书名 (bookId: {bookId})")
                    except Exception as e:
                        book_title = book_title or '未知书名'
                        book_author = book_author or '未知作者'
                        logger.warning(f"获取阅读信息 - 获取书籍详情时发生异常: {str(e)} (bookId: {bookId})")
                else:
                    book_title = book_title or '未知书名'
                    book_author = book_author or '未知作者'
                
                logger.info(f"获取阅读信息 - 成功获取书籍《{book_title}》(作者: {book_author}) 的阅读信息 (bookId: {bookId})")
                logger.info(f"获取阅读信息 - 阅读详情: 阅读时长={reading_time}秒, 进度={progress}%, 开始阅读时间戳={start_reading_time}, 更新时间戳={update_time}")
                logger.info(f"获取阅读信息 - 时间字段详情: finishedDate={result.get('finishedDate')}, lastReadingDate={result.get('lastReadingDate')}, beginReadingDate={result.get('beginReadingDate')}")
                logger.debug(f"获取阅读信息 - 最终返回数据: {result}")
                return result
            else:
                logger.error(f"获取阅读信息 - 请求失败: {r.status_code} - {r.text}")
                logger.debug(f"获取阅读信息 - 失败响应头: {dict(r.headers)}")
                try:
                    errcode = r.json().get("errcode", 0) if r.text else 0
                except:
                    errcode = 0
                self.handle_errcode(errcode)
                return None
                
        except Exception as e:
            logger.error(f"获取阅读信息 - 请求异常: {str(e)}")
            import traceback
            logger.error(f"获取阅读信息 - 异常堆栈: {traceback.format_exc()}")
            return None
    
    def refresh_cookie(self):
        """刷新Cookie，模仿TypeScript版本的实现"""
        try:
            logger.info("尝试刷新Cookie...")
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.103 Safari/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Content-Type': 'application/json',
            }
            
            # 发送HEAD请求到主页
            r = self._send_request(
                "REFRESH_COOKIE",
                "HEAD",
                WEREAD_URL,
                use_session=False,
                headers=headers,
                cookies=self.session.cookies,
                timeout=30,
            )
            
            # 检查是否有新的Cookie
            if 'Set-Cookie' in r.headers:
                logger.info("收到新的Cookie，更新session")
                # 更新session的cookies
                for cookie in r.cookies:
                    self.session.cookies.set(cookie.name, cookie.value)
                return True
            else:
                logger.warning("未收到新的Cookie")
                return False
                
        except Exception as e:
            logger.error(f"刷新Cookie失败: {str(e)}")
            return False

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_review_list(self, bookId):
        headers = dict(self.session.headers)
        params = dict(bookId=bookId, listType=11, mine=1, synckey=0)
        self._send_request("REVIEW_PREFLIGHT", "GET", WEREAD_URL)
        r = self._send_request("GET_REVIEW_LIST", "GET", WEREAD_REVIEW_LIST_URL, params=params, headers=headers)
        
        if r.ok:
            data = r.json()
            logger.info(f"获取想法列表 - 响应数据键: {list(data.keys()) if data else 'None'}")
            logger.debug(f"获取想法列表 - 完整响应: {data}")
            
            # 检查是否有错误码
            if data.get('errCode') and data.get('errCode') != 0:
                logger.warning(f"获取想法列表 - API返回错误: {data.get('errMsg', '未知错误')} (错误码: {data.get('errCode')})")
                if data.get('errCode') == -2012:  # 登录超时
                    logger.warning(f"获取想法列表 - 登录超时，跳过书籍 {bookId}")
                    return []
                self.handle_errcode(data.get('errCode', 0))
                return []
            
            reviews = data.get("reviews", [])
            if reviews:
                reviews = list(map(lambda x: x.get("review"), reviews))
                reviews = [
                    {"chapterUid": 1000000, **x} if x.get("type") == 4 else x
                    for x in reviews
                ]
            logger.info(f"获取到 {len(reviews)} 个想法")
            return reviews
        else:
            logger.error(f"获取想法列表 - 请求失败: {r.status_code} - {r.text}")
            errcode = r.json().get("errcode", 0) if r.text else 0
            self.handle_errcode(errcode)
            return []



    
    def get_api_data(self):
        headers = dict(self.session.headers)
        self._send_request("HISTORY_PREFLIGHT", "GET", WEREAD_URL)
        r = self._send_request("GET_HISTORY", "GET", WEREAD_HISTORY_URL, headers=headers)
        
        if r.ok:
            data = r.json()
            logger.info(f"获取历史数据 - 响应数据键: {list(data.keys()) if data else 'None'}")
            logger.debug(f"获取历史数据 - 完整响应: {data}")
            
            # 检查是否有错误码
            if data.get('errCode') and data.get('errCode') != 0:
                logger.warning(f"获取历史数据 - API返回错误: {data.get('errMsg', '未知错误')} (错误码: {data.get('errCode')})")
                self.handle_errcode(data.get('errCode', 0))
                return None
            
            return data
        else:
            logger.error(f"获取历史数据 - 请求失败: {r.status_code} - {r.text}")
            errcode = r.json().get("errcode", 0) if r.text else 0
            self.handle_errcode(errcode)
            return None

    

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_chapter_info(self, bookId):
        headers = dict(self.session.headers)
        body = {"bookIds": [bookId], "synckeys": [0], "teenmode": 0}
        self._send_request("CHAPTER_PREFLIGHT", "GET", WEREAD_URL)
        r = self._send_request("GET_CHAPTER_INFO", "POST", WEREAD_CHAPTER_INFO, json=body, headers=headers)
        
        if r.ok:
            data = r.json()
            logger.info(f"获取章节信息 - 响应数据键: {list(data.keys()) if data else 'None'}")
            logger.debug(f"获取章节信息 - 完整响应: {data}")
            
            # 检查是否有错误码
            if data.get('errCode') and data.get('errCode') != 0:
                logger.warning(f"获取章节信息 - API返回错误: {data.get('errMsg', '未知错误')} (错误码: {data.get('errCode')})")
                if data.get('errCode') == -2012:  # 登录超时
                    logger.warning(f"获取章节信息 - 登录超时，跳过书籍 {bookId}")
                    return None
                self.handle_errcode(data.get('errCode', 0))
                return None
            
            if (
                "data" in data
                and len(data["data"]) == 1
                and "updated" in data["data"][0]
            ):
                update = data["data"][0]["updated"]
                update.append(
                    {
                        "chapterUid": 1000000,
                        "chapterIdx": 1000000,
                        "updateTime": 1683825006,
                        "readAhead": 0,
                        "title": "点评",
                        "level": 1,
                    }
                )
                logger.info(f"获取到 {len(update)} 个章节信息")
                return {item["chapterUid"]: item for item in update}
            else:
                logger.warning(f"获取章节信息 - 响应数据格式异常")
                return None
        else:
            logger.error(f"获取章节信息 - 请求失败: {r.status_code} - {r.text}")
            errcode = r.json().get("errcode", 0) if r.text else 0
            self.handle_errcode(errcode)
            return None

    def transform_id(self, book_id):
        id_length = len(book_id)
        if re.match("^\\d*$", book_id):
            ary = []
            for i in range(0, id_length, 9):
                ary.append(format(int(book_id[i : min(i + 9, id_length)]), "x"))
            return "3", ary

        result = ""
        for i in range(id_length):
            result += format(ord(book_id[i]), "x")
        return "4", [result]

    def calculate_book_str_id(self, book_id):
        md5 = hashlib.md5()
        md5.update(book_id.encode("utf-8"))
        digest = md5.hexdigest()
        result = digest[0:3]
        code, transformed_ids = self.transform_id(book_id)
        result += code + "2" + digest[-2:]

        for i in range(len(transformed_ids)):
            hex_length_str = format(len(transformed_ids[i]), "x")
            if len(hex_length_str) == 1:
                hex_length_str = "0" + hex_length_str

            result += hex_length_str + transformed_ids[i]

            if i < len(transformed_ids) - 1:
                result += "g"

        if len(result) < 20:
            result += digest[0 : 20 - len(result)]

        md5 = hashlib.md5()
        md5.update(result.encode("utf-8"))
        result += md5.hexdigest()[0:3]
        return result

    def get_url(self, book_id):
        return f"https://weread.qq.com/web/reader/{self.calculate_book_str_id(book_id)}"
