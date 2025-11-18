# 多种动图格式支持 - 实现说明

## 概述

本次更新扩展了插件对动图格式的支持，从原来仅支持 GIF 扩展到支持多种动图格式：
- GIF (Graphics Interchange Format)
- APNG (Animated PNG)
- WebP (动态 WebP)
- MNG (Multiple-image Network Graphics)

## 主要变更

### 1. 格式检测增强

#### 添加的常量
```python
# 支持的动图格式
ANIMATED_FORMATS = {'GIF', 'PNG', 'APNG', 'WEBP', 'MNG'}

# 文件魔术字节（用于格式检测）
MAGIC_BYTES = {
    'GIF': b'GIF8',
    'PNG': b'\x89PNG\r\n\x1a\n',
    'WEBP': b'RIFF',
    'MNG': b'\x8aMNG\r\n\x1a\n'
}
```

#### 新增的检测方法

**`_detect_format_from_bytes(img_bytes: bytes) -> Optional[str]`**
- 根据文件头（魔术字节）检测图片格式
- 用于未来可能的格式验证需求

**`_is_animated(img: PILImage.Image) -> bool`**
- 检测图片是否为动图
- 支持 GIF、PNG/APNG、WebP 格式
- 使用多种方法检测：
  - 检查 `n_frames` 属性
  - 尝试 seek 到第二帧

**`_get_frame_count(img: PILImage.Image) -> int`**
- 获取图片的帧数
- 用于日志记录和调试

### 2. 统一动图处理流程

#### 方法重命名
- `_process_gif()` → `_process_animated_image()`
- 新方法名称更通用，适用于所有动图格式

#### 处理流程改进
```python
# 主处理逻辑更新
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
```

### 3. 格式特定处理

#### APNG 支持
- 自动检测 PNG 格式是否包含多帧
- 处理帧尺寸不一致问题（通过填充）

#### WebP 支持
- 正确读取 WebP 的帧延迟信息
- 支持动态 WebP 的所有帧

#### MNG 支持
- 通过 PIL 的标准接口处理 MNG 格式
- 自动处理 MNG 的帧控制机制

### 4. 保存格式优化

#### 静态图片
- 从 JPEG 改为 **PNG** 格式
- PNG 支持透明度，质量更好

#### 动图
- 所有动图统一输出为 **GIF** 格式
- 原因：GIF 兼容性最好，所有平台都支持

### 5. 日志增强

新增的日志信息：
- 格式检测结果
- 帧数统计
- 每帧的延迟时间
- 输出格式说明

示例日志：
```
检测到动图，格式: WEBP, 帧数: 24
第 0 帧：原始尺寸 800x600，字符画尺寸 640x288，延迟 80ms
WEBP处理完成，共处理 24 帧
WEBP字符画生成成功，输出格式: GIF，大小: 156789 bytes，帧尺寸 640x288
```

## 技术实现细节

### 帧提取
使用 PIL 的 `seek()` 方法遍历所有帧：
```python
frame_index = 0
while True:
    try:
        img.seek(frame_index)
    except EOFError:
        break
    # 处理当前帧
    frame_index += 1
```

### 帧尺寸统一
为确保所有帧尺寸一致，使用白色填充较小的帧：
```python
if frame_img.size != target_size:
    padded_frame = PILImage.new("L", target_size, 255)
    padded_frame.paste(frame_img, (0, 0))
```

### 延迟处理
从帧信息中提取延迟，默认值为 80ms：
```python
duration_ms = frame_info.get("duration", img.info.get("duration", 80))
if not duration_ms or duration_ms <= 0:
    duration_ms = 80
frame_durations.append(duration_ms / 1000.0)
```

## 依赖项更新

新增依赖：
```
imageio-ffmpeg>=0.4.0
```

此依赖提供了对 WebP 和其他格式的更好支持。

## 测试建议

### 测试用例
1. **GIF 动图** - 验证原有功能不受影响
2. **APNG 动图** - 测试 PNG 动画支持
3. **WebP 动图** - 测试 WebP 动画支持
4. **静态 PNG** - 确保不被误识别为动图
5. **静态 JPEG** - 确保正常处理并输出 PNG

### 预期行为
- 所有动图格式都能正确识别
- 帧提取完整无丢失
- 延迟信息正确保留
- 输出的 GIF 播放流畅
- 静态图输出为高质量 PNG

## 已知限制

1. **MNG 格式支持**
   - PIL 对 MNG 的支持有限
   - 某些特殊的 MNG 文件可能无法正确解析

2. **格式兼容性**
   - 输出统一为 GIF，可能损失某些格式特有的特性
   - 如需保留原格式，需要进一步开发

3. **性能考虑**
   - 大型动图（帧数多、尺寸大）处理时间较长
   - 建议在实际使用中添加超时控制

## 向后兼容性

✅ 完全向后兼容
- 原有的 GIF 处理逻辑保持不变
- 静态图片处理保持一致（仅输出格式改为 PNG）
- API 接口无变化

## 未来改进方向

1. 添加格式转换选项（保留原格式 vs 转换为 GIF）
2. 支持更多动图格式（如 AVIF）
3. 添加帧率控制选项
4. 优化大型动图的内存使用
5. 添加进度反馈机制

## 总结

本次更新实现了对多种动图格式的支持，同时保持了代码的简洁性和可维护性。通过统一的处理流程和详细的日志记录，为用户提供了更好的体验。
