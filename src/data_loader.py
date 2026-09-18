import os
import glob
import pandas as pd
import numpy as np

SECTOR_TARGET_WEIGHTS = {
    "Financial Services": 0.3700,
    "Oil Gas & Consumable Fuels": 0.0979,
    "Information Technology": 0.0741,
    "Automobile and Auto Components": 0.0674,
    "Fast Moving Consumer Goods": 0.0581,
    "Telecommunication": 0.0515,
    "Healthcare": 0.0490,
    "Metals & Mining": 0.0454,
    "Construction": 0.0444,
    "Consumer Durables": 0.0275,
    "Consumer Services": 0.0275,
    "Power": 0.0273,
    "Services": 0.0233,
    "Construction Materials": 0.0229,
    "Capital Goods": 0.0135
}

class DataLoader:
    # D:\share_live\NIFTY\ no longer exists, and a missing tracker silently
    # disables the point-in-time filter altogether (see load_pit_reshuffle_basket),
    # putting every delisted name back into the universe. Default to the
    # extended copy that lives with the project.
    DEFAULT_RESHUFFLE = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "nifty50_reshuffle_tracker_v2_extended.xlsx")

    def __init__(self, workspace_dir=r"d:\DK_sir", reshuffle_file=None):
        reshuffle_file = reshuffle_file or self.DEFAULT_RESHUFFLE
        self.workspace_dir = workspace_dir
        self.nifty_dir = os.path.join(workspace_dir, "nifty50")
        self.list_csv = os.path.join(workspace_dir, "ind_nifty50list.csv")
        self.index_csv = os.path.join(workspace_dir, "Nifty 50 Historical Data.csv")
        self.reshuffle_file = reshuffle_file
        
        self.stock_list_df = None
        self.index_df = None
        self.prices_df = None
        self.returns_df = None
        self.stock_sector_map = {}
        self.sector_stock_map = {}
        self.pit_basket_dict = {} # Point-In-Time month -> set of 50 constituent stocks
        
    def load_sector_mapping(self):
        """Loads stock-to-industry mapping from ind_nifty50list.csv."""
        self.stock_list_df = pd.read_csv(self.list_csv)
        self.stock_sector_map = dict(zip(self.stock_list_df['Symbol'], self.stock_list_df['Industry']))
        
        self.sector_stock_map = {}
        for symbol, sector in self.stock_sector_map.items():
            if sector not in self.sector_stock_map:
                self.sector_stock_map[sector] = []
            self.sector_stock_map[sector].append(symbol)
            
        return self.stock_sector_map, self.sector_stock_map

    def load_pit_reshuffle_basket(self):
        """
        Loads point-in-time historical Nifty 50 constituents per month from nifty50_reshuffle_tracker_v2.xlsx
        to eliminate Survivorship Bias.
        """
        if os.path.exists(self.reshuffle_file):
            df_basket = pd.read_excel(self.reshuffle_file, sheet_name="Full Basket Per Month")
            month_cols = [c for c in df_basket.columns if c != 'Stock #']
            
            for col in month_cols:
                stocks = df_basket[col].dropna().astype(str).str.strip().tolist()
                self.pit_basket_dict[col] = set(stocks)
                
            print(f"[Survivorship-Bias-Free Engine] Loaded Point-In-Time basket for {len(self.pit_basket_dict)} historical months.")
        else:
            # Not a warning to shrug at: with no basket the engine applies no
            # universe filter at all, so every delisted CSV on disk becomes
            # selectable and the run is survivorship-biased.
            raise FileNotFoundError(
                f"Reshuffle tracker not found at {self.reshuffle_file}. Without it "
                f"the point-in-time filter is silently disabled and the backtest is "
                f"survivorship-biased. Run extend_pit_basket.py, or pass "
                f"reshuffle_file= explicitly.")

        return self.pit_basket_dict

    def load_nifty_index(self):
        """Loads and processes Nifty 50 Index historical prices and daily returns."""
        df = pd.read_csv(self.index_csv)
        df['Date'] = pd.to_datetime(df['Date'], format='%d-%m-%Y', errors='coerce')
        df = df.dropna(subset=['Date']).sort_values('Date').reset_index(drop=True)
        
        df['Price'] = df['Price'].astype(str).str.replace(',', '').astype(float)
        df['Index_Return'] = df['Price'].pct_change()
        
        self.index_df = df
        return df

    def load_stock_prices(self, start_year=2019):
        """Loads daily Close prices for all stock CSVs in nifty50 directory."""
        if not self.stock_sector_map:
            self.load_sector_mapping()
            
        stock_files = glob.glob(os.path.join(self.nifty_dir, "*.csv"))
        stock_dfs = []
        
        for f in stock_files:
            symbol = os.path.basename(f).replace("_1d_max.csv", "")
            df = pd.read_csv(f, usecols=['Date', 'Close'])
            df['Date'] = pd.to_datetime(df['Date'], format='%d-%m-%Y', errors='coerce')
            df = df[df['Date'] >= pd.to_datetime(f"{start_year}-01-01")]
            df = df.dropna(subset=['Date']).sort_values('Date').drop_duplicates(subset=['Date'])
            df[symbol] = df['Close']
            stock_dfs.append(df[['Date', symbol]])
            
        prices = stock_dfs[0]
        for df in stock_dfs[1:]:
            prices = pd.merge(prices, df, on='Date', how='outer')
            
        prices = prices.sort_values('Date').reset_index(drop=True)
        self.prices_df = prices
        
        returns = prices.set_index('Date').pct_change()
        self.returns_df = returns
        
        return prices, returns

    def get_aligned_data(self, start_date="2020-01-01"):
        if self.returns_df is None:
            self.load_stock_prices(start_year=2019)
        if self.index_df is None:
            self.load_nifty_index()
            
        idx_df = self.index_df.set_index('Date')[['Price', 'Index_Return']]
        stk_ret = self.returns_df[self.returns_df.index >= pd.to_datetime(start_date)]
        
        combined = stk_ret.join(idx_df, how='inner')
        return combined
