"""
Generate a beginner-friendly HTML report from 9sig simulation results.
Usage: python generate_report.py [config.yaml]
"""

import sys
import base64
import yaml
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def img_to_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def action_badge(action: str) -> str:
    if action == "INIT":
        return '<span class="badge badge-init">Start</span>'
    elif action == "BUY" or action == "30DOWN_BUY":
        return '<span class="badge badge-buy">Buy</span>'
    elif action == "SELL":
        return '<span class="badge badge-sell">Sell</span>'
    elif "100UP" in action:
        return '<span class="badge badge-100up">100Up Reset</span>'
    elif "RESET_REBALANCE" in action:
        return '<span class="badge badge-reset">30Down Reset</span>'
    elif "IGNORE_SELL" in action:
        return '<span class="badge badge-ignore">30Down Hold</span>'
    elif "30DOWN_TRIGGERED" in action:
        return '<span class="badge badge-ignore">30Down Active</span>'
    return f'<span class="badge badge-init">{action}</span>'


def make_allocation_chart(results: pd.DataFrame) -> str:
    """Generate allocation chart and return as base64 PNG."""
    dates  = results["quarter"]
    totals = results["total"]

    bah_shares = results["total"].iloc[0] / results["price"].iloc[0]
    bah_values = bah_shares * results["price"]

    rolling_max = totals.cummax()
    drawdowns   = (totals - rolling_max) / rolling_max * 100

    fig, axes = plt.subplots(3, 1, figsize=(12, 13),
                             gridspec_kw={"height_ratios": [3, 1.5, 1.5]})
    fig.patch.set_facecolor("#f9fafb")
    for ax in axes:
        ax.set_facecolor("#f9fafb")

    # Panel 1: Equity curve
    ax1 = axes[0]
    ax1.plot(dates, totals,     label="9sig Portfolio", linewidth=2.5, color="#2563eb")
    ax1.plot(dates, bah_values, label="Buy & Hold TQQQ", linewidth=1.5,
             color="#f97316", alpha=0.8, linestyle="--")

    for _, row in results.iterrows():
        if "30DOWN" in str(row["action"]):
            ax1.axvline(row["quarter"], color="#ef4444", alpha=0.2, linewidth=1)
        if "100UP" in str(row["action"]):
            ax1.axvline(row["quarter"], color="#22c55e", alpha=0.5, linewidth=1.5)

    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax1.set_ylabel("Portfolio Value", fontsize=11)
    ax1.legend(fontsize=10)
    ax1.set_title("Portfolio Growth Over Time", fontsize=13, fontweight="bold", pad=10)
    ax1.grid(True, alpha=0.3)

    # Panel 2: Allocation
    ax2 = axes[1]
    ax2.stackplot(dates, results["etf_value"], results["cash"],
                  labels=["TQQQ", "Cash"],
                  colors=["#2563eb", "#93c5fd"], alpha=0.85)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax2.set_ylabel("Allocation", fontsize=11)
    ax2.legend(fontsize=10)
    ax2.set_title("TQQQ vs Cash Over Time", fontsize=12, fontweight="bold", pad=8)
    ax2.grid(True, alpha=0.3)

    # Panel 3: Drawdown
    ax3 = axes[2]
    ax3.fill_between(dates, drawdowns, 0, color="#ef4444", alpha=0.45, label="Drawdown")
    ax3.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    ax3.set_ylabel("Drawdown", fontsize=11)
    ax3.set_title("Portfolio Drawdown (Peak to Trough)", fontsize=12, fontweight="bold", pad=8)
    ax3.legend(fontsize=10)
    ax3.grid(True, alpha=0.3)

    plt.tight_layout(pad=2.5)

    tmp_path = "/tmp/9sig_report_chart.png"
    plt.savefig(tmp_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    return img_to_base64(tmp_path)


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

def build_html(results: pd.DataFrame, config: dict) -> str:
    starting   = config["starting_capital"]
    final      = results["total"].iloc[-1]
    start_dt   = results["quarter"].iloc[0]
    end_dt     = results["quarter"].iloc[-1]
    years      = (end_dt - start_dt).days / 365.25
    total_ret  = (final - starting) / starting * 100
    cagr       = ((final / starting) ** (1 / years) - 1) * 100 if years > 0 else 0
    q_returns  = results["total"].pct_change().dropna()
    sharpe     = (q_returns.mean() / q_returns.std() * np.sqrt(4)) if q_returns.std() > 0 else 0
    rolling_max   = results["total"].cummax()
    max_dd     = ((results["total"] - rolling_max) / rolling_max * 100).min()

    # Buy-and-hold comparison
    bah_final  = (starting / results["price"].iloc[0]) * results["price"].iloc[-1]
    bah_ret    = (bah_final - starting) / starting * 100
    bah_cagr   = ((bah_final / starting) ** (1 / years) - 1) * 100 if years > 0 else 0

    chart_b64 = make_allocation_chart(results)

    # Quarter rows
    quarter_rows = ""
    for _, row in results.iterrows():
        g = f"{row['quarterly_growth_pct']:.1f}%" if pd.notna(row.get("quarterly_growth_pct")) else "—"
        cls = ""
        if pd.notna(row.get("quarterly_growth_pct")):
            cls = "pos" if row["quarterly_growth_pct"] >= 0 else "neg"
        quarter_rows += f"""
        <tr>
          <td>{row['quarter'].strftime('%b %Y')}</td>
          <td>${row['price']:.2f}</td>
          <td class="{cls}">{g}</td>
          <td>${row['etf_value']:,.0f}</td>
          <td>${row['cash']:,.0f}</td>
          <td>${row['total']:,.0f}</td>
          <td>{action_badge(row['action'])}</td>
        </tr>"""

    generated_on = datetime.now().strftime("%B %d, %Y")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>9sig Strategy — Backtest Report</title>
  <link rel="preconnect" href="https://fonts.googleapis.com"/>
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
  <link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&family=Inter:wght@400;500&display=swap" rel="stylesheet"/>
  <style>
    :root {{
      --bg:        #07090f;
      --bg2:       #0d1017;
      --bg3:       #121620;
      --border:    rgba(255,255,255,0.07);
      --amber:     #f0a500;
      --amber-dim: rgba(240,165,0,0.12);
      --cyan:      #00c8ff;
      --cyan-dim:  rgba(0,200,255,0.10);
      --green:     #22d07a;
      --green-dim: rgba(34,208,122,0.10);
      --red:       #ff4d5a;
      --red-dim:   rgba(255,77,90,0.10);
      --orange:    #ff8c42;
      --orange-dim:rgba(255,140,66,0.10);
      --text:      #dde2ec;
      --text-muted:#6b7590;
      --text-dim:  #9ba3b8;
      --mono:      'JetBrains Mono', monospace;
      --sans:      'Syne', sans-serif;
      --body:      'Inter', sans-serif;
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: var(--body);
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
      min-height: 100vh;
      background-image:
        radial-gradient(ellipse 80% 50% at 50% -10%, rgba(0,200,255,0.06) 0%, transparent 60%),
        linear-gradient(180deg, #07090f 0%, #090c14 100%);
    }}

    .page {{ max-width: 1000px; margin: 0 auto; padding: 40px 24px 80px; }}

    /* ── Animations ─────────────────────────────────────────────────── */
    @keyframes fadeUp {{
      from {{ opacity: 0; transform: translateY(18px); }}
      to   {{ opacity: 1; transform: translateY(0); }}
    }}
    @keyframes shimmer {{
      0%   {{ background-position: -200% center; }}
      100% {{ background-position:  200% center; }}
    }}
    .fade-up {{ animation: fadeUp 0.5s ease both; }}
    .d1 {{ animation-delay: 0.05s; }}
    .d2 {{ animation-delay: 0.12s; }}
    .d3 {{ animation-delay: 0.19s; }}
    .d4 {{ animation-delay: 0.26s; }}
    .d5 {{ animation-delay: 0.33s; }}
    .d6 {{ animation-delay: 0.40s; }}
    .d7 {{ animation-delay: 0.47s; }}

    /* ── Header ─────────────────────────────────────────────────────── */
    .header {{
      position: relative;
      border: 1px solid var(--border);
      border-top: 2px solid var(--amber);
      border-radius: 0 0 16px 16px;
      background: var(--bg2);
      padding: 48px 48px 40px;
      margin-bottom: 40px;
      overflow: hidden;
    }}
    .header::before {{
      content: '';
      position: absolute;
      inset: 0;
      background: radial-gradient(ellipse 60% 80% at 0% 50%, rgba(240,165,0,0.05) 0%, transparent 60%);
      pointer-events: none;
    }}
    .header-tag {{
      font-family: var(--mono);
      font-size: 0.72rem;
      font-weight: 600;
      letter-spacing: 0.15em;
      text-transform: uppercase;
      color: var(--amber);
      margin-bottom: 14px;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .header-tag::before {{
      content: '';
      width: 28px; height: 1.5px;
      background: var(--amber);
    }}
    .header h1 {{
      font-family: var(--sans);
      font-size: 3.2rem;
      font-weight: 800;
      letter-spacing: -0.03em;
      color: #fff;
      line-height: 1.05;
      margin-bottom: 10px;
    }}
    .header h1 span {{
      background: linear-gradient(90deg, var(--amber) 0%, #ffcc55 50%, var(--amber) 100%);
      background-size: 200% auto;
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      animation: shimmer 3s linear infinite;
    }}
    .header .subtitle {{
      font-size: 1rem;
      color: var(--text-dim);
      margin-bottom: 24px;
    }}
    .header .meta-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 20px;
    }}
    .meta-pill {{
      font-family: var(--mono);
      font-size: 0.75rem;
      color: var(--text-muted);
      background: rgba(255,255,255,0.04);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 5px 12px;
    }}
    .meta-pill strong {{ color: var(--text-dim); }}

    /* ── Section headings ───────────────────────────────────────────── */
    .section-label {{
      font-family: var(--mono);
      font-size: 0.7rem;
      font-weight: 600;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--cyan);
      margin-bottom: 6px;
    }}
    h2 {{
      font-family: var(--sans);
      font-size: 1.45rem;
      font-weight: 700;
      color: #fff;
      margin-bottom: 16px;
      letter-spacing: -0.02em;
    }}
    h3 {{
      font-family: var(--sans);
      font-size: 1rem;
      font-weight: 600;
      color: var(--text);
      margin-bottom: 8px;
    }}

    /* ── Cards ──────────────────────────────────────────────────────── */
    .card {{
      background: var(--bg2);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 28px 32px;
      margin-bottom: 24px;
    }}
    .card p {{
      color: var(--text-dim);
      font-size: 0.93rem;
      line-height: 1.75;
    }}

    /* ── Stat grid ──────────────────────────────────────────────────── */
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(148px, 1fr));
      gap: 14px;
      margin-bottom: 28px;
    }}
    .stat-card {{
      background: var(--bg2);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 22px 18px 18px;
      text-align: center;
      position: relative;
      transition: border-color 0.2s, transform 0.2s;
    }}
    .stat-card:hover {{
      border-color: rgba(240,165,0,0.3);
      transform: translateY(-2px);
    }}
    .stat-card::after {{
      content: '';
      position: absolute;
      inset: 0;
      border-radius: 12px;
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.04);
      pointer-events: none;
    }}
    .stat-card .label {{
      font-family: var(--mono);
      font-size: 0.68rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.10em;
      margin-bottom: 10px;
    }}
    .stat-card .value {{
      font-family: var(--mono);
      font-size: 1.9rem;
      font-weight: 700;
      color: var(--amber);
      line-height: 1;
      margin-bottom: 6px;
    }}
    .stat-card .value.neg {{ color: var(--red); }}
    .stat-card .sub {{
      font-size: 0.72rem;
      color: var(--text-muted);
    }}

    /* ── Compare table ──────────────────────────────────────────────── */
    .compare-table {{ width: 100%; border-collapse: collapse; }}
    .compare-table th, .compare-table td {{
      padding: 13px 18px;
      text-align: left;
      border-bottom: 1px solid var(--border);
      font-size: 0.9rem;
    }}
    .compare-table th {{
      font-family: var(--mono);
      font-size: 0.68rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.10em;
      background: var(--bg3);
    }}
    .compare-table th:first-child {{ border-radius: 8px 0 0 8px; }}
    .compare-table th:last-child  {{ border-radius: 0 8px 8px 0; }}
    .compare-table td {{ color: var(--text-dim); }}
    .compare-table td:first-child {{ color: var(--text); }}
    .compare-table .highlight {{
      font-family: var(--mono);
      color: var(--cyan);
      font-weight: 600;
    }}
    .compare-table tbody tr:hover td {{ background: rgba(255,255,255,0.02); }}

    /* ── Chart ──────────────────────────────────────────────────────── */
    .chart-img {{
      width: 100%;
      border-radius: 10px;
      display: block;
      border: 1px solid var(--border);
    }}
    .chart-caption {{
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
      margin-bottom: 18px;
    }}
    .chart-caption span {{
      font-family: var(--mono);
      font-size: 0.75rem;
      color: var(--text-muted);
      background: var(--bg3);
      border: 1px solid var(--border);
      padding: 4px 10px;
      border-radius: 6px;
    }}
    .chart-caption span b {{ color: var(--text-dim); }}

    /* ── Rule boxes ─────────────────────────────────────────────────── */
    .rules-grid {{
      display: grid;
      gap: 14px;
    }}
    .rule-box {{
      border: 1px solid var(--border);
      border-left: 3px solid var(--cyan);
      background: var(--cyan-dim);
      border-radius: 0 10px 10px 0;
      padding: 18px 22px;
    }}
    .rule-box.green  {{ border-left-color: var(--green);  background: var(--green-dim); }}
    .rule-box.orange {{ border-left-color: var(--orange); background: var(--orange-dim); }}
    .rule-box.red    {{ border-left-color: var(--red);    background: var(--red-dim); }}
    .rule-box h3 {{
      font-family: var(--sans);
      font-size: 0.95rem;
      font-weight: 700;
      margin-bottom: 8px;
      color: #fff;
    }}
    .rule-box p  {{ font-size: 0.88rem; color: var(--text-dim); line-height: 1.7; }}
    .rule-box strong {{ color: var(--text); }}
    .rule-box em {{ color: var(--text-muted); font-style: italic; }}

    /* ── Quarter table ──────────────────────────────────────────────── */
    .q-table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
    .q-table th, .q-table td {{
      padding: 9px 14px;
      text-align: right;
      border-bottom: 1px solid rgba(255,255,255,0.04);
    }}
    .q-table th {{
      font-family: var(--mono);
      font-size: 0.66rem;
      background: var(--bg3);
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      text-align: right;
    }}
    .q-table td {{ font-family: var(--mono); color: var(--text-dim); }}
    .q-table td:first-child, .q-table th:first-child {{ text-align: left; }}
    .q-table tbody tr:hover td {{ background: rgba(255,255,255,0.025); }}
    .q-table .pos {{ color: var(--green); }}
    .q-table .neg {{ color: var(--red); }}

    /* ── Badges ─────────────────────────────────────────────────────── */
    .badge {{
      display: inline-block;
      padding: 3px 10px;
      border-radius: 20px;
      font-family: var(--mono);
      font-size: 0.68rem;
      font-weight: 600;
      letter-spacing: 0.04em;
    }}
    .badge-buy    {{ background: rgba(34,208,122,0.15); color: #22d07a; border: 1px solid rgba(34,208,122,0.25); }}
    .badge-sell   {{ background: rgba(255,77,90,0.15);  color: #ff4d5a; border: 1px solid rgba(255,77,90,0.25); }}
    .badge-100up  {{ background: rgba(240,165,0,0.15);  color: var(--amber); border: 1px solid rgba(240,165,0,0.25); }}
    .badge-reset  {{ background: rgba(0,200,255,0.12);  color: var(--cyan);  border: 1px solid rgba(0,200,255,0.2); }}
    .badge-ignore {{ background: rgba(255,140,66,0.13); color: var(--orange);border: 1px solid rgba(255,140,66,0.22); }}
    .badge-init   {{ background: rgba(255,255,255,0.06);color: var(--text-dim);border: 1px solid var(--border); }}

    /* ── Risk list ──────────────────────────────────────────────────── */
    .risk-list {{
      list-style: none;
      display: grid;
      gap: 10px;
    }}
    .risk-list li {{
      display: flex;
      gap: 12px;
      font-size: 0.88rem;
      color: var(--text-dim);
      line-height: 1.6;
    }}
    .risk-list li::before {{
      content: '⚠';
      font-size: 0.8rem;
      color: var(--orange);
      flex-shrink: 0;
      margin-top: 2px;
    }}
    .risk-list strong {{ color: var(--text); }}

    /* ── Disclaimer ─────────────────────────────────────────────────── */
    .disclaimer {{
      border: 1px solid rgba(240,165,0,0.2);
      background: rgba(240,165,0,0.05);
      border-radius: 10px;
      padding: 16px 20px;
      font-size: 0.82rem;
      color: var(--text-muted);
      margin-top: 32px;
      line-height: 1.7;
    }}
    .disclaimer strong {{ color: var(--amber); }}

    /* ── Footer ─────────────────────────────────────────────────────── */
    footer {{
      text-align: center;
      color: var(--text-muted);
      font-family: var(--mono);
      font-size: 0.72rem;
      margin-top: 48px;
      letter-spacing: 0.05em;
    }}
    footer span {{ color: var(--border); margin: 0 8px; }}

    /* ── Divider ────────────────────────────────────────────────────── */
    .divider {{
      border: none;
      border-top: 1px solid var(--border);
      margin: 8px 0 28px;
    }}

    /* ── Scrollable table wrapper ───────────────────────────────────── */
    .table-scroll {{ overflow-x: auto; }}

    @media (max-width: 600px) {{
      .header {{ padding: 32px 24px 28px; }}
      .header h1 {{ font-size: 2.2rem; }}
      .card {{ padding: 20px; }}
    }}
  </style>
</head>
<body>
<div class="page">

  <!-- Header -->
  <div class="header fade-up d1">
    <div class="header-tag">Backtest Report &nbsp;·&nbsp; TQQQ</div>
    <h1><span>9sig</span> Strategy</h1>
    <div class="subtitle">Rules-based quarterly investing — historical simulation</div>
    <div class="meta-row">
      <div class="meta-pill">Period: <strong>{start_dt.strftime('%b %Y')} → {end_dt.strftime('%b %Y')}</strong></div>
      <div class="meta-pill">Capital: <strong>${starting:,.0f}</strong></div>
      <div class="meta-pill">Generated: <strong>{generated_on}</strong></div>
    </div>
  </div>

  <!-- What is this? -->
  <div class="card fade-up d2">
    <div class="section-label">Overview</div>
    <h2>What is the 9sig Strategy?</h2>
    <p>
      The 9sig strategy is a <strong style="color:var(--text)">rules-based quarterly investing system</strong> designed for
      <strong style="color:var(--cyan)">TQQQ</strong> — a fund that moves <em>3× the daily return</em> of the NASDAQ-100 index
      (think Apple, Microsoft, Nvidia, Amazon, etc.).<br><br>
      Instead of trying to time the market, 9sig removes emotion entirely: you follow a simple set of
      rules once per quarter and let the math do the work.
      You start with <strong style="color:var(--text)">60% in TQQQ and 40% in cash</strong>, then rebalance every 3 months
      using a <strong style="color:var(--amber)">9% quarterly growth target</strong>.
    </p>
  </div>

  <!-- Key results -->
  <div class="fade-up d3">
    <div class="section-label">Performance</div>
    <h2>Backtest Results at a Glance</h2>
  </div>
  <div class="stats-grid fade-up d3">
    <div class="stat-card">
      <div class="label">Starting Capital</div>
      <div class="value">${starting:,.0f}</div>
      <div class="sub">{start_dt.strftime('%b %Y')}</div>
    </div>
    <div class="stat-card">
      <div class="label">Final Value</div>
      <div class="value">${final:,.0f}</div>
      <div class="sub">{end_dt.strftime('%b %Y')}</div>
    </div>
    <div class="stat-card">
      <div class="label">Total Return</div>
      <div class="value">{total_ret:.0f}%</div>
      <div class="sub">over {years:.1f} years</div>
    </div>
    <div class="stat-card">
      <div class="label">CAGR</div>
      <div class="value">{cagr:.1f}%</div>
      <div class="sub">per year on average</div>
    </div>
    <div class="stat-card">
      <div class="label">Worst Drawdown</div>
      <div class="value neg">{max_dd:.0f}%</div>
      <div class="sub">peak to trough</div>
    </div>
    <div class="stat-card">
      <div class="label">Sharpe Ratio</div>
      <div class="value">{sharpe:.2f}</div>
      <div class="sub">risk-adjusted return</div>
    </div>
  </div>

  <!-- Comparison table -->
  <div class="card fade-up d4">
    <div class="section-label">Comparison</div>
    <h2>9sig vs Buy &amp; Hold TQQQ</h2>
    <p style="margin-bottom:20px;">"Buy &amp; Hold" means investing all ${starting:,.0f} in TQQQ on day one and never touching it.</p>
    <table class="compare-table">
      <thead>
        <tr>
          <th>Metric</th>
          <th>9sig Strategy</th>
          <th>Buy &amp; Hold TQQQ</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Final Value</td>
          <td class="highlight">${final:,.0f}</td>
          <td>${bah_final:,.0f}</td>
        </tr>
        <tr>
          <td>Total Return</td>
          <td class="highlight">{total_ret:.0f}%</td>
          <td>{bah_ret:.0f}%</td>
        </tr>
        <tr>
          <td>Annual Growth (CAGR)</td>
          <td class="highlight">{cagr:.1f}%</td>
          <td>{bah_cagr:.1f}%</td>
        </tr>
        <tr>
          <td>Worst Drawdown</td>
          <td class="highlight">{max_dd:.0f}%</td>
          <td>~80%+ (2022 crash)</td>
        </tr>
        <tr>
          <td>Active management required?</td>
          <td class="highlight">Once per quarter</td>
          <td>Never</td>
        </tr>
      </tbody>
    </table>
  </div>

  <!-- Charts -->
  <div class="card fade-up d4">
    <div class="section-label">Charts</div>
    <h2>Performance Over Time</h2>
    <div class="chart-caption">
      <span><b>Top:</b> Portfolio value vs buy &amp; hold</span>
      <span><b>Middle:</b> TQQQ vs cash split per quarter</span>
      <span><b>Bottom:</b> Peak-to-trough drawdown</span>
    </div>
    <img class="chart-img" src="data:image/png;base64,{chart_b64}" alt="Performance Charts"/>
  </div>

  <!-- How the rules work -->
  <div class="card fade-up d5">
    <div class="section-label">Rules</div>
    <h2>How the Rules Work</h2>
    <p style="margin-bottom:20px;">Once per quarter you take exactly one action — nothing in between.</p>
    <div class="rules-grid">
      <div class="rule-box green">
        <h3>Every Quarter — The 9% Target Rule</h3>
        <p>
          At the end of each quarter, check how much your TQQQ position has grown or shrunk:<br><br>
          <strong>TQQQ grew more than 9%?</strong> → Sell some TQQQ and move the extra gains to cash.<br>
          <strong>TQQQ grew less than 9%?</strong> → Use cash to buy more TQQQ to reach 9% growth.<br>
          <strong>TQQQ went negative?</strong> → Still buy more TQQQ to reach the 9% target from last quarter.
        </p>
      </div>
      <div class="rule-box red">
        <h3>Special Rule 1 — "30 Down" (Crash Protection)</h3>
        <p>
          <strong>When it triggers:</strong> TQQQ's price drops 30% or more below its highest price
          in the last 2 years.<br><br>
          <strong>What changes:</strong> Don't sell TQQQ even if it grows more than 9% — let it recover.
          Still buy if it's below target. After skipping 2 sell signals, reset the whole portfolio
          back to 60/40.<br><br>
          <em>This rule prevented panic selling during the 2022 crash and kept you fully invested
          for the 2023 recovery.</em>
        </p>
      </div>
      <div class="rule-box orange">
        <h3>Special Rule 2 — "100 Up" (Profit Lock-In)</h3>
        <p>
          <strong>When it triggers:</strong> TQQQ gains 100% or more in a single quarter.<br><br>
          <strong>What happens:</strong> Immediately reset the entire portfolio back to 60/40.<br><br>
          <em>This triggered in Q2 2020 when TQQQ jumped 105% in one quarter after the COVID crash.</em>
        </p>
      </div>
    </div>
  </div>

  <!-- Quarterly table -->
  <div class="card fade-up d6">
    <div class="section-label">History</div>
    <h2>Quarter-by-Quarter Results</h2>
    <div class="table-scroll">
      <table class="q-table">
        <thead>
          <tr>
            <th>Quarter</th>
            <th>TQQQ Price</th>
            <th>Q Growth</th>
            <th>TQQQ Value</th>
            <th>Cash</th>
            <th>Total</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {quarter_rows}
        </tbody>
      </table>
    </div>
  </div>

  <!-- Important risks -->
  <div class="card fade-up d7">
    <div class="section-label">Risk</div>
    <h2>Important Risks to Understand</h2>
    <ul class="risk-list">
      <li><strong>TQQQ is 3× leveraged</strong> — it moves 3 times more than the NASDAQ each day, up <em>and</em> down.</li>
      <li><strong>Volatility decay:</strong> Over time, daily rebalancing in leveraged ETFs can erode returns in sideways markets.</li>
      <li><strong>The 2022 crash shows the real risk:</strong> The portfolio fell over 60% from peak to trough and cash ran out — there was nothing left to buy the dip with.</li>
      <li><strong>Past performance does not guarantee future results.</strong> This is a backtest — real results will differ.</li>
      <li><strong>Tax considerations:</strong> Frequent quarterly rebalancing may trigger capital gains taxes depending on your country/account type.</li>
    </ul>
  </div>

  <div class="disclaimer fade-up d7">
    <strong>Disclaimer:</strong> This report is for educational and informational purposes only.
    It is not financial advice. The results shown are from a historical backtest and do not
    guarantee future performance. Investing in leveraged ETFs involves significant risk,
    including the potential loss of your entire investment. Always consult a qualified financial
    advisor before making investment decisions.
  </div>

  <footer class="fade-up d7">
    9sig Strategy Backtest
    <span>·</span>
    Generated {generated_on}
    <span>·</span>
    TQQQ data {start_dt.strftime('%b %Y')} – {end_dt.strftime('%b %Y')}
  </footer>

</div>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    config      = load_config(config_path)

    results_file = config.get("output_file", "results.csv")
    if not Path(results_file).exists():
        print(f"Results file '{results_file}' not found. Run simulate.py first.")
        sys.exit(1)

    results = pd.read_csv(results_file, parse_dates=["quarter"])

    html = build_html(results, config)

    report_path = Path("index.html")
    with open(report_path, "w") as f:
        f.write(html)

    print(f"Report saved to: {report_path}")
    print("Open it in any web browser to view or share.")


if __name__ == "__main__":
    main()
