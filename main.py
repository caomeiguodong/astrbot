import logging
from jmcomic import *
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
import astrbot.api.message_components as Comp
import jmcomic
import os
import time
from jmcomic import JmModuleConfig

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 配置代理选项
proxy = {
    'http': 'http://127.0.0.1:7897',
    'https': 'http://127.0.0.1:7897'
}
option = JmOption.default()
option.client_proxy = proxy
option = create_option_by_file(r'C:\Users\29234\Desktop\AstrBot\data\plugins\helloworld\option.yml')

# 配置 img2pdf 插件相关参数，将下载的图片转换为 PDF
# 假设将 PDF 存放在 D:/pdf/ 文件夹，使用章节 ID 作为 PDF 文件名规则
pdf_dir = "D:/pdf/"
option.plugins.after_photo = [
    {
        "plugin": "img2pdf",
        "kwargs": {
            "pdf_dir": pdf_dir,
            "filename_rule": "Pid"
        }
    }
]

# 自定义下载文件夹规则
JmModuleConfig.AFIELD_ADVICE['custom_folder'] = lambda album: f'D:/jm/{album.id}_{album.title}'
# 重新设置 dir_rule 以确保自定义规则生效
option.dir_rule.rule = 'Bd_Acustom_folder'


def handle_exception(e, event):
    """
    统一处理异常的方法
    """
    if isinstance(e, MissingAlbumPhotoException):
        logging.error(f'id={e.error_jmid}的本子不存在')
        return event.plain_result(f'id={e.error_jmid}的本子不存在')
    elif isinstance(e, JsonResolveFailException):
        logging.error(f'解析 json 失败')
        resp = e.resp
        logging.error(f'resp.text: {resp.text}, resp.status_code: {resp.status_code}')
        if resp.status_code == 404:
            return event.plain_result('未找到请求的资源')
        else:
            return event.plain_result('解析 json 失败')
    elif isinstance(e, RequestRetryAllFailException):
        logging.error(f'请求失败，重试次数耗尽')
        return event.plain_result('请求失败，重试次数耗尽')
    elif isinstance(e, FileNotFoundError):
        logging.error(f'文件未找到: {e}')
        return event.plain_result(f'文件未找到: {e}')
    elif isinstance(e, JmcomicException):
        logging.error(f'jmcomic 遇到异常: {e}')
        return event.plain_result(f'jmcomic 遇到异常: {e}')
    else:
        logging.error(f'未知异常: {e}')
        return event.plain_result('发生未知异常')


@register("comic_info_sender", "your_name", "一个发送漫画信息和PDF文件到群组的插件，支持搜索并选择下载", "1.0.0", "your_repo_url")
class ComicInfoSenderPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.waiting_for_jm_code = {}
        self.search_results = {}

    # 注册指令的装饰器。指令名为 jm_code，注册成功后，发送 `/jm_code <jm_code>` 就会触发这个指令
    @filter.command("download")
    async def handle_jm_code_input(self, event: AstrMessageEvent, jm_code: str, jm_code1: str):
        try:
            client = option.new_jm_client()
            # 请求本子实体类
            albums = []
            for code in [jm_code, jm_code1]:
                album: JmAlbumDetail = client.get_album_detail(code)
                albums.append(album)
            jmcomic.download_album([jm_code, jm_code1], option)

            for album in albums:
                # 等待下载和转换完成
                pdf_path = os.path.join(pdf_dir, f"{album.album_id}.pdf")
                max_wait_time = 60  # 最大等待时间，单位：秒
                wait_interval = 5  # 检查间隔，单位：秒
                waited_time = 0
                while not os.path.exists(pdf_path) and waited_time < max_wait_time:
                    time.sleep(wait_interval)
                    waited_time += wait_interval

                if not os.path.exists(pdf_path):
                    raise FileNotFoundError(f"PDF 文件 {pdf_path} 未找到。")

                # 整理漫画信息
                comic_info = f"漫画名称：{album.title}\n作者：{album.author}\n章节数：{len(album)}"
                # 构建消息链
                message_chain = [
                    Comp.At(qq=event.get_sender_id()),
                    Comp.Plain("以下是漫画信息：\n"),
                    Comp.Plain(comic_info),
                    Comp.Plain("\n以下是生成的 PDF 文件："),
                    Comp.File(file=pdf_path, name=os.path.basename(pdf_path))
                ]
                # 发送消息到群组
                yield event.chain_result(message_chain)
        except Exception as e:
            yield handle_exception(e, event)

    # 注册指令的装饰器。指令名为 search_comic，注册成功后，发送 `/search_comic <search_query>` 就会触发这个指令
    @filter.command("search")
    async def handle_search_comic(self, event: AstrMessageEvent, search_query: str):
        try:
            client = option.new_jm_client()
            # 分页查询，search_site就是禁漫网页上的【站内搜索】
            page: JmSearchPage = client.search_site(search_query=search_query, page=1)
            album_ids = []
            result_text = "搜索到以下本子，请输入 `/jm_code 车牌1 车牌2 ...` 选择要下载的本子（可输入多个车牌，用空格分隔）：\n"
            for album_id, title in page:
                album_ids.append(album_id)
                result_text += f"[{album_id}]: {title}\n"

            if not album_ids:
                yield event.plain_result(f"未找到与 '{search_query}' 相关的本子。")
                return

            self.search_results[event.get_sender_id()] = album_ids
            yield event.plain_result(result_text)

        except Exception as e:
            yield handle_exception(e, event)