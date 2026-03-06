"""
9sig Quarter-End Decision Calculator
Usage: python calculator.py [config.yaml] [options]
       python calculator.py --help
"""

import argparse
import sys
import yaml
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PortfolioInputs:
    prev_etf_value: float           # ETF position value at START of quarter
    current_etf_value: float        # ETF position value at END of quarter (before trade)
    cash: float                     # Cash balance at end of quarter (before trade)
    thirty_down_active: bool        # Is 30-Down rule currently active?
    sell_signals_ignored: int       # Sell signals already ignored this 30-Down period
    thirty_down_triggered: bool     # Is price <= 30% below 2yr high right now?
    quarterly_growth: float         # (current_price - prev_price) / prev_price
    hundred_up_triggered: bool      # quarterly_growth >= hundred_up_threshold


@dataclass
class QuarterResult:
    action: str
    trade_amount: float             # positive = buy, negative = sell
    etf_value_after: float
    cash_after: float
    total_after: float
    new_thirty_down_active: bool
    new_sell_signals_ignored: int
    target_etf_value: float
    cash_constrained: bool          # True if buy was limited by available cash


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------

def prompt_float(label: str, default: float = 0.0, positive: bool = False) -> float:
    default_str = f"{default:,.2f}"
    while True:
        raw = input(f"  {label} [{default_str}]: ").strip()
        if raw == "":
            return default
        try:
            val = float(raw.replace(",", ""))
            if positive and val <= 0:
                print("    Value must be greater than 0.")
                continue
            return val
        except ValueError:
            print("    Invalid number — please try again.")


def prompt_bool(label: str, default: bool = False) -> bool:
    default_str = "y" if default else "n"
    while True:
        raw = input(f"  {label} (y/n) [{default_str}]: ").strip().lower()
        if raw == "":
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("    Please enter y or n.")


def prompt_int(label: str, default: int = 0, min_val: int = 0) -> int:
    while True:
        raw = input(f"  {label} [{default}]: ").strip()
        if raw == "":
            return default
        try:
            val = int(raw)
            if val < min_val:
                print(f"    Value must be >= {min_val}.")
                continue
            return val
        except ValueError:
            print("    Invalid integer — please try again.")


# ---------------------------------------------------------------------------
# CLI argument parser
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="9sig Quarter-End Decision Calculator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python calculator.py                          # fully interactive
  python calculator.py --prev-etf 10000 --current-etf 9500 --cash 5000 \\
    --no-thirty-down-active --current-price 45 --prev-price 47 --two-yr-high 68
        """,
    )
    p.add_argument("--config", default="config.yaml", help="Path to config.yaml")

    # Portfolio state
    p.add_argument("--prev-etf",     type=float, help="ETF value at start of quarter ($)")
    p.add_argument("--current-etf",  type=float, help="ETF value at end of quarter ($)")
    p.add_argument("--cash",         type=float, help="Cash balance at end of quarter ($)")

    # 30-Down state
    td = p.add_mutually_exclusive_group()
    td.add_argument("--thirty-down-active",    dest="thirty_down_active",
                    action="store_true",  default=None)
    td.add_argument("--no-thirty-down-active", dest="thirty_down_active",
                    action="store_false")
    p.add_argument("--sell-signals-ignored", type=int, help="Sell signals ignored so far (0, 1, …)")

    # Price inputs (method 1)
    p.add_argument("--current-price", type=float, help="Current TQQQ price")
    p.add_argument("--prev-price",    type=float, help="Previous quarter TQQQ price")
    p.add_argument("--two-yr-high",   type=float, help="Highest TQQQ price in last 2 years")

    # Direct override (method 2)
    tri = p.add_mutually_exclusive_group()
    tri.add_argument("--thirty-down-triggered",    dest="thirty_down_triggered",
                     action="store_true",  default=None)
    tri.add_argument("--no-thirty-down-triggered", dest="thirty_down_triggered",
                     action="store_false")
    p.add_argument("--quarterly-growth-pct", type=float,
                   help="Quarterly growth as a percentage (e.g. 15.5 for 15.5%%)")

    return p


# ---------------------------------------------------------------------------
# Input collection
# ---------------------------------------------------------------------------

def get_inputs(config: dict, args: argparse.Namespace) -> PortfolioInputs:
    hundred_up_thresh = config["hundred_up_threshold"]
    thirty_down_thresh = config["thirty_down_threshold"]

    print()
    print("=" * 60)
    print("  9sig Quarter-End Decision Calculator")
    print("=" * 60)

    # ---- Portfolio values ----
    print("\nPortfolio state at START of quarter:")
    prev_etf = args.prev_etf if args.prev_etf is not None else \
        prompt_float("Previous TQQQ position value ($)", positive=True)

    print("\nPortfolio state at END of quarter (before any trade):")
    current_etf = args.current_etf if args.current_etf is not None else \
        prompt_float("Current TQQQ position value ($)", positive=True)
    cash = args.cash if args.cash is not None else \
        prompt_float("Current cash balance ($)")

    # ---- Price / growth method ----
    # Determine if we have enough CLI args to skip the price prompt
    have_method1 = (args.current_price is not None and
                    args.prev_price is not None and
                    args.two_yr_high is not None)
    have_method2 = (args.thirty_down_triggered is not None and
                    args.quarterly_growth_pct is not None)

    if have_method1:
        current_price = args.current_price
        prev_price    = args.prev_price
        two_yr_high   = args.two_yr_high
        quarterly_growth = (current_price - prev_price) / prev_price
        thirty_down_triggered = current_price <= two_yr_high * (1 - thirty_down_thresh)
    elif have_method2:
        quarterly_growth = args.quarterly_growth_pct / 100.0
        thirty_down_triggered = args.thirty_down_triggered
    else:
        print("\nPrice information:")
        print("  How do you want to provide growth/30-Down data?")
        print("  (1) Enter current price + previous price + 2-year high  [recommended]")
        print("  (2) Enter quarterly growth % and 30-Down trigger directly")
        while True:
            choice = input("  Choice [1]: ").strip()
            if choice in ("", "1", "2"):
                break
            print("    Please enter 1 or 2.")
        method = int(choice) if choice in ("1", "2") else 1

        if method == 1:
            current_price = prompt_float("Current TQQQ price ($)", positive=True)
            prev_price    = prompt_float("Previous quarter-end TQQQ price ($)", positive=True)
            two_yr_high   = prompt_float("Highest TQQQ price in last 2 years ($)", positive=True)
            quarterly_growth = (current_price - prev_price) / prev_price
            thirty_down_triggered = current_price <= two_yr_high * (1 - thirty_down_thresh)
            print(f"\n  Computed quarterly growth: {quarterly_growth * 100:+.2f}%")
            print(f"  30-Down level (70% of 2yr high): ${two_yr_high * (1 - thirty_down_thresh):,.2f}")
            print(f"  30-Down triggered: {'YES' if thirty_down_triggered else 'No'}")
        else:
            pct = prompt_float("Quarterly growth % (e.g. 15.5 for +15.5%, -8.0 for -8.0%)")
            quarterly_growth = pct / 100.0
            thirty_down_triggered = prompt_bool(
                f"Is 30-Down triggered? (price <= {thirty_down_thresh*100:.0f}% below 2yr high)",
                default=False,
            )

    hundred_up_triggered = quarterly_growth >= hundred_up_thresh

    # ---- 30-Down state ----
    print("\n30-Down rule state:")
    if args.thirty_down_active is not None:
        thirty_down_active = args.thirty_down_active
    else:
        thirty_down_active = prompt_bool("Is 30-Down rule currently active?", default=False)

    if thirty_down_active:
        if args.sell_signals_ignored is not None:
            sell_signals_ignored = args.sell_signals_ignored
        else:
            sell_signals_ignored = prompt_int(
                "Sell signals already ignored this 30-Down period",
                default=0,
                min_val=0,
            )
    else:
        sell_signals_ignored = 0

    return PortfolioInputs(
        prev_etf_value=prev_etf,
        current_etf_value=current_etf,
        cash=cash,
        thirty_down_active=thirty_down_active,
        sell_signals_ignored=sell_signals_ignored,
        thirty_down_triggered=thirty_down_triggered,
        quarterly_growth=quarterly_growth,
        hundred_up_triggered=hundred_up_triggered,
    )


# ---------------------------------------------------------------------------
# Decision logic  (ported from simulate.py lines 113-176)
# ---------------------------------------------------------------------------

def run_quarter_decision(inputs: PortfolioInputs, config: dict) -> QuarterResult:
    q_target       = config["quarterly_growth_target"]
    ignore_count   = config["thirty_down_ignore_signals"]
    initial_alloc  = config["initial_etf_allocation"]

    cur  = inputs.current_etf_value
    cash = inputs.cash
    total = cur + cash

    target_etf_value = inputs.prev_etf_value * (1 + q_target)

    action               = "HOLD"
    trade_amount         = 0.0
    etf_after            = cur
    cash_after           = cash
    new_thirty_down      = inputs.thirty_down_active
    new_ignored          = inputs.sell_signals_ignored
    cash_constrained     = False

    if inputs.hundred_up_triggered:
        # Rebalance to original 60/40
        target_etf = total * initial_alloc
        trade_amount = target_etf - cur          # positive = buy, negative = sell
        etf_after    = target_etf
        cash_after   = total - target_etf
        action       = "100UP_REBALANCE"
        new_thirty_down = False
        new_ignored     = 0

    elif inputs.thirty_down_triggered and not inputs.thirty_down_active:
        # First activation of 30-Down
        new_thirty_down = True
        new_ignored     = 0
        if cur < target_etf_value:
            buy = min(target_etf_value - cur, cash)
            cash_constrained = buy < (target_etf_value - cur)
            trade_amount = buy
            etf_after    = cur + buy
            cash_after   = cash - buy
            action       = "30DOWN_BUY"
        else:
            action = "30DOWN_TRIGGERED"

    elif inputs.thirty_down_active:
        if cur >= target_etf_value:
            # Sell signal — ignore it
            new_ignored = inputs.sell_signals_ignored + 1
            if new_ignored >= ignore_count:
                # Limit reached — rebalance and exit 30-Down
                target_etf   = total * initial_alloc
                trade_amount = target_etf - cur
                etf_after    = target_etf
                cash_after   = total - target_etf
                action       = "30DOWN_RESET_REBALANCE"
                new_thirty_down = False
                new_ignored     = 0
            else:
                action       = f"30DOWN_IGNORE_SELL_{new_ignored}"
                trade_amount = 0.0
        else:
            # Buy signal still active
            buy = min(target_etf_value - cur, cash)
            cash_constrained = buy < (target_etf_value - cur)
            trade_amount = buy
            etf_after    = cur + buy
            cash_after   = cash - buy
            action       = "30DOWN_BUY"

    else:
        # Standard rebalancing
        if cur > target_etf_value:
            sell         = cur - target_etf_value
            trade_amount = -sell
            etf_after    = target_etf_value
            cash_after   = cash + sell
            action       = "SELL"
        elif cur < target_etf_value:
            buy = min(target_etf_value - cur, cash)
            cash_constrained = buy < (target_etf_value - cur)
            trade_amount = buy
            etf_after    = cur + buy
            cash_after   = cash - buy
            action       = "BUY"
        # else HOLD — defaults already set

    return QuarterResult(
        action=action,
        trade_amount=trade_amount,
        etf_value_after=etf_after,
        cash_after=cash_after,
        total_after=etf_after + cash_after,
        new_thirty_down_active=new_thirty_down,
        new_sell_signals_ignored=new_ignored,
        target_etf_value=target_etf_value,
        cash_constrained=cash_constrained,
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

ACTION_EXPLANATIONS = {
    "BUY":                      "ETF is below the 9% growth target — buy the shortfall.",
    "SELL":                     "ETF has exceeded the 9% growth target — sell the surplus.",
    "HOLD":                     "ETF is exactly at target — no trade needed.",
    "100UP_REBALANCE":          "TQQQ gained 100%+ this quarter — immediately rebalance to original allocation.",
    "30DOWN_BUY":               "30-Down rule active — ETF is below target, buy the shortfall.",
    "30DOWN_TRIGGERED":         "30-Down rule just triggered — ETF is already at or above target, no buy.",
    "30DOWN_RESET_REBALANCE":   "30-Down rule: sell-signal ignore limit reached — rebalance and reset.",
}


def _explain(action: str) -> str:
    if action in ACTION_EXPLANATIONS:
        return ACTION_EXPLANATIONS[action]
    if action.startswith("30DOWN_IGNORE_SELL_"):
        n = action.split("_")[-1]
        return f"30-Down active — ETF above target (sell signal #{n} ignored)."
    return ""


def _trade_label(trade_amount: float) -> str:
    if trade_amount > 0:
        return f"+${trade_amount:,.2f}  (buy TQQQ)"
    if trade_amount < 0:
        return f"-${abs(trade_amount):,.2f}  (sell TQQQ)"
    return "$0.00  (no trade)"


def print_result(inputs: PortfolioInputs, result: QuarterResult, config: dict) -> None:
    r   = result
    pct = inputs.quarterly_growth * 100
    alloc_pct = r.etf_value_after / r.total_after * 100 if r.total_after > 0 else 0.0

    print()
    print("=" * 60)
    print("  9sig Quarter-End Decision")
    print("=" * 60)
    print(f"  Quarterly growth      {pct:>+10.2f}%")
    print(f"  Target ETF value      ${r.target_etf_value:>12,.2f}")
    print(f"  Current ETF value     ${inputs.current_etf_value:>12,.2f}")
    gap = r.target_etf_value - inputs.current_etf_value
    gap_str = f"+${gap:,.2f}" if gap >= 0 else f"-${abs(gap):,.2f}"
    print(f"  Gap to target         {gap_str:>14}")
    print()
    print(f"  ACTION: {r.action}")
    explanation = _explain(r.action)
    if explanation:
        print(f"  {explanation}")
    print(f"  Trade amount          {_trade_label(r.trade_amount):>30}")
    print()
    print("-" * 60)
    print("  Portfolio AFTER trade:")
    print(f"    ETF value           ${r.etf_value_after:>12,.2f}")
    print(f"    Cash                ${r.cash_after:>12,.2f}")
    print(f"    Total               ${r.total_after:>12,.2f}")
    print(f"    ETF allocation      {alloc_pct:>11.1f}%")
    print()
    print("  Strategy state AFTER:")
    print(f"    30-Down active      {'Yes' if r.new_thirty_down_active else 'No':>14}")
    print(f"    Sell signals ignored{r.new_sell_signals_ignored:>14}")
    print("=" * 60)

    if r.cash_constrained:
        shortfall = r.target_etf_value - inputs.current_etf_value - r.trade_amount
        print(f"\n  Note: Cash was insufficient to fully reach target.")
        print(f"        Bought ${r.trade_amount:,.2f} (all available cash).")
        print(f"        Remaining gap: ${shortfall:,.2f}")

    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = build_arg_parser()
    args   = parser.parse_args()

    config_path = args.config
    try:
        config = load_config(config_path)
    except FileNotFoundError:
        print(f"Error: config file not found: {config_path}")
        print("Run from the TQQQ directory or pass --config path/to/config.yaml")
        sys.exit(1)

    inputs = get_inputs(config, args)
    result = run_quarter_decision(inputs, config)
    print_result(inputs, result, config)


if __name__ == "__main__":
    main()
