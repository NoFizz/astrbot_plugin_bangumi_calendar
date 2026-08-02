"""HTML 卡片模板常量：Jinja2 语法，由 AstrBot 的 html_render 渲染为图片。"""

HTML_TMPL = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=660, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; font-family: sans-serif; }
    html, body { background: #fff0f3; color: #222; width: 660px; min-width: 660px; max-width: 660px; margin: 0; padding: 0; min-height: 100%; overflow-x: hidden; }
    .header {
      text-align: center; padding: 28px 0 22px;
      background: #fb7299; width: 660px; position: relative;
      border-radius: 0;
    }
    .container {
      width: 660px; margin: 0; padding: 0;
      background: #fff0f3; overflow: hidden;
      border-radius: 0 0 16px 16px;
      box-shadow: 0 4px 12px rgba(251, 114, 153, 0.15);
    }
    .header h1 { font-size: 38px; font-weight: 700; color: #fff; margin-bottom: 8px; text-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    .header .date { font-size: 20px; color: #ffd6e0; }
    .header::after {
      content: ""; position: absolute; bottom: 0; left: 0; right: 0; height: 4px;
      background: linear-gradient(90deg, #fb7299, #ff99b1, #fb7299);
    }
    .body { display: block; width: 100%; padding: 24px 6px; }
    .anime-card {
      display: flex; background: #fff; border-radius: 12px;
      margin-bottom: 14px; overflow: hidden; border: 1px solid #e3e5e7;
      min-height: 210px; width: 100%; box-shadow: 0 2px 6px rgba(0,0,0,0.05);
    }
    .anime-card .cover { width: 150px; min-height: 210px; object-fit: cover; flex-shrink: 0; background: #e3e5e7; }
    .anime-card .info { padding: 20px; display: flex; flex-direction: column; justify-content: center; flex: 1; min-width: 0; }
    .anime-card .title { font-size: 26px; font-weight: 700; color: #18191c; margin-bottom: 4px; word-break: break-all; line-height: 1.3; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .anime-card .title-jp { font-size: 17px; color: #9499a0; margin-bottom: 14px; word-break: break-all; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden; }
    .anime-card .meta { font-size: 18px; color: #61666d; line-height: 1.6; }
    .anime-card .meta .score { color: #fb7299; font-weight: 700; font-size: 22px; }
    .anime-card .meta .doing { color: #00a1d6; font-weight: 700; }
    .footer { text-align: center; padding: 18px 0 22px; font-size: 14px; color: #9499a0; border-top: 1px solid #e3e5e7; width: 100%; background: #fff; }
    .no-cover .info { padding: 20px; }
    .cover-placeholder { width: 150px; min-height: 210px; flex-shrink: 0; background: #e3e5e7; display: flex; align-items: center; justify-content: center; font-size: 20px; color: #c9ccd0; }
  </style>
</head>
<body>
  <div class="header">
    <h1>新番日推</h1>
    <div class="date">{{ date }} {{ weekday }} · 共 {{ count }} 部</div>
  </div>
  <div class="container">
    <div class="body">
      {% for a in items %}
      <div class="anime-card">
        {% if a.cover %}
        <img class="cover" src="{{ a.cover }}" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'" />
        <div class="cover-placeholder" style="display:none">无图</div>
        {% else %}
        <div class="cover-placeholder">无图</div>
        {% endif %}
        <div class="info">
          <div class="title">{{ a.name_cn or a.name }}</div>
          {% if a.name_cn and a.name and a.name_cn != a.name %}
          <div class="title-jp">{{ a.name }}</div>
          {% endif %}
          <div class="meta">
            评分: <span class="score">{{ a.score }}</span>
            &nbsp;·&nbsp; 在看: <span class="doing">{{ a.doing }}</span>人
            &nbsp;·&nbsp; {{ a.air_date }}
          </div>
        </div>
      </div>
      {% endfor %}
    </div>
    <div class="footer">数据来源: Bangumi · bangumi.tv</div>
  </div>
</body>
</html>
'''
