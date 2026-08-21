from .base import Tool, ToolResult, RiskLevel
from .registry import ToolRegistry


def build_default_registry(config: dict) -> ToolRegistry:
    from .system_tools import (
        GetTimeTool, GetDateTool, GetSystemInfoTool, SetVolumeTool,
        OpenApplicationTool, CloseApplicationTool, TakeScreenshotTool,
        PlayMusicTool, OpenUrlTool,
    )
    from .file_tools import (
        ListFilesTool, ReadFileTool, CreateFileTool, WriteFileTool,
        CopyFileTool, MoveFileTool, DeleteFileTool,
    )
    from .web_tools import WebSearchTool, FetchWebpageTool

    reg = ToolRegistry(config)
    for tool in (
        GetTimeTool(config), GetDateTool(config), GetSystemInfoTool(config),
        SetVolumeTool(config), OpenApplicationTool(config), CloseApplicationTool(config),
        TakeScreenshotTool(config), PlayMusicTool(config), OpenUrlTool(config),
        ListFilesTool(config), ReadFileTool(config), CreateFileTool(config),
        WriteFileTool(config), CopyFileTool(config), MoveFileTool(config),
        DeleteFileTool(config), WebSearchTool(config), FetchWebpageTool(config),
    ):
        reg.register(tool)
    return reg
