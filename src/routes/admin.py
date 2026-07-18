import os
import time
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from src.config import ADMIN_KEY
from src.crud import save_device_settings, get_device_settings
from src.services import (
    CACHE_FILE, STT_CACHE_FILE, TTS_CACHE_FILE
)
from src.business_logic import generate_growths_summary
from src.logger import setup_logger

logger = setup_logger("routes.admin")
router = APIRouter()

@router.post("/api/admin/clear-cache")
async def clear_cache(request: Request):
    admin_key = ADMIN_KEY
    if admin_key:
        auth_header = request.headers.get("Authorization")
        if auth_header != f"Bearer {admin_key}":
            raise HTTPException(status_code=403, detail="Forbidden")
            
    # Clear memory caches
    from src.services import IMAGE_CACHE, STT_CACHE, TTS_CACHE
    IMAGE_CACHE.clear()
    STT_CACHE.clear()
    TTS_CACHE.clear()
    
    for f_path in [CACHE_FILE, STT_CACHE_FILE, TTS_CACHE_FILE]:
        if os.path.exists(f_path):
            os.remove(f_path)
            
    print("All caches cleared manually.")
    return {"status": "success", "message": "All caches cleared"}

@router.post("/api/admin/settings/{device_token}")
async def update_device_settings(device_token: str, request: Request):
    try:
        body = await request.json()
        voice_name = body.get("voice_name")
        if not voice_name:
            raise HTTPException(status_code=400, detail="Missing voice_name")
        
        save_device_settings(device_token, voice_name)
        return {"success": True, "message": "Settings updated successfully", "voice_name": voice_name}
    except Exception as e:
        logger.error(f"[SETTINGS] Failed to update settings for {device_token}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/admin/reports/{device_token}")
async def get_admin_report(device_token: str):
    data = generate_growths_summary(device_token)
    active_voice = get_device_settings(device_token)
    
    # Render Trend SVG
    trend_svg = ""
    trend_points = data.get("linguistic_trend", [])
    if trend_points:
        svg_width = 600
        svg_height = 200
        padding = 40
        num_points = len(trend_points)
        
        x_step = (svg_width - 2 * padding) / max(1, num_points - 1)
        points_str = []
        dots = []
        for idx, pt in enumerate(trend_points):
            x = padding + idx * x_step
            y = svg_height - padding - (pt["score"] / 100.0) * (svg_height - 2 * padding)
            points_str.append(f"{x},{y}")
            dots.append(f'<circle cx="{x}" cy="{y}" r="5" class="fill-indigo-600 stroke-white stroke-2 hover:r-7 transition-all cursor-pointer" title="{pt["time"]}: {pt["score"]}%"/>')
            
        path_d = f"M {points_str[0]}" + " " + " ".join([f"L {p}" for p in points_str[1:]]) if points_str else ""
        
        grid_lines = []
        for val in [0, 25, 50, 75, 100]:
            y = svg_height - padding - (val / 100.0) * (svg_height - 2 * padding)
            grid_lines.append(f'<line x1="{padding}" y1="{y}" x2="{svg_width-padding}" y2="{y}" stroke="#e5e7eb" stroke-dasharray="4"/>')
            grid_lines.append(f'<text x="{padding-10}" y="{y+4}" font-size="10" fill="#9ca3af" text-anchor="end">{val}%</text>')
            
        for idx, pt in enumerate(trend_points):
            x = padding + idx * x_step
            grid_lines.append(f'<text x="{x}" y="{svg_height - padding + 20}" font-size="10" fill="#9ca3af" text-anchor="middle">{pt["time"]}</text>')
            
        trend_svg = f"""
        <svg viewBox="0 0 {svg_width} {svg_height}" class="w-full h-auto">
            {"".join(grid_lines)}
            <path d="{path_d}" fill="none" stroke="url(#gradient)" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
            {"".join(dots)}
            <defs>
                <linearGradient id="gradient" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stop-color="#4f46e5" />
                    <stop offset="100%" stop-color="#ec4899" />
                </linearGradient>
            </defs>
        </svg>
        """
    else:
        trend_svg = """
        <div class="flex items-center justify-center h-48 bg-gray-50 rounded-xl border border-dashed border-gray-200">
            <span class="text-gray-400 text-sm">暂无言语丰富度发展走势数据</span>
        </div>
        """
        
    emotion_html = ""
    for emotion, count in data.get("emotions", []):
        color_classes = "bg-indigo-50 text-indigo-700 border-indigo-200"
        if emotion in ["悲伤", "焦虑", "分离焦虑"]:
            color_classes = "bg-rose-50 text-rose-700 border-rose-200"
        elif emotion in ["愤怒"]:
            color_classes = "bg-amber-50 text-amber-700 border-amber-200"
        elif emotion in ["好奇", "快乐"]:
            color_classes = "bg-emerald-50 text-emerald-700 border-emerald-200"
            
        emotion_html += f"""
        <span class="inline-flex items-center px-4 py-2 rounded-full text-sm font-semibold border {color_classes} shadow-sm transition-all hover:scale-105 duration-200">
            {emotion}
            <span class="ml-2 bg-white/60 px-1.5 py-0.5 rounded-full text-xs font-bold">{count}次</span>
        </span>
        """
        
    interest_html = ""
    colors_pool = [
        "bg-pink-50 text-pink-700 border-pink-200",
        "bg-purple-50 text-purple-700 border-purple-200",
        "bg-blue-50 text-blue-700 border-blue-200",
        "bg-teal-50 text-teal-700 border-teal-200",
        "bg-yellow-50 text-yellow-700 border-yellow-200",
        "bg-orange-50 text-orange-700 border-orange-200"
    ]
    for idx, (interest, count) in enumerate(data.get("interests", [])):
        color = colors_pool[idx % len(colors_pool)]
        interest_html += f"""
        <span class="inline-flex items-center px-3.5 py-1.5 rounded-xl text-sm font-semibold border {color} shadow-sm transition-all hover:scale-105 duration-200">
            🔍 {interest} ({count}次)
        </span>
        """
        
    if not emotion_html:
        emotion_html = '<span class="text-gray-400 text-sm">暂无识别的情绪特征</span>'
    if not interest_html:
        interest_html = '<span class="text-gray-400 text-sm">暂无提取的兴趣主题</span>'
        
    drawings_html = ""
    for d in data.get("drawings", []):
        drawings_html += f"""
        <div class="bg-white rounded-2xl border border-gray-100 overflow-hidden shadow-sm hover:shadow-md transition-shadow duration-300">
            <div class="aspect-square bg-gray-50 flex items-center justify-center p-2">
                <img src="{d['url']}" class="max-h-full max-w-full object-contain rounded-lg" alt="{d['prompt']}"/>
            </div>
            <div class="p-4">
                <p class="font-semibold text-gray-800 text-sm mb-1 truncate">{d['prompt']}</p>
                <span class="text-xs text-gray-400">{time.strftime('%Y-%m-%d %H:%M', time.localtime(d['timestamp']))}</span>
            </div>
        </div>
        """
        
    if not drawings_html:
        drawings_html = """
        <div class="col-span-full flex flex-col items-center justify-center py-12 bg-gray-50 rounded-2xl border border-dashed border-gray-200 text-gray-400">
            <span class="text-3xl mb-2">🎨</span>
            <span class="text-sm">小朋友还没有使用绘画创作功能哦</span>
        </div>
        """

    alert_banner = ""
    if data.get("requires_attention_count", 0) > 0:
        alert_banner = f"""
        <div class="bg-red-50 border-l-4 border-red-500 p-4 rounded-xl mb-8 shadow-sm">
            <div class="flex items-start">
                <div class="flex-shrink-0 text-red-500 text-xl">⚠️</div>
                <div class="ml-3">
                    <h3 class="text-sm font-bold text-red-800">特别心理成长预警提示</h3>
                    <div class="mt-1 text-sm text-red-700">
                        在近期的交互中，共检测到 <span class="font-extrabold">{data['requires_attention_count']}次</span> 极度消极、焦虑或分离恐惧的情绪，建议家长及老师在日常生活中给予儿童更多的关怀、安全感支持，并耐心倾听其内心世界。
                    </div>
                </div>
            </div>
        </div>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>小探宝儿童成长与行为心理诊断报告</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://fonts.googleapis.com/css2?family=Quicksand:wght=400;600;700&family=Noto+Sans+SC:wght=400;500;700&display=swap" rel="stylesheet">
        <style>
            body {{
                font-family: 'Quicksand', 'Noto Sans SC', sans-serif;
            }}
        </style>
    </head>
    <body class="bg-[#f8fafc] text-gray-800 min-h-screen">
        <div class="max-w-6xl mx-auto px-4 py-8">
            <!-- HEADER -->
            <div class="bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 rounded-3xl p-8 md:p-12 text-white shadow-xl mb-8 relative overflow-hidden">
                <div class="absolute -right-10 -bottom-10 w-48 h-48 bg-white/10 rounded-full blur-2xl"></div>
                <div class="absolute -left-10 -top-10 w-48 h-48 bg-pink-500/20 rounded-full blur-2xl"></div>
                <div class="relative z-10">
                    <span class="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-white/20 backdrop-blur-md text-white mb-4 border border-white/10">
                        🧸 智能玩偶成长 analysis 报告
                    </span>
                    <h1 class="text-3xl md:text-5xl font-black mb-3 tracking-wide">小探宝成长行为心理诊断</h1>
                    <p class="text-white/80 text-sm md:text-base font-medium flex flex-wrap items-center gap-y-2 gap-x-4">
                        <span>设备令牌: <code class="bg-black/20 px-2 py-0.5 rounded font-mono text-white">{device_token}</code></span>
                        <span class="hidden md:inline">|</span>
                        <span>报告生成日期: {time.strftime('%Y-%m-%d %H:%M:%S')}</span>
                    </p>
                </div>
            </div>

            <!-- PRE_ALERT_BANNER -->
            {alert_banner}

            <!-- VOICE SETTINGS PANEL -->
            <div class="bg-white rounded-3xl p-6 md:p-8 border border-gray-100 shadow-sm mb-8">
                <div class="flex items-center space-x-3 mb-4">
                    <span class="text-3xl">🧸</span>
                    <div>
                        <h2 class="text-xl font-bold text-gray-800">小探宝音色专属配置</h2>
                        <p class="text-xs text-gray-400">为孩子定制最自然的回复声音，支持中英文双语、温暖稚嫩的优质儿童及温馨少女原声</p>
                    </div>
                </div>
                
                <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mt-6">
                    <!-- Option 1: Anna -->
                    <div id="voice-anna" onclick="selectVoice('anna')" class="voice-card cursor-pointer relative p-5 rounded-2xl border-2 transition-all duration-200 hover:shadow-md flex flex-col justify-between {'border-indigo-500 bg-indigo-50/30' if active_voice.endswith(':anna') or active_voice == 'anna' else 'border-gray-100 hover:border-gray-200'}">
                        <div>
                            <div class="flex items-center justify-between mb-2">
                                <span class="font-bold text-gray-800 text-sm md:text-base flex items-center gap-1.5">👧 温暖童真 (少女) <span class="text-[10px] bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded-md font-medium">推荐</span></span>
                                <span class="radio-indicator text-indigo-500 text-lg">{'●' if active_voice.endswith(':anna') or active_voice == 'anna' else '○'}</span>
                            </div>
                            <p class="text-xs text-gray-500 leading-relaxed">最受欢迎！中英文双语，声线极其亲切、温暖、活泼，犹如温柔的小姐姐，最适合陪伴孩子学习与玩耍。</p>
                        </div>
                    </div>
                    
                    <!-- Option 2: Mia -->
                    <div id="voice-mia" onclick="selectVoice('mia')" class="voice-card cursor-pointer relative p-5 rounded-2xl border-2 transition-all duration-200 hover:shadow-md flex flex-col justify-between {'border-indigo-500 bg-indigo-50/30' if active_voice.endswith(':mia') or active_voice == 'mia' else 'border-gray-100 hover:border-gray-200'}">
                        <div>
                            <div class="flex items-center justify-between mb-2">
                                <span class="font-bold text-gray-800 text-sm md:text-base flex items-center gap-1.5">👶 俏皮活泼 (可爱小女孩)</span>
                                <span class="radio-indicator text-indigo-500 text-lg">{'●' if active_voice.endswith(':mia') or active_voice == 'mia' else '○'}</span>
                            </div>
                            <p class="text-xs text-gray-500 leading-relaxed">稚嫩可爱，充满好奇心与探求朝气，元气满满，极富感染力，能迅速与3-8岁的小朋友建立深厚的玩伴信任。</p>
                        </div>
                    </div>
                    
                    <!-- Option 3: Bella -->
                    <div id="voice-bella" onclick="selectVoice('bella')" class="voice-card cursor-pointer relative p-5 rounded-2xl border-2 transition-all duration-200 hover:shadow-md flex flex-col justify-between {'border-indigo-500 bg-indigo-50/30' if active_voice.endswith(':bella') or active_voice == 'bella' else 'border-gray-100 hover:border-gray-200'}">
                        <div>
                            <div class="flex items-center justify-between mb-2">
                                <span class="font-bold text-gray-800 text-sm md:text-base flex items-center gap-1.5">🌸 甜美贴心 (温馨女声)</span>
                                <span class="radio-indicator text-indigo-500 text-lg">{'●' if active_voice.endswith(':bella') or active_voice == 'bella' else '○'}</span>
                            </div>
                            <p class="text-xs text-gray-500 leading-relaxed">声线甜美细腻，温柔体贴，具有极强的情感疗愈效果，最适合在小朋友情绪不稳定或具有分离焦虑时给予支持。</p>
                        </div>
                    </div>
                </div>
                
                <div class="mt-6 flex flex-wrap items-center justify-between gap-4 border-t border-gray-50 pt-5">
                    <div class="text-xs text-gray-400 flex items-center gap-1">
                        <span>当前音色:</span>
                        <span id="current-voice-label" class="font-semibold text-gray-700 bg-gray-100 px-2.5 py-1 rounded-md">{'温暖童真 (少女/Anna)' if active_voice.endswith(':anna') or active_voice == 'anna' else '俏皮活泼 (可爱小女孩/Mia)' if active_voice.endswith(':mia') or active_voice == 'mia' else '甜美贴心 (温馨女声/Bella)' if active_voice.endswith(':bella') or active_voice == 'bella' else '温暖童真 (少女/Anna)'}</span>
                    </div>
                    
                    <button id="save-settings-btn" onclick="saveVoiceSettings()" class="bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white font-bold px-6 py-2.5 rounded-xl shadow-md transition-all duration-150 transform hover:-translate-y-0.5 active:translate-y-0 text-sm flex items-center gap-2">
                        <span>💾 保存音色配置</span>
                    </button>
                </div>
            </div>

            <!-- STATS COUNTERS -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                <div class="bg-white p-6 rounded-2xl border border-gray-100 shadow-sm flex items-center space-x-4">
                    <div class="p-4 bg-indigo-50 text-indigo-500 rounded-xl text-2xl">💬</div>
                    <div>
                        <p class="text-xs font-bold text-gray-400 uppercase tracking-wider">对话交互记录</p>
                        <h3 class="text-2xl font-black text-gray-800">{data['total_interactions']} 次</h3>
                    </div>
                </div>
                <div class="bg-white p-6 rounded-2xl border border-gray-100 shadow-sm flex items-center space-x-4">
                    <div class="p-4 bg-emerald-50 text-emerald-500 rounded-xl text-2xl">📈</div>
                    <div>
                        <p class="text-xs font-bold text-gray-400 uppercase tracking-wider">言语丰富度均分</p>
                        <h3 class="text-2xl font-black text-gray-800">{data['linguistic_score_avg']}%</h3>
                    </div>
                </div>
                <div class="bg-white p-6 rounded-2xl border border-gray-100 shadow-sm flex items-center space-x-4">
                    <div class="p-4 bg-rose-50 text-rose-500 rounded-xl text-2xl">❤️</div>
                    <div>
                        <p class="text-xs font-bold text-gray-400 uppercase tracking-wider">特别关注与情绪预警</p>
                        <h3 class="text-2xl font-black text-gray-800">{data['requires_attention_count']} 次</h3>
                    </div>
                </div>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-8">
                <!-- CHART & TAGS -->
                <div class="lg:col-span-2 space-y-8">
                    <!-- LANGUAGE SCORE CHART -->
                    <div class="bg-white p-6 md:p-8 rounded-3xl border border-gray-100 shadow-sm">
                        <div class="flex items-center justify-between mb-6">
                            <div>
                                <h2 class="text-xl font-bold text-gray-800">言语发展与句子逻辑性走势</h2>
                                <p class="text-xs text-gray-400">最近十次儿童表达词汇丰富度及语法组织力评分走势</p>
                            </div>
                            <span class="text-xs font-bold bg-indigo-50 text-indigo-600 px-2.5 py-1 rounded-full">发展状态评估</span>
                        </div>
                        {trend_svg}
                    </div>

                    <!-- EMOTIONS & INTERESTS -->
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
                        <div class="bg-white p-6 rounded-3xl border border-gray-100 shadow-sm">
                            <h2 class="text-lg font-bold text-gray-800 mb-4">心理状态特征分类统计</h2>
                            <div class="flex flex-wrap gap-2">
                                {emotion_html}
                            </div>
                        </div>
                        <div class="bg-white p-6 rounded-3xl border border-gray-100 shadow-sm">
                            <h2 class="text-lg font-bold text-gray-800 mb-4">核心趣味探索主题分布</h2>
                            <div class="flex flex-wrap gap-2">
                                {interest_html}
                            </div>
                        </div>
                    </div>
                </div>

                <!-- PSYCH REPORT BLOCK -->
                <div class="lg:col-span-1 bg-white p-6 md:p-8 rounded-3xl border border-gray-100 shadow-sm flex flex-col h-full">
                    <div class="flex items-center space-x-3 mb-6">
                        <span class="p-2 bg-purple-50 text-purple-600 rounded-lg">🎓</span>
                        <h2 class="text-xl font-bold text-gray-800">专业测评与诊断意见</h2>
                    </div>
                    <div class="prose prose-sm text-gray-600 leading-relaxed overflow-y-auto max-h-[500px] flex-1 whitespace-pre-line border-t border-gray-100 pt-4">
                        {data['summary']}
                    </div>
                </div>
            </div>

            <!-- DRAWINGS WALL -->
            <div class="bg-white p-6 md:p-8 rounded-3xl border border-gray-100 shadow-sm mb-8">
                <div class="flex items-center justify-between mb-6">
                    <div>
                        <h2 class="text-xl font-bold text-gray-800">儿童数字手绘创作墙 (Seedream 5.0 pro)</h2>
                        <p class="text-xs text-gray-400">儿童通过语音命令让小探宝现场创作的简笔画，已自动通过 1-bit 排包算法推送到硬件端打印</p>
                    </div>
                    <span class="text-xs font-bold bg-pink-50 text-pink-600 px-2.5 py-1 rounded-full">作品展示</span>
                </div>
                <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
                    {drawings_html}
                </div>
            </div>
            
            <!-- FOOTER -->
            <div class="text-center text-gray-400 text-xs py-6">
                <p>© 2026 小探宝智能交互研究实验室. 保留所有权利。</p>
                <p class="mt-1">通过先进多模态大模型及向量数据库，提供科学非介入式的早期成长心理支持</p>
            </div>
        </div>

        <script>
            let selectedVoice = "{'anna' if active_voice.endswith(':anna') or active_voice == 'anna' else 'mia' if active_voice.endswith(':mia') or active_voice == 'mia' else 'bella' if active_voice.endswith(':bella') or active_voice == 'bella' else 'anna'}";
            
            function selectVoice(voiceId) {{
                selectedVoice = voiceId;
                
                document.querySelectorAll('.voice-card').forEach(card => {{
                    card.classList.remove('border-indigo-500', 'bg-indigo-50/30');
                    card.classList.add('border-gray-100');
                    card.querySelector('.radio-indicator').innerText = '○';
                }});
                
                const activeCard = document.getElementById('voice-' + voiceId);
                activeCard.classList.remove('border-gray-100');
                activeCard.classList.add('border-indigo-500', 'bg-indigo-50/30');
                activeCard.querySelector('.radio-indicator').innerText = '●';
                
                const labelMap = {{
                    'anna': '温暖童真 (少女/Anna)',
                    'mia': '俏皮活泼 (可爱小女孩/Mia)',
                    'bella': '甜美贴心 (温馨女声/Bella)'
                }};
                document.getElementById('current-voice-label').innerText = labelMap[voiceId];
            }}
            
            async function saveVoiceSettings() {{
                const btn = document.getElementById('save-settings-btn');
                const origText = btn.innerHTML;
                btn.disabled = true;
                btn.innerHTML = '⚡ 正在保存...';
                
                try {{
                    const response = await fetch('/api/admin/settings/{device_token}', {{
                        method: 'POST',
                        headers: {{
                            'Content-Type': 'application/json'
                        }},
                        body: JSON.stringify({{
                            voice_name: 'FunAudioLLM/CosyVoice2-0.5B:' + selectedVoice
                        }})
                    }});
                    
                    const resData = await response.json();
                    if (resData.success) {{
                        btn.innerHTML = '✅ 保存成功！';
                        btn.classList.remove('from-indigo-500', 'to-purple-600');
                        btn.classList.add('from-emerald-500', 'to-teal-600');
                        setTimeout(() => {{
                            btn.innerHTML = origText;
                            btn.disabled = false;
                            btn.classList.remove('from-emerald-500', 'to-teal-600');
                            btn.classList.add('from-indigo-500', 'to-purple-600');
                        }}, 2000);
                    }} else {{
                        throw new Error(resData.detail || '保存失败');
                    }}
                }} catch (err) {{
                    alert('保存配置出错: ' + err.message);
                    btn.innerHTML = origText;
                    btn.disabled = false;
                }}
            }}
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)
