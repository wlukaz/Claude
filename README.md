# LoseIt → Claude auto-sync

LoseIt has no public API for personal data, but on Android it writes every logged food (calories,
macros and micronutrients) and every weigh-in to **Health Connect**. This project moves that data to
a Google Sheet in your Drive automatically, where Claude can read it through the Google Drive connector.

```
LoseIt ──► Health Connect ──► LoseIt Sync (Android app, every 6 h) ──► Apps Script web app ──► Google Sheet ──► Claude
```

## What lands in the sheet

| Tab | Contents |
| --- | --- |
| `food_log` | One row per logged food: date, time, meal, food name, and all 42 Health Connect nutrient fields (calories, protein, carbs, fiber, sugar, fat breakdown, cholesterol, sodium, potassium, vitamins A–K, B-vitamins, minerals, caffeine). Blank = LoseIt didn't report it. |
| `daily_totals` | One row per day: entry count, last weigh-in, and the sum of every nutrient. |
| `weight` | Weigh-ins in lb and kg. |
| `sync_info` | Time and date range of the last sync. |

Each sync re-sends the last 7 days and the script replaces those days, so edits and deletions in LoseIt carry over.

## Setup (about 10 minutes)

### 1. LoseIt → Health Connect
In LoseIt: **Settings → Automatic Tracking → Health Connect**. Turn on writing **Nutrition** and **Weight**.

### 2. Apps Script (the receiver in your Google account)
1. Go to <https://script.google.com> → **New project**. Paste in [`apps-script/Code.gs`](apps-script/Code.gs).
2. Select `setup` in the function dropdown → **Run** → approve the permissions.
   Open **Execution log**: it prints the new sheet's URL and your **sync token**.
3. **Deploy → New deployment → Web app**. Execute as **Me**, Who has access **Anyone** → **Deploy**.
   Copy the **Web app URL** (ends in `/exec`). The token is what keeps other people out.

### 3. Android app
1. Open the repo's **Actions** tab → latest **Build LoseIt Sync APK** run → download `loseit-sync-apk`.
   Unzip it and install `app-debug.apk` (allow installs from your browser/file manager).
2. Open **LoseIt Sync**, paste the Web app URL and token. Leave the source as `com.fitnow.loseit`
   (blank would also include other nutrition apps). Tap **Save settings & schedule auto-sync**.
3. Tap **Grant Health Connect access** and allow Nutrition, Weight, **access data in the background**
   and **access past data** (the last two only appear on newer Health Connect versions).
4. Set **Backfill days** (for example 365) and tap **Backfill history**. Without "past data" access,
   Health Connect only returns the 30 days before you first granted access.

After that it runs on its own every 6 hours. If your phone doesn't offer background access, it syncs whenever you open the app.

### 4. Claude
Ask Claude something like *"Read my 'LoseIt Sync (Health Connect)' sheet in Google Drive and update my fitness dashboard."*
To refresh on a schedule, ask Claude to create a Routine that does that each morning.

## Notes
- Builds are signed with a throwaway key per CI run, so installing a newer build means uninstalling the
  old one first. To avoid that, add a repo secret `DEBUG_KEYSTORE_B64` containing
  `base64 -w0 debug.keystore` of a keystore made with
  `keytool -genkey -v -keystore debug.keystore -storepass android -alias androiddebugkey -keypass android -keyalg RSA -validity 10000 -dname "CN=Android Debug"`.
  Never commit the keystore: this repo is public.
- The URL and token are stored only on your phone, never in this repo.
- Whether a nutrient is filled in depends on what LoseIt writes to Health Connect for that food.
