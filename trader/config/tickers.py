"""
Static universe of 15 large-cap Nifty 50 stocks for Phase 1.
Do not make this dynamic — stability matters for paper-trading reproducibility.
"""
from dataclasses import dataclass
from typing import Literal

VolumeCategory = Literal["High", "Medium", "Low"]


@dataclass(frozen=True)
class Ticker:
    symbol: str
    name: str
    sector: str
    volume: VolumeCategory

    @property
    def nse_symbol(self) -> str:
        """NSE symbol as used in jugaad-data / nselib queries."""
        return self.symbol


UNIVERSE: list[Ticker] = [
    Ticker("RELIANCE",   "Reliance Industries",       "Energy",        "High"),
    Ticker("TCS",        "Tata Consultancy Services", "IT",            "High"),
    Ticker("HDFCBANK",   "HDFC Bank",                 "Banking",       "High"),
    Ticker("INFY",       "Infosys",                   "IT",            "High"),
    Ticker("ICICIBANK",  "ICICI Bank",                "Banking",       "High"),
    Ticker("HINDUNILVR", "Hindustan Unilever",         "FMCG",         "High"),
    Ticker("ITC",        "ITC Limited",               "FMCG",         "High"),
    Ticker("LT",         "Larsen & Toubro",           "Capital Goods", "High"),
    Ticker("AXISBANK",   "Axis Bank",                 "Banking",       "High"),
    Ticker("KOTAKBANK",  "Kotak Mahindra Bank",       "Banking",       "High"),
    Ticker("BHARTIARTL", "Bharti Airtel",             "Telecom",       "High"),
    Ticker("MARUTI",     "Maruti Suzuki",             "Auto",          "High"),
    Ticker("BAJFINANCE", "Bajaj Finance",             "NBFC",          "High"),
    Ticker("ASIANPAINT", "Asian Paints",              "Paints",        "Medium"),
    Ticker("ADANIENT",   "Adani Enterprises",         "Conglomerate",  "High"),
]

SYMBOLS: list[str] = [t.symbol for t in UNIVERSE]

TICKER_MAP: dict[str, Ticker] = {t.symbol: t for t in UNIVERSE}


def get_ticker(symbol: str) -> Ticker:
    if symbol not in TICKER_MAP:
        raise ValueError(f"Unknown ticker: {symbol}. Must be one of: {SYMBOLS}")
    return TICKER_MAP[symbol]


def get_tickers_by_sector(sector: str) -> list[Ticker]:
    return [t for t in UNIVERSE if t.sector == sector]
