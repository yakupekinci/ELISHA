from .base import Tool, ToolResult, RiskLevel
from .registry import ToolRegistry


def build_default_registry(config: dict, memory_store=None) -> ToolRegistry:
    from .system_tools import (
        GetTimeTool, GetDateTool, GetSystemInfoTool, SetVolumeTool,
        OpenApplicationTool, CloseApplicationTool, TakeScreenshotTool,
        PlayMusicTool, OpenUrlTool, GetLocationTool,
        SetReminderTool, CreateNoteTool, BatteryTool, ScreenContextTool,
        SetWatchTopicsTool, SystemLoadTool, AutostartTool,
    )
    from .file_tools import (
        ListFilesTool, ReadFileTool, CreateFileTool, WriteFileTool,
        CopyFileTool, MoveFileTool, DeleteFileTool,
    )
    from .web_tools import WebSearchTool, FetchWebpageTool
    from .vision_tools import AnalyzeScreenTool
    from .extra_tools import (YouTubePlayTool, SendMessageTool, GameUpdateTool,
                              FlightFinderTool, AnalyzeCameraTool, DashboardTool)
    from .media_tools import MediaControlTool, AppManagerTool

    # Engellenen araçlar (config'ten, hiç register edilmez → LLM göremez)
    blocked = set((config or {}).get("security", {}).get("blocked_tools", []))

    reg = ToolRegistry(config)

    all_tools = [
        GetTimeTool(config), GetDateTool(config), GetSystemInfoTool(config),
        SetVolumeTool(config), OpenApplicationTool(config), CloseApplicationTool(config),
        TakeScreenshotTool(config), PlayMusicTool(config), OpenUrlTool(config),
        GetLocationTool(config),
        SetReminderTool(config), CreateNoteTool(config),
        BatteryTool(config), ScreenContextTool(config),
        SetWatchTopicsTool(config), SystemLoadTool(config),
        AutostartTool(config),
        YouTubePlayTool(config), SendMessageTool(config), GameUpdateTool(config),
        FlightFinderTool(config), AnalyzeCameraTool(config), DashboardTool(config),
        MediaControlTool(config), AppManagerTool(config),
        ListFilesTool(config), ReadFileTool(config), CreateFileTool(config),
        WriteFileTool(config), CopyFileTool(config), MoveFileTool(config),
        WebSearchTool(config), FetchWebpageTool(config),
        AnalyzeScreenTool(config),
    ]

    # DeleteFileTool — yalnızca açıkça izin verilmişse register et
    # Varsayılan: KAYITLI DEĞİL (güvenlik riski çok yüksek)
    if (config or {}).get("tools", {}).get("delete_file", {}).get("enabled", False):
        all_tools.append(DeleteFileTool(config))

    for tool in all_tools:
        if tool.name in blocked:
            continue  # bloklanmış → atla
        reg.register(tool)

    # ── EKLENTİLER: plugins/ klasörüne düşen .py dosyaları otomatik araç olur ──
    # (desen: FatihMakes/Mark-LI plugin sistemi — kırık plugin asla düşürmez)
    try:
        from pathlib import Path as _P
        from ..plugin_loader import discover_plugins, make_plugin_tool
        core_names = ({t.name for t in all_tools}
                      | {"remember", "recall", "forget", "run_shell",
                         "delete_file", "analyze_screen"})
        for rec in discover_plugins(_P("plugins"), core_names).values():
            if rec.name not in blocked:
                reg.register(make_plugin_tool(rec, config))
    except Exception as _pe:
        print(f"⚠️ Plugin sistemi yüklenemedi: {_pe}")

    if memory_store is not None:
        from .memory_tools import RememberTool, RecallTool, ForgetTool
        if "remember" not in blocked:
            reg.register(RememberTool(config, memory_store))
        if "recall" not in blocked:
            reg.register(RecallTool(config, memory_store))
        if "forget" not in blocked:
            reg.register(ForgetTool(config, memory_store))

    # AŞAMA 6: shell aracı — yalnızca config'te açıkça açıldıysa
    if ((config or {}).get("tools", {}) or {}).get("run_shell", {}).get("enabled", False):
        if "run_shell" not in blocked:
            from .shell_tool import RunShellTool
            reg.register(RunShellTool(config))

    return reg
