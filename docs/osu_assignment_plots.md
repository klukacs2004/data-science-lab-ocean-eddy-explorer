# A projektkiírás ábrái az OSU adatokra

A `scripts/plot_osu_assignment.py` az Escudier et al. (2016), DOI:
10.1002/2015JC011371, 3. és 4.1. szakasza és 7–8. ábrája alapján készült.
A helyi PDF szövegét és ábráit használtuk. Az eredeti két oszlop mediterrán
altimetriát és modellt jelent. Itt csak OSU-adatok szerepelnek: a 7. ábrán a három
módszer együtt, a 8. ábrán módszerenként egy panel. Nincsenek kitalált referenciagörbék.

## Futtatás

A projekt gyökerében:

```bash
# Gyors ellenőrzés; három nap még nem ad érdemi életciklusgörbét.
.venv/bin/python scripts/plot_osu_assignment.py \
  --start 1993-01-01 --end 1993-01-03 --output /tmp/osu-three-days

# Teljes időszak, az évhatárokon is folytonos követéssel:
OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/plot_osu_assignment.py \
  --start 1993-01-01 --end 2014-12-31 --output artifacts/osu_assignment

# Újrarajzolás új detektálás és követés nélkül:
.venv/bin/python scripts/plot_osu_assignment.py \
  --catalogue artifacts/osu_assignment/observations.csv.gz \
  --output artifacts/osu_assignment_replot

# Tesztek:
.venv/bin/python -m unittest discover -s tests -p test_osu_assignment_plots.py

# Csak a Figure 8 újrarajzolása a már kiszámított átlagokból:
.venv/bin/python scripts/plot_osu_assignment.py \
  --figure8-csv artifacts/osu_assignment_1993_2012/figure8_data.csv \
  --output artifacts/osu_assignment_1993_2012
```

A kimeneti könyvtár már létezhet; az új futás felülírja az általa készített
azonos nevű eredményfájlokat. A könyvtár egyéb fájljait megtartja.
Dátumok nélkül a teljes 1993–2014-es
időszak az alapérték. A program napi előrehaladást ír ki. A detektálásokat
memóriában tartja a követésig, ezért a teljes futás hosszú és memóriaigényes.
Rövid időablakból nem lehet a teljes időszakra következtetni.

## Meglévő implementációk és beállítások

A szkript közvetlenül az `eddy_detection` és `eddy_tracking` függvényeit hívja.
A napi NetCDF-mezőket az explorer betöltői olvassák, pontos rácsegyezéssel.

- Chelton: `scan_thresholds`, `standardize_chelton`, `track_chelton`.
  Nincs további felüláteresztő szűrés; a követési keresés féltengelyei
  kelet/nyugat/észak–dél irányban 30/50/30 km. Amplitúdó- és területarány:
  0.25–2.5.
- Nencioli: `detect_eddies`, `standardize_nencioli`, `track_nencioli`.
  a=2, b=2, 40 km/nap, greedy hozzárendelés, hézagáthidalás nélkül.
- Halo: `HaloDetector`, `standardize_okubo_weiss`, `track_halo`.
  2 cm kontúrlépés, 600 km maximális átmérő, két Hanning-simítás a W mezőn.
  Reprezentatív relatív örvényesség, globális hozzárendelés, 50 km/nap
  maximális elmozdulás, hézagáthidalás nélkül. A nem meghatározható
  örvényesség miatt kizárt detektálások száma a konfigurációba kerül.

A pontos paramétereket és bemeneti fájlmetaadatokat a `configuration.json`
rögzíti. Ezek az eredeti módszerek ihlette helyi implementációk, nem az eredeti
szerzői kódok. Minden követő megtartja az egynapos szegmenseket is, mert az
előzetes élettartamszűrés torzítaná az eloszlást.

## Számítás és kimenetek

`figure7_distributions.png/.pdf`:

- Felül a napi effektív sugár R=sqrt(S/pi), 2 km-es binenként, az összes
  érvényes sugarú napi detektálás százalékában. Hosszabb pálya több nappal
  szerepel. A cikk nem rögzíti a binhatárokat; a 2 km dokumentált választás.
  A tengelyek a cikket követik: sugár 0–100 km, gyakoriság 0–18%,
  jelölések 25 km-enként és 5 százalékonként. A tartományon kívüli adatok
  megmaradnak a CSV-ben és a százalékok nevezőjében.
- Alul 100 × N(T≥d)/N logaritmikus százaléktengellyel. Egy pálya egyszer számít.
  T az első és utolsó megfigyelés közötti napok száma +1. Ez empirikus felső
  kumulatív eloszlás, nem Kaplan–Meier-becslés. A nulla érték csak a logaritmikus
  rajzról hiányzik, a CSV-ben megmarad.
  A megjelenített tengelyek 0–250 nap és 0.3–100%; az időjelölések
  50 naponta, a logaritmikus százalékjelölések 1, 10 és 100 értéknél vannak.

`figure8_radius.png/.pdf`:

- A cikk megjelenítését követve a vízszintes tengely 0–225 nap (jelölések
  0, 50, 100, 150, 200), a sugártengely alsó határa 17.5 km, felső határa
  legalább 65 km, de automatikusan bővül, hogy minden megjelenített görbe
  elférjen 5% ráhagyással, 10 km-re felfelé kerekítve. A jelölések 10 km-enként
  vannak. A feliratok `Life (days)` és `Radius (km)`.
  A sugár és az élettartam tartományhatárai a cikk ábrájáról leolvasott értékek.

- Osztályok: [7,25), [25,50), [50,100), [100,150), [150,200), [200,250].
  A cikk nem rögzíti a közös határértékek besorolását; nincs kettős számlálás.
- q=(t−1)/T, ahol t az életkor 1-től számozva. A vízszintes koordináta q szorozva
  az osztályközéppel (16, 37.5, 75, 125, 175, 225 nap); a sugár km-ben szerepel,
  nincs saját pályaátlagával normalizálva.
- Egy nap széles skálázott időbinenként előbb pályán belül átlagolunk, majd a
  pályákat egyforma súllyal átlagoljuk. Nem interpolálunk megfigyelési hézagon.
  Ezt a binelést és súlyozást a cikk nem részletezi: saját dokumentált választás.
- Legalább 20 külön pálya kell egy látható binhez. Kevés adat esetén megszakad
  vagy hiányzik a görbe. A `--min-count` teszteléshez felülírható.
- Az időablak első/utolsó napját érintő pályák alapértelmezésben kimaradnak az
  életciklusábrából, mert a teljes élettartamuk bizonytalan. A
  `--include-censored-cycles` bevonja őket. A 7. ábra mindet tartalmazza.

A Nencioli tartalék körgeometriája nem fizikai sugármérés: sugárstatisztikához
csak a `streamfunction` eredetű sugarak használhatók. Az időtartam-statisztika
minden pályát megtart. A binenkénti hozzájárulók a `figure8_data.csv`-ben szerepelnek.

További kimenet: `radius_span.png/.pdf` és `correlations.csv` (Pearson- és
Spearman-együttható a pályánkénti átlagos sugár és időtartam között).
A tengelyfeliratok a cikk szóhasználatát követik: a 7. ábrán `Radius (km)`,
`% of eddy detected`, `Lifetime (days)` és `cumulative % of eddy detected`;
a 8. ábrán `Life (days)` és `Radius (km)`. A kiegészítő szórásdiagramon
`Lifetime (days)` és `Mean radius (km)` szerepel, mert ott pályaátlagot rajzolunk.
A `Lifetime` ebben az OSU-feldolgozásban megfigyelt követési időtartamot jelent.
A `tracks.csv`, `observations.csv.gz` és az ábrák CSV-i ellenőrizhetők,
újrafelhasználhatók. Kevés vagy konstans adatnál nem számítunk korrelációt.

A megfigyelt követési szegmens időtartama nem bizonyított fizikai élettartam:
a detektálási hiányok és a követési szabályok is befolyásolják. A mediterrán
csúcssugarak nem elvárt OSU-eredmények; a térbeli felbontás és a régiók eltérése
is számít az összehasonlításnál.

## Prezentációba illeszthető PNG-k

```bash
.venv/bin/python scripts/export_comparison_presentation.py
```

A szkript a meglévő `artifacts/osu_assignment_1993_2012` CSV-statisztikáiból
készíti el a `figure7_comparison_presentation.png` és
`figure8_comparison_presentation.png` képeket az
`artifacts/presentation_comparison` könyvtárban. A képek 3840 × 2160 pixelesek,
16:9 képaránnyal, 32 pontos főcímmel, 24 pontos tengelyfeliratokkal és
18 pontos tengelyjelölésekkel. Másik eredménykönyvtár a `--source`, másik
kimeneti könyvtár a `--output` kapcsolóval választható.

A prezentációs változat a cikk PDF-jének 9–10. oldalán ellenőrzött, rögzített
tengelytartományokat használja: a 7. ábrán 0–100 km és 0–18%, illetve
0–250 nap és logaritmikus 0.3–100%; a 8. ábrán 0–225 nap és 17.5–65 km.
A tartományon kívüli értékek nem változtatják meg a százalékok nevezőit.
A 8. ábrán a teljes 1993–2012-es Chelton-átlaggörbék 65 km fölött vannak;
ezt külön felirat jelzi, és a Halo részben levágott értékeit is megjelöljük.
A statisztikák és az eredeti ábrák megmaradnak. Az új export paramétereit és
a bemeneti CSV-k SHA-256 lenyomatait az `export_configuration.json` rögzíti.
