import io
import ssl
import imageio
import httpx
from typing import List, Optional
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Image, Plain

# 字体配置
DEFAULT_FONT_PATH = Path(__file__).parent / "font" / "consola.ttf"
FONT_SIZE = 14

# 字符映射
STR_MAP = "@@$$&B88QMMGW##EE93SPPDOOU**==()+^,\"--''.  "

# SSL配置
SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1 | ssl.OP_NO_TLSv1_3
SSL_CONTEXT.set_ciphers("HIGH:!aNULL:!MD5")

# HTTP客户端
HTTP_CLIENT = httpx.AsyncClient(verify=SSL_CONTEXT)


@register("charpic", "移植自1umine的nonebot_plugin_charpic", "将图片转换为ASCII艺术字符画的插件，支持静态图片和GIF", "1.0.0")
class CharPicPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def initialize(self):
        """插件初始化"""
        logger.info("字符画插件初始化完成")
        
        # 检查字体文件
        if not DEFAULT_FONT_PATH.exists():
            logger.warning(f"字体文件不存在: {DEFAULT_FONT_PATH}")
        else:
            try:
                # 尝试加载字体文件
                ImageFont.truetype(str(DEFAULT_FONT_PATH), FONT_SIZE)
                logger.info("字体文件加载成功")
            except Exception as e:
                logger.error(f"字体文件加载失败: {e}")

    @filter.command("字符画", "charpic")
    async def charpic_handler(self, event: AstrMessageEvent):
        """字符画生成指令处理器"""
        try:
            logger.info(f"收到字符画生成请求，来自用户: {event.get_sender_name()}")
            
            # 获取消息中的图片
            image_url = await self._get_image_from_message(event)
            
            if not image_url:
                logger.warning("未找到图片URL")
                yield event.plain_result("请发送图片并使用 /字符画 指令，或者回复一条包含图片的消息使用 /字符画")
                return

            logger.info(f"找到图片URL: {image_url}")
            yield event.plain_result("正在生成字符画，请稍候...")

            # 下载图片
            img = await self._download_image(image_url)
            if not img:
                logger.error("图片下载失败")
                yield event.plain_result("图片下载失败，请稍后再试")
                return

            logger.info(f"成功下载图片，尺寸: {img.size}, 格式: {img.format}")

            # 处理图片
            if img.format == "GIF":
                logger.info("开始处理GIF图片")
                result_bytes = await self._process_gif(img)
            else:
                logger.info("开始处理静态图片")
                result_bytes = await self._process_static_image(img)

            if result_bytes:
                logger.info(f"字符画生成成功，大小: {len(result_bytes)} bytes")
                yield event.image_result(result_bytes)
            else:
                logger.error("字符画生成失败")
                yield event.plain_result("字符画生成失败")

        except Exception as e:
            logger.error(f"字符画生成出错: {e}")
            yield event.plain_result(f"生成字符画时出错: {str(e)}")

    async def _get_image_from_message(self, event: AstrMessageEvent) -> Optional[str]:
        """从消息中获取图片URL"""
        try:
            message_chain = event.get_messages()
            
            # 遍历消息链查找图片
            for component in message_chain:
                if isinstance(component, Image):
                    # 如果是图片组件，获取其URL
                    if hasattr(component, 'url') and component.url:
                        return component.url
                    elif hasattr(component, 'image_url') and component.image_url:
                        return component.image_url
                    elif hasattr(component, 'file') and component.file:
                        return component.file
                    elif hasattr(component, 'image_file') and component.image_file:
                        return component.image_file
            
            # 如果当前消息没有图片，检查是否是回复消息
            # 尝试获取回复消息的图片
            if hasattr(event, 'reply') and event.reply:
                reply_chain = event.reply.get_messages() if hasattr(event.reply, 'get_messages') else []
                for component in reply_chain:
                    if isinstance(component, Image):
                        if hasattr(component, 'url') and component.url:
                            return component.url
                        elif hasattr(component, 'image_url') and component.image_url:
                            return component.image_url
                        elif hasattr(component, 'file') and component.file:
                            return component.file
                        elif hasattr(component, 'image_file') and component.image_file:
                            return component.image_file
            
            return None
        except Exception as e:
            logger.error(f"获取图片URL失败: {e}")
            return None

    async def _download_image(self, image_url: str) -> Optional[Image.Image]:
        """下载图片"""
        try:
            if not image_url:
                return None
                
            response = await HTTP_CLIENT.get(image_url)
            if response.status_code != 200:
                logger.warning(f"图片 {image_url} 下载失败: {response.status_code}")
                return None
            
            img = Image.open(io.BytesIO(response.content))
            return img
        except Exception as e:
            logger.error(f"下载图片时出错: {e}")
            return None

    async def _get_pic_text(self, img: Image.Image, new_w: int = 150) -> str:
        """将图片转换为字符文本"""
        try:
            n = len(STR_MAP)
            img = img.convert("L")
            w, h = img.size
            
            # 计算新的尺寸，保持宽高比
            if w > new_w:
                new_h = int(new_w * h / w)
                img = img.resize((new_w, new_h))
            else:
                # 如果图片不宽，就按高度压缩一半
                new_h = int(h / 2)
                img = img.resize((w, new_h))
            
            s = ""
            for x in range(img.height):
                for y in range(img.width):
                    gray_v = img.getpixel((y, x))
                    s += STR_MAP[int(n * (gray_v / 256))]
                s += "\n"
            
            return s
        except Exception as e:
            logger.error(f"转换图片为字符文本时出错: {e}")
            return ""

    async def _get_text_dimensions(self, font_path: str, font_size: int, text: str) -> tuple[ImageFont.FreeTypeFont, int, int]:
        """获取文本的尺寸"""
        try:
            font = ImageFont.truetype(font_path, font_size)
            
            # 创建一个临时图片用于计算文本尺寸
            temp_img = Image.new("L", (1, 1))
            draw = ImageDraw.Draw(temp_img)
            
            try:
                # 旧版本PIL
                w, h = draw.textsize(text, font=font)
            except AttributeError:
                # 新版本PIL (>=10.0)
                bbox = draw.textbbox((0, 0), text, font=font)
                w = bbox[2] - bbox[0]
                h = bbox[3] - bbox[1]
            
            return font, w, h
        except Exception as e:
            logger.error(f"获取文本尺寸时出错: {e}")
            # 使用默认字体
            font = ImageFont.load_default()
            # 简单估算尺寸
            lines = text.split('\n')
            max_width = max(len(line) for line in lines) * 8
            height = len(lines) * 10
            return font, max_width, height

    async def _text_to_image(self, text: str) -> Image.Image:
        """将文本转换为图片"""
        try:
            if not text:
                return Image.new("L", (1, 1), "#FFFFFF")
            
            font_path = str(DEFAULT_FONT_PATH)
            if not Path(font_path).exists():
                logger.warning(f"字体文件不存在: {font_path}，使用默认字体")
                font = ImageFont.load_default()
                # 简单估算尺寸
                lines = text.split('\n')
                max_width = max(len(line) for line in lines) * 10
                height = len(lines) * 12
                img = Image.new("L", (max_width, height), "#FFFFFF")
                draw = ImageDraw.Draw(img)
                draw.text((0, 0), text, fill="#000000", font=font)
                return img
            
            font, w, h = await self._get_text_dimensions(font_path, FONT_SIZE, text)
            img = Image.new("L", (w, h), "#FFFFFF")
            draw = ImageDraw.Draw(img)
            draw.text((0, 0), text, fill="#000000", font=font)
            return img
        except Exception as e:
            logger.error(f"将文本转换为图片时出错: {e}")
            # 返回一个简单的错误图片
            return Image.new("L", (100, 50), "#FFFFFF")

    async def _process_static_image(self, img: Image.Image) -> Optional[bytes]:
        """处理静态图片"""
        try:
            logger.info(f"开始处理静态图片，原始尺寸: {img.size}")
            
            text = await self._get_pic_text(img)
            if not text:
                logger.error("图片转换为字符文本失败")
                return None
            
            logger.info(f"图片转换为字符文本成功，文本长度: {len(text)}")
            
            result_img = await self._text_to_image(text)
            if not result_img:
                logger.error("字符文本转换为图片失败")
                return None
            
            logger.info(f"字符文本转换为图片成功，结果尺寸: {result_img.size}")
            
            output = io.BytesIO()
            result_img.save(output, format="jpeg")
            result_bytes = output.getvalue()
            
            logger.info(f"静态图片字符画生成成功，大小: {len(result_bytes)} bytes")
            return result_bytes
        except Exception as e:
            logger.error(f"处理静态图片时出错: {e}")
            return None

    async def _process_gif(self, gif: Image.Image) -> Optional[bytes]:
        """处理GIF图片"""
        try:
            frame_list: List[Image.Image] = []
            frame_count = 0
            
            # 逐帧处理GIF
            try:
                while True:
                    current_frame = gif.tell()
                    frame = gif.copy()
                    
                    # 将当前帧转换为字符画
                    text = await self._get_pic_text(frame, new_w=80)
                    frame_img = await self._text_to_image(text)
                    frame_list.append(frame_img)
                    frame_count += 1
                    
                    # 移动到下一帧
                    gif.seek(current_frame + 1)
            except EOFError:
                # GIF处理完毕
                pass
            
            logger.info(f"GIF处理完成，共处理 {frame_count} 帧")
            
            if not frame_list:
                logger.error("没有成功处理的GIF帧")
                return None
            
            # 保存为GIF
            output = io.BytesIO()
            imageio.mimsave(output, frame_list, format="gif", duration=0.08)
            result_bytes = output.getvalue()
            logger.info(f"GIF字符画生成成功，大小: {len(result_bytes)} bytes")
            return result_bytes
        except Exception as e:
            logger.error(f"处理GIF时出错: {e}")
            return None

    async def terminate(self):
        """插件销毁时的清理工作"""
        await HTTP_CLIENT.aclose()
        logger.info("字符画插件已停止")