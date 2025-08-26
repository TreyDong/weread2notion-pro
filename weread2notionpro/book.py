import pendulum
import logging
from weread2notionpro.notion_helper import NotionHelper
from weread2notionpro.weread_api import WeReadApi
from weread2notionpro import utils
from weread2notionpro.config import book_properties_type_dict, tz

# 获取logger实例
logger = logging.getLogger(__name__)

TAG_ICON_URL = "https://www.notion.so/icons/tag_gray.svg"
USER_ICON_URL = "https://www.notion.so/icons/user-circle-filled_gray.svg"
BOOK_ICON_URL = "https://www.notion.so/icons/book_gray.svg"
rating = {"poor": "⭐️", "fair": "⭐️⭐️⭐️", "good": "⭐️⭐️⭐️⭐️⭐️"}



def insert_book_to_notion(books, index, bookId, all_books_dict=None):
    """插入Book到Notion"""
    book = {}
    if bookId in archive_dict:
        book["书架分类"] = archive_dict.get(bookId)
    if bookId in notion_books:
        book.update(notion_books.get(bookId))
    
    # 优先从所有书本数据获取详细信息，如果没有则通过API获取
    if all_books_dict and bookId in all_books_dict:
        shelf_book = all_books_dict[bookId]
        book_title = shelf_book.get('title', '未知书名')
        logger.info(f"   从书架数据获取书籍信息: {book_title} (bookId: {bookId})")
        book.update({
            'title': shelf_book.get('title', '未知书名'),
            'author': shelf_book.get('author', '未知作者'),
            'cover': shelf_book.get('cover', ''),
            'bookId': bookId,
            'categories': shelf_book.get('categories', []),
            'intro': shelf_book.get('intro', ''),
            'isbn': shelf_book.get('isbn', ''),
            'price': shelf_book.get('price', 0),
            'publishTime': shelf_book.get('publishTime', ''),
            'translator': shelf_book.get('translator', '')
        })
    else:
        logger.info(f"   书架数据中未找到书籍 {bookId}，尝试通过API获取书籍信息...")
        try:
            book_info = weread_api.get_bookinfo(bookId)
            if book_info:
                api_book_title = book_info.get('title', '未知书名')
                logger.info(f"   通过API获取书籍信息: {api_book_title} (bookId: {bookId})")
                book.update({
                    'title': book_info.get('title', '未知书名'),
                    'author': book_info.get('author', '未知作者'),
                    'cover': book_info.get('cover', ''),
                    'bookId': bookId,
                    'categories': book_info.get('categories', []),
                    'intro': book_info.get('intro', ''),
                    'isbn': book_info.get('isbn', ''),
                    'price': book_info.get('price', 0),
                    'publishTime': book_info.get('publishTime', ''),
                    'translator': book_info.get('translator', '')
                })
            else:
                logger.error(f"   错误：无法获取书籍 {bookId} 的基本信息")
                raise Exception(f"无法获取书籍 {bookId} 的基本信息，API返回为空")
        except Exception as e:
            logger.error(f"   获取书籍 {bookId} 信息失败: {str(e)}")
            raise Exception(f"获取书籍 {bookId} 信息失败: {str(e)}") from e
    
    book_title = book.get('title', '未知书名')
    logger.info(f"   开始获取书籍《{book_title}》的阅读信息 (bookId: {bookId})")
    
    readInfo = weread_api.get_read_info(bookId)
    if readInfo != None:
        logger.info(f"   成功获取阅读信息 (bookId: {bookId})")
        logger.debug(f"   阅读信息原始数据键: {list(readInfo.keys())}")
        
        # 研究了下这个状态不知道什么情况有的虽然读了状态还是1 markedStatus = 1 想读 4 读完 其他为在读
        readInfo.update(readInfo.get("readDetail", {}))
        readInfo.update(readInfo.get("bookInfo", {}))
        book.update(readInfo)
        
        # 更新后重新获取书籍标题，因为阅读信息可能包含更准确的书籍信息
        updated_book_title = book.get('title', '未知书名')
        logger.info(f"   书籍《{updated_book_title}》阅读信息合并完成，当前book数据键: {list(book.keys())}")
    else:
        logger.warning(f"   警告：无法获取阅读信息 (bookId: {bookId})")
    book["阅读进度"] = (
        100 if (book.get("markedStatus") == 4) else book.get("readingProgress", 0)
    ) / 100
    markedStatus = book.get("markedStatus")
    status = "想读"
    if markedStatus == 4:
        status = "已读"
    elif book.get("readingTime", 0) >= 60:
        status = "在读"
    book["阅读状态"] = status
    book["阅读时长"] = book.get("readingTime")
    book["阅读天数"] = book.get("totalReadDay")
    book["评分"] = book.get("newRating")
    if book.get("newRatingDetail") and book.get("newRatingDetail").get("myRating"):
        book["我的评分"] = rating.get(book.get("newRatingDetail").get("myRating"))
    elif status == "已读":
        book["我的评分"] = "未评分"
    # 处理时间字段 - 将时间戳转换为日期格式
    def convert_timestamp_to_date(timestamp):
        """将时间戳转换为日期格式"""
        if timestamp and isinstance(timestamp, (int, float)) and timestamp > 0:
            try:
                # 转换时间戳为日期字符串格式 (YYYY-MM-DD)
                import datetime
                dt = datetime.datetime.fromtimestamp(timestamp)
                return dt.strftime('%Y-%m-%d')
            except (ValueError, TypeError, OSError):
                pass
        return None
    
    # 记录原始时间戳用于调试
    logger.info(f"   书籍《{book_title}》的时间戳字段处理:")
    logger.info(f"     原始时间戳 - startReadingTime: {book.get('startReadingTime')}")
    logger.info(f"     原始时间戳 - updateTime: {book.get('updateTime')}")
    logger.info(f"     原始时间戳 - finishedDate: {book.get('finishedDate')}")
    logger.info(f"     原始时间戳 - lastReadingDate: {book.get('lastReadingDate')}")
    logger.info(f"     原始时间戳 - readingBookDate: {book.get('readingBookDate')}")
    logger.info(f"     原始时间戳 - beginReadingDate: {book.get('beginReadingDate')}")
    
    # 获取各种时间戳并转换为日期格式
    start_reading_time = convert_timestamp_to_date(book.get("startReadingTime"))
    update_time = convert_timestamp_to_date(book.get("updateTime"))
    finished_date = convert_timestamp_to_date(book.get("finishedDate"))
    last_reading_date = convert_timestamp_to_date(book.get("lastReadingDate"))
    reading_book_date = convert_timestamp_to_date(book.get("readingBookDate"))
    
    # 记录转换后的日期
    logger.info(f"     转换后日期 - startReadingTime: {start_reading_time}")
    logger.info(f"     转换后日期 - updateTime: {update_time}")
    logger.info(f"     转换后日期 - finishedDate: {finished_date}")
    logger.info(f"     转换后日期 - lastReadingDate: {last_reading_date}")
    logger.info(f"     转换后日期 - readingBookDate: {reading_book_date}")
    begin_reading_date = convert_timestamp_to_date(book.get("beginReadingDate"))
    
    # 记录转换后的日期
    logger.info(f"转换后的日期字段:")
    logger.info(f"  开始阅读时间: {start_reading_time}")
    logger.info(f"  更新时间: {update_time}")
    logger.info(f"  完成时间: {finished_date}")
    logger.info(f"  最后阅读时间: {last_reading_date}")
    
    # 设置时间字段 - 优先级：完成时间 > 最后阅读时间 > 更新时间 > 开始阅读时间
    # 确保传递给Notion的是时间戳数字格式，而不是日期字符串
    time_value = (
        book.get("finishedDate")
        or book.get("lastReadingDate") 
        or book.get("updateTime")
        or book.get("startReadingTime")
        or book.get("readingBookDate")
    )
    
    # 确保时间值是数字类型
    if time_value and isinstance(time_value, (int, float)) and time_value > 0:
        book["时间"] = time_value
    else:
        book["时间"] = None
    
    # 设置开始阅读时间和最后阅读时间 - 确保传递数字格式
    start_time_value = book.get("startReadingTime") or book.get("beginReadingDate")
    if start_time_value and isinstance(start_time_value, (int, float)) and start_time_value > 0:
        book["开始阅读时间"] = start_time_value
    else:
        book["开始阅读时间"] = None
        
    last_time_value = book.get("lastReadingDate") or book.get("updateTime")
    if last_time_value and isinstance(last_time_value, (int, float)) and last_time_value > 0:
        book["最后阅读时间"] = last_time_value
    else:
        book["最后阅读时间"] = None
    cover = book.get("cover")
    if cover and isinstance(cover, str):
        cover = cover.replace("/s_", "/t7_")
    if not cover or not isinstance(cover, str) or not cover.strip() or not cover.startswith("http"):
        cover = BOOK_ICON_URL
    if bookId not in notion_books:
        book["书名"] = book.get("title")
        book["BookId"] = book.get("bookId")
        book["ISBN"] = book.get("isbn")
        book["链接"] = weread_api.get_url(bookId)
        book["简介"] = book.get("intro")
        author = book.get("author")
        if author and isinstance(author, str):
            book["作者"] = [
                notion_helper.get_relation_id(
                    x, notion_helper.author_database_id, USER_ICON_URL
                )
                for x in author.split(" ") if x.strip()
            ]
        else:
            book["作者"] = []
        if book.get("categories"):
            book["分类"] = [
                notion_helper.get_relation_id(
                    x.get("title"), notion_helper.category_database_id, TAG_ICON_URL
                )
                for x in book.get("categories")
            ]
    properties = utils.get_properties(book, book_properties_type_dict)
    if book.get("时间") and isinstance(book.get("时间"), (int, float)) and book.get("时间") > 0:
        notion_helper.get_date_relation(
            properties,
            pendulum.from_timestamp(book.get("时间"), tz="Asia/Shanghai"),
        )

    logger.info(
        f"正在插入《{book.get('title')}》,一共{len(books)}本，当前是第{index+1}本。"
    )
    logger.info(f"传入Notion的完整参数 - properties: {properties}")
    logger.info(f"传入Notion的完整参数 - cover/icon: {utils.get_icon(cover)}")
    
    parent = {"database_id": notion_helper.book_database_id, "type": "database_id"}
    result = None
    try:
        if bookId in notion_books:
            logger.info(f"更新现有页面 - page_id: {notion_books.get(bookId).get('pageId')}")
            result = notion_helper.update_page(
                page_id=notion_books.get(bookId).get("pageId"),
                properties=properties,
                cover=utils.get_icon(cover),
            )
        else:
            logger.info(f"创建新页面 - parent: {parent}")
            result = notion_helper.create_book_page(
                parent=parent,
                properties=properties,
                icon=utils.get_icon(cover),
            )
        
        if not result or not result.get("id"):
            logger.error(f"   错误：Notion API返回结果无效，无法获取页面ID")
            raise Exception(f"Notion API返回结果无效，无法获取页面ID")
            
        page_id = result.get("id")
        logger.info(f"   成功创建/更新Notion页面，page_id: {page_id}")
        
        # 插入阅读数据
        if book.get("readDetail") and book.get("readDetail").get("data"):
            try:
                data = book.get("readDetail").get("data")
                data = {item.get("readDate"): item.get("readTime") for item in data}
                logger.info(f"   开始插入阅读数据，共{len(data)}条记录")
                insert_read_data(page_id, data)
                logger.info(f"   阅读数据插入完成")
            except Exception as e:
                logger.error(f"   插入阅读数据失败: {str(e)}")
                # 阅读数据插入失败不影响主要的书籍同步，只记录错误
                
    except Exception as e:
        logger.error(f"   同步书籍《{book.get('title', '未知书名')}》到Notion失败: {str(e)}")
        raise Exception(f"同步书籍《{book.get('title', '未知书名')}》到Notion失败: {str(e)}") from e
    
    # 返回同步成功标志
    return True


def insert_read_data(page_id, readTimes):
    try:
        logger.info(f"     开始处理阅读数据，page_id: {page_id}")
        readTimes = dict(sorted(readTimes.items()))
        filter = {"property": "书架", "relation": {"contains": page_id}}
        
        try:
            results = notion_helper.query_all_by_book(notion_helper.read_database_id, filter)
            logger.info(f"     查询到{len(results)}条现有阅读记录")
        except Exception as e:
            logger.error(f"     查询现有阅读记录失败: {str(e)}")
            raise Exception(f"查询现有阅读记录失败: {str(e)}") from e
            
        # 更新现有记录
        updated_count = 0
        for result in results:
            try:
                timestamp = result.get("properties").get("时间戳").get("number")
                duration = result.get("properties").get("时长").get("number")
                id = result.get("id")
                if timestamp in readTimes:
                    value = readTimes.pop(timestamp)
                    if value != duration:
                        insert_to_notion(
                            page_id=id,
                            timestamp=timestamp,
                            duration=value,
                            book_database_id=page_id,
                        )
                        updated_count += 1
            except Exception as e:
                logger.error(f"     更新阅读记录失败 (timestamp: {timestamp}): {str(e)}")
                # 继续处理其他记录
                
        logger.info(f"     更新了{updated_count}条现有阅读记录")
        
        # 创建新记录
        new_count = 0
        for key, value in readTimes.items():
            try:
                insert_to_notion(None, int(key), value, page_id)
                new_count += 1
            except Exception as e:
                logger.error(f"     创建新阅读记录失败 (timestamp: {key}): {str(e)}")
                # 继续处理其他记录
                
        logger.info(f"     创建了{new_count}条新阅读记录")
        
    except Exception as e:
        logger.error(f"     处理阅读数据失败: {str(e)}")
        raise Exception(f"处理阅读数据失败: {str(e)}") from e


def insert_to_notion(page_id, timestamp, duration, book_database_id):
    try:
        parent = {"database_id": notion_helper.read_database_id, "type": "database_id"}
        
        # 构建properties时添加异常处理
        try:
            properties = {
                "标题": utils.get_title(
                    pendulum.from_timestamp(timestamp, tz=tz).to_date_string()
                ),
                "日期": utils.get_date(
                    start=pendulum.from_timestamp(timestamp, tz=tz).format(
                        "YYYY-MM-DD HH:mm:ss"
                    )
                ),
                "时长": utils.get_number(duration),
                "时间戳": utils.get_number(timestamp),
                "书架": utils.get_relation([book_database_id]),
            }
        except Exception as e:
            logger.error(f"       构建阅读记录属性失败 (timestamp: {timestamp}): {str(e)}")
            raise Exception(f"构建阅读记录属性失败: {str(e)}") from e
            
        # 执行Notion API调用
        try:
            if page_id != None:
                logger.debug(f"       更新阅读记录 page_id: {page_id}, timestamp: {timestamp}")
                notion_helper.client.pages.update(page_id=page_id, properties=properties)
            else:
                logger.debug(f"       创建新阅读记录 timestamp: {timestamp}, duration: {duration}")
                notion_helper.client.pages.create(
                    parent=parent,
                    icon=utils.get_icon("https://www.notion.so/icons/target_red.svg"),
                    properties=properties,
                )
        except Exception as e:
            action = "更新" if page_id else "创建"
            logger.error(f"       {action}阅读记录失败 (timestamp: {timestamp}): {str(e)}")
            raise Exception(f"{action}阅读记录失败: {str(e)}") from e
            
    except Exception as e:
        logger.error(f"       处理阅读记录失败 (timestamp: {timestamp}): {str(e)}")
        raise Exception(f"处理阅读记录失败: {str(e)}") from e


weread_api = WeReadApi()
notion_helper = NotionHelper()
archive_dict = {}
notion_books = {}


def main():
    global notion_books
    global archive_dict
    # 在main函数中初始化API对象

    
    try:
         logger.info("开始同步微信读书数据到Notion...")
         
         logger.info("1. 获取微信读书所有书籍信息（使用书架API）...")
         bookshelf_data = weread_api.get_bookshelf()
         if not bookshelf_data or not bookshelf_data.get('books'):
             logger.error("错误：无法获取微信读书书架信息")
             return
         all_books = bookshelf_data.get('books', [])
         logger.info(f"   获取到书架信息，包含 {len(all_books)} 本书")
         
         logger.info("2. 处理完整的书架数据...")
         # 使用真实的书架数据
         bookshelf_books = bookshelf_data
         
         logger.info("3. 获取Notion中的书籍信息...")
         notion_books = notion_helper.get_all_book()
         logger.info(f"   Notion中已有 {len(notion_books)} 本书")
         
         logger.info("4. 处理书籍进度信息...")
         bookProgress = bookshelf_books.get("bookProgress", [])
         if bookProgress is None:
             logger.warning("   警告：未获取到书籍进度信息")
             bookProgress = []
         else:
             logger.info(f"   获取到 {len(bookProgress)} 本书的进度信息")
         bookProgress = {book.get("bookId"): book for book in bookProgress if book.get("bookId")}
         
         logger.info("5. 处理书架分类信息...")
         archives = bookshelf_books.get("archive", [])
         logger.info(f"   获取到 {len(archives)} 个分类")
         for archive in archives:
             name = archive.get("name")
             bookIds = archive.get("bookIds", [])
             archive_dict.update({bookId: name for bookId in bookIds})
             logger.info(f"   分类 '{name}' 包含 {len(bookIds)} 本书")
         
         logger.info("6. 分析需要同步的书籍...")
         not_need_sync = []
         for key, value in notion_books.items():
             if (
                 (
                     key not in bookProgress
                     or value.get("readingTime") == bookProgress.get(key).get("readingTime")
                 )
                 and (archive_dict.get(key) == value.get("category"))
                 and (value.get("cover") is not None)
                 and (
                     value.get("status") != "已读"
                     or (value.get("status") == "已读" and value.get("myRating"))
                 )
             ):
                 not_need_sync.append(key)
         logger.info(f"   {len(not_need_sync)} 本书无需同步")
         
         logger.info("7. 整理需要同步的书籍列表...")
         # 从所有书架书籍中提取书籍ID
         all_book_ids = [book.get("bookId") for book in all_books if book.get("bookId")]
         logger.info(f"   从书架获取到 {len(all_book_ids)} 本书")
         
         # 将所有书籍转换为字典形式，以bookId为键
         all_books_dict = {book.get("bookId"): book for book in all_books if book.get("bookId")}
         logger.info(f"   构建书架字典，包含 {len(all_books_dict)} 本书")
         
         # 使用所有书架书籍，去除无需同步的书籍
         books = list(set(all_book_ids) - set(not_need_sync))
         logger.info(f"   共需要同步 {len(books)} 本书")
         
         logger.info("8. 开始同步书籍...")
         for index, bookId in enumerate(books):
             logger.info(f"   正在同步第 {index + 1}/{len(books)} 本书 (ID: {bookId})")
             try:
                 insert_book_to_notion(books, index, bookId, all_books_dict)
                 logger.info(f"   ✓ 书籍 {bookId} 同步成功")
             except Exception as e:
                 logger.error(f"   ✗ 书籍 {bookId} 同步失败: {str(e)}")
                 continue
         
         logger.info("同步完成！")
         
    except Exception as e:
        logger.error(f"同步过程中发生错误: {str(e)}")
        raise


if __name__ == "__main__":
    main()
