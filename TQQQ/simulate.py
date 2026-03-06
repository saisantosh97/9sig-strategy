"""
9sig Strategy Simulation
Usage: python simulate.py [config.yaml]
"""

import sys
import yaml
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")  # non-interactive backend; set before importing pyplot
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from pathlib import Path


# ---------------------------------------------------------------------------
# Config & Data
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_quarterly_closes(config: dict) -> pd.Series:
    df = pd.read_csv(config["data_file"])
    df.columns = df.columns.str.lower()
    df["date"] = pd.to_datetime(df["date"], format="mixed", dayfirst=False)
    df = df.sort_values("date").reset_index(drop=True)
    df = df.set_index("date")["close"]

    start = config.get("start_date")
    end = config.get("end_date")
    if start:
        df = df[df.index >= pd.Timestamp(start)]
    if end:
        df = df[df.index <= pd.Timestamp(end)]

    # Last close of each calendar quarter ("Q" works on pandas < 2.2, "QE" on >= 2.2)
    try:
        return df.resample("QE").last().dropna()
    except ValueError:
        return df.resample("Q").last().dropna()


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def run_simulation(config: dict) -> pd.DataFrame:
    quarterly = load_quarterly_closes(config)

    if len(quarterly) < 2:
        raise ValueError("Need at least 2 quarters of data.")

    starting_capital        = config["starting_capital"]
    initial_etf_alloc       = config["initial_etf_allocation"]
    q_target                = config["quarterly_growth_target"]
    thirty_down_thresh      = config["thirty_down_threshold"]
    lookback_q              = config["thirty_down_lookback_quarters"]
    ignore_count            = config["thirty_down_ignore_signals"]
    hundred_up_thresh       = config["hundred_up_threshold"]

    # ---- initial state ----
    init_price  = quarterly.iloc[0]
    etf_value   = starting_capital * initial_etf_alloc
    cash        = starting_capital * (1 - initial_etf_alloc)
    shares      = etf_value / init_price

    # 30-Down state
    thirty_down_active      = False
    sell_signals_ignored    = 0

    records = [{
        "quarter":                  quarterly.index[0],
        "price":                    init_price,
        "shares":                   shares,
        "etf_value":                etf_value,
        "cash":                     cash,
        "total":                    etf_value + cash,
        "quarterly_growth_pct":     None,
        "action":                   "INIT",
        "trade_amount":             0.0,
        "thirty_down_active":       False,
        "thirty_down_triggered":    False,
        "hundred_up_triggered":     False,
    }]

    for i in range(1, len(quarterly)):
        current_price   = quarterly.iloc[i]
        current_date    = quarterly.index[i]
        prev_price      = quarterly.iloc[i - 1]

        prev_etf_value      = shares * prev_price
        current_etf_value   = shares * current_price
        quarterly_growth    = (current_price - prev_price) / prev_price
        target_etf_value    = prev_etf_value * (1 + q_target)
        total_portfolio     = current_etf_value + cash

        # ---- 30-Down trigger check ----
        lookback_prices         = quarterly.iloc[max(0, i - lookback_q):i]
        highest_in_lookback     = lookback_prices.max()
        thirty_down_level       = highest_in_lookback * (1 - thirty_down_thresh)
        thirty_down_triggered   = current_price <= thirty_down_level

        # ---- 100-Up trigger check ----
        hundred_up_triggered = quarterly_growth >= hundred_up_thresh

        action       = "HOLD"
        trade_amount = 0.0

        # ----------------------------------------------------------------
        # Decision logic
        # ----------------------------------------------------------------
        if hundred_up_triggered:
            # Immediately rebalance to original 60/40
            target_etf   = total_portfolio * initial_etf_alloc
            trade_amount = target_etf - current_etf_value
            shares       = target_etf / current_price
            cash         = total_portfolio - target_etf
            action       = "100UP_REBALANCE"
            thirty_down_active   = False
            sell_signals_ignored = 0

        elif thirty_down_triggered and not thirty_down_active:
            # Activate 30-Down rule
            thirty_down_active   = True
            sell_signals_ignored = 0
            if current_etf_value < target_etf_value:
                buy_amount   = min(target_etf_value - current_etf_value, cash)
                shares       = (current_etf_value + buy_amount) / current_price
                cash        -= buy_amount
                trade_amount = buy_amount
                action       = "30DOWN_BUY"
            else:
                action = "30DOWN_TRIGGERED"

        elif thirty_down_active:
            if current_etf_value >= target_etf_value:
                # Sell signal – ignore it
                sell_signals_ignored += 1
                action       = f"30DOWN_IGNORE_SELL_{sell_signals_ignored}"
                trade_amount = 0.0
                if sell_signals_ignored >= ignore_count:
                    # Rebalance to 60/40 and reset
                    target_etf   = total_portfolio * initial_etf_alloc
                    trade_amount = target_etf - current_etf_value
                    shares       = target_etf / current_price
                    cash         = total_portfolio - target_etf
                    action       = "30DOWN_RESET_REBALANCE"
                    thirty_down_active   = False
                    sell_signals_ignored = 0
            else:
                # Buy signal still applies
                buy_amount   = min(target_etf_value - current_etf_value, cash)
                shares       = (current_etf_value + buy_amount) / current_price
                cash        -= buy_amount
                trade_amount = buy_amount
                action       = "30DOWN_BUY"

        else:
            # Standard rebalancing
            if current_etf_value > target_etf_value:
                sell_amount  = current_etf_value - target_etf_value
                shares       = target_etf_value / current_price
                cash        += sell_amount
                trade_amount = -sell_amount
                action       = "SELL"
            elif current_etf_value < target_etf_value:
                buy_amount   = min(target_etf_value - current_etf_value, cash)
                shares       = (current_etf_value + buy_amount) / current_price
                cash        -= buy_amount
                trade_amount = buy_amount
                action       = "BUY"

        etf_val_after = shares * current_price

        records.append({
            "quarter":                  current_date,
            "price":                    current_price,
            "shares":                   shares,
            "etf_value":                etf_val_after,
            "cash":                     cash,
            "total":                    etf_val_after + cash,
            "quarterly_growth_pct":     quarterly_growth * 100,
            "action":                   action,
            "trade_amount":             trade_amount,
            "thirty_down_active":       thirty_down_active,
            "thirty_down_triggered":    thirty_down_triggered,
            "hundred_up_triggered":     hundred_up_triggered,
        })

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Performance metrics
# ---------------------------------------------------------------------------

def calc_metrics(results: pd.DataFrame, config: dict) -> dict:
    starting = config["starting_capital"]
    final    = results["total"].iloc[-1]

    total_return_pct = (final - starting) / starting * 100

    start_dt = results["quarter"].iloc[0]
    end_dt   = results["quarter"].iloc[-1]
    years    = (end_dt - start_dt).days / 365.25
    cagr     = ((final / starting) ** (1 / years) - 1) * 100 if years > 0 else 0

    # Quarterly returns for Sharpe
    q_returns = results["total"].pct_change().dropna()
    sharpe    = (q_returns.mean() / q_returns.std() * np.sqrt(4)) if q_returns.std() > 0 else 0

    # Max drawdown
    rolling_max  = results["total"].cummax()
    drawdowns    = (results["total"] - rolling_max) / rolling_max * 100
    max_drawdown = drawdowns.min()

    # Action counts
    action_counts = results["action"].value_counts().to_dict()

    return {
        "start":            start_dt.date(),
        "end":              end_dt.date(),
        "years":            round(years, 1),
        "starting_capital": starting,
        "final_value":      final,
        "total_return_pct": total_return_pct,
        "cagr":             cagr,
        "sharpe":           sharpe,
        "max_drawdown_pct": max_drawdown,
        "quarters":         len(results) - 1,
        "action_counts":    action_counts,
    }


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------

def print_summary(metrics: dict):
    m = metrics
    print(f"\n{'=' * 54}")
    print(f"  9sig Strategy Simulation Results")
    print(f"{'=' * 54}")
    print(f"  Period          {m['start']}  →  {m['end']}  ({m['years']} yrs)")
    print(f"  Starting cap    ${m['starting_capital']:>12,.2f}")
    print(f"  Final value     ${m['final_value']:>12,.2f}")
    print(f"  Total return    {m['total_return_pct']:>11.1f}%")
    print(f"  CAGR            {m['cagr']:>11.2f}%")
    print(f"  Sharpe (ann.)   {m['sharpe']:>11.2f}")
    print(f"  Max drawdown    {m['max_drawdown_pct']:>11.1f}%")
    print(f"  Quarters run    {m['quarters']:>12}")
    print(f"{'=' * 54}")
    print(f"\n  Action breakdown:")
    for action, count in sorted(m["action_counts"].items(), key=lambda x: -x[1]):
        print(f"    {action:<30} {count:>4}")
    print()


def print_quarterly_table(results: pd.DataFrame):
    print(f"\n{'Quarter':<12} {'Price':>9} {'ETF Value':>12} {'Cash':>12} "
          f"{'Total':>12} {'Q Growth':>9} {'Action'}")
    print("-" * 85)
    for _, row in results.iterrows():
        q_str    = str(row["quarter"].date())
        g_str    = f"{row['quarterly_growth_pct']:.1f}%" if pd.notna(row["quarterly_growth_pct"]) else "  -"
        print(f"{q_str:<12} {row['price']:>9.2f} {row['etf_value']:>12,.2f} "
              f"{row['cash']:>12,.2f} {row['total']:>12,.2f} {g_str:>9}  {row['action']}")


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def make_charts(results: pd.DataFrame, metrics: dict, config: dict):
    dates  = results["quarter"]
    totals = results["total"]

    # Buy-and-hold benchmark: $starting_capital worth of TQQQ on day 1
    bah_shares = config["starting_capital"] / results["price"].iloc[0]
    bah_values = bah_shares * results["price"]

    rolling_max  = totals.cummax()
    drawdowns    = (totals - rolling_max) / rolling_max * 100

    fig, axes = plt.subplots(3, 1, figsize=(13, 14),
                             gridspec_kw={"height_ratios": [3, 1.5, 1.5]})
    fig.suptitle("9sig Strategy – TQQQ Backtest", fontsize=15, fontweight="bold", y=0.99)

    # ---- Panel 1: Equity curve ----
    ax1 = axes[0]
    ax1.plot(dates, totals,     label="9sig Portfolio",   linewidth=2,   color="#1f77b4")
    ax1.plot(dates, bah_values, label="Buy & Hold TQQQ",  linewidth=1.5, color="#ff7f0e", alpha=0.75, linestyle="--")

    # Annotate special events
    for _, row in results.iterrows():
        if "30DOWN" in str(row["action"]):
            ax1.axvline(row["quarter"], color="red",   alpha=0.25, linewidth=0.8)
        if "100UP" in str(row["action"]):
            ax1.axvline(row["quarter"], color="green", alpha=0.4,  linewidth=1)

    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax1.set_ylabel("Portfolio Value")
    ax1.legend(loc="upper left")
    ax1.set_title(
        f"Period: {metrics['start']} → {metrics['end']}  |  "
        f"CAGR: {metrics['cagr']:.1f}%  |  "
        f"Max DD: {metrics['max_drawdown_pct']:.1f}%  |  "
        f"Sharpe: {metrics['sharpe']:.2f}",
        fontsize=10
    )
    ax1.grid(True, alpha=0.3)

    # ---- Panel 2: ETF vs Cash allocation ----
    ax2 = axes[1]
    ax2.stackplot(dates, results["etf_value"], results["cash"],
                  labels=["ETF", "Cash"],
                  colors=["#1f77b4", "#aec7e8"], alpha=0.85)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax2.set_ylabel("Allocation")
    ax2.legend(loc="upper left")
    ax2.set_title("ETF vs Cash Allocation")
    ax2.grid(True, alpha=0.3)

    # ---- Panel 3: Drawdown ----
    ax3 = axes[2]
    ax3.fill_between(dates, drawdowns, 0, color="crimson", alpha=0.5, label="Drawdown")
    ax3.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    ax3.set_ylabel("Drawdown")
    ax3.set_title("Portfolio Drawdown")
    ax3.legend(loc="lower left")
    ax3.grid(True, alpha=0.3)

    plt.tight_layout()

    if config.get("save_charts", True):
        chart_path = Path(config.get("output_file", "results.csv")).with_suffix(".png")
        plt.savefig(chart_path, dpi=150, bbox_inches="tight")
        print(f"Chart saved to: {chart_path}")

    if config.get("show_charts", False):
        matplotlib.use("TkAgg")
        plt.show()

    plt.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    config      = load_config(config_path)

    results = run_simulation(config)
    metrics = calc_metrics(results, config)

    print_summary(metrics)

    if config.get("print_quarterly", True):
        print_quarterly_table(results)

    output_file = config.get("output_file", "results.csv")
    results.to_csv(output_file, index=False)
    print(f"\nDetailed results saved to: {output_file}")

    make_charts(results, metrics, config)


if __name__ == "__main__":
    main()
