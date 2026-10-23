# Modello del Filtro contenuti

**CLIP ViT-B/32** di OpenAI (licenza MIT, `LICENZA-CLIP.txt`; repository `openai/CLIP` al
commit `d05afc436d78f1c48dc0dbf8e5980a9d471f35f6`), nella versione ONNX quantizzata pubblicata
da Xenova su Hugging Face (`Xenova/clip-vit-base-patch32`, revisione
`d15189d7028b43f1d3e65039190477f6af591c2a`). Gira con il solo `onnxruntime`, senza PyTorch.

- `clip_visione.onnx` (89 MB, la parte delle immagini): **non sta nel repository**. Lo scarica
  `scarica_modello.py` (lo chiama il Dockerfile), controllando lo SHA-256
  `583fd1110a514667812fee7d684952aaf82a99b959760c8d7dca7e0ab9839299`.
- `frasi.json`: le descrizioni delle quattro classi (nudo, intimo, vestito, altro), in inglese
  come vuole CLIP.
- `clip_classi.npy`: la media normalizzata delle frasi di ogni classe, calcolata una volta con
  la parte di testo di CLIP (`prepara_classi.py`); sul server la parte di testo non serve.

## Come è stato tarato (23/10/2026)

CLIP guarda un quadrato: le immagini larghe o alte (un video 16:9) si guardano a pezzi quadrati
sovrapposti che coprono tutta l'immagine, e conta il pezzo con più nudo. Probabilità di «nudo»
con il codice del server (versione quantizzata), soglie di bassa / media / alta:

| Gruppo | Immagini | ≥ 0,70 (bassa) | ≥ 0,50 (media) | ≥ 0,35 (alta) |
|---|---|---|---|---|
| Quadri di nudo (WikiArt) | 102 | 90% | 95% | 96% |
| Gli stessi, a tutto schermo 16:9 | 102 | 94% | 97% | 97% |
| Intimo: reggiseni, slip, boxer, camicie da notte (foto prodotto) | 250 | 0% | 0,8% | 0,8% |
| Lo stesso intimo, a tutto schermo 16:9 | 120 | 0% | 0,8% | 4,2% |
| Abiti, top, magliette | 150 | 0% | 0% | 0% |
| Intervista a una donna vestita (190 fotogrammi) | 190 | 0% | 0,5% | 3,2% |
| Colori pieni 16:9 (compresi i toni della pelle) | 13 | 0% | 0% | 0% |

Un video di prova di 30 s (intervista, 4 s di quadri di nudo, 4 s di intimo a tutto schermo) è
coperto solo nel tratto del nudo, a tutte e tre le severità.

Le frasi (`frasi.json`) sono state scelte confrontando varianti: le frasi di «nudo» comprendono il
seno scoperto (un quadro così passava da 0,46 a 0,77); quelle di «altro» comprendono sfondi pieni,
sfumature e grafiche (senza, un fotogramma bianco o color pelle arrivava a 0,6 di «nudo»). Frasi
su «spalle scoperte / abito senza spalline» tra i vestiti abbassavano troppo il seno scoperto e
sono state scartate. Il modello provato prima (GantMan nsfw_model) dava fino a 0,94 di «porno» a
un'intervista con una persona vestita: è stato scartato.

Le immagini di prova (WikiArt, un catalogo di moda, un'animazione dal repository nsfwjs) sono
servite solo alla taratura e non sono nel repository. Non sono state usate foto esplicite: il
riconoscimento del nudo fotografico va verificato sul campo con la «Prova» del pannello.
