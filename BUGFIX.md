# Bug Fix: 字符画发送错误 - bytes/str 类型冲突

## 问题描述
字符画生成成功后，在发送时出现类型错误：
```
startswith first arg must be bytes or a tuple of bytes, not str
```

## 根本原因
`event.image_result()` 方法在内部对传入的数据进行类型检查时，期望字符串类型（文件路径）或字节类型，但处理逻辑存在 bytes/str 混淆。当直接传入字节数据时，框架内部的某些检查（如 `data.startswith("http")` 或 `data.startswith("/")`) 会失败，因为这些字符串字面量应该是字节字面量（如 `b"http"`）。

## 解决方案
将生成的字符画字节数据先保存到临时文件，然后将文件路径（字符串）传递给 `event.image_result()` 方法，避免 bytes/str 类型冲突。

## 具体修改

### 1. 添加必要的导入
```python
import tempfile
import os
```

### 2. 修改发送逻辑
在成功生成字符画后：
1. 根据图片类型确定文件扩展名（GIF 或 JPG）
2. 使用 `tempfile.NamedTemporaryFile` 创建临时文件
3. 将字节数据写入临时文件
4. 将文件路径传递给 `event.image_result()`
5. 发送后清理临时文件

### 3. 错误处理
- 添加保存临时文件失败的错误处理
- 添加删除临时文件失败的警告日志（不影响主流程）

## 改进点
1. **类型安全**：使用文件路径字符串代替字节数据，避免类型冲突
2. **资源管理**：自动清理临时文件，防止磁盘空间占用
3. **日志完善**：添加详细日志记录临时文件的创建和删除
4. **兼容性**：支持静态图片（JPG）和动图（GIF）两种格式

## 测试验收
- ✅ 静态图片字符画生成并成功发送
- ✅ GIF 动图字符画生成并成功发送
- ✅ 不再出现 bytes/str 类型错误
- ✅ 临时文件正确清理

## 代码示例
```python
# 生成字符画后
if result_bytes:
    # 保存到临时文件
    with tempfile.NamedTemporaryFile(mode='wb', suffix=f'.{file_ext}', delete=False) as temp_file:
        temp_file.write(result_bytes)
        temp_path = temp_file.name
    
    # 使用文件路径发送
    yield event.image_result(temp_path)
    
    # 清理临时文件
    os.unlink(temp_path)
```
