import os
import pandas as pd
import numpy as np
from src.data_loader import DataLoader
from src.backtest_engine import run_rolling_backtest
from src.elbow_analyzer import sweep_alpha_for_elbow_curve
from src.excel_reporter import generate_excel_report

def main():
    print("=" * 70)
    print("SURVIVORSHIP-BIAS-FREE SPARSE NIFTY 50 LASSO STRATEGY BACKTEST")
    print("=" * 70)
    
    # 1. Load Data with Reshuffle Tracker
    print("\n[1/5] Loading Point-In-Time Dataset & Reshuffle Tracker...")
    # D:\share_live\NIFTY\ is gone; DataLoader now defaults to the extended
    # tracker in the project root (see DataLoader.DEFAULT_RESHUFFLE).
    loader = DataLoader(workspace_dir=r"d:\DK_sir")
    stock_sector_map, sector_stock_map = loader.load_sector_mapping()
    pit_basket_dict = loader.load_pit_reshuffle_basket()
    prices, _ = loader.load_stock_prices(start_year=2019)
    
    aligned_data = loader.get_aligned_data(start_date="2020-01-01")
    
    stock_cols = [c for c in aligned_data.columns if c not in ['Price', 'Index_Return']]
    returns_matrix = aligned_data[stock_cols]
    index_returns = aligned_data['Index_Return']
    
    print(f"Dataset date range: {aligned_data.index.min().date()} to {aligned_data.index.max().date()}")
    print(f"Total trading days: {len(aligned_data)}")
    print(f"Total stocks tracked: {len(stock_cols)}")
    print(f"Historical PIT months loaded: {len(pit_basket_dict)}")
    
    # 2. Run Point-in-Time Rolling Backtest
    print("\n[2/5] Executing Survivorship-Bias-Free Rolling Backtest (alpha=0.001, Monthly Rebalance)...")
    results_df, metrics, rebalance_history = run_rolling_backtest(
        returns_matrix=returns_matrix,
        index_returns=index_returns,
        sector_stock_map=sector_stock_map,
        lookback_days=252,
        rebalance_freq='monthly',
        alpha=0.001,
        pit_basket_dict=pit_basket_dict
    )
    
    # Print Metrics
    print("\n" + "=" * 50)
    print("SURVIVORSHIP-FREE PERFORMANCE METRICS SUMMARY")
    print("=" * 50)
    print(f"Evaluation Period        : {metrics['start_date']} to {metrics['end_date']}")
    print(f"Average Selected Stocks  : {metrics['avg_stock_count']:.1f} / 50 stocks")
    print(f"Annualized Tracking Error: {metrics['tracking_error']*100:.2f}%")
    print(f"Correlation with NIFTY 50: {metrics['correlation']:.4f}")
    print(f"Portfolio CAGR           : {metrics['cagr_portfolio']*100:.2f}%")
    print(f"NIFTY 50 Index CAGR      : {metrics['cagr_index']*100:.2f}%")
    print(f"Portfolio Volatility     : {metrics['volatility_portfolio']*100:.2f}%")
    print(f"NIFTY 50 Volatility      : {metrics['volatility_index']*100:.2f}%")
    print(f"Portfolio Sharpe Ratio   : {metrics['sharpe_portfolio']:.2f}")
    print(f"NIFTY 50 Sharpe Ratio    : {metrics['sharpe_index']:.2f}")
    print("=" * 50)
    
    # 3. Generate Survivorship-Free Detailed Excel Report
    print("\n[3/5] Exporting Multi-Tab Survivorship-Free Detailed Excel Report...")
    excel_path = os.path.join(r"d:\DK_sir", "Sparse_Lasso_Nifty50_Survivorship_Free_Report.xlsx")
    generate_excel_report(
        results_df=results_df,
        metrics=metrics,
        rebalance_history=rebalance_history,
        elbow_df=None,
        stock_sector_map=stock_sector_map,
        returns_matrix=returns_matrix,
        prices_df=prices,
        output_path=excel_path,
        initial_capital=100000.0
    )
    
    print("\nExecution & Excel Export completed successfully!")
    print(f"Excel Report File: {excel_path}")

if __name__ == "__main__":
    main()
