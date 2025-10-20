import json
import logging
import os
import re
import time
import uuid
from datetime import timedelta
from time import perf_counter
from typing import Any, Dict, Optional

import pendulum
from notion_client import Client
from retrying import retry
from dotenv import load_dotenv

load_dotenv()
from weread2notionpro.utils  import (
    format_date,
    get_date,
    get_first_and_last_day_of_month,
    get_first_and_last_day_of_week,
    get_first_and_last_day_of_year,
    get_icon,
    get_number,
    get_relation,
    get_rich_text,
    get_title,
    timestamp_to_date,
    get_property_value,
)

TAG_ICON_URL = "https://www.notion.so/icons/tag_gray.svg"
USER_ICON_URL = "https://www.notion.so/icons/user-circle-filled_gray.svg"
TARGET_ICON_URL = "https://www.notion.so/icons/target_red.svg"
BOOKMARK_ICON_URL = "https://www.notion.so/icons/bookmark_gray.svg"

logger = logging.getLogger(__name__)

NOTION_LOG_PREVIEW = 800
SENSITIVE_SUBSTRINGS = ("token", "cookie", "secret", "auth", "password")


def _truncate_value(value: Optional[str]) -> str:
    if value is None:
        return "None"
    if len(value) > NOTION_LOG_PREVIEW:
        return f"{value[:NOTION_LOG_PREVIEW]}... (截断, 原长度 {len(value)})"
    return value


def _sanitize_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        sanitized: Dict[Any, Any] = {}
        for key, value in payload.items():
            if isinstance(key, str) and any(token in key.lower() for token in SENSITIVE_SUBSTRINGS):
                sanitized[key] = "<已隐藏>"
            else:
                sanitized[key] = _sanitize_payload(value)
        return sanitized
    if isinstance(payload, list):
        return [_sanitize_payload(item) for item in payload]
    return payload


def _serialize_payload(payload: Any) -> str:
    try:
        sanitized = _sanitize_payload(payload)
        if isinstance(sanitized, (dict, list)):
            text = json.dumps(sanitized, ensure_ascii=False, default=str)
        else:
            text = str(sanitized)
    except Exception as exc:
        text = f"<无法序列化: {exc}>"
    return _truncate_value(text)


class NotionHelper:
    database_name_dict = {
        "BOOK_DATABASE_NAME": "书架",
        "REVIEW_DATABASE_NAME": "笔记",
        "BOOKMARK_DATABASE_NAME": "划线",
        "DAY_DATABASE_NAME": "日",
        "WEEK_DATABASE_NAME": "周",
        "MONTH_DATABASE_NAME": "月",
        "YEAR_DATABASE_NAME": "年",
        "CATEGORY_DATABASE_NAME": "分类",
        "AUTHOR_DATABASE_NAME": "作者",
        "CHAPTER_DATABASE_NAME": "章节",
        "READ_DATABASE_NAME": "阅读记录",
        "SETTING_DATABASE_NAME": "设置",
    }
    database_id_dict = {}
    heatmap_block_id = None
    show_color = True
    block_type = "callout"
    sync_bookmark = True
    def __init__(self):
        self.client = Client(auth=os.getenv("NOTION_TOKEN"), log_level=logging.ERROR)
        self.__cache = {}
        self.page_id = self.extract_page_id(os.getenv("NOTION_PAGE"))
        self.search_database(self.page_id)
        for key in self.database_name_dict.keys():
            if os.getenv(key) != None and os.getenv(key) != "":
                self.database_name_dict[key] = os.getenv(key)
        self.book_database_id = self.database_id_dict.get(
            self.database_name_dict.get("BOOK_DATABASE_NAME")
        )
        self.review_database_id = self.database_id_dict.get(
            self.database_name_dict.get("REVIEW_DATABASE_NAME")
        )
        self.bookmark_database_id = self.database_id_dict.get(
            self.database_name_dict.get("BOOKMARK_DATABASE_NAME")
        )
        self.day_database_id = self.database_id_dict.get(
            self.database_name_dict.get("DAY_DATABASE_NAME")
        )
        self.week_database_id = self.database_id_dict.get(
            self.database_name_dict.get("WEEK_DATABASE_NAME")
        )
        self.month_database_id = self.database_id_dict.get(
            self.database_name_dict.get("MONTH_DATABASE_NAME")
        )
        self.year_database_id = self.database_id_dict.get(
            self.database_name_dict.get("YEAR_DATABASE_NAME")
        )
        self.category_database_id = self.database_id_dict.get(
            self.database_name_dict.get("CATEGORY_DATABASE_NAME")
        )
        self.author_database_id = self.database_id_dict.get(
            self.database_name_dict.get("AUTHOR_DATABASE_NAME")
        )
        self.chapter_database_id = self.database_id_dict.get(
            self.database_name_dict.get("CHAPTER_DATABASE_NAME")
        )
        self.read_database_id = self.database_id_dict.get(
            self.database_name_dict.get("READ_DATABASE_NAME")
        )  
        self.setting_database_id = self.database_id_dict.get(
            self.database_name_dict.get("SETTING_DATABASE_NAME")
        )
        self.update_book_database()
        if self.read_database_id is None:
            self.create_database()
        if self.setting_database_id is None:
            self.create_setting_database()
        if self.setting_database_id:
            self.insert_to_setting_database()
        logger.info(
            "NotionHelper 初始化完成: book_db=%s, review_db=%s, bookmark_db=%s, read_db=%s",
            self.book_database_id,
            self.review_database_id,
            self.bookmark_database_id,
            self.read_database_id,
        )

    def _notion_api_call(self, name: str, func, *, summary: Optional[Dict[str, Any]] = None, **kwargs):
        request_id = f"NOTION-{name}-{uuid.uuid4().hex[:8]}"
        start_time = perf_counter()
        logger.info(f"[{request_id}] {name} - Notion API调用开始")
        if summary:
            for key, value in summary.items():
                logger.info(f"[{request_id}] {key}: {value}")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"[{request_id}] 调用参数: {_serialize_payload(kwargs)}")
        try:
            result = func(**kwargs)
        except Exception as exc:
            duration = perf_counter() - start_time
            logger.error(f"[{request_id}] {name} - 调用失败: {exc}")
            logger.error(f"[{request_id}] 调用耗时: {duration:.3f} 秒")
            raise
        duration = perf_counter() - start_time
        logger.info(f"[{request_id}] {name} - 调用成功, 耗时 {duration:.3f} 秒")

        if isinstance(result, dict):
            logger.info(f"[{request_id}] 返回字段: {list(result.keys())}")
            if 'id' in result:
                logger.info(f"[{request_id}] 返回ID: {result.get('id')}")
        elif isinstance(result, list):
            logger.info(f"[{request_id}] 返回列表长度: {len(result)}")

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"[{request_id}] 返回内容: {_serialize_payload(result)}")
        return result

    def extract_page_id(self, notion_url):
        # 正则表达式匹配 32 个字符的 Notion page_id
        match = re.search(
            r"([a-f0-9]{32}|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})",
            notion_url,
        )
        if match:
            return match.group(0)
        else:
            raise Exception(f"获取NotionID失败，请检查输入的Url是否正确")

    def search_database(self, block_id):
        response = self._notion_api_call(
            "BLOCK_CHILDREN_LIST",
            self.client.blocks.children.list,
            summary={"block_id": block_id},
            block_id=block_id,
        )
        children = response.get("results", [])
        logger.info(f"检索到 {len(children)} 个子块 (block_id: {block_id})")
        # 遍历子块
        for child in children:
            # 检查子块的类型
            if child["type"] == "child_database":
                self.database_id_dict[child.get("child_database").get("title")] = (
                    child.get("id")
                )
            elif child["type"] == "embed" and child.get("embed").get("url"):
                if child.get("embed").get("url").startswith("https://heatmap.malinkang.com/"):
                    self.heatmap_block_id = child.get("id")
            # 如果子块有子块，递归调用函数
            if "has_children" in child and child["has_children"]:
                self.search_database(child["id"])

    def update_book_database(self):
        """更新数据库"""
        response = self._notion_api_call(
            "DATABASE_RETRIEVE",
            self.client.databases.retrieve,
            summary={"database_id": self.book_database_id},
            database_id=self.book_database_id,
        )
        id = response.get("id")
        properties = response.get("properties")
        update_properties = {}
        if (
            properties.get("阅读时长") is None
            or properties.get("阅读时长").get("type") != "number"
        ):
            update_properties["阅读时长"] = {"number": {}}
        if (
            properties.get("书架分类") is None
            or properties.get("书架分类").get("type") != "select"
        ):
            update_properties["书架分类"] = {"select": {}}
        if (
            properties.get("豆瓣链接") is None
            or properties.get("豆瓣链接").get("type") != "url"
        ):
            update_properties["豆瓣链接"] = {"url": {}}
        if (
            properties.get("我的评分") is None
            or properties.get("我的评分").get("type") != "select"
        ):
            update_properties["我的评分"] = {"select": {}}
        if (
            properties.get("豆瓣短评") is None
            or properties.get("豆瓣短评").get("type") != "rich_text"
        ):
            update_properties["豆瓣短评"] = {"rich_text": {}}
        """NeoDB先不添加了，现在受众还不广，可能有的小伙伴不知道是干什么的"""
        if len(update_properties) > 0:
            self._notion_api_call(
                "DATABASE_UPDATE",
                self.client.databases.update,
                summary={
                    "database_id": id,
                    "update_keys": list(update_properties.keys()),
                },
                database_id=id,
                properties=update_properties,
            )

    def create_database(self):
        title = [
            {
                "type": "text",
                "text": {
                    "content": self.database_name_dict.get("READ_DATABASE_NAME"),
                },
            },
        ]
        properties = {
            "标题": {"title": {}},
            "时长": {"number": {}},
            "时间戳": {"number": {}},
            "日期": {"date": {}},
            "书架": {
                "relation": {
                    "database_id": self.book_database_id,
                    "single_property": {},
                }
            },
        }
        parent = parent = {"page_id": self.page_id, "type": "page_id"}
        title_text = ''.join([
            t.get('text', {}).get('content', '')
            for t in title
            if isinstance(t, dict)
        ])
        response = self._notion_api_call(
            "DATABASE_CREATE_READ",
            self.client.databases.create,
            summary={
                "parent_type": parent.get("type"),
                "title": _truncate_value(title_text),
                "property_keys": list(properties.keys()),
            },
            parent=parent,
            title=title,
            icon=get_icon("https://www.notion.so/icons/target_gray.svg"),
            properties=properties,
        )
        self.read_database_id = response.get("id")    
        
    def create_setting_database(self):
        title = [
            {
                "type": "text",
                "text": {
                    "content": self.database_name_dict.get("SETTING_DATABASE_NAME"),
                },
            },
        ]
        properties = {
            "标题": {"title": {}},
            "NotinToken": {"rich_text": {}},
            "NotinPage": {"rich_text": {}},
            "WeReadCookie": {"rich_text": {}},
            "根据划线颜色设置文字颜色": {"checkbox": {}},
            "同步书签": {"checkbox": {}},
            # "Cookie状态": {
            #     "select": {
            #         "options": [
            #             {"name": "可用", "color": "green"},
            #             {"name": "过期", "color": "red"},
            #         ]
            #     }
            # },
            "样式": {
                "select": {
                    "options": [
                        {"name": "callout", "color": "blue"},
                        {"name": "quote", "color": "green"},
                        {"name": "paragraph", "color": "purple"},
                        {"name": "bulleted_list_item", "color": "yellow"},
                        {"name": "numbered_list_item", "color": "pink"},
                    ]
                }
            },
            "最后同步时间": {"date": {}},
        }
        parent = parent = {"page_id": self.page_id, "type": "page_id"}
        title_text = ''.join([
            t.get('text', {}).get('content', '')
            for t in title
            if isinstance(t, dict)
        ])
        response = self._notion_api_call(
            "DATABASE_CREATE_SETTING",
            self.client.databases.create,
            summary={
                "parent_type": parent.get("type"),
                "title": _truncate_value(title_text),
                "property_keys": list(properties.keys()),
            },
            parent=parent,
            title=title,
            icon=get_icon("https://www.notion.so/icons/gear_gray.svg"),
            properties=properties,
        )
        self.setting_database_id = response.get("id")

    def insert_to_setting_database(self):
        existing_response = self.query(
            database_id=self.setting_database_id,
            filter={"property": "标题", "title": {"equals": "设置"}},
        )
        existing_pages = existing_response.get("results")
        properties = {
            "标题": {"title": [{"type": "text", "text": {"content": "设置"}}]},
            "最后同步时间": {"date": {"start": pendulum.now("Asia/Shanghai").isoformat()}},
            "NotinToken": {"rich_text": [{"type": "text", "text": {"content": os.getenv("NOTION_TOKEN")}}]},
            "NotinPage": {"rich_text": [{"type": "text", "text": {"content": os.getenv("NOTION_PAGE")}}]},
            "WeReadCookie": {"rich_text": [{"type": "text", "text": {"content": os.getenv("WEREAD_COOKIE")}}]},
        }
        if existing_pages:
            remote_properties = existing_pages[0].get("properties")
            self.show_color = get_property_value(remote_properties.get("根据划线颜色设置文字颜色"))
            self.sync_bookmark = get_property_value(remote_properties.get("同步书签"))
            self.block_type = get_property_value(remote_properties.get("样式"))
            page_id = existing_pages[0].get("id")
            self._notion_api_call(
                "PAGE_UPDATE_SETTING",
                self.client.pages.update,
                summary={
                    "page_id": page_id,
                    "property_keys": list(properties.keys()),
                },
                page_id=page_id,
                properties=properties,
            )
        else:
            properties["根据划线颜色设置文字颜色"] = {"checkbox": True}
            properties["同步书签"] = {"checkbox": True}
            properties["样式"] = {"select": {"name": "callout"}}
            self._notion_api_call(
                "PAGE_CREATE_SETTING",
                self.client.pages.create,
                summary={
                    "database_id": self.setting_database_id,
                    "property_keys": list(properties.keys()),
                },
                parent={"database_id": self.setting_database_id},
                properties=properties,
            )
  
        

    def update_heatmap(self, block_id, url):
        # 更新 image block 的链接
        return self._notion_api_call(
            "BLOCK_UPDATE_HEATMAP",
            self.client.blocks.update,
            summary={"block_id": block_id, "url": url},
            block_id=block_id,
            embed={"url": url},
        )

    def get_week_relation_id(self, date):
        year = date.isocalendar().year
        week = date.isocalendar().week
        week = f"{year}年第{week}周"
        start, end = get_first_and_last_day_of_week(date)
        properties = {"日期": get_date(format_date(start), format_date(end))}
        return self.get_relation_id(
            week, self.week_database_id, TARGET_ICON_URL, properties
        )

    def get_month_relation_id(self, date):
        # Windows不支持%-m格式，使用%m然后去掉前导零
        month_num = str(int(date.strftime("%m")))
        month = date.strftime("%Y年") + month_num + "月"
        start, end = get_first_and_last_day_of_month(date)
        properties = {"日期": get_date(format_date(start), format_date(end))}
        return self.get_relation_id(
            month, self.month_database_id, TARGET_ICON_URL, properties
        )

    def get_year_relation_id(self, date):
        year = date.strftime("%Y")
        start, end = get_first_and_last_day_of_year(date)
        properties = {"日期": get_date(format_date(start), format_date(end))}
        return self.get_relation_id(
            year, self.year_database_id, TARGET_ICON_URL, properties
        )

    def get_day_relation_id(self, date):
        new_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
        timestamp = (new_date - timedelta(hours=8)).timestamp()
        day = new_date.strftime("%Y年%m月%d日")
        properties = {
            "日期": get_date(format_date(date)),
            "时间戳": get_number(timestamp),
        }
        properties["年"] = get_relation(
            [
                self.get_year_relation_id(new_date),
            ]
        )
        properties["月"] = get_relation(
            [
                self.get_month_relation_id(new_date),
            ]
        )
        properties["周"] = get_relation(
            [
                self.get_week_relation_id(new_date),
            ]
        )
        return self.get_relation_id(
            day, self.day_database_id, TARGET_ICON_URL, properties
        )

    def get_relation_id(self, name, id, icon, properties={}):
        key = f"{id}{name}"
        if key in self.__cache:
            logger.debug(f"命中缓存的关联ID: {name} ({key})")
            return self.__cache.get(key)
        filter = {"property": "标题", "title": {"equals": name}}
        response = self._notion_api_call(
            "DATABASE_QUERY_RELATION",
            self.client.databases.query,
            summary={"database_id": id, "title": name},
            database_id=id,
            filter=filter,
        )
        if len(response.get("results")) == 0:
            parent = {"database_id": id, "type": "database_id"}
            properties["标题"] = get_title(name)
            response = self._notion_api_call(
                "PAGE_CREATE_RELATION",
                self.client.pages.create,
                summary={
                    "database_id": id,
                    "title": name,
                    "property_keys": list(properties.keys()),
                },
                parent=parent,
                properties=properties,
                icon=get_icon(icon),
            )
            page_id = response.get("id")
            logger.info(f"创建新的关联项: {name} (page_id: {page_id})")
        else:
            page_id = response.get("results")[0].get("id")
            logger.info(f"复用既有关联项: {name} (page_id: {page_id})")
        self.__cache[key] = page_id
        return page_id

    def insert_bookmark(self, id, bookmark):
        logger.info(
            "准备插入划线: bookId=%s, bookmarkId=%s, 内容预览=%s",
            bookmark.get("bookId"),
            bookmark.get("bookmarkId"),
            _truncate_value(bookmark.get("markText", "")),
        )
        icon = get_icon(BOOKMARK_ICON_URL)
        properties = {
            "Name": get_title(bookmark.get("markText", "")),
            "bookId": get_rich_text(bookmark.get("bookId")),
            "range": get_rich_text(bookmark.get("range")),
            "bookmarkId": get_rich_text(bookmark.get("bookmarkId")),
            "blockId": get_rich_text(bookmark.get("blockId")),
            "chapterUid": get_number(bookmark.get("chapterUid")),
            "bookVersion": get_number(bookmark.get("bookVersion")),
            "colorStyle": get_number(bookmark.get("colorStyle")),
            "type": get_number(bookmark.get("type")),
            "style": get_number(bookmark.get("style")),
            "书籍": get_relation([id]),
        }
        if "createTime" in bookmark:
            create_time = timestamp_to_date(int(bookmark.get("createTime")))
            properties["Date"] = get_date(create_time.strftime("%Y-%m-%d %H:%M:%S"))
            self.get_date_relation(properties, create_time)
        parent = {"database_id": self.bookmark_database_id, "type": "database_id"}
        self.create_page(parent, properties, icon)

    def insert_review(self, id, review):
        time.sleep(0.1)
        logger.info(
            "准备插入笔记: bookId=%s, reviewId=%s, 内容预览=%s",
            review.get("bookId"),
            review.get("reviewId"),
            _truncate_value(review.get("content", "")),
        )
        icon = get_icon(TAG_ICON_URL)
        properties = {
            "Name": get_title(review.get("content", "")),
            "bookId": get_rich_text(review.get("bookId")),
            "reviewId": get_rich_text(review.get("reviewId")),
            "blockId": get_rich_text(review.get("blockId")),
            "chapterUid": get_number(review.get("chapterUid")),
            "bookVersion": get_number(review.get("bookVersion")),
            "type": get_number(review.get("type")),
            "书籍": get_relation([id]),
        }
        if "range" in review:
            properties["range"] = get_rich_text(review.get("range"))
        if "star" in review:
            properties["star"] = get_number(review.get("star"))
        if "abstract" in review:
            properties["abstract"] = get_rich_text(review.get("abstract"))
        if "createTime" in review:
            create_time = timestamp_to_date(int(review.get("createTime")))
            properties["Date"] = get_date(create_time.strftime("%Y-%m-%d %H:%M:%S"))
            self.get_date_relation(properties, create_time)
        parent = {"database_id": self.review_database_id, "type": "database_id"}
        self.create_page(parent, properties, icon)

    def insert_chapter(self, id, chapter):
        time.sleep(0.1)
        logger.info(
            "准备插入章节: bookId=%s, chapterUid=%s, title=%s",
            chapter.get("bookId"),
            chapter.get("chapterUid"),
            _truncate_value(chapter.get("title", "")),
        )
        icon = {"type": "external", "external": {"url": TAG_ICON_URL}}
        properties = {
            "Name": get_title(chapter.get("title")),
            "blockId": get_rich_text(chapter.get("blockId")),
            "chapterUid": {"number": chapter.get("chapterUid")},
            "chapterIdx": {"number": chapter.get("chapterIdx")},
            "readAhead": {"number": chapter.get("readAhead")},
            "updateTime": {"number": chapter.get("updateTime")},
            "level": {"number": chapter.get("level")},
            "书籍": {"relation": [{"id": id}]},
        }
        parent = {"database_id": self.chapter_database_id, "type": "database_id"}
        self.create_page(parent, properties, icon)

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def update_book_page(self, page_id, properties):
        return self._notion_api_call(
            "PAGE_UPDATE_BOOK",
            self.client.pages.update,
            summary={
                "page_id": page_id,
                "property_keys": list(properties.keys()),
            },
            page_id=page_id,
            properties=properties,
        )

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def update_page(self, page_id, properties, cover):
        return self._notion_api_call(
            "PAGE_UPDATE",
            self.client.pages.update,
            summary={
                "page_id": page_id,
                "property_keys": list(properties.keys()),
                "has_cover": cover is not None,
            },
            page_id=page_id,
            properties=properties,
            cover=cover,
        )


    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def create_page(self, parent, properties, icon):
        return self._notion_api_call(
            "PAGE_CREATE",
            self.client.pages.create,
            summary={
                "parent_ref": parent.get("database_id") or parent.get("page_id"),
                "property_keys": list(properties.keys()),
            },
            parent=parent,
            properties=properties,
            icon=icon,
        )

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def create_book_page(self, parent, properties, icon):
        return self._notion_api_call(
            "PAGE_CREATE_BOOK",
            self.client.pages.create,
            summary={
                "parent_ref": parent.get("database_id") or parent.get("page_id"),
                "property_keys": list(properties.keys()),
            },
            parent=parent,
            properties=properties,
            icon=icon,
            cover=icon,
        )

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def query(self, **kwargs):
        kwargs = {k: v for k, v in kwargs.items() if v}
        return self._notion_api_call(
            "DATABASE_QUERY_GENERIC",
            self.client.databases.query,
            summary={"database_id": kwargs.get("database_id")},
            **kwargs,
        )

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_block_children(self, id):
        response = self._notion_api_call(
            "BLOCK_CHILDREN_LIST",
            self.client.blocks.children.list,
            summary={"block_id": id},
            block_id=id,
        )
        return response.get("results")

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def append_blocks(self, block_id, children):
        return self._notion_api_call(
            "BLOCK_APPEND",
            self.client.blocks.children.append,
            summary={"block_id": block_id, "children": len(children)},
            block_id=block_id,
            children=children,
        )

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def append_blocks_after(self, block_id, children, after):
        #奇怪不知道为什么会多插入一个children，没找到问题，先暂时这么解决，搜索是否有parent
        parent_response = self._notion_api_call(
            "BLOCK_RETRIEVE",
            self.client.blocks.retrieve,
            summary={"block_id": after},
            block_id=after,
        )
        parent = parent_response.get("parent")
        if(parent.get("type")=="block_id"):
            after = parent.get("block_id")
        return self._notion_api_call(
            "BLOCK_APPEND_AFTER",
            self.client.blocks.children.append,
            summary={"block_id": block_id, "after": after, "children": len(children)},
            block_id=block_id,
            children=children,
            after=after,
        )

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def delete_block(self, block_id):
        return self._notion_api_call(
            "BLOCK_DELETE",
            self.client.blocks.delete,
            summary={"block_id": block_id},
            block_id=block_id,
        )

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_all_book(self):
        """从Notion中获取所有的书籍"""
        results = self.query_all(self.book_database_id)
        books_dict = {}
        for result in results:
            bookId = get_property_value(result.get("properties").get("BookId"))
            books_dict[bookId] = {
                "pageId": result.get("id"),
                "readingTime": get_property_value(
                    result.get("properties").get("阅读时长")
                ),
                "category": get_property_value(
                    result.get("properties").get("书架分类")
                ),
                "Sort": get_property_value(result.get("properties").get("Sort")),
                "douban_url": get_property_value(
                    result.get("properties").get("豆瓣链接")
                ),
                "cover": result.get("cover"),
                "myRating": get_property_value(
                    result.get("properties").get("我的评分")
                ),
                "comment": get_property_value(result.get("properties").get("豆瓣短评")),
                "status": get_property_value(result.get("properties").get("阅读状态")),
            }
        logger.info(f"从Notion读取到 {len(books_dict)} 本书的索引信息")
        return books_dict

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def query_all_by_book(self, database_id, filter):
        results = []
        has_more = True
        start_cursor = None
        while has_more:
            response = self._notion_api_call(
                "DATABASE_QUERY_PAGED",
                self.client.databases.query,
                summary={
                    "database_id": database_id,
                    "start_cursor": start_cursor,
                },
                database_id=database_id,
                filter=filter,
                start_cursor=start_cursor,
                page_size=100,
            )
            start_cursor = response.get("next_cursor")
            has_more = response.get("has_more")
            results.extend(response.get("results"))
        logger.info(f"数据库 {database_id} 查询完成，共返回 {len(results)} 条记录")
        return results

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def query_all(self, database_id):
        """获取database中所有的数据"""
        results = []
        has_more = True
        start_cursor = None
        while has_more:
            response = self._notion_api_call(
                "DATABASE_QUERY_ALL",
                self.client.databases.query,
                summary={
                    "database_id": database_id,
                    "start_cursor": start_cursor,
                },
                database_id=database_id,
                start_cursor=start_cursor,
                page_size=100,
            )
            start_cursor = response.get("next_cursor")
            has_more = response.get("has_more")
            results.extend(response.get("results"))
        logger.info(f"数据库 {database_id} 全量查询完成，共返回 {len(results)} 条记录")
        return results

    def get_date_relation(self, properties, date):
        properties["年"] = get_relation(
            [
                self.get_year_relation_id(date),
            ]
        )
        properties["月"] = get_relation(
            [
                self.get_month_relation_id(date),
            ]
        )
        properties["周"] = get_relation(
            [
                self.get_week_relation_id(date),
            ]
        )
        properties["日"] = get_relation(
            [
                self.get_day_relation_id(date),
            ]
        )
