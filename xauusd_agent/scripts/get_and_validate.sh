#!/usr/bin/env bash
#
# get_and_validate.sh — one command: pull real history from MT5, then run the
# honest verdict (backtest + Monte-Carlo + walk-forward + buy&hold) with the
# trend/regime mode on. This is the *only* step that turns the agent's "≈ -1%
# on a noise-sized sample" into a real, statistically meaningful return number.
#
# Run it ON the machine where MetaTrader 5 is installed (the `download` step
# needs a live MT5 terminal). Defaults pull ~3 years of M15 XAUUSD — enough
# bars for ~100+ out-of-sample trades, which is what the verdict needs to mean
# anything.
#
# Usage:
#   ./get_and_validate.sh                         # defaults below
#   ./get_and_validate.sh -s XAUUSD -t M15 -b 2022-01-01 -e 2025-01-01
#   ./get_and_validate.sh --dxy DX_M15.csv        # also enable the USD macro filter
#   ./get_and_validate.sh --no-regime             # A/B: run without trend mode
#   ./get_and_validate.sh --login 123 --server Broker-Server --password '***'
#
set -euo pipefail

# ---- defaults ----------------------------------------------------------------
SYMBOL="XAUUSD"
TF="M15"
START="2022-01-01"
END="$(date +%F)"          # today
OUT=""                      # derived from symbol/tf if empty
REGIME="--regime"           # trend mode on by default (the whole point)
DXY=""                      # optional US Dollar Index csv -> macro filter
SPLITS="6"                  # more folds: longer history supports more OOS windows
MONTECARLO="2000"
LOGIN=""; PASSWORD=""; SERVER=""

# ---- args --------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--symbol)    SYMBOL="$2"; shift 2 ;;
    -t|--timeframe) TF="$2"; shift 2 ;;
    -b|--start)     START="$2"; shift 2 ;;
    -e|--end)       END="$2"; shift 2 ;;
    -o|--out)       OUT="$2"; shift 2 ;;
    --dxy)          DXY="$2"; shift 2 ;;
    --splits)       SPLITS="$2"; shift 2 ;;
    --montecarlo)   MONTECARLO="$2"; shift 2 ;;
    --no-regime)    REGIME=""; shift ;;
    --login)        LOGIN="$2"; shift 2 ;;
    --password)     PASSWORD="$2"; shift 2 ;;
    --server)       SERVER="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,24p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

[[ -z "$OUT" ]] && OUT="${SYMBOL}_${TF}_${START}_${END}.csv"

# Run module-style from the repo root so `python -m xauusd_agent` resolves.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"
PY="${PYTHON:-python}"

echo "==> 1/2  download  $SYMBOL $TF  $START -> $END  ->  $OUT"
if [[ -f "$OUT" ]]; then
  echo "    $OUT already exists — skipping download (delete it to refetch)."
else
  dl_args=(download --symbol "$SYMBOL" --timeframe "$TF"
           --start "$START" --end "$END" --out "$OUT")
  [[ -n "$LOGIN"    ]] && dl_args+=(--login "$LOGIN")
  [[ -n "$PASSWORD" ]] && dl_args+=(--password "$PASSWORD")
  [[ -n "$SERVER"   ]] && dl_args+=(--server "$SERVER")
  "$PY" -m xauusd_agent "${dl_args[@]}"
fi

[[ -n "$REGIME" ]] && REGIME_LABEL="ON" || REGIME_LABEL="OFF"
echo "==> 2/2  validate  (regime $REGIME_LABEL, splits=$SPLITS, mc=$MONTECARLO)"
val_args=(validate --csv "$OUT" --tf "$TF"
          --splits "$SPLITS" --montecarlo "$MONTECARLO")
[[ -n "$REGIME" ]] && val_args+=($REGIME)
[[ -n "$DXY"    ]] && val_args+=(--dxy-csv "$DXY")
"$PY" -m xauusd_agent "${val_args[@]}"

echo
echo "Done. Read the === VERDICT === line above. If it still says NOT VALIDATED,"
echo "widen the date range (-b earlier) for more out-of-sample trades."
