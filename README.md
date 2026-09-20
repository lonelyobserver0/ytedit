# ytEdit

Frontend desktop Qt/PySide6 per yt-dlp + FFmpeg.

## Arch Linux

Dipendenze di sistema:

```bash
sudo pacman -S ffmpeg mpv python
# mpv fornisce anche libmpv, usata dal player integrato
```

Avvio (gli script creano l'ambiente virtuale e installano le dipendenze al
primo lancio, poi si limitano ad avviare l'applicazione):

```bash
./run.sh          # bash
./run.fish        # fish
```

Opzioni comuni ai due script:

| Opzione | Effetto |
|---|---|
| `-x`, `--xcb` | forza `QT_QPA_PLATFORM=xcb` (già scelto in automatico su Wayland quando XWayland è disponibile) |
| `-w`, `--wayland` | resta su Wayland nativo: l'anteprima mpv si apre in una finestra separata |
| `-u`, `--update` | reinstalla/aggiorna le dipendenze Python |
| `-c`, `--check` | verifica ambiente e dipendenze, poi esce |
| `-h`, `--help` | mostra l'aiuto |

Gli argomenti non riconosciuti vengono passati a `main.py`. Le dipendenze
vengono reinstallate solo quando `requirements.txt` cambia (o con `--update`).

Installazione manuale, in alternativa:

```bash
python -m venv .venv
source .venv/bin/activate.fish
pip install -r requirements.txt
python main.py
```

`ffmpeg` e `ffprobe` devono essere nel `PATH`; `mpv` serve solo per l'anteprima.
Per una diagnosi dell'ambiente: `python -m ytedit.doctor`.

## Funzionalità

**Download**
- analisi dell'URL con yt-dlp (asincrona, l'interfaccia non si blocca)
- selezione qualità (fino a 1080p/720p/480p/360p) e contenitore (MP4/MKV/WEBM)
- solo audio: **originale** (nessuna ricodifica, predefinito) oppure opus, m4a,
  mp3, flac, wav — da YouTube la sorgente è già lossy, quindi convertirla in flac
  non aggiunge nulla e ricomprimerla in mp3 toglie
- sottotitoli con scelta delle lingue (`it,en` oppure `all`)
- opzione **Intera playlist**: spenta (predefinita) un URL con `&list=` scarica
  solo il video indicato; accesa scarica tutta la playlist in una sottocartella
  con indice progressivo
- coda di download sequenziale con stato per elemento
- argomenti extra yt-dlp (uno per riga, es. `--cookies-from-browser firefox`)
- barra di avanzamento alimentata dalle percentuali reali di yt-dlp

**Flusso consigliato**

1. incolla l'URL e premi **Analizza**: il video si apre subito nell'editor e parte
   in **streaming** tramite mpv + yt-dlp — non viene scaricato nulla
2. scegli il punto IN e OUT guardando l'anteprima (`IN = posizione` / `OUT = posizione`)
3. decidi cosa vuoi (video o solo audio, qualità, contenitore) e premi
   **⬇ Scarica IN–OUT**: yt-dlp scarica *solo* quell'intervallo
   (`--download-sections`), non il video intero
4. il file locale sostituisce l'URL nell'editor e gli strumenti FFmpeg diventano
   disponibili per rifiniture

La casella **Solo selezione IN–OUT** nel tab Download fa la stessa cosa dal
pulsante Scarica.

**Editor**
- **player video integrato**: libmpv viene renderizzata dentro un widget OpenGL
  di Qt, quindi il video sta nella finestra anche su Wayland nativo (non è mpv
  come processo esterno agganciato con `--wid`, che richiede X11)
- riproduzione in streaming diretta da URL, senza download preventivo
- controlli barra OSC, pausa, stop, salti di ±5 s e seek esatto (non al keyframe)
- **timeline** sotto il video: testina trascinabile per scorrere avanti e indietro,
  maniglie IN/OUT per delimitare il segmento, con selezione evidenziata e durata
  mostrata; sincronizzata in entrambi i versi con i campi IN e OUT
- pulsanti `IN = posizione` / `OUT = posizione` che leggono il tempo dal player via IPC
- taglio veloce (`-c copy`) o preciso (ricodifica)
- due azioni opposte sulla selezione: **tieni solo la selezione** oppure
  **rimuovi la selezione**, che elimina l'intervallo e ricuce le parti rimanenti
  in un solo passaggio FFmpeg (`trim` + `concat`)
- estrazione audio, sostituzione della traccia audio
- scala, rotazione, volume, dissolvenze audio in entrata/uscita

**Strumenti**
- unione di più file, con o senza ricodifica
- sottotitoli: masterizzati nel video (burn-in) o incorporati come traccia

**Avanzato**
- anteprima in tempo reale dei comandi yt-dlp e FFmpeg che verranno eseguiti
- interruzione dell'operazione FFmpeg in corso
- impostazioni persistenti (destinazione, qualità, formato, lingue, geometria finestra)

## Aspetto

Tre temi, selezionabili nel tab **Avanzato** e applicati a caldo, senza riavviare:

| Tema | Da dove viene |
|---|---|
| `scuro` | predefinito |
| `chiaro` | per chi lavora con luce in faccia |
| `pywal` | letto da `~/.cache/wal/colors.json`, compare solo se il file esiste |

Cambia la palette, non il significato dei colori: l'accento marca ciò che è
selezionato o attivo, un secondo colore compare solo sull'azione che distrugge, e
il riquadro del video resta scuro in ogni tema perché un'immagine si giudica su un
contorno neutro.

Per pywal accento e colore di pericolo si scelgono per saturazione e tinta, non
per indice: `color1` non è affidabilmente "il rosso", dipende dall'immagine.

Interfaccia in Adwaita Sans, timecode e comandi in JetBrains Mono (cifre
incolonnate). Tutto in `ytedit/theme.py`.

## Note

- **Player video**: con `python-mpv` installato (è in `requirements.txt`) il video
  è renderizzato dentro la finestra su qualsiasi piattaforma Qt, Wayland incluso.
  Se `python-mpv` o `libmpv` mancano, l'app ripiega su mpv come processo esterno
  agganciato con `--wid`: quello richiede X11, e in quel solo caso l'app passa
  automaticamente alla piattaforma Qt `xcb` in una sessione Wayland
  (disattivabile con `./run.sh --wayland` o `YTEDIT_KEEP_WAYLAND=1`).
- Gli URL YouTube del tipo `watch?v=…&list=RD…` sono *mix* generati
  automaticamente e di fatto infiniti: l'analisi usa `--flat-playlist` e
  `--no-playlist` per restare in pochi secondi invece di non terminare mai.
- I codec di uscita seguono il contenitore di destinazione (x264/AAC per MP4 e MKV,
  VP9/Opus per WebM, codec nativo per i contenitori solo-audio).
- Il taglio veloce senza ricodifica taglia sul keyframe più vicino: per un punto di
  attacco esatto serve il taglio preciso.
