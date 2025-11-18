import io
import ssl
import imageio
import httpx
import tempfile
import os
from typing import List, Optional, Tuple
from pathlib import Path

from PIL import Image as PILImage, ImageDraw, ImageFont, ImageSequence
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Image, Plain
try:
    from astrbot.api.message_components import Reply
except ImportError:
    Reply = None

# 字体配置
DEFAULT_FONT_PATH = Path(__file__).parent / "font" / "consola.ttf"
FONT_SIZE = 14
# 字体宽高比补偿系数 (字符宽度/字符高度)
# 大多数等宽字体的宽度约为高度的 0.5-0.6 倍
FONT_ASPECT_RATIO = 0.55

# 字符映射
STR_MAP = "@@$$&B88QMMGW##EE93SPPDOOU**==()+^,\"--''.  "

# 支持的动图格式
ANIMATED_FORMATS = {'GIF', 'PNG', 'APNG', 'WEBP', 'MNG'}

# 文件魔术字节（用于格式检测）
MAGIC_BYTES = {
    'GIF': b'GIF8',
    'PNG': b'\x89PNG\r\n\x1a\n',
    'WEBP': b'RIFF',
    'MNG': b'\x8aMNG\r\n\x1a\n'
}

# SSL配置
SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1 | ssl.OP_NO_TLSv1_3
SSL_CONTEXT.set_ciphers("HIGH:!aNULL:!MD5")

# HTTP客户端
HTTP_CLIENT = httpx.AsyncClient(verify=SSL_CONTEXT)


@register("charpic", "移植自1umine的nonebot_plugin_charpic", "将图片转换为ASCII艺术字符画的插件，支持静态图片和动图（GIF/APNG/WebP/MNG）", "1.0.0")
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

            # 检测是否为动图
            is_animated = self._is_animated(img)
            
            if is_animated:
                frame_count = self._get_frame_count(img)
                logger.info(f"检测到动图，格式: {img.format}, 帧数: {frame_count}")
                result_bytes = await self._process_animated_image(img)
                file_ext = "gif"
            else:
                logger.info(f"开始处理静态图片，格式: {img.format}")
                result_bytes = await self._process_static_image(img)
                file_ext = "png"

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
        """从消息中获取图片URL
        
        支持两种方式获取图片：
        1. 从当前消息中直接获取图片
        2. 从引用/回复的消息中获取图片
        """
        try:
            images = []
            
            # 获取当前消息的消息链
            message_chain = None
            if hasattr(event, 'message_obj') and hasattr(event.message_obj, 'message'):
                message_chain = event.message_obj.message
            elif hasattr(event, 'get_messages'):
                message_chain = event.get_messages()
            
            if not message_chain:
                logger.warning("无法获取消息链")
                return None
            
            # 遍历消息链中的所有组件
            for component in message_chain:
                # 方式一：从当前消息获取图片
                if isinstance(component, Image):
                    images.append(component)
                    logger.info("在当前消息中找到图片")
                
                # 方式二：从引用消息获取图片
                elif Reply is not None and isinstance(component, Reply):
                    logger.info("检测到引用消息，尝试获取引用消息中的图片")
                    replied_chain = getattr(component, 'chain', None)
                    if replied_chain:
                        for reply_comp in replied_chain:
                            if isinstance(reply_comp, Image):
                                images.append(reply_comp)
                                logger.info("在引用消息中找到图片")
            
            # 兼容旧版本，尝试从 event.reply 中获取图片
            if not images and hasattr(event, 'reply') and event.reply:
                logger.info("未在当前消息中找到图片，尝试从回复消息中获取图片")
                reply_chain = None
                if hasattr(event.reply, 'get_messages'):
                    reply_chain = event.reply.get_messages()
                elif hasattr(event.reply, 'message'):
                    reply_chain = getattr(event.reply, 'message')
                if reply_chain:
                    for reply_component in reply_chain:
                        if isinstance(reply_component, Image):
                            images.append(reply_component)
                        elif Reply is not None and isinstance(reply_component, Reply):
                            nested_chain = getattr(reply_component, 'chain', None)
                            if nested_chain:
                                for nested_comp in nested_chain:
                                    if isinstance(nested_comp, Image):
                                        images.append(nested_comp)
                    if images:
                        logger.info("在回复消息中找到图片")
            
            # 当找到多张图片时，使用第一张
            if len(images) > 1:
                logger.info(f"找到 {len(images)} 张图片，使用第一张")
            
            if images:
                image_component = images[0]
                # 获取图片 URL/路径
                # 尝试多个可能的属性名
                for attr_name in ['file', 'url', 'image_url', 'image_file', 'path']:
                    if hasattr(image_component, attr_name):
                        image_path = getattr(image_component, attr_name)
                        if image_path:
                            logger.info(f"成功获取图片路径: {image_path}")
                            return image_path
                
                logger.warning("图片组件存在但无法获取图片路径")
                return None
            
            logger.info("未在消息或引用消息中找到图片")
            return None
            
        except Exception as e:
            logger.error(f"获取图片URL失败: {e}", exc_info=True)
            return None

    async def _download_image(self, image_url: str) -> Optional[PILImage.Image]:
        """下载图片，支持本地文件路径和网络URL"""
        try:
            if not image_url:
                return None

            # 处理可能的 Path 或其他类型
            if isinstance(image_url, Path):
                image_url = str(image_url)
            elif not isinstance(image_url, str):
                image_url = str(image_url)

            image_url = image_url.strip()
            if not image_url:
                return None

            # 支持 file:// 协议和本地路径
            local_path = None
            if image_url.startswith("file://"):
                local_path = image_url[7:]
            elif image_url.startswith("http://") or image_url.startswith("https://"):
                local_path = None
            else:
                local_path = image_url

            if local_path:
                if not os.path.exists(local_path):
                    logger.warning(f"本地图片不存在: {local_path}")
                    return None
                with open(local_path, "rb") as f:
                    img_data = f.read()
                return PILImage.open(io.BytesIO(img_data))

            response = await HTTP_CLIENT.get(image_url)
            if response.status_code != 200:
                logger.warning(f"图片 {image_url} 下载失败: {response.status_code}")
                return None

            img = PILImage.open(io.BytesIO(response.content))
            return img
        except Exception as e:
            logger.error(f"下载图片时出错: {e}")
            return None

    def _detect_format_from_bytes(self, img_bytes: bytes) -> Optional[str]:
        """根据文件头（魔术字节）检测图片格式"""
        try:
            if img_bytes.startswith(MAGIC_BYTES['GIF']):
                return 'GIF'
            elif img_bytes.startswith(MAGIC_BYTES['PNG']):
                return 'PNG'
            elif img_bytes.startswith(MAGIC_BYTES['MNG']):
                return 'MNG'
            elif img_bytes.startswith(MAGIC_BYTES['WEBP']):
                if b'WEBP' in img_bytes[:20]:
                    return 'WEBP'
            return None
        except Exception as e:
            logger.error(f"检测图片格式时出错: {e}")
            return None

    def _is_animated(self, img: PILImage.Image) -> bool:
        """检测图片是否为动图"""
        try:
            if img.format == 'GIF':
                try:
                    img.seek(1)
                    img.seek(0)
                    return True
                except EOFError:
                    return False
            
            if img.format in ('PNG', 'APNG'):
                if hasattr(img, 'n_frames') and img.n_frames > 1:
                    return True
                try:
                    img.seek(1)
                    img.seek(0)
                    return True
                except (EOFError, AttributeError):
                    return False
            
            if img.format == 'WEBP':
                if hasattr(img, 'n_frames') and img.n_frames > 1:
                    return True
                try:
                    img.seek(1)
                    img.seek(0)
                    return True
                except EOFError:
                    return False
            
            return False
        except Exception as e:
            logger.warning(f"检测动图时出错: {e}")
            return False

    def _get_frame_count(self, img: PILImage.Image) -> int:
        """获取图片的帧数"""
        try:
            if hasattr(img, 'n_frames'):
                return img.n_frames
            
            frame_count = 0
            try:
                while True:
                    img.seek(frame_count)
                    frame_count += 1
            except EOFError:
                pass
            
            img.seek(0)
            return frame_count
        except Exception as e:
            logger.error(f"获取帧数时出错: {e}")
            return 0

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
            result_img.save(output, format="PNG")
            result_bytes = output.getvalue()
            
            logger.info(f"静态图片字符画生成成功，大小: {len(result_bytes)} bytes")
            return result_bytes
        except Exception as e:
            logger.error(f"处理静态图片时出错: {e}")
            return None

    async def _process_animated_image(self, img: PILImage.Image) -> Optional[bytes]:
        """处理动图（GIF/APNG/WebP/MNG）"""
        try:
            img_format = img.format or 'UNKNOWN'
            logger.info(f"开始处理动图，格式: {img_format}")
            
            processed_frames: List[PILImage.Image] = []
            frame_durations: List[float] = []
            max_width = 0
            max_height = 0
            frame_index = 0

            try:
                img.seek(0)
            except EOFError:
                logger.error(f"{img_format} 不包含有效帧")
                return None

            while True:
                try:
                    img.seek(frame_index)
                except EOFError:
                    break

                raw_frame = img.copy()
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

                duration_ms = frame_info.get("duration", img.info.get("duration", 80))
                if not duration_ms or duration_ms <= 0:
                    duration_ms = 80
                frame_durations.append(duration_ms / 1000.0)

                logger.info(
                    f"第 {frame_index} 帧：原始尺寸 {original_size[0]}x{original_size[1]}，字符画尺寸 {frame_img.width}x{frame_img.height}，延迟 {duration_ms}ms"
                )

                frame_index += 1

            frame_count = len(processed_frames)
            logger.info(f"{img_format}处理完成，共处理 {frame_count} 帧")

            if frame_count == 0:
                logger.error(f"没有成功处理的{img_format}帧")
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
                f"{img_format}字符画生成成功，输出格式: GIF，大小: {len(result_bytes)} bytes，帧尺寸 {target_size[0]}x{target_size[1]}"
            )
            return result_bytes
        except Exception as e:
            logger.error(f"处理动图时出错: {e}")
            return None

    async def terminate(self):
        """插件销毁时的清理工作"""
        await HTTP_CLIENT.aclose()
        logger.info("字符画插件已停止")