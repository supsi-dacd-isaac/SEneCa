# Risultati nativi Vensim — 13 ottobre 2026

Equivalenza fra Vensim e il backend Python–Julia: non raggiunta. Il test statico e il base originale non bastano a dichiararla. Il confronto completo con Julia non è stato eseguito su questo host.

## Ambiente

- Branch `vensim-native-alignment`, commit di partenza `72c872315f19d214351823c93308ad3733284b81`. Worktree separato; la copia su `main` non è stata modificata.
- Python 3.11.9 a 64 bit, ambiente `.venv` del worktree. Versioni effettive: NumPy 2.4.6, pandas 3.0.6, pyarrow 25.0.1, PySD 3.14.3, xarray 2026.9.0.
- Vensim DSS 10.2.2, build `TK-240930.00384`, file `C:\Program Files\Vensim\vendss64.exe` (versione file 10.2.2.0).
- DLL `C:\Windows\System32\vendll64.dll`, 12 242 728 byte, SHA256 `8557fd69f2c13f96c9281e5a6f8e7a586468810b76c8f0ba6af8a6ff7168ad9c`.
- `SURE.mdl` estratto da `17db1f4245c6bb0e8ef41a4cac5e8d3a6817cac6` con `git show` e `Path.write_bytes`. SHA256 `322f21d0b7825224f492b50963dcdbfc3b7ea0b2dce9e29a1b438614d0d4465f`.
- VPMX dei dieci run archiviati, già presente e non ripubblicato: SHA256 `bc18a741008dd2b299083d9c81a0f59acc2288d884991833dd3634354f52bf01`, 157 593 444 byte.

Lo ZIP `e32566e762aa3741b23190d63af024c01ca602c998923e700a887ebf782e464a` non era nel messaggio né sul disco. I cinque file della prova sono stati rigenerati con `scripts.sure_v4.allocation_probe prepare` dallo stesso sorgente e dallo stesso generatore. I checksum del manifest sono quelli di questa rigenerazione:

| File | SHA256 |
|---|---|
| `allocation_probe.mdl` | `c60b2b30e3a61036a2894341671ab9c714f7b0e735b623093e48aeed7521201d` |
| `cases.json` | `e3e75f3c16186afdd93bf48ec19f7f45ae8485adec830c951ca58589dd162efc` |
| `SURE_priority_candidate.mdl` | `d019f7f83f3db73dcac34e5dca9ddc2014acdf77a01f604296447839a54a50a8` |
| `SURE_priority_candidate.patch` | `4f4ec159b9c0bd637a50d9997761349850d04e422d06abad2d3bedd04746b3d0` |

`allocation_probe.vpmx` pubblicato da DSS 10.2.2: 93 811 byte, SHA256 `a0ff7f08233cf900ada175d381451381956ce25f6e24a071ddef026cf82dafb2`. Vensim segnala che le due allocazioni non sono usate da altre equazioni; la DLL le ha comunque restituite. Nessuna equazione è stata cambiata per ottenere un esito positivo.

## Allocatori

Cinquanta casi, nove fornitori, 450 celle per funzione. Tolleranza dello script invariata, mezzo ULP Float32 compreso. Entrambe le funzioni falliscono.

| Funzione | Casi falliti | Celle fallite | Errore assoluto massimo | Errore massimo sul bilancio |
|---|---:|---:|---:|---:|
| ALLOCATE AVAILABLE | 32 / 50 | 35 / 450 | 1,643·10⁻⁴ | 1,643·10⁻⁴ |
| ALLOCATE BY PRIORITY | 32 / 50 | 39 / 450 | 5,117·10⁻⁷ | 1,255·10⁻⁷ |

Il minimo valore nativo strettamente positivo è 1,024·10⁻⁷. Nei dati non compare una soglia di 0,01. Gli scarti grandi di AVAILABLE stanno sul fornitore marginale, in una sola cella, e coincidono con l'errore di bilancio: la quantità su quel fornitore cambia, l'identità del fornitore marginale no. I casi peggiori sono gli offset ±0,0001 rispetto al confine fra fornitori.

La traslazione delle priorità di +200 lascia le allocazioni native invariate oltre il rumore: differenza massima 2,98·10⁻⁸ per AVAILABLE e 7,11·10⁻¹⁵ per BY PRIORITY. Il gruppo con priorità negative e quello traslato in positivo hanno lo stesso errore massimo.

Due confronti di positività grezza vanno letti con la magnitudine, senza un taglio fisso:

- Al confine esatto dei primi quattro fornitori, Python lascia 5,55·10⁻¹⁷ sul fornitore successivo e Vensim scrive 0. È il residuo float64 del riferimento, presente per entrambe le funzioni e per entrambe le traslazioni.
- BY PRIORITY, al confine esatto dei primi otto fornitori, assegna 1,024·10⁻⁷ al nono fornitore. AVAILABLE su quegli stessi ingressi non lo fa. È l'unico spostamento del fornitore marginale di dimensione superiore al residuo 1e-17.

Sugli otto casi di pareggio e di profili sovrapposti, la disponibilità nulla e quella abbondante coincidono. Lo scarto massimo di BY PRIORITY è il caso sovrapposto con disponibilità 0,2: gli stessi tre fornitori alti ricevono quote diverse, con errore di bilancio −6,6·10⁻⁸. AVAILABLE su quel caso arriva a 7,7·10⁻⁷.

Per questo esito BY PRIORITY non è stato pubblicato nel modello SURE completo.

## Ritardi

Modello autonomo, Euler verificato dalla traiettoria, passo 1, tempi 0…8. `STEP(10, 1)` e `SMOOTH(..., 2)`.

Lo SMOOTH salvato coincide con `s[0] = 0`, `s[n+1] = s[n] + (Input[n] - s[n]) / 2`. La variante che usa `Input[n+1]` scarta di 5 al primo passo.

Per ogni ritardo 0,01, 0,1, 1, 2 e 4, `DELAY FIXED(Smoothed, ritardo, 0)` e `DELAY FIXED(SMOOTH(Input, 2), ritardo, 0)` coincidono (differenza massima 0).

I ritardi 0,01 e 0,1 coincidono con il ritardo 1: è lo SMOOTH salvato, quindi già aggiornato, spostato di un passo. I ritardi 2 e 4 coincidono con lo SMOOTH salvato spostato di 2 e di 4 passi. L'ipotesi di una lettura ulteriore prima dell'aggiornamento, aggiunta a quel ritardo, è smentita dai ritardi 2 e 4. I ritardi inferiori al passo sono quindi quantizzati a un passo, e il valore ritardato è quello già scritto da SMOOTH.

Una run fino a 4, poi due run complete nello stesso processo e una in un processo nuovo, riproducono la prima run con differenza massima 0. La memoria dei ritardi viene reinizializzata.

Avviso di pubblicazione: le dieci serie ritardate risultano non usate da altre equazioni. La DLL le ha lette ugualmente. Integrazione non impostata da un comando separato: è quella di default del testo caricato, e la traiettoria dello SMOOTH è l'Euler esplicito sopra.

## SURE originale, solo `01_base`

VPMX originale, cartella di lavoro distinta, dati esterni copiati accanto al modello. `SIMULATE>SETVAL|SAVEPER=1` è stato rifiutato (`rc=0`); è rimasta l'equazione del modello `SAVEPER = TIME STEP`. Passo 1, orizzonte 2011–2050, output annuale.

I quattro provvedimenti sono stati inviati fra virgolette, per esempio `SIMULATE>SETVAL|"Provvedimento 1.2"=0.0`. Letture di controllo, presenti solo all'istante 2011:

| Variabile | Valore letto |
|---|---:|
| ICE ban year | 2050 |
| Deflussi minimi LPAc | 1 |
| Cambiamento climatico Hydro | 1 |

Confronto con `outputs.parquet` archiviato, uguaglianza Float32 cella per cella: 848 048 righe, 0 coordinate mancanti, 0 valori diversi. Non c'è una prima divergenza sul base. Gli scarti già noti rispetto a Python non nascono da una riesecuzione diversa del VPMX archiviato.

`Hourly exported electricity[...,Import]`: 288 serie, solo l'anno 2011, valore 0. Lo stesso limite è nell'archivio. Le righe non sono state riempite. Il valore è Float32, come restituito dalla DLL; l'anno è il tempo Float32 della DLL.

I dieci diagnostici aggiuntivi sono in `diagnostics-01-base.parquet` (71 880 righe, griglia annuale completa). Il candidato con BY PRIORITY non è stato simulato.

## Cosa resta

- Gli altri nove scenari, il base ripetuto e il base in un processo nuovo.
- Il modello candidato, solo se si accetta di studiarlo nonostante il fallimento della tolleranza statica.
- Il confronto di questi ingressi nativi con Julia, sull'ambiente previsto.
- Lo ZIP originale, se va recuperato per confermare i byte del manifest oltre alla rigenerazione.

Script: `scripts/vensim_native/`. Artefatti grezzi, fuori da Git: `dist/sure-alignment/`. Archivio `dist/sure-alignment/native-results-20261013.zip`, 106 283 680 byte, SHA256 `2b587916c3d99cec015c2c7d1f18364c99b49f238d521a766c5539d365eb97c6`. Il VPMX originale non è duplicato nell'archivio: resta il file con hash `bc18a741…`.
