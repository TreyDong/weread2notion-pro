import logging
from weread2notionpro.notion_helper import NotionHelper
from weread2notionpro.weread_api import WeReadApi

from weread2notionpro.utils import (
    get_block,
    get_heading,
    get_number,
    get_number_from_result,
    get_quote,
    get_rich_text_from_result,
    get_table_of_contents,
)

# 获取logger实例
logger = logging.getLogger(__name__)


def get_bookmark_list(page_id, bookId):
    """获取我的划线"""
    filter = {
        "and": [
            {"property": "书籍", "relation": {"contains": page_id}},
            {"property": "blockId", "rich_text": {"is_not_empty": True}},
        ]
    }
    logger.info(f"开始查询已有划线，page_id={page_id}")
    results = notion_helper.query_all_by_book(
        notion_helper.bookmark_database_id, filter
    )
    logger.info(f"Notion现有划线记录: {len(results)} 条")
    dict1 = {
        get_rich_text_from_result(x, "bookmarkId"): get_rich_text_from_result(
            x, "blockId"
        )
        for x in results
    }
    dict2 = {get_rich_text_from_result(x, "blockId"): x.get("id") for x in results}
    bookmarks = weread_api.get_bookmark_list(bookId)
    logger.info(f"微信读书返回划线: {len(bookmarks)} 条")
    reused_count = 0
    for i in bookmarks:
        if i.get("bookmarkId") in dict1:
            i["blockId"] = dict1.pop(i.get("bookmarkId"))
            reused_count += 1
    logger.info(f"划线匹配现有块: {reused_count} 条, 待删除多余块: {len(dict1)} 条")
    for blockId in dict1.values():
        logger.info(f"删除冗余划线block {blockId}")
        notion_helper.delete_block(blockId)
        notion_helper.delete_block(dict2.get(blockId))
    return bookmarks


def get_review_list(page_id,bookId):
    """获取笔记"""
    filter = {
        "and": [
            {"property": "书籍", "relation": {"contains": page_id}},
            {"property": "blockId", "rich_text": {"is_not_empty": True}},
        ]
    }
    logger.info(f"开始查询已有想法，page_id={page_id}")
    results = notion_helper.query_all_by_book(notion_helper.review_database_id, filter)
    logger.info(f"Notion现有想法记录: {len(results)} 条")
    dict1 = {
        get_rich_text_from_result(x, "reviewId"): get_rich_text_from_result(
            x, "blockId"
        )
        for x in results
    }
    dict2 = {get_rich_text_from_result(x, "blockId"): x.get("id") for x in results}
    reviews = weread_api.get_review_list(bookId)
    logger.info(f"微信读书返回想法: {len(reviews)} 条")
    reused_count = 0
    for i in reviews:
        if i.get("reviewId") in dict1:
            i["blockId"] = dict1.pop(i.get("reviewId"))
            reused_count += 1
    logger.info(f"想法匹配现有块: {reused_count} 条, 待删除多余块: {len(dict1)} 条")
    for blockId in dict1.values():
        logger.info(f"删除冗余想法block {blockId}")
        notion_helper.delete_block(blockId)
        notion_helper.delete_block(dict2.get(blockId))
    return reviews


def check(bookId):
    """检查是否已经插入过"""
    filter = {"property": "BookId", "rich_text": {"equals": bookId}}
    response = notion_helper.query(
        database_id=notion_helper.book_database_id, filter=filter
    )
    if len(response["results"]) > 0:
        return response["results"][0]["id"]
    return None


def get_sort():
    """获取database中的最新时间"""
    filter = {"property": "Sort", "number": {"is_not_empty": True}}
    sorts = [
        {
            "property": "Sort",
            "direction": "descending",
        }
    ]
    response = notion_helper.query(
        database_id=notion_helper.book_database_id,
        filter=filter,
        sorts=sorts,
        page_size=1,
    )
    if len(response.get("results")) == 1:
        return response.get("results")[0].get("properties").get("Sort").get("number")
    return 0



def sort_notes(page_id, chapter, bookmark_list):
    """对笔记进行排序"""
    bookmark_list = sorted(
        bookmark_list,
        key=lambda x: (
            x.get("chapterUid", 1),
            0
            if (x.get("range", "") == "" or x.get("range").split("-")[0] == "")
            else int(x.get("range").split("-")[0]),
        ),
    )

    notes = []
    if chapter != None:
        filter = {"property": "书籍", "relation": {"contains": page_id}}
        results = notion_helper.query_all_by_book(
            notion_helper.chapter_database_id, filter
        )
        dict1 = {
            get_number_from_result(x, "chapterUid"): get_rich_text_from_result(
                x, "blockId"
            )
            for x in results
        }
        dict2 = {get_rich_text_from_result(x, "blockId"): x.get("id") for x in results}
        d = {}
        for data in bookmark_list:
            chapterUid = data.get("chapterUid", 1)
            if chapterUid not in d:
                d[chapterUid] = []
            d[chapterUid].append(data)
        for key, value in d.items():
            if key in chapter:
                if key in dict1:
                    chapter.get(key)["blockId"] = dict1.pop(key)
                notes.append(chapter.get(key))
            notes.extend(value)
        for blockId in dict1.values():
            notion_helper.delete_block(blockId)
            notion_helper.delete_block(dict2.get(blockId))
    else:
        notes.extend(bookmark_list)
    return notes


def append_blocks(id, contents):
    logger.info(f"准备写入 {len(contents)} 条内容块到页面 {id}")
    before_block_id = ""
    block_children = notion_helper.get_block_children(id)
    if len(block_children) > 0 and block_children[0].get("type") == "table_of_contents":
        before_block_id = block_children[0].get("id")
    else:
        response = notion_helper.append_blocks(
            block_id=id, children=[get_table_of_contents()]
        )
        before_block_id = response.get("results")[0].get("id")
    blocks = []
    sub_contents = []
    l = []
    for content in contents:
        if len(blocks) == 100:
            results = append_blocks_to_notion(id, blocks, before_block_id, sub_contents)
            before_block_id = results[-1].get("blockId")
            l.extend(results)
            blocks.clear()
            sub_contents.clear()
            if not notion_helper.sync_bookmark and content.get("type")==0:
                continue
            blocks.append(content_to_block(content))
            sub_contents.append(content)
        elif "blockId" in content:
            if len(blocks) > 0:
                l.extend(
                    append_blocks_to_notion(id, blocks, before_block_id, sub_contents)
                )
                blocks.clear()
                sub_contents.clear()
            before_block_id = content["blockId"]
        else:
            if not notion_helper.sync_bookmark and content.get("type")==0:
                continue
            blocks.append(content_to_block(content))
            sub_contents.append(content)
    
    if len(blocks) > 0:
        l.extend(append_blocks_to_notion(id, blocks, before_block_id, sub_contents))
    for index, value in enumerate(l):
        logger.info(f"正在插入第{index+1}条笔记，共{len(l)}条")
        if "bookmarkId" in value:
            notion_helper.insert_bookmark(id, value)
        elif "reviewId" in value:
            notion_helper.insert_review(id, value)
        else:
            notion_helper.insert_chapter(id, value)


def content_to_block(content):
    if "bookmarkId" in content:
        return get_block(
            content.get("markText",""),
            notion_helper.block_type,
            notion_helper.show_color,
            content.get("style"),
            content.get("colorStyle"),
            content.get("reviewId"),
        )
    elif "reviewId" in content:
        return get_block(
            content.get("content",""),
            notion_helper.block_type,
            notion_helper.show_color,
            content.get("style"),
            content.get("colorStyle"),
            content.get("reviewId"),
        )
    else:
        return get_heading(content.get("level"), content.get("title"))


def append_blocks_to_notion(id, blocks, after, contents):
    logger.info(
        "向页面 %s 追加 %d 个块 (after=%s)",
        id,
        len(blocks),
        after,
    )
    response = notion_helper.append_blocks_after(
        block_id=id, children=blocks, after=after
    )
    results = response.get("results")
    logger.info(f"追加结果返回 {len(results)} 个块")
    l = []
    for index, content in enumerate(contents):
        result = results[index]
        logger.debug(
            "追加块%d: id=%s, type=%s",
            index + 1,
            result.get("id"),
            result.get("type"),
        )
        if content.get("abstract") != None and content.get("abstract") != "":
            notion_helper.append_blocks(
                block_id=result.get("id"), children=[get_quote(content.get("abstract"))]
            )
            logger.debug(
                "在块 %s 下追加引用摘要", result.get("id")
            )
        content["blockId"] = result.get("id")
        l.append(content)
    return l

weread_api = WeReadApi()
notion_helper = NotionHelper()
def main(target_book_id=None):
    notion_books = notion_helper.get_all_book()
    books = weread_api.get_notebooklist()
    if books != None:
        # 如果指定了目标书籍ID，只处理该书籍
        if target_book_id:
            books = [book for book in books if book.get("bookId") == target_book_id]
            if not books:
                logger.warning(f"未找到指定的书籍 {target_book_id}")
                return
            logger.info(f"指定同步书籍: {target_book_id}")
        
        for index, book in enumerate(books):
            bookId = book.get("bookId")
            title = book.get("title")
            author = book.get("author", "未知作者")
            sort = book.get("sort")
            note_count = book.get("noteCount", 0)
            review_count = book.get("reviewCount", 0)
            
            logger.info(f"\n{'='*60}")
            logger.info(f"开始处理第 {index+1}/{len(books)} 本书籍")
            logger.info(f"书籍信息: 《{title}》 - {author}")
            logger.info(f"书籍ID: {bookId}")
            logger.info(f"笔记统计: {note_count} 个标注, {review_count} 个想法")
            logger.info(f"排序值: {sort}")
            
            if not title:
                logger.warning(f"跳过书籍 {bookId}，缺少书籍标题")
                continue
            if bookId not in notion_books:
                logger.info(f"书籍《{title}》不在Notion数据库中，跳过同步")
                continue
            if sort == notion_books.get(bookId).get("Sort"):
                logger.info(f"书籍《{title}》的排序值未变化，跳过同步")
                continue
            
            pageId = notion_books.get(bookId).get("pageId")
            logger.info(f"开始同步《{title}》的笔记内容...")
            
            chapter = weread_api.get_chapter_info(bookId)
            logger.info(f"获取章节信息完成，章节数: {len(chapter) if chapter else 0}")
            
            bookmark_list = get_bookmark_list(pageId, bookId)
            logger.info(f"获取标注列表完成，标注数: {len(bookmark_list)}")
            
            reviews = get_review_list(pageId,bookId)
            logger.info(f"获取想法列表完成，想法数: {len(reviews)}")
            
            bookmark_list.extend(reviews)
            total_notes = len(bookmark_list)
            logger.info(f"合并后总笔记数: {total_notes}")
            
            content = sort_notes(pageId, chapter, bookmark_list)
            logger.info(f"笔记排序完成，准备写入Notion...")
            
            append_blocks(pageId, content)
            logger.info(f"笔记内容写入完成")
            
            properties = {
                "Sort":get_number(sort)
            }
            notion_helper.update_book_page(page_id=pageId,properties=properties)
            logger.info(f"书籍属性更新完成")
            logger.info(f"《{title}》同步完成！")
            logger.info(f"{'='*60}\n")

if __name__ == "__main__":
    import sys
    # 支持命令行参数指定书籍ID
    target_book_id = sys.argv[1] if len(sys.argv) > 1 else None
    if target_book_id:
        logger.info(f"命令行指定同步书籍ID: {target_book_id}")
    main(target_book_id)
