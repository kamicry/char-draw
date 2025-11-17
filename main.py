import io
import ssl
import imageio
import httpx
import tempfile
import os
from typing import List, Optional
from pathlib import Path

from PIL import Image as PILImage, ImageDraw, ImageFont
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Image, Plain

# 字体配置
DEFAULT_FONT_PATH = Path(__file__).parent / "font" / "consola.ttf"
FONT_SIZE = 14
# 字体宽高比补偿系数 (字符宽度/字符高度)
# 大多数等宽字体的宽度约为高度的 0.5-0.6 倍
FONT_ASPECT_RATIO = 0.55

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
                file_ext = "gif"
            else:
                logger.info("开始处理静态图片")
                result_bytes = await self._process_static_image(img)
                file_ext = "jpg"

            if result_bytes:
                logger.info(f"字符画生成成功，大小: {len(result_bytes)} bytes")
                
                # 保存到临时文件
                try:
                    with tempfile.NamedTemporaryFile(mode='wb', suffix=f'.{file_ext}', delete=False) as temp_file:
                        temp_file.write(result_bytes)
                        temp_path = temp_file.name
                    
                    logger.info(f"字符画已保存到临时文件: {temp_path}")
                    yield event.image_result(temp_path)
                    
                    # 发送后删除临时文件
                    try:
                        os.unlink(temp_path)
                        logger.info(f"已删除临时文件: {temp_path}")
                    except Exception as e:
                        logger.warning(f"删除临时文件失败: {e}")
                except Exception as e:
                    logger.error(f"保存临时文件失败: {e}")
                    yield event.plain_result("字符画生成失败")
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

    async def _download_image(self, image_url: str) -> Optional[PILImage.Image]:
        """下载图片"""
        try:
            if not image_url:
                return None
                
            response = await HTTP_CLIENT.get(image_url)
            if response.status_code != 200:
                logger.warning(f"图片 {image_url} 下载失败: {response.status_code}")
                return None
            
            img = PILImage.open(io.BytesIO(response.content))
            return img
        except Exception as e:
            logger.error(f"下载图片时出错: {e}")
            return None

    async def _get_pic_text(self, img: PILImage.Image, new_w: int = 150, enforce_target_width: bool = False) -> str:
        """将图片转换为字符文本"""
        try:
            n = len(STR_MAP)
            img = img.convert("L")
            w, h = img.size

            if w == 0 or h == 0:
                logger.warning("输入图片尺寸非法，无法转换为字符文本")
                return ""

            target_w = w
            if new_w:
                if enforce_target_width or w > new_w:
                    target_w = max(1, new_w)

            scale = target_w / w if w else 1
            target_h = max(1, int(h * scale * FONT_ASPECT_RATIO))

            if img.size != (target_w, target_h):
                img = img.resize((target_w, target_h))

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
            temp_img = PILImage.new("L", (1, 1))
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

    async def _text_to_image(self, text: str) -> PILImage.Image:
        """将文本转换为图片"""
        try:
            if not text:
                return PILImage.new("L", (1, 1), "#FFFFFF")
            
            font_path = str(DEFAULT_FONT_PATH)
            if not Path(font_path).exists():
                logger.warning(f"字体文件不存在: {font_path}，使用默认字体")
                font = ImageFont.load_default()
                # 简单估算尺寸
                lines = text.split('\n')
                max_width = max(len(line) for line in lines) * 10
                height = len(lines) * 12
                img = PILImage.new("L", (max_width, height), "#FFFFFF")
                draw = ImageDraw.Draw(img)
                draw.text((0, 0), text, fill="#000000", font=font)
                return img
            
            font, w, h = await self._get_text_dimensions(font_path, FONT_SIZE, text)
            img = PILImage.new("L", (w, h), "#FFFFFF")
            draw = ImageDraw.Draw(img)
            draw.text((0, 0), text, fill="#000000", font=font)
            return img
        except Exception as e:
            logger.error(f"将文本转换为图片时出错: {e}")
            # 返回一个简单的错误图片
            return PILImage.new("L", (100, 50), "#FFFFFF")

    async def _process_static_image(self, img: PILImage.Image) -> Optional[bytes]:
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

    async def _process_gif(self, gif: PILImage.Image) -> Optional[bytes]:
        """处理GIF图片"""
        try:
            processed_frames: List[PILImage.Image] = []
            frame_durations: List[float] = []
            max_width = 0
            max_height = 0
            frame_index = 0

            try:
                gif.seek(0)
            except EOFError:
                logger.error("GIF 不包含有效帧")
                return None

            while True:
                try:
                    gif.seek(frame_index)
                except EOFError:
                    break

                raw_frame = gif.copy()
                frame_info = getattr(raw_frame, "info", {}) if hasattr(raw_frame, "info") else {}
                frame = raw_frame.convert("RGBA")
                original_size = frame.size

                text = await self._get_pic_text(frame, new_w=80, enforce_target_width=True)
                if not text:
                    logger.warning(f"第 {frame_index} 帧字符画内容为空")

                frame_img = await self._text_to_image(text)
                if frame_img.mode != "L":
                    frame_img = frame_img.convert("L")

                processed_frames.append(frame_img)
                max_width = max(max_width, frame_img.width)
                max_height = max(max_height, frame_img.height)

                duration_ms = frame_info.get("duration", gif.info.get("duration", 80))
                if not duration_ms or duration_ms <= 0:
                    duration_ms = 80
                frame_durations.append(duration_ms / 1000.0)

                logger.info(
                    f"第 {frame_index} 帧：原始尺寸 {original_size[0]}x{original_size[1]}，字符画尺寸 {frame_img.width}x{frame_img.height}"
                )

                frame_index += 1

            frame_count = len(processed_frames)
            logger.info(f"GIF处理完成，共处理 {frame_count} 帧")

            if frame_count == 0:
                logger.error("没有成功处理的GIF帧")
                return None

            target_size = (max_width, max_height)
            if target_size[0] == 0 or target_size[1] == 0:
                logger.error(f"字符画帧尺寸异常: {target_size}")
                return None

            uniform_frames: List[PILImage.Image] = []

            for idx, frame_img in enumerate(processed_frames):
                if frame_img.size != target_size:
                    padded_frame = PILImage.new("L", target_size, 255)
                    padded_frame.paste(frame_img, (0, 0))
                    uniform_frames.append(padded_frame)
                    logger.debug(
                        f"第 {idx} 帧已填充至统一尺寸 {target_size[0]}x{target_size[1]}"
                    )
                else:
                    uniform_frames.append(frame_img)

            unique_sizes = {frame.size for frame in uniform_frames}
            if len(unique_sizes) != 1:
                logger.error(f"字符画帧尺寸仍不一致: {unique_sizes}")
                return None

            uniform_frames = [frame if frame.mode == "L" else frame.convert("L") for frame in uniform_frames]

            if not frame_durations:
                duration_arg = 0.08
            elif len(frame_durations) == 1:
                duration_arg = frame_durations[0]
            else:
                duration_arg = frame_durations

            output = io.BytesIO()
            imageio.mimsave(output, uniform_frames, format="gif", duration=duration_arg)
            result_bytes = output.getvalue()
            logger.info(
                f"GIF字符画生成成功，大小: {len(result_bytes)} bytes，帧尺寸 {target_size[0]}x{target_size[1]}"
            )
            return result_bytes
        except Exception as e:
            logger.error(f"处理GIF时出错: {e}")
            return None

    async def terminate(self):
        """插件销毁时的清理工作"""
        await HTTP_CLIENT.aclose()
        logger.info("字符画插件已停止")