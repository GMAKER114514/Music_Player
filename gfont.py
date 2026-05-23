import pygame
def get_chinese_font(size):
    """
    智能获取中文字体，优先使用 Ubuntu 常见中文字体
    根据你的 fc-list 输出，添加了精确的字体名称
    """
    candidates = [
    "SimHei",           # 黑体
    "Microsoft YaHei",  # 微软雅黑
    "FangSong",         # 仿宋
    "KaiTi",            # 楷体
    "SimSun",           # 宋体
]
    for name in candidates:
        try:
            font = pygame.font.SysFont(name, size)
            # 测试渲染一个中文字符
            test_surface = font.render("测", True, (255, 255, 255))
            if test_surface.get_width() > 0:
                print(f"✓ 使用字体: {name}")  # 调试信息
                return font
        except Exception as e:
            print(f"✗ 字体 {name} 加载失败: {e}")
            continue
    
    # 保底：尝试使用字体文件路径直接加载
    fallback_paths = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
    ]
    for path in fallback_paths:
        try:
            font = pygame.font.Font(path, size)
            test_surface = font.render("测", True, (255, 255, 255))
            if test_surface.get_width() > 0:
                print(f"✓ 使用字体文件: {path}")
                return font
        except:
            continue
    
    # 最后保底：使用默认字体（可能无法显示中文）
    print("⚠ 警告: 未找到中文字体，界面可能显示异常")
    return pygame.font.Font(None, size)