# Il Merit-Order Effect nel Mercato Elettrico Italiano

**Quanto la generazione rinnovabile abbassa i prezzi elettrici del giorno prima — zona Nord, 2022–2024, con la crisi del gas 2022 nel campione.**

![Risultati](figures/results.png)

## Domanda di ricerca

A parità di domanda e costo dei combustibili, di quanto un GW aggiuntivo di generazione rinnovabile non programmabile (fotovoltaico + eolico) abbassa il prezzo zonale dell'elettricità del giorno prima?

Le rinnovabili offrono a costo marginale quasi nullo, entrando per prime nella curva di offerta e spiazzando gli impianti a gas al margine — il **merit-order effect**. Questo progetto lo misura su dati reali del mercato italiano, che coprono sia la crisi energetica del 2022 sia la normalizzazione del 2023-24.

## Risultati principali

OLS con dummy mensili ed errori standard HAC Newey-West (lag = 24), 26.250 osservazioni orarie, R² = 0,895:

| Fattore | Effetto sul prezzo zonale Nord | IC 95% |
|---|---|---|
| Rinnovabili **+1 GW** | **−4,1 EUR/MWh** | [−4,4, −3,8] |
| Gas TTF **+1 EUR/MWh** | **+2,0 EUR/MWh** | [+1,9, +2,0] |
| Domanda **+1 GW** | **+6,3 EUR/MWh** | [+5,9, +6,7] |

Il passthrough del gas di ≈2 è coerente con impianti a ciclo combinato che fissano il prezzo marginale con un'efficienza termica di ~50%.

**Il merit-order effect dipende dal regime.** Ristimando anno per anno:

| Anno | Effetto FER (EUR/MWh per GW) | Passthrough gas | R² |
|---|---|---|---|
| 2022 (crisi) | **−6,3** | +1,85 | 0,861 |
| 2023 | −3,3 | +1,60 | 0,728 |
| 2024 | −2,5 | +2,29 | 0,717 |

L'effetto scala con il prezzo del combustibile marginale spiazzato: quando il gas trattava sopra i 100 EUR/MWh, ogni MWh rinnovabile che spiazzava un impianto a gas valeva molto di più che in tempi normali.

## Dati

| Dataset | Fonte | Frequenza | Note |
|---|---|---|---|
| Fabbisogno zonale (Nord) | [Terna Download Center](https://www.terna.it/en/electric-system/transparency-report/download-center) | 15 min → oraria | `Total Load` |
| Generazione FER (PV + eolico) | Terna Download Center | Oraria | Nazionale, `Renewable Generation`, GWh |
| Prezzo zonale (Nord) | [GME](https://www.mercatoelettrico.org) | Oraria | MGP giorno prima |
| Gas TTF front-month | [Investing.com](https://www.investing.com/commodities/dutch-ttf-gas-c1-futures-historical-data) | Giornaliera → oraria (ffill) | EUR/MWh |

I file grezzi non sono ridistribuiti qui (licenze delle fonti); scaricali dai link sopra e mettili in `data/` con i nomi indicati in `src/data_loader.py`.

## Metodo

`prezzo ~ domanda + rinnovabili + gas + domanda_residua² + dummy mensili`

- Le **dummy mensili** assorbono la stagionalità condivisa che altrimenti creerebbe correlazione spuria (inverno = gas alto, domanda alta, poco sole).
- Il **termine quadratico sulla domanda residua** cattura la convessità della curva di offerta (impianti di picco costosi ad alta domanda residua).
- Gli **errori HAC Newey-West (lag 24)** gestiscono la forte autocorrelazione dei prezzi orari (Durbin-Watson grezzo ≈ 0,17); gli errori standard OLS classici sovrastimerebbero la precisione di circa **2,4×** sul coefficiente delle rinnovabili.
- **Robustezza**: le stime sono stabili anno per anno in segno e ordine di grandezza, e invariate escludendo le 22 ore di stress di sistema (prezzo ≤ 5 EUR/MWh).
- **Robustezza geografica**: ristimando su una specificazione interamente nazionale (prezzo PUN + fabbisogno Italia + generazione nazionale) si ottiene un merit-order effect di **−4,7 EUR/MWh per GW** (contro −4,1 nella specificazione zonale Nord) e un passthrough del gas identico (**+1,95** contro +1,99). Il risultato non dipende dalla scelta zonale-vs-nazionale — il che risolve direttamente il caveat sull'asimmetria zonale invece di limitarsi a dichiararlo.

| Specificazione | Merit-order (per GW) | Passthrough gas | R² |
|---|---|---|---|
| Zona Nord (principale) | −4,1 EUR/MWh | +1,99 | 0,895 |
| Nazionale (PUN) | −4,7 EUR/MWh | +1,95 | 0,905 |

### Validazione metodologica su dati sintetici

Prima di toccare i dati reali, l'intera pipeline è stata validata su un mercato simulato con un coefficiente merit-order *noto* nascosto nell'equazione del prezzo (`simulation/simulation_validation.py`). La regressione recupera i parametri veri esattamente una volta gestita la distorsione del price floor — prova che la logica di stima è solida. Questo approccio "prima simula" ha anche fatto emergere un omitted-variable bias (il gas) e un confondimento stagionale prima che potessero contaminare l'analisi sui dati reali.

## Struttura del repository

```
├── README.md
├── requirements.txt
├── data/                      # metti qui i file scaricati (non tracciati)
├── src/
│   ├── data_loader.py         # legge, pulisce, allinea tutte le fonti su griglia oraria
│   ├── analysis.py            # regressione principale + stabilità annuale + robustezza
│   └── plots.py               # genera figures/results.png
├── simulation/
│   └── simulation_validation.py   # validazione della pipeline su dati sintetici
└── figures/
    └── results.png
```

## Riprodurre l'analisi

```bash
pip install -r requirements.txt
# scarica i file sorgente in data/ (vedi sezione Dati)
python src/analysis.py     # stime e controlli di robustezza
python src/plots.py        # genera figures/results.png
```

## Limiti e sviluppi futuri

Questa è una baseline deliberatamente trasparente, non un modello strutturale:

1. **Associazione, non identificazione.** L'OLS con controlli misura un'associazione condizionata. L'identificazione causale richiederebbe strumenti (es. la velocità del vento come IV per la produzione rinnovabile).
2. **Specificazione lineare.** I prezzi elettrici hanno code spesse e picchi di scarsità (kurtosis ≈ 11 nei residui); una quantile regression o modelli a regimi catturerebbero meglio gli estremi.
3. **Asimmetria zonale.** Nella specificazione principale prezzo e domanda sono zona Nord, mentre la generazione FER è nazionale — Terna pubblica la generazione oraria per fonte solo a livello nazionale (la disaggregazione zonale esiste per la *capacità installata*, non per la *generazione oraria effettiva*). Poiché il Nord Italia concentra la quota maggiore della capacità fotovoltaica nazionale (Lombardia e Veneto sono 1ª e 2ª regione), la generazione nazionale è un proxy di primo ordine ragionevole. **Questa scelta è validata dal controllo di robustezza nazionale sopra**, dove tutte le variabili condividono lo stesso livello geografico (nazionale) e il merit-order effect è confermato.
4. **Il curtailment fotovoltaico** non è osservabile nei dati di generazione effettiva; un controllo proxy (escludendo le ore di stress) suggerisce un impatto limitato in questo campione.
5. **I flussi tra zone** e le importazioni via interconnector sono omessi; un panel su tutte e sette le zone di mercato è l'estensione naturale.

## Autore

Manuel Giannetti — analista di mercati energetici e geopolitica. Scrive di sicurezza energetica su [IARI](https://iari.site).

*Fonti dati: Terna S.p.A., GME S.p.A., ICE Endex via Investing.com. Tutti i dati sono pubblicamente disponibili.*
