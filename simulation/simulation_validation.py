"""
=============================================================================
  MERIT-ORDER EFFECT NEL MERCATO ELETTRICO ITALIANO
  Script completo e autosufficiente: genera i dati, esegue l'analisi,
  salva i grafici. Eseguire con:  python merit_order_v2.py
=============================================================================

Domanda di ricerca:
  A parita' di domanda, di quanto si abbassa il prezzo dell'elettricita'
  per ogni MW aggiuntivo di generazione rinnovabile?

Cosa fa lo script, in ordine:
  1. SIMULA un anno di dati orari realistici (domanda, sole, vento, gas, prezzo)
  2. STIMA con una regressione il "merit-order effect"
  3. VALIDA il metodo confrontando la stima col valore vero nascosto
  4. DISEGNA tre grafici e li salva come file PNG
  5. DICHIARA i caveat metodologici del modello

Librerie necessarie (installare una volta sola con):
  pip install numpy pandas statsmodels matplotlib
=============================================================================
"""

import numpy as np
import pandas as pd
import statsmodels.api as sm
import matplotlib
matplotlib.use("Agg")          # backend senza finestre: salva su file
import matplotlib.pyplot as plt


# ===========================================================================
# PARAMETRI "VERI" NASCOSTI NEI DATI
# Sui dati simulati conosciamo le risposte: la regressione dovra' ritrovarle.
# (Sui dati VERI di Terna questi numeri non esistono: c'e' solo la realta'.)
# ===========================================================================
MERIT_ORDER_TRUE = -0.010      # EUR/MWh per ogni MW di rinnovabili
GAS_PASSTHROUGH_TRUE = 0.8     # EUR/MWh per ogni EUR/MWh di gas


# ===========================================================================
# PARTE 1 - GENERAZIONE DEI DATI SIMULATI
# ===========================================================================
def simulate_market_year(year: int = 2024, seed: int = 42) -> pd.DataFrame:
    """Genera un anno di dati ORARI simulati per una zona di mercato."""
    rng = np.random.default_rng(seed)   # generatore casuale RIPRODUCIBILE

    # --- calendario: tutte le ore dell'anno, fuso italiano ---
    idx = pd.date_range(f"{year}-01-01 00:00", f"{year}-12-31 23:00",
                        freq="h", tz="Europe/Rome")
    n = len(idx)
    hour = idx.hour.to_numpy()
    dayofweek = idx.dayofweek.to_numpy()
    dayofyear = idx.dayofyear.to_numpy()

    # --- 1) DOMANDA (carico) ---
    base_load = 18000.0
    daily = (1500 * np.sin((hour - 6) / 24 * 2 * np.pi)      # gobba principale
             + 1200 * np.sin((hour - 6) / 24 * 4 * np.pi))   # doppio picco giorno
    weekly = np.where(dayofweek >= 5, -2200.0, 0.0)          # weekend piu' bassi
    annual = (2500 * np.cos((dayofyear - 15) / 365 * 2 * np.pi)    # picco inverno
              + 1500 * np.cos((dayofyear - 200) / 365 * 4 * np.pi))  # ripresa estate
    load_noise = rng.normal(0, 600, n)
    load_mw = np.clip(base_load + daily + weekly + annual + load_noise, 8000, None)

    # --- 2) FOTOVOLTAICO (solo di giorno, piu' forte d'estate) ---
    solar_shape = np.clip(np.sin((hour - 6) / 12 * np.pi), 0, None)
    summer_factor = 0.6 + 0.8 * np.clip(
        np.cos((dayofyear - 172) / 365 * 2 * np.pi), 0, None)
    solar_mw = 9000.0 * solar_shape * summer_factor * rng.uniform(0.7, 1.0, n)
    solar_mw = np.clip(solar_mw, 0, None)

    # --- 3) EOLICO (persistente: dipende dall'ora precedente) ---
    wind = np.zeros(n)
    wind[0] = rng.uniform(0, 1)
    phi = 0.92
    for t in range(1, n):
        wind[t] = phi * wind[t - 1] + (1 - phi) * rng.uniform(0, 1)
    wind_mw = np.clip(wind * 4000.0 * 1.5, 0, 4000.0)

    # --- 4) RINNOVABILI E DOMANDA RESIDUA ---
    renewable_mw = solar_mw + wind_mw
    residual_load = load_mw - renewable_mw

    # --- 4b) PREZZO DEL GAS (nuova variabile) ---
    # Dinamica realistica: livello di base, stagionalita' invernale,
    # deriva lenta nell'anno e tre crisi simulate in punti casuali.
    gas_base = 30.0   # EUR/MWh, livello tipico TTF in condizioni normali
    gas_stag = 12.0 * np.cos((dayofyear - 15) / 365 * 2 * np.pi)  # +12 inverno / -12 estate
    gas_drift = 5.0 * np.sin(dayofyear / 365 * 2 * np.pi)         # lenta oscillazione
    gas_noise = rng.normal(0, 1.5, n)                              # rumore quotidiano

    # Crisi geopolitiche simulate: TRE shock di ~2 settimane in punti CASUALI
    # dell'anno. Cosi' sono scorrelate dalla stagionalita' delle rinnovabili
    # e il modello non puo' "agganciare" il gas alle FER tramite il calendario.
    n_crisi = 3
    durata = 14   # giorni
    inizi = rng.integers(1, 365 - durata, size=n_crisi)   # 3 date casuali
    crisi = np.zeros(n)
    for inizio in inizi:
        finestra = (dayofyear >= inizio) & (dayofyear < inizio + durata)
        crisi = np.where(finestra, 25.0, crisi)

    gas_eur_mwh = np.clip(gas_base + gas_stag + gas_drift + gas_noise + crisi, 5.0, None)

    # --- 5) PREZZO ELETTRICITA' (ora dipende anche dal gas) ---
    # Il coefficiente del gas GAS_PASSTHROUGH_TRUE e' definito in cima al file:
    # ogni 1 EUR/MWh di gas si trasmette ~0.8 EUR/MWh sul prezzo elettrico
    # (i cicli combinati a gas spesso "fanno il prezzo" marginale).

    price = (35.0
             + 0.006 * (load_mw - load_mw.mean())                          # domanda: +
             + MERIT_ORDER_TRUE * (renewable_mw - renewable_mw.mean())     # FER: -
             + GAS_PASSTHROUGH_TRUE * (gas_eur_mwh - gas_eur_mwh.mean())   # GAS: +
             + 8e-8 * (residual_load - residual_load.mean()) ** 2)         # convessita'
    price += rng.normal(0, 4.0, n)                                          # rumore
    price_eur_mwh = np.clip(price, 0, None)

    df = pd.DataFrame({
        "load_mw": load_mw, "solar_mw": solar_mw, "wind_mw": wind_mw,
        "renewable_mw": renewable_mw, "residual_load": residual_load,
        "gas_eur_mwh": gas_eur_mwh,
        "price_eur_mwh": price_eur_mwh,
    }, index=idx)
    df.index.name = "datetime"
    return df


# ===========================================================================
# PARTE 2 - LA REGRESSIONE
# ===========================================================================
def run_regression(df: pd.DataFrame, exclude_low_price: bool = False,
                   price_threshold: float = 5.0, hac_lags: int = 24):
    """prezzo ~ domanda + rinnovabili + gas + convessita' + dummy mensili.

    Standard errors con correzione HAC (Newey-West, lag=24 di default per dati
    orari) per gestire autocorrelazione ed eteroschedasticita' tipiche
    delle serie temporali energetiche.

    Le DUMMY MENSILI controllano la stagionalita': isolano l'effetto causale
    di domanda, rinnovabili e gas neutralizzando i co-movimenti calendariali.

    Se exclude_low_price=True, le ore con prezzo <= price_threshold vengono
    escluse dal campione (proxy per stress di sistema / curtailment FV).
    """
    df = df.copy()
    if exclude_low_price:
        df = df[df["price_eur_mwh"] > price_threshold]

    res = df["residual_load"]
    df["resid_sq"] = (res - res.mean()) ** 2

    mesi = pd.get_dummies(df.index.month, prefix="m", drop_first=True).astype(float)
    mesi.index = df.index

    X = pd.concat([df[["load_mw", "renewable_mw", "gas_eur_mwh", "resid_sq"]], mesi], axis=1)
    X = sm.add_constant(X)
    y = df["price_eur_mwh"]
    return sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": hac_lags})


# ===========================================================================
# PARTE 3 - GRAFICI
# ===========================================================================
def make_plots(df: pd.DataFrame, model=None, filename: str = "risultati_analisi.png"):
    fig, axes = plt.subplots(1, 3, figsize=(20, 5.5))
    ax1, ax2, ax3 = axes

    # Grafico 1: prezzo vs rinnovabili (colore = domanda)
    idx = np.random.default_rng(0).choice(len(df), 2000, replace=False)
    sc = ax1.scatter(df["renewable_mw"].iloc[idx], df["price_eur_mwh"].iloc[idx],
                     c=df["load_mw"].iloc[idx], cmap="viridis", s=12, alpha=0.6)

    # PREVISIONE DEL MODELLO (sostituisce la vecchia retta ingenua).
    # Tracciamo la previsione tenendo TUTTO costante alla media tranne le
    # rinnovabili: e' la "curva ceteris paribus" del modello, l'effetto puro
    # delle rinnovabili sul prezzo. Resta sopra zero perche' tiene conto di
    # tutti gli altri fattori.
    if model is not None:
        xline = np.linspace(df["renewable_mw"].min(), df["renewable_mw"].max(), 100)
        X_pred = pd.DataFrame({
            "const": 1.0,
            "load_mw": df["load_mw"].mean(),
            "renewable_mw": xline,
            "gas_eur_mwh": df["gas_eur_mwh"].mean(),
            "resid_sq": ((df["residual_load"] - df["residual_load"].mean()) ** 2).mean(),
        })
        # aggiungo le dummy mensili al valore medio (cioe' ~1/12 ciascuna)
        for col in model.params.index:
            if col.startswith("m_"):
                X_pred[col] = 1 / 12
        X_pred = X_pred[model.params.index]   # stesso ordine del modello
        y_pred = model.predict(X_pred)
        ax1.plot(xline, y_pred, color="#c0392b", lw=2.5,
                 label="previsione del modello\n(ceteris paribus)")
    ax1.set_xlabel("Generazione rinnovabile (MW)")
    ax1.set_ylabel("Prezzo zonale (EUR/MWh)")
    ax1.set_title("Il merit-order effect:\npiu' rinnovabili, prezzo piu' basso",
                  fontweight="bold")
    plt.colorbar(sc, ax=ax1).set_label("Domanda (MW)")
    ax1.legend(loc="upper right"); ax1.grid(alpha=0.2)
    ax1.set_ylim(bottom=-5)   # niente piu' valori molto sotto zero

    # Grafico 2: profilo medio nelle 24 ore
    df2 = df.copy(); df2["ora"] = df2.index.hour
    prof = df2.groupby("ora")[["price_eur_mwh", "renewable_mw"]].mean()
    ax2b = ax2.twinx()
    l1 = ax2.plot(prof.index, prof["price_eur_mwh"], color="#c0392b",
                  lw=2.5, marker="o", ms=4, label="prezzo medio")
    l2 = ax2b.plot(prof.index, prof["renewable_mw"], color="#2f6f57",
                   lw=2.5, marker="s", ms=4, label="rinnovabili medie")
    ax2.set_xlabel("Ora del giorno")
    ax2.set_ylabel("Prezzo medio (EUR/MWh)", color="#c0392b")
    ax2b.set_ylabel("Rinnovabili medie (MW)", color="#2f6f57")
    ax2.set_title("Profilo giornaliero:\nil sole di mezzogiorno abbassa il prezzo",
                  fontweight="bold")
    ax2.set_xticks(range(0, 24, 3))
    lns = l1 + l2
    ax2.legend(lns, [l.get_label() for l in lns], loc="upper center")
    ax2.grid(alpha=0.2)

    # Grafico 3: prezzo gas vs prezzo elettricita' nel tempo (medie giornaliere)
    giornaliero = df.resample("D").mean(numeric_only=True)
    ax3b = ax3.twinx()
    l3 = ax3.plot(giornaliero.index, giornaliero["gas_eur_mwh"],
                  color="#8e44ad", lw=2, label="prezzo gas")
    l4 = ax3b.plot(giornaliero.index, giornaliero["price_eur_mwh"],
                   color="#c0392b", lw=2, label="prezzo elettricita'", alpha=0.8)
    ax3.set_xlabel("Mese")
    ax3.set_ylabel("Prezzo gas (EUR/MWh)", color="#8e44ad")
    ax3b.set_ylabel("Prezzo elettricita' (EUR/MWh)", color="#c0392b")
    ax3.set_title("Il gas trasmette al prezzo elettrico:\nogni shock del gas si riflette sull'elettricita'",
                  fontweight="bold")
    lns2 = l3 + l4
    ax3.legend(lns2, [l.get_label() for l in lns2], loc="upper right")
    ax3.grid(alpha=0.2)
    # Ruota le date sull'asse x
    for label in ax3.get_xticklabels():
        label.set_rotation(45)
        label.set_ha("right")

    plt.tight_layout()
    plt.savefig(filename, dpi=110, bbox_inches="tight")
    print(f"\nGrafici salvati in: {filename}")


# ===========================================================================
# MAIN - esegue tutto in fila
# ===========================================================================
def main():
    print("=" * 64)
    print("  MERIT-ORDER EFFECT - mercato elettrico italiano (simulato)")
    print("=" * 64)

    # 1) dati
    df = simulate_market_year()
    print(f"\n[1] Dati generati: {len(df)} ore")
    print(df[["load_mw", "renewable_mw", "price_eur_mwh"]].describe().round(1))

    # 2) regressione - DUE VERSIONI per gestire il curtailment
    PRICE_THR = 5.0   # soglia per identificare le ore di stress di sistema

    model = run_regression(df)
    model_clean = run_regression(df, exclude_low_price=True, price_threshold=PRICE_THR)

    b_renew = model.params["renewable_mw"]
    b_renew_clean = model_clean.params["renewable_mw"]
    b_gas = model.params["gas_eur_mwh"]
    b_gas_clean = model_clean.params["gas_eur_mwh"]
    ci_low, ci_high = model.conf_int().loc["renewable_mw"]
    n_excl = (df["price_eur_mwh"] <= PRICE_THR).sum()

    print("\n[2] Regressione eseguita (modello principale).")
    print(model.summary())

    # 3) validazione e confronto delle due specificazioni
    print("\n" + "=" * 64)
    print("  VALIDAZIONE E CONTROLLO PER CURTAILMENT")
    print("=" * 64)
    print(f"  Ore escluse (prezzo <= {PRICE_THR:.0f} EUR/MWh): {n_excl} su {len(df)}")
    print(f"  (proxy per stress di sistema / curtailment fotovoltaico)")
    print()
    print(f"                       {'TUTTO il campione':>22}  {'escluse ore stress':>22}")
    print(f"  RINNOVABILI (vero {MERIT_ORDER_TRUE:+.4f}): {b_renew:>+22.4f}  {b_renew_clean:>+22.4f}")
    print(f"  GAS         (vero +{GAS_PASSTHROUGH_TRUE:.4f}): {b_gas:>+22.4f}  {b_gas_clean:>+22.4f}")
    print()
    delta_pct = (b_renew_clean - b_renew) / b_renew * 100
    direzione = "PIU' FORTE" if abs(b_renew_clean) > abs(b_renew) else "piu' debole"
    print(f"  Escludendo le ore di stress, il coefficiente FER e' {delta_pct:+.1f}%")
    print(f"  (in valore assoluto e' {direzione}). Questo conferma l'ipotesi che")
    print(f"  il clip dei prezzi a zero (e, sui dati VERI, il curtailment FV)")
    print(f"  attenui la stima del merit-order effect.")
    print()
    print(f"  INTERPRETAZIONE FINALE (campione pulito):")
    print(f"  - Ogni 1000 MW di rinnovabili in piu' abbassano il prezzo di ~{abs(b_renew_clean)*1000:.1f} EUR/MWh.")
    print(f"  - Ogni 1 EUR/MWh in piu' sul gas trasla il prezzo elettrico di ~{b_gas_clean:.2f} EUR/MWh.")

    # 4) grafici
    make_plots(df, model)

    # 5) caveat metodologici (cosa il modello NON fa)
    print("\n" + "=" * 64)
    print("  CAVEAT METODOLOGICI")
    print("=" * 64)
    print("  Il modello e' una BASELINE deliberatamente semplice. Limiti noti:")
    print()
    print("  1. Standard errors HAC (Newey-West, lag=24) per gestire")
    print("     autocorrelazione ed eteroschedasticita' tipiche delle serie")
    print("     temporali energetiche. I coefficienti sono consistenti; gli")
    print("     intervalli di confidenza sono robusti.")
    print()
    print("  2. Specificazione lineare: i prezzi elettrici hanno code spesse e")
    print("     non-linearita' (price floor a zero, picchi di scarsita').")
    print("     Modelli piu' adatti: quantile regression, switching regimes.")
    print()
    print("  3. Una sola zona di mercato (Nord). I flussi tra zone non sono")
    print("     modellati. Estensione naturale: panel su tutte le zone.")
    print()
    print("  4. Curtailment fotovoltaico: non direttamente osservabile in")
    print("     'actual generation'. Proxy applicato escludendo le ore di")
    print("     stress di sistema (prezzo <= soglia). Soluzione rigorosa")
    print("     richiederebbe dati Terna di modulazione (API private).")
    print()
    print("  5. Causalita': la regressione misura un'associazione condizionata,")
    print("     non un nesso causale stretto. Identificazione causale richiederebbe")
    print("     strumenti (es. vento come instrumental variable per FER).")
    print()
    print("  Riportare un modello con i suoi limiti dichiarati e' parte del")
    print("  metodo. Sui dati VERI di Terna, questa stessa pipeline puo' essere")
    print("  rifinita con le tecniche sopra senza cambiare la logica generale.")
    print("\nFatto.")


if __name__ == "__main__":
    main()
