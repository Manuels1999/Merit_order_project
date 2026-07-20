"""
plots.py
------------------
Genera i grafici dei risultati sui DATI VERI del mercato elettrico
italiano (Nord, 2022-2024). Quattro pannelli pensati per il portfolio.
"""

import sys
sys.path.insert(0, ".")
import numpy as np
import pandas as pd
import statsmodels.api as sm
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from data_loader import load_dataset


def run_regression(df, hac_lags=24):
    df = df.copy()
    res = df["residual_load"]
    df["resid_sq"] = (res - res.mean()) ** 2
    mesi = pd.get_dummies(df.index.month, prefix="m", drop_first=True).astype(float)
    mesi.index = df.index
    X = pd.concat([df[["load_mw", "renewable_mw", "gas_eur_mwh", "resid_sq"]], mesi], axis=1)
    X = sm.add_constant(X)
    y = df["price_eur_mwh"]
    return sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": hac_lags})


def make_plots(df, model, filename="figures/results.png"):
    fig, axes = plt.subplots(2, 2, figsize=(16, 11))
    (ax1, ax2), (ax3, ax4) = axes

    # --- PANEL 1: power vs gas price over time (the 2022 crisis) ---
    daily = df.resample("D").mean(numeric_only=True)
    ax1b = ax1.twinx()
    l1 = ax1.plot(daily.index, daily["price_eur_mwh"], color="#c0392b", lw=1.3,
                  label="North zonal power price")
    l2 = ax1b.plot(daily.index, daily["gas_eur_mwh"], color="#8e44ad", lw=1.3,
                   alpha=0.8, label="TTF gas")
    ax1.set_ylabel("Power price (EUR/MWh)", color="#c0392b")
    ax1b.set_ylabel("TTF gas (EUR/MWh)", color="#8e44ad")
    ax1.set_title("The 2022 energy crisis and normalization\n"
                  "power and gas prices move together", fontweight="bold")
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    lns = l1 + l2
    ax1.legend(lns, [l.get_label() for l in lns], loc="upper right")
    ax1.grid(alpha=0.2)

    # --- PANEL 2: merit-order effect (price vs renewables) ---
    idx = np.random.default_rng(0).choice(len(df), 3000, replace=False)
    sc = ax2.scatter(df["renewable_mw"].iloc[idx], df["price_eur_mwh"].iloc[idx],
                     c=df["gas_eur_mwh"].iloc[idx], cmap="plasma", s=10, alpha=0.5)
    # previsione del modello ceteris paribus
    xline = np.linspace(df["renewable_mw"].min(), df["renewable_mw"].max(), 100)
    X_pred = pd.DataFrame({
        "const": 1.0, "load_mw": df["load_mw"].mean(), "renewable_mw": xline,
        "gas_eur_mwh": df["gas_eur_mwh"].mean(),
        "resid_sq": ((df["residual_load"] - df["residual_load"].mean()) ** 2).mean(),
    })
    for col in model.params.index:
        if col.startswith("m_"):
            X_pred[col] = 1 / 12
    X_pred = X_pred[model.params.index]
    ax2.plot(xline, model.predict(X_pred), color="#2f6f57", lw=3,
             label="model prediction (ceteris paribus)")
    ax2.set_xlabel("PV + wind generation (MW)")
    ax2.set_ylabel("North zonal price (EUR/MWh)")
    ax2.set_title("The merit-order effect on real data\n"
                  "more renewables -> lower prices", fontweight="bold")
    plt.colorbar(sc, ax=ax2).set_label("TTF gas (EUR/MWh)")
    ax2.legend(loc="upper right"); ax2.grid(alpha=0.2)

    # --- PANEL 3: average hourly profile (the solar effect) ---
    prof = df.groupby(df.index.hour)[["price_eur_mwh", "solar_mw"]].mean()
    ax3b = ax3.twinx()
    l3 = ax3.plot(prof.index, prof["price_eur_mwh"], color="#c0392b",
                  lw=2.5, marker="o", ms=4, label="mean price")
    l4 = ax3b.plot(prof.index, prof["solar_mw"], color="#f39c12",
                   lw=2.5, marker="s", ms=4, label="mean solar output")
    ax3.set_xlabel("Hour of day")
    ax3.set_ylabel("Mean price (EUR/MWh)", color="#c0392b")
    ax3b.set_ylabel("Mean solar output (MW)", color="#f39c12")
    ax3.set_title("Average daily profile\n"
                  "the midday solar peak depresses prices", fontweight="bold")
    ax3.set_xticks(range(0, 24, 3))
    lns3 = l3 + l4
    ax3.legend(lns3, [l.get_label() for l in lns3], loc="upper left")
    ax3.grid(alpha=0.2)

    # --- PANEL 4: estimated coefficients with confidence intervals ---
    variabili = {
        "Demand\n(+1 GW)": ("load_mw", 1000),
        "Renewables\n(+1 GW)": ("renewable_mw", 1000),
        "TTF gas\n(+1 EUR/MWh)": ("gas_eur_mwh", 1),
    }
    nomi, valori, errori = [], [], []
    for nome, (var, scala) in variabili.items():
        coef = model.params[var] * scala
        lo, hi = model.conf_int().loc[var]
        nomi.append(nome)
        valori.append(coef)
        errori.append((hi - lo) / 2 * scala)
    colori = ["#3a6ea5" if v > 0 else "#c0392b" for v in valori]
    ax4.barh(nomi, valori, xerr=errori, color=colori, alpha=0.8, capsize=5)
    ax4.axvline(0, color="black", lw=0.8)
    ax4.set_xlabel("Effect on price (EUR/MWh)")
    ax4.set_title("Estimated effects on the power price\n"
                  "(95% confidence intervals, Newey-West)", fontweight="bold")
    ax4.grid(alpha=0.2, axis="x")
    for i, v in enumerate(valori):
        offset = 0.35 if v > 0 else -0.35
        ax4.text(v + offset, i, f"{v:+.1f}",
                 va="center", ha="left" if v > 0 else "right", fontweight="bold")
    ax4.set_xlim(-6, 9)   # margine per le etichette

    plt.tight_layout()
    plt.savefig(filename, dpi=110, bbox_inches="tight")
    print(f"Figure saved to: {filename}")


if __name__ == "__main__":
    df = load_dataset()
    model = run_regression(df)
    make_plots(df, model)
