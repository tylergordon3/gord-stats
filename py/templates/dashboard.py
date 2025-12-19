DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Bracket Gordology – {LEAGUE_TITLE}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">

  <link rel="stylesheet" href="/assets/css/style.css">
  <link rel="stylesheet" href="/assets/css/custom.css">

  <style>
    .dashboard {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 20px;
    }}

    .card {{
      border: 1px solid #d0d7de;
      border-radius: 6px;
      padding: 12px 14px;
      background: #fff;
    }}

    .card h3 {{
      margin: 0 0 8px;
      font-size: 15px;
      border-bottom: 1px solid #eee;
      padding-bottom: 4px;
    }}

    .card ul {{
      list-style: none;
      padding: 0;
      margin: 0;
    }}

    .card li {{
      padding: 6px 0;
      font-size: 14px;
      display: flex;
      justify-content: space-between;
      gap: 10px;
    }}

    .card table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}

    .card td {{
      padding: 6px 4px;
    }}

    .card td:last-child {{
      text-align: right;
      font-weight: 600;
    }}

    .more {{
      display: block;
      margin-top: 8px;
      font-size: 13px;
      text-decoration: none;
    }}
  </style>
</head>

<body>

<div class="dashboard">

  <div class="card">
    <h3>{LEAGUE_TITLE}</h3>
    <p style="margin:6px 0 0;font-size:14px;">
      Daily model projections, rankings, and historical results.
    </p>
  </div>

  <div class="card">
    <h3>🔥 Today</h3>
    <ul>
      {TODAY_GAMES}
    </ul>
    <a class="more" href="predict_{TODAY}.html">View full slate →</a>
  </div>

  <div class="card">
    <h3>📈 Model Edge</h3>
    <table>
      {MODEL_EDGES}
    </table>
    <a class="more" href="predict_{TODAY}.html">Full projections →</a>
  </div>

  <div class="card">
    <h3>📊 Rankings Snapshot</h3>
    <ol style="margin:0;padding-left:18px;font-size:14px;">
      {RANKINGS}
    </ol>
    <a class="more" href="rankings.html">Full rankings →</a>
  </div>

</div>

</body>
</html>
"""
