"""
data_loader.py
--------------
Loads and aligns real Italian electricity market data (2022-2024) into a
single hourly DataFrame.

Sources (files expected in the data/ folder, see README for download links):
  - Fabbisogno{YYYY}.xlsx                Terna Download Center, zonal load, 15-min
  - Generazione_rinnovabili_{YYYY}.xlsx  Terna Download Center, national RES generation, hourly (GWh)
  - PrezzoNord{YYYY}.xlsx                GME, MGP zonal price North, hourly
  - Dutch_TTF_Natural_Gas_Futures_Historical_Data*.csv  Investing.com, daily

Output columns:
  load_mw, solar_mw, wind_mw, renewable_mw, gas_eur_mwh, price_eur_mwh, residual_load
"""

import pandas as pd
import warnings

warnings.filterwarnings("ignore")

YEARS = [2022, 2023, 2024]


def load_load_north(folder: str) -> pd.Series:
    """Zone-North load: 15-min data aggregated to hourly means."""
    dfs = [pd.read_excel(f"{folder}/Fabbisogno{y}.xlsx") for y in YEARS]
    fabb = pd.concat(dfs, ignore_index=True)
    nord = fabb[fabb["Bidding Zone"] == "North"].copy()
    nord["datetime"] = pd.to_datetime(nord["Date"])
    return (nord.set_index("datetime")["Total Load [MW]"]
                .resample("h").mean()
                .rename("load_mw"))


def load_renewables(folder: str) -> pd.DataFrame:
    """National PV + Wind generation. Terna reports GWh; converted to MW
    (numerically equivalent over one hour after x1000)."""
    dfs = [pd.read_excel(f"{folder}/Generazione_rinnovabili_{y}.xlsx") for y in YEARS]
    gen = pd.concat(dfs, ignore_index=True)
    # Terna export files contain a trailing "Applied filters" text row
    gen["datetime"] = pd.to_datetime(gen["Date"], errors="coerce")
    gen = gen.dropna(subset=["datetime", "Energy Source"])
    gen = gen[gen["Energy Source"].isin(["Photovoltaic", "Wind"])]
    wide = gen.pivot_table(index="datetime", columns="Energy Source",
                           values="Renewable Generation", aggfunc="sum") * 1000.0
    wide = wide.rename(columns={"Photovoltaic": "solar_mw", "Wind": "wind_mw"})
    wide["renewable_mw"] = wide["solar_mw"].fillna(0) + wide["wind_mw"].fillna(0)
    return wide[["solar_mw", "wind_mw", "renewable_mw"]]


def load_prices_north(folder: str) -> pd.Series:
    """GME MGP zonal price for North. Handles Italian decimal commas,
    1-24 hour numbering, and DST duplicate hours (averaged)."""
    dfs = [pd.read_excel(f"{folder}/PrezzoNord{y}.xlsx") for y in YEARS]
    pr = pd.concat(dfs, ignore_index=True)
    pr["price_eur_mwh"] = pr["€/MWh"].astype(str).str.replace(",", ".").astype(float)
    pr["datetime"] = (pd.to_datetime(pr["Data"], format="%d/%m/%Y")
                      + pd.to_timedelta(pr["Ora"] - 1, unit="h"))
    return pr.groupby("datetime")["price_eur_mwh"].mean().sort_index()


def load_gas(folder: str) -> pd.Series:
    """Daily TTF front-month settlement from Investing.com CSV exports."""
    import glob
    parts = [pd.read_csv(f) for f in
             sorted(glob.glob(f"{folder}/Dutch_TTF_Natural_Gas_Futures_Historical_Data*.csv"))]
    gas = pd.concat(parts, ignore_index=True)
    gas["date"] = pd.to_datetime(gas["Date"], format="%m/%d/%Y")
    gas = (gas[["date", "Price"]]
           .drop_duplicates(subset="date")
           .sort_values("date")
           .set_index("date"))
    return gas["Price"].rename("gas_eur_mwh")


def load_dataset(folder: str = "data") -> pd.DataFrame:
    """Builds the final hourly dataset by aligning all sources."""
    load = load_load_north(folder)
    fer = load_renewables(folder)
    price = load_prices_north(folder)
    gas_daily = load_gas(folder)

    df = pd.concat([load, fer, price], axis=1)
    # Daily gas propagated to every hour of the day; weekends forward-filled
    df["gas_eur_mwh"] = gas_daily.reindex(df.index.normalize()).values
    df["gas_eur_mwh"] = df["gas_eur_mwh"].ffill()
    df = df.dropna()

    df["residual_load"] = df["load_mw"] - df["renewable_mw"]
    df.index.name = "datetime"
    return df


if __name__ == "__main__":
    df = load_dataset()
    print(f"Dataset: {len(df)} hourly observations, "
          f"{df.index.min().date()} -> {df.index.max().date()}")
    print(df.describe().round(1))


# ===========================================================================
# NATIONAL CONFIGURATION (robustness check)
# Uses PUN national price + Italy-wide load + national generation.
# Fully consistent geographic level (all national), removing the zonal
# asymmetry of the North-zone specification.
# ===========================================================================

def load_load_italy(folder: str) -> pd.Series:
    """National load (Bidding Zone = 'Italy'), 15-min aggregated to hourly."""
    dfs = [pd.read_excel(f"{folder}/Fabbisogno{y}.xlsx") for y in YEARS]
    fabb = pd.concat(dfs, ignore_index=True)
    ita = fabb[fabb["Bidding Zone"] == "Italy"].copy()
    ita["datetime"] = pd.to_datetime(ita["Date"])
    return (ita.set_index("datetime")["Total Load [MW]"]
                .resample("h").mean()
                .rename("load_mw"))


def load_pun(folder: str) -> pd.Series:
    """National single price (PUN), hourly. Same cleaning as zonal price."""
    dfs = [pd.read_excel(f"{folder}/Prezzi{y}.xlsx") for y in YEARS]
    pr = pd.concat(dfs, ignore_index=True)
    pr["price_eur_mwh"] = pr["€/MWh"].astype(str).str.replace(",", ".").astype(float)
    pr["datetime"] = (pd.to_datetime(pr["Data"], format="%d/%m/%Y")
                      + pd.to_timedelta(pr["Ora"] - 1, unit="h"))
    return pr.groupby("datetime")["price_eur_mwh"].mean().sort_index()


def load_dataset_national(folder: str = "data") -> pd.DataFrame:
    """National-level dataset: PUN + Italy load + national generation."""
    load = load_load_italy(folder)
    fer = load_renewables(folder)      # already national
    price = load_pun(folder)
    gas_daily = load_gas(folder)

    df = pd.concat([load, fer, price], axis=1)
    df["gas_eur_mwh"] = gas_daily.reindex(df.index.normalize()).values
    df["gas_eur_mwh"] = df["gas_eur_mwh"].ffill()
    df = df.dropna()
    df["residual_load"] = df["load_mw"] - df["renewable_mw"]
    df.index.name = "datetime"
    return df
