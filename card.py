"""HTML 卡片模板常量：Jinja2 语法，由 AstrBot 的 html_render 渲染为图片。

设计规范：NoFizz-AstrBot 插件 UI 设计规范（Bilibili Web 设计系统 v1.4 官方色卡）。
- 品牌粉 #FF6699 渐变头部 + 品牌蓝 #00AEEC 数据强调；浅色专用（聊天卡片渲染为
  PNG，无深色模式，故不引入 ``[data-theme="dark"]`` 变量块，但保留 ``:root``
  变量架构以便后续扩展）。
- 全插件统一微软雅黑（用户指定），回退系统无衬线字体。
- 卡片圆角 8px、间距 4px 网格、规范阴影层级。
- 三栏布局（760px）：左序号区 88px（浅灰底品牌粉数字）| 中封面 150px | 右信息
  （标题/评分/在看/首播/排名/tag 徽章）。
- 所有数据插值显式 ``| e`` 转义（不依赖 html_render 环境的 autoescape 开关）；
  ``or`` 优先级低于过滤器，必须加括号 ``(a.name_cn or a.name) | e``，否则
  仅 ``a.name`` 被转义而主标题 ``a.name_cn`` 裸奔。
"""

# Copyright 2026 NoFizz
# SPDX-License-Identifier: AGPL-3.0-or-later

HTML_TMPL = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=760, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <style>
    /* Bilibili 设计系统变量（规范 §〇 :root 块，v1.4 官方色卡，浅色适配）：聊天卡片固定浅色，无深色模式 */
    :root {
      --bg: #FFFFFF;              /* 页面背景 = 官方 --bg1 */
      --card-bg: #FFFFFF;         /* 卡片背景 = 官方 --bg1_float */
      --text: #18191C;            /* 标题/正文（近黑）= 官方 --text1 */
      --text-secondary: #61666D;  /* 次要文字 = 官方 --text2 */
      --text-muted: #9499A0;      /* 辅助/弱化文字 = 官方 --text3 */
      --primary: #00AEEC;         /* 品牌蓝（在看人数等数据强调）= 官方 --brand_blue */
      --accent: #FF6699;          /* 品牌粉（头部/评分/标题竖条/tag 徽章）= 官方 --brand_pink / --Pi5 */
      --on-accent: #FFFFFF;       /* 品牌粉底上的文字 = 官方 --text_white */
      --on-primary: #FFFFFF;      /* 品牌蓝底上的文字 = 官方 --text_white */
      --subtle: #F1F2F3;          /* 次面背景（封面占位底）= 官方 --graph_bg_regular */
      --border: #E3E5E7;          /* 边框 = 官方 --line_regular / --Ga2 */
      --card-border: #E3E5E7;     /* 卡片边框 = 官方 --line_regular / --Ga2 */
      --accent-soft: #FFECF1;     /* 浅粉底 = 官方 --brand_pink_thin / --Pi1 */
      --radius-sm: 4px;           /* 操作元素圆角 */
      --radius: 6px;              /* toast 圆角 */
      --radius-lg: 8px;           /* 大卡片圆角 */
      --shadow: 0 1px 0 rgba(0, 0, 0, 0.04);        /* 卡片默认投影 */
      --shadow-hover: 0 3px 6px rgba(0, 0, 0, 0.12); /* 浮层投影 */
      /* 全插件统一微软雅黑（用户指定），回退到系统无衬线字体 */
      --font: "Microsoft YaHei", "微软雅黑", "PingFang SC", "Noto Sans SC", sans-serif;
      /* 新宋体：标题与序号专用（用户指定），回退到宋体系列 */
      --font-song: "NSimSun", "新宋体", SimSun, "宋体", serif;
    }

    * { margin: 0; padding: 0; box-sizing: border-box; }
    /* 760px 固定宽度契约，必须与 html_render 的 viewport_width 保持一致 */
    html, body {
      width: 760px; min-width: 760px; max-width: 760px;
      background: var(--bg); color: var(--text);
      font-family: var(--font); font-size: 14px; line-height: 1.6;
      overflow-x: hidden;
    }

    /* 头部：品牌粉纯色（官方 --brand_pink #FF6699，无渐变），底部透明白渐变指示条 */
    .header {
      position: relative; text-align: center;
      padding: 32px 24px 28px;
      background: var(--accent);
      border-radius: var(--radius-lg) var(--radius-lg) 0 0;
    }
    .header::after {
      content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 4px;
      background: linear-gradient(90deg, rgba(255, 255, 255, 0.4), rgba(255, 255, 255, 0.9), rgba(255, 255, 255, 0.4));
    }
    .header h1 {
      font-family: var(--font-song); font-size: 34px; font-weight: 700;
      color: var(--on-accent); letter-spacing: -0.01em; line-height: 1.2;
      text-shadow: 0 2px 6px rgba(0, 0, 0, 0.12);
    }
    .header .date { margin-top: 10px; font-size: 18px; color: rgba(255, 255, 255, 0.92); }

    .container {
      background: var(--bg);
      border-radius: 0 0 var(--radius-lg) var(--radius-lg);
      box-shadow: var(--shadow);
    }
    .body { padding: 20px 24px 24px; }

    /* 番剧卡片：白底 + 1px 边框 + 8px 圆角 + 默认投影（规范 §4/§5） */
    .anime-card {
      display: flex; width: 100%; min-height: 180px;
      background: var(--card-bg); border: 1px solid var(--card-border);
      border-radius: var(--radius-lg); overflow: hidden;
      box-shadow: var(--shadow); margin-bottom: 20px;
    }
    .anime-card:last-child { margin-bottom: 0; }
    .anime-card .cover {
      width: 150px; min-height: 180px; flex-shrink: 0;
      object-fit: cover; background: var(--subtle);
    }
    .cover-placeholder {
      width: 150px; min-height: 180px; flex-shrink: 0;
      background: var(--subtle); color: var(--text-muted);
      display: flex; align-items: center; justify-content: center; font-size: 20px;
    }
    .anime-card .info {
      flex: 1; min-width: 0; padding: 16px 20px;
      display: flex; flex-direction: column; justify-content: center;
    }
    /* 标题行：番剧名（左，flex 占满）+ rank 胶囊（右） */
    .anime-card .title-row {
      display: flex; align-items: flex-start; gap: 8px;
    }
    /* 标题：微软雅黑 + 品牌粉 3px 竖条，最多两行 */
    .anime-card .title {
      flex: 1; min-width: 0;
      font-family: var(--font); font-size: 24px; font-weight: 600;
      color: var(--text); line-height: 1.3; word-break: break-all;
      border-left: 3px solid var(--accent); padding-left: 10px;
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
    }
    /* rank 胶囊：品牌蓝底白字，位于番剧名末尾右侧 */
    .anime-card .rank-badge {
      flex-shrink: 0; margin-top: 2px;
      padding: 3px 10px; border-radius: 999px;
      background: var(--primary); color: var(--on-primary);
      font-size: 12px; font-weight: 600; line-height: 1.4; white-space: nowrap;
    }
    /* 日文原名：次要文字，单行截断 */
    .anime-card .title-jp {
      font-size: 15px; color: var(--text-muted); margin-top: 10px;
      word-break: break-all; line-height: 1.4;
      display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden;
    }
    .anime-card .meta { margin-top: 14px; font-size: 17px; color: var(--text-secondary); line-height: 1.6; }
    .anime-card .meta .score { color: var(--accent); font-weight: 700; font-size: 22px; }
    .anime-card .meta .doing { color: var(--primary); font-weight: 700; }

    /* 序号区（左栏）：64px 定宽，白底与信息区一致，右侧浅灰分隔线，新宋体品牌粉大号数字垂直居中 */
    .anime-card .index-col {
      width: 64px; flex-shrink: 0;
      display: flex; align-items: center; justify-content: center;
      background: var(--card-bg); border-right: 1px solid var(--card-border);
    }
    .anime-card .index-num {
      font-family: var(--font-song); font-size: 48px; font-weight: 700;
      color: var(--accent); line-height: 1;
    }
    /* tag 行：flex 可换行，浅粉底胶囊徽章（品牌粉系，与评分强调一致） */
    .anime-card .tags {
      display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px;
    }
    .anime-card .tag {
      padding: 5px 10px; border-radius: 999px;
      background: var(--accent-soft); color: var(--accent);
      font-size: 12px; font-weight: 400; line-height: 1.4;
    }

    .footer {
      text-align: center; padding: 16px 24px 20px;
      font-size: 13px; color: var(--text-muted);
      background: var(--card-bg); border-top: 1px solid var(--card-border);
    }
    /* 作者署名：数据来源下方，居中 */
    .footer .credit {
      margin-top: 6px; font-size: 12px; color: var(--text-muted);
    }
  </style>
</head>
<body>
  <div class="header">
    <h1>新番日推</h1>
    <div class="date">{{ date | e }} {{ weekday | e }} · 共 {{ count | e }} 部</div>
  </div>
  <div class="container">
    <div class="body">
      {% for a in items %}
      <div class="anime-card">
        <div class="index-col">
          <div class="index-num">{{ a.index | e }}</div>
        </div>
        {% if a.cover %}
        <!-- onerror：封面加载失败时隐藏 img、显示占位（名称已转义，注入无法破坏结构） -->
        <img class="cover" src="{{ a.cover | e }}" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'" alt="" />
        <div class="cover-placeholder" style="display:none">无图</div>
        {% else %}
        <div class="cover-placeholder">无图</div>
        {% endif %}
        <div class="info">
          <div class="title-row">
            <!-- or 优先级低于 |：必须整体加括号，否则 name_cn 不被转义 -->
            <div class="title">{{ (a.name_cn or a.name) | e }}</div>
            {% if a.rank %}
            <span class="rank-badge">Rank {{ a.rank | e }}</span>
            {% endif %}
          </div>
          {% if a.name_cn and a.name and a.name_cn != a.name %}
          <div class="title-jp">{{ a.name | e }}</div>
          {% endif %}
          <div class="meta">
            评分: <span class="score">{{ a.score | e }}</span>
            &nbsp;·&nbsp; 在看: <span class="doing">{{ a.doing | e }}</span>人
            &nbsp;·&nbsp; {{ a.air_date | e }}
          </div>
          {% if a.tags %}
          <div class="tags">{% for t in a.tags %}<span class="tag">{{ t | e }}</span>{% endfor %}</div>
          {% endif %}
        </div>
      </div>
      {% endfor %}
    </div>
    <div class="footer">
      数据来源: Bangumi · bangumi.tv
      <div class="credit">NoFizz</div>
    </div>
  </div>
</body>
</html>
'''
