# 🖥️ Smart Desk — üz tanıma ilə ağıllı iş masası

Webcam səni izləyir və:

| Hadisə | Nə baş verir |
|---|---|
| 🟢 **Masaya oturursan** | Səni tanıyır və iş mühitini açır: VS Code, Slack, Spotify playlist… |
| 🔒 **Masadan qalxırsan** | ~12 saniyədən sonra ekran avtomatik kilidlənir |
| 🚨 **Başqası oturur** | Ekranı kilidləyir, şəklini çəkir və **Telegram**-la sənə göndərir |
| 👀 **Arxandan kimsə baxır** *(istəyə görə)* | "Shoulder surfer" xəbərdarlığı |
| 📊 **Gün sonu** | `--report`: bu gün masada nə qədər oturmusan |

Yalnız **OpenCV** istifadə olunur (YuNet aşkarlama və SFace tanıma). `dlib` və ya `face_recognition` kompilyasiya etmək lazım deyil. Windows, macOS və Linux-da işləyir, GPU tələb etmir.

---

## 🚀 Quraşdırma (5 dəqiqə)

```bash
cd smart-desk
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml    # Windows: copy config.example.yaml config.yaml
```

Modellər (~40 MB) ilk işə salınmada `models/` qovluğuna avtomatik yüklənir.

### 1. Üzünü tanıt

```bash
python enroll.py --name ruslan
```

Kamera açılır və ekrandakı göstərişlərə əməl edirsən: sola bax, sağa bax, gülümsə… Proqram 25 nümunə yığır.
Fərqli işıqda yenidən işə salıb nümunə əlavə etmək tanımanı yaxşılaşdırır:

```bash
python enroll.py --name ruslan --append
```

**İkinci sahib əlavə etmək** (məs. komputeri birlikdə istifadə etdiyin biri):
```bash
python enroll.py --name aysel
```
Sonra `config.yaml`-da `owner: [ruslan, aysel]` yaz. Sahiblərdən hər hansı biri oturanda proqramlar açılır. Hamısı masadan uzaqlaşanda ekran kilidlənir.

Ad tanıdılıb, amma `owner` siyahısında deyilsə, həmin şəxs **"etibarlı"** sayılır: xəbərdarlıq göndərilmir, amma iş mühiti də açılmır.

### 2. `config.yaml`-ı düzəlt

- `owner:` — enroll zamanı verdiyin ad, bir neçə nəfər üçün `[ruslan, aysel]`
- `on_arrival:` — öz OS-in üçün açılacaq proqramlar. Standart olaraq **Opera** və **Claude** açılır; kod onların quraşdırma yerini özü axtarır. Microsoft Store/MSIX ilə quraşdırılan Claude Desktop Windows Start menyusundan tapılır. Heç cür tapılmasa, əvəzinə claude.ai açılır. Proqram artıq açıqdırsa, təkrar açılmır.
  Yoxlamaq üçün `python desk.py --check-apps` işlət. Burada ❌ görsən, proqramın `.exe` faylının yolunu `paths:` siyahısına əlavə et.
- `lock_after_seconds`, `threshold` və s. — şərhlərdə izah olunub

### 3. Telegram botu (istəyə görə)

1. Telegram-da **@BotFather** → `/newbot` → token-i kopyala.
2. Token-i env dəyişəninə yaz (daha təhlükəsizdir) və ya `config.yaml`-a qoy:
   ```bash
   export TELEGRAM_BOT_TOKEN="123456:ABC..."      # Windows: setx TELEGRAM_BOT_TOKEN "..."
   ```
3. Botuna Telegram-da `/start` yaz, sonra:
   ```bash
   python desk.py --telegram-setup   # chat_id-ni göstərir
   ```
4. Çıxan `chat_id`-ni `TELEGRAM_CHAT_ID`-yə və ya config-ə yaz və `--telegram-setup`-ı yenidən işə sal. Test mesajı gəlməlidir ✅

### 4. İşə sal

```bash
python desk.py --preview    # kamera pəncərəsi ilə (demo / test üçün)
python desk.py              # pəncərəsiz, arxa fonda
python desk.py --report     # bugünkü hesabat
```

`--preview` rejimində üzlər rənglə işarələnir: 🟩 sən, 🟦 etibarlı şəxs, 🟥 yad. Yuxarı paneldə kilidə qalan saniyələr görünür.

---

## ⚙️ Kompüter açılanda avtomatik başlasın

**Windows (bir əmr):**
```powershell
.venv\Scripts\activate
python autostart.py install      # silmək: python autostart.py uninstall
```
Bu əmr Startup qovluğuna `SmartDesk.vbs` faylı qoyur. Kompüter açılanda Smart Desk 20 saniyədən sonra **konsol pəncərəsi olmadan** başlayır. Loglar `desk.log` faylına yazılır.
Diqqət: arxa fonda işləyən Smart Desk kameranı tutur. `--preview` ilə əl ilə işə salmaq istəsən, əvvəlcə onu dayandır: Task Manager → `pythonw.exe` → End task.

**macOS:** *System Settings → General → Login Items*-ə skripti əlavə et. Kameraya və *Accessibility*-yə icazə ver (kilid üçün `System Events` istifadə olunur).

**Linux (systemd user):**
```ini
# ~/.config/systemd/user/smart-desk.service
[Service]
WorkingDirectory=%h/smart-desk
ExecStart=%h/smart-desk/.venv/bin/python desk.py
Restart=on-failure
[Install]
WantedBy=default.target
```
```bash
systemctl --user enable --now smart-desk
```

---

## 🧠 Necə işləyir

```
kamera → YuNet (üz tap) → SFace (128 ölçülü vektor) → faces/*.npy ilə müqayisə (cosine)
                                                    ↓
                     DeskBrain vəziyyət maşını: YOXSAN ⇄ MASADASAN
                     ├─ 3 ardıcıl kadr səni görür → "arrived" (+ proqramları aç)
                     ├─ 12 saniyə görmür          → "left" + ekranı kilidlə
                     └─ 4 ardıcıl kadr yad üz      → snapshot + Telegram (60 s cooldown)
```

- Analiz saniyədə 5 kadrla aparılır (`fps`), adi noutbukda CPU yükü ~5–10% olur.
- Tək bir səhv kadr heç nəyi tetikləmir: hər qərar bir neçə ardıcıl kadra əsaslanır.
- Bütün hadisələr `events.db` (SQLite) faylına yazılır. Bu fayldan öz dashboard-unu da qura bilərsən.

Fayllar:

| Fayl | Vəzifə |
|---|---|
| `face_engine.py` | Model yükləmə, aşkarlama, tanıma, üz bazası |
| `enroll.py` | Üz nümunələrini yığır (kamera və ya şəkil qovluğundan) |
| `desk.py` | Əsas dövr, `DeskBrain` vəziyyət maşını, overlay, Telegram setup |
| `actions.py` | Ekran kilidi (Win/mac/Linux), proqram açma, Telegram API |
| `autostart.py` | Windows Startup-a əlavə et / sil |
| `events.py` | SQLite jurnal və gündəlik hesabat |
| `tests/` | Kamerasız vəziyyət maşını testləri (`python tests/test_brain.py`) |

## 🔧 Problemlər

| Problem | Həll |
|---|---|
| Səni tanımır | Fərqli işıqda `enroll.py --append` işlət və ya `threshold`-u 0.36-ya endir |
| Başqasını sən kimi tanıyır | `threshold`-u 0.45–0.50-yə qaldır |
| Çox tez kilidlənir | `lock_after_seconds`-u artır |
| Kamera açılmır | Başqa proqram (Zoom/Teams) kameranı istifadə edirmi? `camera: 1` sına |
| Linux-da kilid işləmir | `loginctl lock-session`-u əl ilə yoxla; DE-nə uyğun əmri `actions.py`-a əlavə et |

> ⚠️ **Qeyd:** Bu, əyləncəli və rahatlıq üçün olan bir layihədir, təhlükəsizlik sistemi deyil. Liveness yoxlaması yoxdur, yəni telefondakı şəkil ilə aldatmaq mümkündür. Əsas qoruma yenə də OS şifrən olaraq qalır. Üz vektorları yalnız sənin kompüterində (`faces/`) saxlanılır və heç yerə göndərilmir.

## 💡 Növbəti ideyalar

- Liveness: göz qırpımını yoxlamaq (MediaPipe Face Mesh, EAR)
- Pomodoro: 50 dəqiqə fasiləsiz oturanda "dur, gəzin" xatırlatması
- Duruş analizi: əyilib oturanda xəbərdarlıq
- Səni görəndə Home Assistant ilə masa lampasını yandırmaq
