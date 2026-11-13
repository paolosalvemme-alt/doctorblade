# Collegamenti SKR Mini E3 V3.0: endstop X e piatto riscaldante

Questa guida descrive come collegare e verificare il finecorsa X-min e il pad
riscaldante in silicone sulla BIGTREETECH SKR Mini E3 V3.0 del doctor blade.
I nomi dei pin vengono dal pinout ufficiale BTT (`BTT_E3_SKR_MINI_V3.0_PIN.pdf`).

> **Sicurezza.** Fai ogni modifica di cablaggio con l'alimentatore **spento e
> scollegato dalla rete** e con il cavo USB staccato. Le prime prove vanno fatte
> senza lama, a bassa velocità, con l'interruttore di alimentazione a portata di
> mano.

## 1. Dove sono i connettori

Nel PDF la scheda è disegnata con i morsetti di potenza in basso a sinistra.
Nella foto della tua scheda è **ruotata di 90°**: i morsetti a vite sono in
alto a sinistra e la fila di connettori bianchi in basso nel PDF corre lungo il
**lato sinistro** della scheda, dall'alto verso il basso, in questo ordine:

| Connettore | Pin (dal PDF) | Uso nel doctor blade |
| --- | --- | --- |
| POWER | 12/24V, GND | Ingresso alimentatore |
| HB (morsetto a vite) | `-` / `+`, comandato da **PC9** | Fili di potenza del pad in silicone |
| E0 (morsetto a vite) | comandato da PC8 | Non usato |
| FAN2, FAN0 | PB15, PC6 | Non usati |
| **X-STOP** | **GND, PC0** | Finecorsa X-min |
| Y-STOP, Z-STOP | PC1, PC2 | Non usati |
| **THB** | **GND, PC4** | Termistore del pad |
| TH0 | GND, PA0 | Non usato (è il termistore dell'estrusore) |
| XM | 2B 1B 1A 2A | Motore della madrevite (già funzionante) |

Il ponticello **X-DIAG** si trova vicino al connettore X-STOP.

## 2. Endstop X-min: perché l'homing non funziona

### 2.1 Cause più probabili, in ordine

1. **Ponticello X-DIAG inserito.** Sulla SKR Mini E3 V3 il ponticello X-DIAG
   collega l'uscita DIAG del driver TMC2209 allo stesso pin PC0 del connettore
   X-STOP (serve per il *sensorless homing*). Con un finecorsa meccanico il
   ponticello **va tolto**, altrimenti il driver e l'interruttore pilotano lo
   stesso pin e la lettura è sbagliata o casuale.
2. **Fili sul pin sbagliato.** Nella foto i due fili del finecorsa arrivano alla
   scheda con connettori Dupont femmina infilati su pin maschi. Verifica che
   siano proprio sui due pin del connettore **X-STOP** e non sul ponticello
   X-DIAG, sulle ventole o su Y-STOP. I Dupont infilati su pin JST fanno spesso
   contatto intermittente: usa un connettore **JST-XH a 2 poli**.
3. **Finecorsa a 3 fili collegato come se fosse a 2.** La schedina rossa del
   finecorsa ha tre contatti (di solito marcati `S`/`SIG`, `-`/`GND`,
   `+`/`VCC`), mentre X-STOP della SKR ne ha solo due (`GND`, `PC0`).
4. **Firmware.** Marlin deve usare X-min, con pull-up attivo e il livello di
   intervento corretto.

### 2.2 Collegamento consigliato

**Opzione A, tramite la schedina rossa:**

| Schedina finecorsa | SKR X-STOP |
| --- | --- |
| `S` / `SIG` | `PC0` |
| `-` / `GND` | `GND` |
| `+` / `VCC` | **non collegato** |

Senza `+` il LED della schedina **non si accende: è normale** e non significa
che il finecorsa sia guasto. Non collegare `+` ai 5 V: i pin della scheda
lavorano a 3,3 V.

Prima di tutto verifica con il tester, in continuità, sui contatti `S` e `-`
della schedina scollegata:

- leva rilasciata, poi leva premuta: la continuità tra `S` e `-` **deve
  cambiare**. In questo caso l'opzione A funziona.
- Se la continuità cambia solo tra `S` e `+`, quella schedina commuta verso
  VCC e non funziona con due fili: usa l'opzione B.

**Opzione B, consigliata per un'apparecchiatura da laboratorio:** collega
direttamente il microinterruttore, scavalcando l'elettronica della schedina, in
configurazione **normalmente chiusa (NC)**:

| Microinterruttore | SKR X-STOP |
| --- | --- |
| `C` / `COM` (comune) | `GND` |
| `NC` (normalmente chiuso) | `PC0` |

Con il cablaggio NC, un filo rotto o staccato si legge come `TRIGGERED`, e il
programma **blocca l'homing** invece di spingere il carrello contro il fondo
corsa. Questa è la scelta più sicura.

### 2.3 Impostazioni Marlin per l'endstop

In `Configuration.h`:

```cpp
#define USE_XMIN_PLUG
#define X_HOME_DIR -1
#define ENDSTOPPULLUPS               // oppure almeno ENDSTOPPULLUP_XMIN
#define X_MIN_ENDSTOP_HIT_STATE HIGH // Marlin 2.1.2 e successivi, cablaggio NC
// Marlin precedenti: #define X_MIN_ENDSTOP_INVERTING false
```

Con il cablaggio NC: leva rilasciata, contatto chiuso, PC0 a GND, livello LOW,
`open`. Leva premuta, contatto aperto, pull-up, livello HIGH, `TRIGGERED`.
Se `M119` risulta invertito, cambia `X_MIN_ENDSTOP_HIT_STATE` (o
`X_MIN_ENDSTOP_INVERTING`) e ricompila. Non invertire i fili per compensare.

Disattiva il sensorless homing per X: in `Configuration_adv.h` la riga
`#define SENSORLESS_HOMING` deve essere commentata, così come
`X_STALL_SENSITIVITY`.

Il resto della convenzione di asse (−X verso il finecorsa, `INVERT_X_DIR`,
software endstop) è descritto in [`FIRMWARE_X_AXIS.md`](FIRMWARE_X_AXIS.md).

### 2.4 Verifica con il programma (senza movimento)

1. Collega la scheda, premi **Connect** e attendi **Ready**.
2. Nella scheda **Manual Motion** attiva **Live endstop monitor**: il programma
   invia `M119` ogni 0,5 s, non muove il motore e non scalda.
3. Premi e rilascia la leva più volte. Lo stato deve passare tra
   **OPEN (lever released)** e **TRIGGERED (lever pressed)** e il contatore
   **State changes seen** deve salire.

| Cosa vedi | Causa probabile | Rimedio |
| --- | --- | --- |
| Sempre `OPEN`, anche premendo | Filo sul pin sbagliato o interrotto; schedina che commuta verso `+` | Verifica X-STOP (PC0/GND), poi passa all'opzione B |
| Sempre `TRIGGERED` | Ponticello X-DIAG inserito; filo staccato con cablaggio NC; livello invertito | Togli X-DIAG, controlla i fili, poi `X_MIN_ENDSTOP_HIT_STATE` |
| Stato invertito (premuto = `OPEN`) | Livello di intervento invertito | Cambia `X_MIN_ENDSTOP_HIT_STATE` in Marlin |
| Lo stato cambia a caso | Contatto Dupont instabile o ponticello X-DIAG | Connettore JST-XH crimpato, togli X-DIAG |
| Lo stato è corretto ma `G28 X` va dalla parte opposta | Direzione motore | `INVERT_X_DIR`, vedi `FIRMWARE_X_AXIS.md` |
| `M119` non riporta `x_min` | `USE_XMIN_PLUG` non definito | Ricompila Marlin |

Solo quando il monitor segue correttamente la leva, spegni il monitor e prova
**Home X**, tenendo la mano sull'interruttore di alimentazione. Controlla anche
che il carrello prema davvero la leva **prima** di arrivare a battuta
meccanica.

## 3. Pad riscaldante in silicone

### 3.1 Prima di collegare: leggi l'etichetta del pad

Su ogni pad in silicone c'è un'etichetta con **tensione** e **potenza**, ad
esempio `24V 150W` o `220V 200W`. Leggi anche la tensione dell'alimentatore
(l'alimentatore "a mattoncino" della foto). Il collegamento dipende da questi
due dati:

| Pad | Alimentatore | Collegamento |
| --- | --- | --- |
| 12 V DC | 12 V | Diretto su HB (3.2) |
| 24 V DC | 24 V | Diretto su HB (3.2) |
| 12 V DC | 24 V | **Non collegare**: il pad assorbirebbe 4 volte la potenza nominale (rischio di incendio) |
| 24 V DC | 12 V | Scalda a 1/4 della potenza: Marlin darà `Heating failed` |
| 220/230 V AC | qualsiasi | **Mai su HB**: serve un relè statico (SSR), vedi 3.3 |

Controlla anche la corrente: `I = P / V`. Per esempio, 150 W a 24 V fanno
6,3 A e 100 W a 12 V fanno 8,3 A. L'uscita HB della SKR Mini E3 V3 è adatta
fino a circa 10 A (verifica il valore nel manuale BTT della tua revisione). Per
correnti maggiori usa un modulo MOSFET esterno comandato da HB. L'alimentatore
deve erogare la potenza del pad più circa 30 W per scheda e motore.

### 3.2 Pad a 12/24 V DC collegato direttamente

| Pad | SKR |
| --- | --- |
| 2 fili di potenza (più grossi) | Morsetto a vite **HB** `+` e `-` (polarità indifferente per un pad resistivo) |
| 2 fili sottili del termistore | Connettore **THB** (`GND`, `PC4`; polarità indifferente) |

- Usa capicorda a puntale sui fili di potenza e stringi bene le viti: un
  contatto lento sul morsetto HB scalda e può fondere il morsetto.
- Usa una sezione di almeno 0,75–1 mm² (18 AWG) per i fili di potenza.
- Il morsetto `+` di HB è **sempre in tensione**: la scheda commuta il `-`.
  Nessun filo del pad deve toccare il telaio o la piastra in alluminio.
- Il termistore va su **THB**, non su TH0. Nella foto della scheda i due
  connettori bianchi in basso a sinistra sono THB (quello più in alto) e TH0.
- Il termistore deve essere a buon contatto termico con la piastra riscaldata
  (incollato o fissato con nastro Kapton); se si stacca, Marlin segnala
  `Thermal runaway`.
- Aggiungi un fusibile sulla linea di potenza del pad (vedi il README).

### 3.3 Pad a 220/230 V AC con relè statico (SSR)

Se non hai esperienza con impianti a tensione di rete, fai eseguire questo
cablaggio da un elettricista qualificato.

| Da | A |
| --- | --- |
| HB `+` | SSR ingresso `3 (+)` |
| HB `-` | SSR ingresso `4 (-)` |
| Fase (L) della rete, tramite fusibile | SSR uscita `1` |
| SSR uscita `2` | Pad, filo 1 |
| Neutro (N) | Pad, filo 2 |
| Terra (PE) | Piastra/telaio metallico |

- Usa un SSR DC→AC (ingresso 3–32 V DC, uscita AC) di marca affidabile, con
  corrente nominale ampiamente superiore a quella del pad, montato su un
  dissipatore.
- Aggiungi un **termofusibile** o un termostato bimetallico a riarmo manuale a
  contatto con la piastra, in serie al pad, come protezione indipendente da
  Marlin.
- La piastra metallica deve essere collegata a terra.

### 3.4 Impostazioni Marlin per il piatto

In `Configuration.h`:

```cpp
#define TEMP_SENSOR_BED 1      // NTC 100k (tipico dei pad in silicone, B3950)
#define BED_MAXTEMP 110        // il programma limita comunque a 90 C senza conferma
#define THERMAL_PROTECTION_BED // lasciare attivo (tempi in Configuration_adv.h)
```

Il file `pins_BTT_SKR_MINI_E3_V3_0.h` di Marlin usa già `HEATER_BED_PIN PC9`
e `TEMP_BED_PIN PC4`: non serve modificarlo. Se `TEMP_SENSOR_BED` vale `0`,
Marlin non gestisce il piatto: il programma se ne accorge alla connessione
(nessun `B:` nella risposta a `M105`) e disabilita i comandi del piatto.

### 3.5 Prima accensione del riscaldatore con il programma

1. Collega la scheda e attendi **Ready**. Apri la scheda **Heated Bed**.
2. A pad freddo, **Current bed temperature** deve indicare la temperatura
   ambiente (circa 18–28 °C) e **Thermistor / heater check** deve essere verde.
   Una lettura intorno a −14 °C indica un termistore scollegato.
3. Imposta 40 °C e premi **Set Bed Temperature**. **Heater power** deve
   salire verso il 100 % (`B@:127`) e la temperatura deve aumentare entro un
   minuto.
4. Se dopo 2 minuti la temperatura non è salita di almeno 2 °C, il programma
   **spegne il riscaldatore** e mostra la diagnosi.
5. Premi **Heater Off** al termine della prova.

| Cosa vedi | Causa probabile |
| --- | --- |
| Temperatura circa −14 °C, errore `MINTEMP` | Termistore scollegato, interrotto o collegato su TH0 invece di THB |
| Temperatura molto alta a pad freddo, errore `MAXTEMP` | Termistore in cortocircuito o `TEMP_SENSOR_BED` sbagliato |
| `B@` al 100 % ma la temperatura non sale | Pad non collegato a HB, morsetto lento, alimentatore spento o sottodimensionato, pad a 24 V su alimentatore a 12 V |
| `B@` sempre 0 con target impostato | Marlin in errore (`KILLED`) o piatto non abilitato nel firmware |
| Nessuna temperatura del piatto, comandi disabilitati | `TEMP_SENSOR_BED 0` nel firmware |
| Sale e poi `Thermal runaway` | Termistore staccato dalla piastra, alimentazione instabile |

Dopo un errore termico Marlin si blocca (`KILLED`): risolvi il problema, poi
premi RESET sulla scheda o spegni e riaccendi prima di riconnetterti.
