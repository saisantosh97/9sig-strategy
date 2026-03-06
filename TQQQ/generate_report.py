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
        color = ""
        if pd.notna(row.get("quarterly_growth_pct")):
            color = "color:#16a34a;" if row["quarterly_growth_pct"] >= 0 else "color:#dc2626;"
        quarter_rows += f"""
        <tr>
          <td>{row['quarter'].strftime('%b %Y')}</td>
          <td>${row['price']:.2f}</td>
          <td style="{color}">{g}</td>
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
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #f1f5f9;
      color: #1e293b;
      line-height: 1.6;
    }}
    .page {{ max-width: 960px; margin: 0 auto; padding: 32px 20px 60px; }}

    /* Header */
    .header {{
      background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%);
      color: white;
      border-radius: 16px;
      padding: 40px 40px 32px;
      margin-bottom: 32px;
    }}
    .header h1 {{ font-size: 2rem; font-weight: 800; margin-bottom: 6px; }}
    .header .subtitle {{ font-size: 1.05rem; opacity: 0.85; }}
    .header .meta {{ margin-top: 16px; font-size: 0.88rem; opacity: 0.7; }}

    /* Section titles */
    h2 {{ font-size: 1.35rem; font-weight: 700; margin: 36px 0 14px; color: #0f172a; }}
    h3 {{ font-size: 1.05rem; font-weight: 600; margin: 20px 0 8px; color: #1e293b; }}

    /* Cards */
    .card {{
      background: white;
      border-radius: 12px;
      padding: 24px;
      margin-bottom: 24px;
      box-shadow: 0 1px 4px rgba(0,0,0,0.07);
    }}

    /* Stat grid */
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }}
    .stat-card {{
      background: white;
      border-radius: 12px;
      padding: 20px;
      text-align: center;
      box-shadow: 0 1px 4px rgba(0,0,0,0.07);
    }}
    .stat-card .label {{ font-size: 0.8rem; color: #64748b; text-transform: uppercase;
                         letter-spacing: 0.05em; margin-bottom: 6px; }}
    .stat-card .value {{ font-size: 1.6rem; font-weight: 800; color: #2563eb; }}
    .stat-card .sub   {{ font-size: 0.78rem; color: #94a3b8; margin-top: 4px; }}

    /* Compare table */
    .compare-table {{ width: 100%; border-collapse: collapse; }}
    .compare-table th, .compare-table td {{
      padding: 12px 16px; text-align: left; border-bottom: 1px solid #e2e8f0;
    }}
    .compare-table th {{ font-size: 0.82rem; color: #64748b; text-transform: uppercase;
                         letter-spacing: 0.05em; background: #f8fafc; }}
    .compare-table .highlight {{ color: #2563eb; font-weight: 700; }}

    /* Chart */
    .chart-img {{ width: 100%; border-radius: 10px; display: block; }}

    /* Rules */
    .rule-box {{
      border-left: 4px solid #2563eb;
      background: #eff6ff;
      border-radius: 0 10px 10px 0;
      padding: 16px 20px;
      margin-bottom: 14px;
    }}
    .rule-box.green  {{ border-color: #16a34a; background: #f0fdf4; }}
    .rule-box.orange {{ border-color: #ea580c; background: #fff7ed; }}
    .rule-box.red    {{ border-color: #dc2626; background: #fef2f2; }}
    .rule-box h3     {{ margin: 0 0 6px; font-size: 1rem; }}
    .rule-box p      {{ font-size: 0.9rem; color: #334155; margin: 0; }}

    /* Quarter table */
    .q-table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
    .q-table th, .q-table td {{
      padding: 9px 12px; text-align: right; border-bottom: 1px solid #f1f5f9;
    }}
    .q-table th {{ background: #f8fafc; color: #64748b; font-size: 0.78rem;
                   text-transform: uppercase; letter-spacing: 0.04em; text-align: right; }}
    .q-table td:first-child, .q-table th:first-child {{ text-align: left; }}
    .q-table tr:hover {{ background: #f8fafc; }}

    /* Badges */
    .badge {{
      display: inline-block; padding: 3px 9px; border-radius: 20px;
      font-size: 0.75rem; font-weight: 600;
    }}
    .badge-buy    {{ background: #dcfce7; color: #166534; }}
    .badge-sell   {{ background: #fee2e2; color: #991b1b; }}
    .badge-100up  {{ background: #fef9c3; color: #854d0e; }}
    .badge-reset  {{ background: #ede9fe; color: #5b21b6; }}
    .badge-ignore {{ background: #fff7ed; color: #9a3412; }}
    .badge-init   {{ background: #e2e8f0; color: #475569; }}

    /* Disclaimer */
    .disclaimer {{
      background: #fefce8; border: 1px solid #fde047;
      border-radius: 10px; padding: 16px 20px;
      font-size: 0.82rem; color: #713f12; margin-top: 32px;
    }}

    footer {{ text-align: center; color: #94a3b8; font-size: 0.8rem; margin-top: 40px; }}
  </style>
</head>
<body>
<div class="page">

  <!-- Header -->
  <div class="header">
    <h1>9sig Strategy</h1>
    <div class="subtitle">TQQQ Backtest Report — A Beginner's Guide</div>
    <div class="meta">
      Simulation period: {start_dt.strftime('%B %Y')} → {end_dt.strftime('%B %Y')} &nbsp;|&nbsp;
      Starting capital: ${starting:,.0f} &nbsp;|&nbsp;
      Generated: {generated_on}
    </div>
  </div>

  <!-- What is this? -->
  <div class="card">
    <h2>What is the 9sig Strategy?</h2>
    <p style="color:#475569; font-size:0.95rem;">
      The 9sig strategy is a <strong>rules-based quarterly investing system</strong> designed for
      <strong>TQQQ</strong> — a fund that moves <em>3× the daily return</em> of the NASDAQ-100 index
      (think Apple, Microsoft, Nvidia, Amazon, etc.).<br><br>
      Instead of trying to time the market, 9sig removes emotion entirely: you follow a simple set of
      rules once per quarter and let the math do the work.
      You start with <strong>60% in TQQQ and 40% in cash</strong>, then rebalance every 3 months
      using a <strong>9% quarterly growth target</strong>.
    </p>
  </div>

  <!-- Key results -->
  <h2>Backtest Results at a Glance</h2>
  <div class="stats-grid">
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
      <div class="label">Annual Growth (CAGR)</div>
      <div class="value">{cagr:.1f}%</div>
      <div class="sub">per year on average</div>
    </div>
    <div class="stat-card">
      <div class="label">Worst Drawdown</div>
      <div class="value" style="color:#dc2626;">{max_dd:.0f}%</div>
      <div class="sub">peak to trough</div>
    </div>
    <div class="stat-card">
      <div class="label">Sharpe Ratio</div>
      <div class="value">{sharpe:.2f}</div>
      <div class="sub">risk-adjusted return</div>
    </div>
  </div>

  <!-- Comparison table -->
  <div class="card">
    <h2 style="margin-top:0;">9sig vs Buy & Hold TQQQ</h2>
    <p style="color:#64748b; font-size:0.88rem; margin-bottom:16px;">
      "Buy & Hold" means investing all ${ starting:,.0f} in TQQQ on day one and never touching it.
    </p>
    <table class="compare-table">
      <thead>
        <tr>
          <th>Metric</th>
          <th>9sig Strategy</th>
          <th>Buy & Hold TQQQ</th>
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
          <td>Requires active management?</td>
          <td class="highlight">Once per quarter</td>
          <td>Never</td>
        </tr>
      </tbody>
    </table>
  </div>

  <!-- Charts -->
  <div class="card">
    <h2 style="margin-top:0;">Performance Charts</h2>
    <p style="color:#64748b; font-size:0.88rem; margin-bottom:16px;">
      <strong>Top:</strong> Portfolio value over time vs buying and holding. &nbsp;
      <strong>Middle:</strong> How your money is split between TQQQ and cash each quarter. &nbsp;
      <strong>Bottom:</strong> How far the portfolio fell from its highest point at any time.
    </p>
    <img class="chart-img" src="data:image/png;base64,{chart_b64}" alt="Performance Charts"/>
  </div>

  <!-- How the rules work -->
  <div class="card">
    <h2 style="margin-top:0;">How the Rules Work</h2>
    <p style="color:#475569; font-size:0.9rem; margin-bottom:18px;">
      Once per quarter you do exactly one of the following actions — nothing in between.
    </p>

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

  <!-- Quarterly table -->
  <div class="card">
    <h2 style="margin-top:0;">Quarter-by-Quarter Results</h2>
    <div style="overflow-x:auto;">
      <table class="q-table">
        <thead>
          <tr>
            <th>Quarter</th>
            <th>TQQQ Price</th>
            <th>Q Growth</th>
            <th>TQQQ Value</th>
            <th>Cash</th>
            <th>Total</th>
            <th>Action Taken</th>
          </tr>
        </thead>
        <tbody>
          {quarter_rows}
        </tbody>
      </table>
    </div>
  </div>

  <!-- Important risks -->
  <div class="card">
    <h2 style="margin-top:0;">Important Risks to Understand</h2>
    <ul style="color:#475569; font-size:0.9rem; padding-left:20px; line-height:2;">
      <li><strong>TQQQ is 3× leveraged</strong> — it moves 3 times more than the NASDAQ each day, up <em>and</em> down.</li>
      <li><strong>Volatility decay:</strong> Over time, daily rebalancing in leveraged ETFs can erode returns in sideways markets.</li>
      <li><strong>The 2022 crash shows the real risk:</strong> The portfolio fell over 60% from peak to trough and cash ran out — there was nothing left to buy the dip with.</li>
      <li><strong>Past performance does not guarantee future results.</strong> This is a backtest — real results will differ.</li>
      <li><strong>Tax considerations:</strong> Frequent quarterly rebalancing may trigger capital gains taxes depending on your country/account type.</li>
    </ul>
  </div>

  <div class="disclaimer">
    <strong>Disclaimer:</strong> This report is for educational and informational purposes only.
    It is not financial advice. The results shown are from a historical backtest and do not
    guarantee future performance. Investing in leveraged ETFs involves significant risk,
    including the potential loss of your entire investment. Always consult a qualified financial
    advisor before making investment decisions.
  </div>

  <footer>
    9sig Strategy Backtest &nbsp;|&nbsp; Generated on {generated_on} &nbsp;|&nbsp;
    Data: TQQQ ({start_dt.strftime('%b %Y')} – {end_dt.strftime('%b %Y')})
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
