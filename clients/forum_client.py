import requests
from typing import List, Optional, Callable, Dict, Any
from datetime import datetime
import logging
import pickle
import os
import re
from lxml import etree

from models.post import ForumPost

class ForumLoginException(Exception):
    """论坛登录异常"""
    pass

class CaptchaRequiredException(Exception):
    """需要验证码异常"""
    def __init__(self, captcha_image: bytes, message: str = "需要输入验证码"):
        self.captcha_image = captcha_image
        super().__init__(message)

class ForumClient:
    """论坛客户端"""
    
    def __init__(self, base_url: str, username: str, password: str, session_file: Optional[str] = None, work_dir: Optional[str] = None):
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.is_logged_in = False
        self.logger = logging.getLogger(__name__)
        
        # 设置 session 文件路径
        if session_file is None:
            self.session_file = f"forum_session_{username}.pkl"
        else:
            self.session_file = session_file
        if work_dir is not None:
            self.session_file = os.path.join(work_dir, self.session_file)
        
        # 设置请求头
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36'
        })
        
        # 尝试加载已保存的 session
        self._load_session()
    
    def _save_session(self):
        """保存 session 到文件"""
        try:
            session_data = {
                'cookies': self.session.cookies.get_dict(),
                'headers': dict(self.session.headers),
                'is_logged_in': self.is_logged_in
            }
            
            with open(self.session_file, 'wb') as f:
                pickle.dump(session_data, f)
            
            self.logger.info(f"Session 已保存到 {self.session_file}")
        except Exception as e:
            self.logger.error(f"保存 session 失败: {e}")
    
    def _load_session(self):
        """从文件加载 session"""
        try:
            if not os.path.exists(self.session_file):
                self.logger.info("Session 文件不存在，将创建新的 session")
                return
            
            with open(self.session_file, 'rb') as f:
                session_data = pickle.load(f)
            
            # 恢复 cookies
            for name, value in session_data.get('cookies', {}).items():
                self.session.cookies.set(name, value)
            
            # 恢复登录状态
            self.is_logged_in = session_data.get('is_logged_in', False)
            
            # 验证 session 是否仍然有效
            if self.is_logged_in and not self.check_login_status():
                self.logger.info("加载的 session 已失效")
                self.is_logged_in = False
            else:
                self.logger.info("Session 加载成功")
                
        except Exception as e:
            self.logger.error(f"加载 session 失败: {e}")
            self.is_logged_in = False
    
    def clear_session(self):
        """清除 session 文件"""
        try:
            if os.path.exists(self.session_file):
                os.remove(self.session_file)
                self.logger.info("Session 文件已清除")
            self.is_logged_in = False
        except Exception as e:
            self.logger.error(f"清除 session 失败: {e}")
    
    def login(self, captcha_callback: Optional[Callable[[bytes], str]] = None) -> bool:
        """登录论坛"""
        # 如果已经登录且 session 有效，直接返回
        if self.is_logged_in and self.check_login_status():
            self.logger.info("已登录，无需重新登录")
            return True
        
        try:
            # 获取登录页面
            login_page = self.session.get(f"{self.base_url}/member.php?mod=logging&action=login")
            if login_page.status_code != 200:
                raise ForumLoginException("无法访问登录页面")

            # 解析登录页面
            tree = etree.HTML(login_page.content, parser=etree.HTMLParser())
            form = tree.xpath('//form[@name="login"]')[0]
            loginhash = form.xpath('./@id')[0].split('_')[-1]
            formhash = form.xpath('.//input[@name="formhash"]/@value')[0]
            
            # 准备登录数据
            # query_data = {
            #     'mod': 'logging',
            #     'action': 'login',
            #     'loginsubmit': 'yes',
            #     'loginhash': loginhash,
            #     'inajax': '1',
            # }
            
            login_data = {
                'duceapp': 'yes',
                'formhash': formhash,
                'referer': f"{self.base_url}/",
                'lssubmit': 'yes',
                'loginfield': 'auto',
                'username': self.username,
                'password': self.password,
                'questionid': '0',
                'answer': '',
                'cookietime': '2592000',  # 30天
                'smscode': '',
            }
            
            # 提交登录
            login_url = f"{self.base_url}/member.php?mod=logging&action=login&loginsubmit=yes&loginhash={loginhash}&inajax=1"
            response = self.session.post(login_url, data=login_data)
            
            # 查找验证码
            if False:
                pass
            
            # 检查登录是否成功
            if "reload" in response.text and self.base_url in response.text:
                self.is_logged_in = True
                self.logger.info("论坛登录成功")
                # 保存 session
                self._save_session()
                return True
            else:
                raise ForumLoginException("登录失败，用户名密码或验证码错误")
                
        except Exception as e:
            self.logger.error(f"登录过程出错: {e}")
            raise
    
    def get_latest_posts(self, limit: int = 10) -> List[ForumPost]:
        """获取最新帖子"""
        if not self.is_logged_in:
            raise ForumLoginException("未登录，无法获取帖子")
        
        try:
            # 获取帖子列表页面
            response = self.session.get(f"{self.base_url}/forum.php?mod=guide&view=newthread")
            
            # 检查是否需要重新登录
            if "login" in response.url or "登录" in response.text:
                self.is_logged_in = False
                # 清除失效的 session
                self.clear_session()
                raise ForumLoginException("登录已失效")
            
            tree = etree.HTML(response.content, parser=etree.HTMLParser())
            threads = []
            
            # 解析帖子列表
            thread_elements = tree.xpath('//div[@id="forumnew"]/following-sibling::*[1]/tbody')
            
            for element in thread_elements:
                post = self._parse_post_list_element(element)
                if post:
                    threads.append(post)
            
            return threads
            
        except Exception as e:
            self.logger.error(f"获取帖子失败: {e}")
            raise

    def _parse_post_list_element(self, element: etree._Element) -> Optional[ForumPost]:
        """解析单个帖子列表元素（仅基本信息）"""
        try:
            title = element.xpath('.//th[@class="common"]/a/text()')[0].strip()
            url = element.xpath('.//th[@class="common"]/a/@href')[0].strip()
            url = self.base_url + '/' + url
            thread_id = int(url.split('t')[-1].split('-')[0])
            author = element.xpath('.//td[@class="by"]/cite/a/text()')[0].strip()
            
            # 创建ForumPost对象，传入forum_client以支持懒加载
            return ForumPost(
                id=thread_id,
                title=title,
                url=url,
                author=author,
                forum_client=self
            )
            
        except Exception as e:
            self.logger.error(f"解析帖子列表元素失败: {e}")
            return None
    
    def load_post_details(self, url: str) -> Optional[Dict[str, Any]]:
        """加载帖子详细信息"""
        try:
            self.logger.info(f"加载帖子详细信息: {url}")
            
            response = self.session.get(url)
            if response.status_code != 200:
                self.logger.error(f"无法访问帖子页面: {url}")
                return None
            
            post_tree = etree.HTML(response.content, parser=etree.HTMLParser())
            post_element = post_tree.xpath('//div[@id="postlist"]/div[contains(@id, "post_")]')[0]
            post_id = post_element.xpath('./@id')[0].split('_')[-1]
            
            # 解析发布时间
            publish_time = self._parse_time(post_element.xpath(f'.//em[@id="authorposton{post_id}"]/span/@title')[0].strip())
            
            # 解析内容
            post_message = post_element.xpath(f'.//td[@id="postmessage_{post_id}"]')[0]
            content = self._parse_message_content(post_message)
            
            # 解析图片（可以在_parse_message_content中收集）
            images = self._extract_images_from_content(post_message)
            
            # 解析标签（如果有的话）
            tags = self._extract_tags_from_content(post_message)
            
            return {
                'content': content,
                'publish_time': publish_time,
                'images': images,
                'tags': tags
            }
            
        except Exception as e:
            self.logger.error(f"加载帖子详细信息失败: {e}")
            return None
    
    def _extract_images_from_content(self, message_element: etree._Element) -> List[str]:
        """从内容中提取图片URL"""
        images = []
        try:
            img_elements = message_element.xpath('.//img')
            for img in img_elements:
                src = img.get('src', '')
                if src and not src.startswith('data:'):
                    # 确保URL完整
                    if src.startswith('/'):
                        src = self.base_url + src
                    elif not src.startswith('http'):
                        src = self.base_url + '/' + src
                    images.append(src)
        except Exception as e:
            self.logger.error(f"提取图片失败: {e}")
        return images
    
    def _extract_tags_from_content(self, message_element: etree._Element) -> List[str]:
        """从内容中提取标签"""
        tags = []
        try:
            # 这里可以根据实际论坛的标签格式来解析
            # 例如寻找特定的CSS类或者标签格式
            tag_elements = message_element.xpath('.//span[@class="tag"] | .//a[contains(@class, "tag")]')
            for tag_elem in tag_elements:
                tag_text = tag_elem.text or ''
                if tag_text.strip():
                    tags.append(tag_text.strip())
        except Exception as e:
            self.logger.error(f"提取标签失败: {e}")
        return tags
    
    def _parse_time(self, time_str: str) -> datetime:
        """解析时间字符串"""
        try:
            return datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            self.logger.error(f"时间解析失败: {time_str}")
            return datetime.now()
    
    def _parse_message_content(self, message_element: etree._Element) -> str:
        """解析帖子内容为字符串"""
        try:
            content_parts = []
            skip_next_steam_span = False  # 添加标志来跳过Steam相关的span
            
            # 递归解析元素内容
            def parse_element(element):
                nonlocal skip_next_steam_span

                # 处理文本内容
                if element.text:
                    text = element.text.strip()
                    if text:
                        content_parts.append(text)
                
                # 处理子元素
                for child in element:
                    tag = child.tag.lower()
                    
                    if tag == 'img':
                        # 处理图片
                        src = child.get('file', '')
                        if src and not src.startswith('data:'):
                            # 确保URL完整
                            if src.startswith('/'):
                                src = self.base_url + src
                            elif not src.startswith('http'):
                                src = self.base_url + '/' + src
                            content_parts.append(f"[图片: {src}]")
                    
                    elif tag == 'a':
                        # 处理链接
                        href = child.get('href', '')
                        link_text = child.text or ''
                        
                        # Steam相关链接特殊处理
                        if 'steam' in href.lower():
                            if link_text:
                                content_parts.append(f"[Steam链接: {link_text}]")
                            else:
                                content_parts.append(f"[Steam链接: {href}]")
                        elif href.startswith('#'):
                            # 页面内锚点链接，只保留文本
                            if link_text:
                                content_parts.append(link_text)
                        elif href and link_text:
                            if 'javascript:' in href:
                                # 跳过JavaScript链接
                                continue
                            # 确保URL完整
                            if href.startswith('/'):
                                href = self.base_url + href
                            content_parts.append(f"[链接: {link_text} - {href}]")
                        elif link_text:
                            content_parts.append(link_text)
                    
                    elif tag == 'iframe':
                        # 处理iframe（如Steam小部件）
                        src = child.get('src', '')
                        if 'steam' in src.lower(): # https://store.steampowered.com/widget/3289890/?utm_source=keylol
                            # app_id_match = re.search(r'/(\d+)/', src)
                            # if app_id_match:
                            #     app_id = app_id_match.group(1)
                            #     # 添加Steam小部件标记
                            #     content_parts.append(f"[Steam小部件: {app_id}]")
                            # else:
                            #     content_parts.append(f"[Steam小部件: {src}]")
                            if ('widget' in src):
                                src = src.replace('widget', 'app')
                            content_parts.append(f"[Steam小部件: {src.split('?')[0]}]")
                            # 设置标志，跳过下一个Steam相关的span
                            skip_next_steam_span = True
                        elif 'countdown' in src.lower():
                            t = src.split('t=')[-1].split('&')[0]
                            if t.isdigit():
                                local_time = datetime.fromtimestamp(int(t))
                                content_parts.append(f"[倒计时: {local_time.strftime('%Y-%m-%d %H:%M:%S')}]")
                        else:
                            content_parts.append("[嵌入内容]")
                    
                    elif tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                        # 处理标题
                        title_text = self._extract_text_content(child)
                        if title_text:
                            content_parts.append(f"\n**{title_text}**\n")
                    
                    elif tag == 'blockquote':
                        # 处理引用
                        quote_text = self._extract_text_content(child)
                        if quote_text:
                            # 为引用添加前缀
                            quoted_lines = [f"> {line}" for line in quote_text.split('\n') if line.strip()]
                            content_parts.append('\n' + '\n'.join(quoted_lines) + '\n')
                    
                    elif tag == 'br':
                        # 处理换行
                        content_parts.append('\n')
                    
                    elif tag == 'span':
                        # 检查是否需要跳过Steam相关的span
                        style_attr = child.get('style', '')
                        
                        # 检查是否是Steam小部件后的相关span（通过样式特征识别）
                        if skip_next_steam_span and ('font-size: 10px' in style_attr or 'overflow: visible' in style_attr):
                            # 检查span内容是否包含Steam相关链接
                            span_text = self._extract_text_content(child)
                            steam_links = child.xpath('.//a[contains(@href, "steam") or contains(@href, "steamdb")]')
                            
                            if steam_links or 'steam' in span_text.lower():
                                # 跳过这个Steam相关的span
                                skip_next_steam_span = False  # 重置标志
                                continue
                        
                        # 处理其他span元素
                        class_attr = child.get('class', '')
                        
                        # 跳过某些不需要的元素
                        if any(skip_class in class_attr for skip_class in [
                            'swi-block', 'steam-info-wrapper', 'tip', 'steam-info-loading', 'original_text_style1'
                        ]):
                            continue
                        
                        # 递归处理子元素
                        parse_element(child)
                    
                    elif tag in ['div']:
                        # 处理一般容器元素
                        class_attr = child.get('class', '')
                        
                        # 跳过某些不需要的元素
                        if any(skip_class in class_attr for skip_class in [
                            'swi-block', 'steam-info-wrapper', 'tip', 'steam-info-loading', 'original_text_style1'
                        ]):
                            continue
                        
                        # 递归处理子元素
                        parse_element(child)
                    
                    elif tag == 'strong' or tag == 'b':
                        # 处理粗体
                        bold_text = self._extract_text_content(child)
                        if bold_text:
                            content_parts.append(f"**{bold_text}**")
                    
                    elif tag == 'em' or tag == 'i':
                        # 处理斜体
                        italic_text = self._extract_text_content(child)
                        if italic_text:
                            content_parts.append(f"*{italic_text}*")
                    
                    elif tag in ['p', 'div'] and child.text:
                        # 处理段落
                        para_text = self._extract_text_content(child)
                        if para_text:
                            content_parts.append(f"\n{para_text}\n")
                    
                    elif any(skip_tag in tag for skip_tag in ['script', 'style', 'noscript']):
                        # 跳过脚本和样式元素
                        continue
                    
                    else:
                        # 递归处理其他元素
                        parse_element(child)
                    
                    # 处理尾部文本
                    if child.tail:
                        tail_text = child.tail.strip()
                        if tail_text:
                            content_parts.append(tail_text)
            
            # 开始解析
            parse_element(message_element)
            
            # 合并内容并清理
            content = ' '.join(content_parts)
            
            # 清理多余的空白字符
            content = re.sub(r'\n\s*\n', '\n\n', content)  # 合并多个空行
            content = re.sub(r' +', ' ', content)  # 合并多个空格
            content = content.strip()
            
            return content
            
        except Exception as e:
            self.logger.error(f"解析帖子内容失败: {e}")
            return "内容解析失败"

    def _extract_text_content(self, element: etree._Element) -> str:
        """提取元素的纯文本内容"""
        try:
            # 使用xpath提取所有文本节点
            text_nodes = element.xpath('.//text()')
            text_content = ' '.join(node.strip() for node in text_nodes if node.strip())
            return text_content
        except Exception as e:
            self.logger.error(f"提取文本内容失败: {e}")
            return element.text or ''
    
    def check_login_status(self) -> bool:
        """检查登录状态"""
        try:
            response = self.session.get(self.base_url)
            is_valid = "member.php?mod=logging&amp;action=login" not in response.url and self.is_logged_in
            if not is_valid:
                self.is_logged_in = False
            return is_valid
        except Exception as e:
            self.logger.error(f"检查登录状态失败: {e}")
            return False
    
    def __del__(self):
        """析构函数，确保 session 被保存"""
        if hasattr(self, 'is_logged_in') and self.is_logged_in:
            self._save_session()