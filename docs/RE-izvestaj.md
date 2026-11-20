# Magic Mouse 2 na Windows-u — novi RE (2026-11-19) i plan za MagicMouse Studio

Izvori: novi, nezavisni RE nad `MagicUtilities-Setup-3.1.6.4.exe` (privremeno instaliran radi izvlačenja payload-a, jer innoextract/REA ne podržavaju Inno 7.1.1) i nad Apple Boot Camp drajverom `applewirelessmouse.sys` 6.1.7700.0.
Detalji i dokazi (radni folder, nije deo ovog repozitorijuma): `scratch/re/mu3164/` (`scan/`, `analysis/*/NALAZI.md`, `decomp/`).
Sav kod u ovom repozitorijumu je napisan od nule; iz Magic Utilities i Apple drajvera nije preuzet nijedan deo koda ni resursa.
Oznake: **[K]** potvrđeno kodom, **[V]** verovatno, **[N]** nepoznato, **[T]** treba živi test.

---

## 1. Odgovor u jednoj rečenici

MU (i Apple) **ne čitaju senzor i bateriju iz user-moda** — sve radi **kernel filter drajver ispod `HidBth`** koji vidi Bluetooth L2CAP saobraćaj, sam šalje mišu komandu za multi-touch, prepisuje HID deskriptor, od touch podataka pravi skrol, a sirove prste i bateriju šalje aplikaciji sopstvenim kanalom; aplikacija ih samo **crta (Direct2D)**.

## 2. Arhitektura MU 3.1.6.4

| Komponenta | Uloga | Zaštita |
|---|---|---|
| `MagicMouse.sys` 3.1.5.3 (KMDF 1.15, LowerFilter na BTHENUM HID čvoru, WHCP potpis) | BT/USB filter, gesture engine, RawPdo | ~5,5 MB VM/mutacija; licenca-gejtovani event handleri [K] |
| `MagicMouseUtilities.exe` (Delphi/FPC, D2D1/DWrite) | UI, prikaz prstiju, baterija, podešavanja | WinLicense [K] |
| `MagicUtilities_Service.exe` | instalacija/restart drajvera, pipe-ovi `MuMousePipe/MuKeyboardPipe/MuTrackpadPipe` | WinLicense [K] |
| `DriverUnInstaller.exe` (FreePascal) | pnputil-like install/uninstall INF-ova | nezaštićen [K] |
| `BluetoothPairing.exe` (.NET) | uparivanje po MAC-u preko WinRT | slabo [K] |

### 2.1. Drajver — Bluetooth put [K]
1. `EvtIoInternalDeviceControl` hvata `IOCTL_INTERNAL_BTH_SUBMIT_BRB` (0x410003); BRB tipovi 0x102/0x103 (open channel), 0x104 (close), 0x105 (ACL transfer), 0x320.
2. Iz completion-a OPEN_CHANNEL pamti PSM **0x11 = control**, **0x13 = interrupt** i njihove handle-ove.
3. `EvtIoDeviceControl` hvata `IOCTL_BTH_SDP_SERVICE_ATTRIBUTE_SEARCH` (0x410210) i **menja SDP zapis/HID deskriptor** (atribut 0x0206):
   - mouse TLC, Report ID 2: 5 dugmadi, X/Y int8, **Wheel int16 + AC Pan int16** (smooth scrolling varijanta dodaje Resolution Multiplier, Feature ID 3/4);
   - **vendor TLC UP 0xFF00/U 1, Report ID 0x44, 63 B** — placeholder da HidBth/HIDClass prihvati sirov touch izveštaj u istom baferu.
4. Na control kanal šalje sopstvene BRB-ove (`BthAllocateBrb`): keep-alive `90 00` (HIDP SET_IDLE) svakih `BthKeepAlivePeriod` (2000 ms), `71` (SET_PROTOCOL report).
5. **Multi-touch uključivanje**: `53 F1 02 01` na control kanal posle prvog interrupt izveštaja po konekciji — potvrđeno u Apple drajveru [K]; u MU je telo u zaštićenom delu, ali dolazni `A1 12` dugi izveštaji pokazuju da je MT mod aktivan [V]. `F1 C8 09` (Linux) se ne pojavljuje ni u jednom drajveru.
6. Dolazni interrupt izveštaji se menjaju u mestu:
   - `A1 12 …` (≥15 B): touch frame → gesture engine → prepisan u `A1 02 btn dx dy wheel16 pan16`;
   - snimak prstiju (0x58 B) → event 0x15 → **RawPdo** ka aplikaciji;
   - `A1 90 flags pct` → **baterija** (ctx: flags, procenat; početno −1) → event 0xA/0xF ka aplikaciji.
7. RawPdo `{7D55502A-…}\MagicMouseRawPdo`, interfejs `{FAE1EF32-137E-485E-8D89-95D0D3BD8479}`, inverted-call; paketi **AES-CBC + SHA256 vezani za MachineGuid** → MU drajver se ne može koristiti iz tuđe aplikacije (i ne treba) [V].

### 2.2. Format podataka [K — isto u MU, Apple i Linux]
```
Touch:   [0x12, buttons, …header do offseta 14…, N × 8 B prst]      (N ≤ 5 u praksi)
Prst:    id     = ((f6<<2)|(f5>>6)) & 0xF
         x      = sext12(((f1&0x0F)<<8) | f0)          opseg ≈ −1100..1258
         y      = −sext12((f2<<4) | (f1>>4))           opseg ≈ −1589..2047
         major  = f3, minor = f4, size = f5 & 0x3F, orient = (f6>>2) − 32
         state  = (f7>>4) & 7      (3 = start, 4 = drag, 0 = podignut)
Baterija: [0x90, flags, percent]   (snimljeno na ovoj mašini: 90 00 58 = 88 %)
          alternativno [0xF0, 0x90, flags, pct] i odgovor na GET_REPORT feature 0x47: [0x47, pct]
```

### 2.3. Aplikacija [K za tekst/registre, V za crtanje]
- Prikaz: custom **Direct2D** crtanje slike miša (Silver / Space Gray / Black) sa elipsama prstiju; „Live touches“ (drajver šalje svaki 3. frame), oznake *on surface / lifted*; editor zona na slici (tap oblast, ignorisane ivice 150, dno 900, srednje dugme 819/1638/1228 u sirovim jedinicama).
- Baterija: ceo procenat, −1 = nepoznato; upozorenja 10 % / 5 %, „napunjeno“ 80 %, snooze (min / 1 h / 2 h / sutra), tajmer 15 min. **Ne upisuje** se u Windows battery property.
- Funkcije: skrol (1/2 prsta, smooth, inverzno V/H, samo ortogonalno, ubrzanje, brzina), middle click (4 načina), swipe back/forward, 2-prsta swipe (desktop / Task View), tap-to-click (1/2/3 prsta), double-tap drag, left-handed, zone ignorisanja, suspend uređaja (display off / sleep / logoff / baterija). Pragovi: swipe 75/45 (2 prsta 35/40), scroll offset 225 step 120, tap 200 ms / 80 / sense 7, double-tap-drag 100–200 ms.

### 2.4. Apple Boot Camp drajver (referenca bez obfuskacije) [K]
Isti princip, manji: KMDF LowerFilter, BRB 0x102–0x105, SDP 0x410210 zamena deskriptorom od 116 B (mouse ID 2 + **Feature 0x47 Battery Strength** + placeholder Input 0x27 46 B → InputLen 47), `53 F1 02 01`, skrol iz 1–2 prsta (kompenzacija pomeranja tela, axis-lock 22°, ubrzanje, bez inercije). **Guta report 0x90** — zato Windows sa Apple drajverom nikad ne vidi bateriju.

## 3. Da li je moguća „100 % replika“?

| Šta | Moguće? | Napomena |
|---|---|---|
| Ista funkcionalnost (prikaz prstiju, baterija, skrol, geste, podešavanja) preko BT | **Da** | sopstveni KMDF filter po gornjem receptu |
| Korišćenje MU drajvera/protokola | Ne | šifrovan, vezan za mašinu i licencu; i ne bi bilo pošteno |
| Bajt-identična kopija MU binarija/UI-a | Ne | WinLicense + autorsko pravo; pravimo **sopstvenu** app |
| Drajver bez test-signing režima | Samo uz EV sertifikat + Microsoft attestation potpis | za ličnu upotrebu: `bcdedit /set testsigning on` (već uključen) |

**Data kabl**: za konačno BT rešenje **nije potreban**. Koristan je u fazi 1 (USB, bez drajvera) za proveru dekodera i kao rezervni put.

## 3a. Provereno uživo na ovom mišu (2026-11-19, posle RE)

| Test | Rezultat |
|---|---|
| USB kabl, bez drajvera: `GetInputReport(0x90)` na `MI_00&COL02` | ✅ baterija (`90 03 5e` = 94 %, flags 0x03 dok se puni) |
| USB kabl: `HidD_SetFeature(F1 02 01)` iz user-moda | ❌ `ERROR_INVALID_FUNCTION` — USB deskriptor nema nijedan feature/output report |
| USB kabl + naš filter: `SET_REPORT F1 02 01 / F1 C8 09 / 02 01` na interfejs 1 | prihvaćeno (`STATUS_SUCCESS`), ali **miš preko USB-a ne šalje nikakav unos** (ni dodir, ni klik, ni pokret) — kabl služi samo za punjenje/uparivanje/bateriju |
| **BT + naš filter ISPOD Apple drajvera** (`LowerFilters = {mmsfilter, applewirelessmouse}`) | ✅ sirovi `0x12` frame-ovi 14+8·N B (1–3+ prsta), ~90/s; Apple i dalje radi kursor + skrol |
| BT baterija | ✅ miš šalje `90 00 64` (100 %) **pri povezivanju**; Apple ga guta, naš filter ga hvata i kešira |
| BT `HidD_GetFeature(0x47)` (Apple deskriptor) | ❌ miš ne odgovara |
| Stanja prsta (`state>>4`) | 1/2 prilazi, 3 dodir, 4 prevlačenje, 5–7 podizanje |
| Orijentacija | potvrđeno: X = levo→desno, manji Y = prednji deo |

Zaključak: **za senzore je obavezan Bluetooth + kernel filter**; data kabl nije potreban (koristan samo za bateriju dok se puni).

## 4. Plan — MagicMouse Studio (novi kod, ništa iz starog prototipa)

```
MagicMouseStudio/
  driver/   mmsfilter.sys  — KMDF 1.15 LowerFilter ispod HidBth (BTHENUM 0001004C_PID&0269)
            • BRB 0x102–0x105: control/interrupt handle po PSM-u
            • SDP 0x410210: sopstveni deskriptor = mouse (ID 2, wheel16+pan16, Resolution Multiplier)
                             + Feature 0x47 baterija + vendor TLC (UP 0xFF00) za sirove frame-ove
            • posle 1. interrupt izveštaja: 53 F1 02 01 (fallback F1 C8 09), keep-alive 90 00
            • 0x12 → skrol (wheel/pan) + kopija u ring; 0x90 → baterija
            • control device \\.\MagicMouseStudio: IOCTL_MMS_GET_FRAME (inverted call), IOCTL_MMS_GET_BATTERY
  app/      Python + PySide6 tray app
            • mmstudio/hid.py, protocol.py (gotovo, testirano)
            • transport: USB (bez drajvera) | mmsfilter (BT)
            • UI: živi prikaz prstiju na slici miša, baterija + upozorenja, podešavanja skrola/gesta
  docs/     ovaj izveštaj
```

Redosled: (1) USB put + UI (kabl), (2) drajver: prvo samo pasivni log BRB-ova (bez menjanja), (3) MT enable + prosleđivanje frame-ova/baterije, (4) deskriptor + skrol, (5) geste i podešavanja.
Rizik faze 2–4: restart BT uređaja, moguć BSOD dok se testira; uvek postoji povratak na Apple drajver (`driver\uninstall.ps1` uklanja samo naš filter).
