# Garmin Connect API — capability notes

Living reference for what this account/device can actually provide, so we don't
re-investigate from scratch every time someone wants to add a new dashboard
section. Add to this as new endpoints get explored — don't rewrite it from
scratch, append/update the relevant section.

## Device on the account

**Forerunner 935** (2017 running watch, firmware 21.00) — the only device on
this account. Its capability flags (`client.get_devices()[0]`) gate almost
everything below: most of Garmin's newer "wellness" metrics are permanently
unavailable on this hardware, not missing from our scripts. If the user ever
upgrades their watch, re-run the probe below — several ❌ items would likely
flip to ✅.

## Feature status (tested 2026-09-14, account has ~1 year of history)

### ✅ Available, live/fresh data

| Feature | Call | Notes |
|---|---|---|
| VO2 Max (running) | `client.get_max_metrics_range(start, end)` | List of `{calendarDate, generic: {vo2MaxValue, vo2MaxPreciseValue, fitnessAge, ...}}`. Also under `.mostRecentVO2Max` in `get_training_status`. Real trend, e.g. 56.2 → 56.5 over consecutive days. |
| Training Status | `client.get_training_status(date)` | `.mostRecentTrainingStatus.latestTrainingStatusData.<deviceId>` → `weeklyTrainingLoad`, `trainingStatus` (numeric code, **mapping unverified**, see TODO), `loadTunnelMin`/`loadTunnelMax` (optimal weekly load range), `loadLevelTrend`, `sport`. |
| Fitness Age | `client.get_fitnessage_data(date)` | `chronologicalAge`, `fitnessAge`, `achievableFitnessAge`, plus contributing components (resting HR, vigorous minutes/week, BMI). Not in the original feature wishlist but free bonus, real data. |

### ⚠️ Endpoint works but data is stale (device isn't actively recomputing it)

| Feature | Call | Last computed |
|---|---|---|
| Race predictions | `client.get_race_predictions()` | 2024-04-10 (`racePredictionsRunCapable: False` on this device — don't build a "live" card around this) |
| Cycling FTP | `client.get_cycling_ftp()` | 2024-10-19 (user is primarily a runner anyway, low priority) |
| Lactate threshold | `client.get_lactate_threshold(latest=True)` | 2025-07-30 |

**Why these are stuck, and why we can't fix it from the script:** these three
are computed **on the watch/firmware itself** (Firstbeat algorithms), then
just uploaded as-is during a sync — Garmin's cloud API is read-only for us,
there's no "recompute" call to trigger. Race predictions are outright
unsupported on this device (`racePredictionsRunCapable: False`) so that value
will likely stay frozen at 2024-04-10 forever, regardless of usage, until the
watch itself is replaced. FTP and lactate threshold are nominally supported
(`ftpCapable`/`lactateThresholdCapable: True`) and could update on their own
if the user does the specific efforts that trigger a recalculation (a
structured FTP test, a sustained threshold-pace run) — but that's down to
how the watch is used, not something we can influence via the API.

### ❌ Not available for this account/device (empty response)

Confirmed via `get_devices()` capability flags — these return `{}` / `[]` / `null`
no matter what date range you pass, so don't waste calls re-probing them:

| Feature (French name from Garmin's marketing page) | Call tried | Device flag |
|---|---|---|
| Statut VFC / HRV status | `get_hrv_data`, `get_hrv_data_range` | `hrvStatusCapable: False` |
| Préparation à l'entraînement / Training readiness | `get_training_readiness`, `get_morning_training_readiness` | `trainingReadinessCapable: False` |
| Tolérance de course / Running tolerance | `get_running_tolerance` | `runningToleranceCapable: False` |
| Score d'endurance / Endurance score | `get_endurance_score` | `hillScoreAndEnduranceScoreCapable: False` |
| Hill score | `get_hill_score` | same flag as above |
| Body Battery | `get_body_battery` | `bodyBatteryCapable: False` (already known, see `garmin_bulk_backfill.py` docstring) |
| Coach de sommeil / Sleep score | n/a (Garmin computes this on-device) | `sleepScoreCapable: False`, `onDeviceSleepCalculationCapable: False` — we do have raw sleep duration/phases, just not Garmin's own 0-100 quality score |
| Stamina | — | not even exposed by the `garminconnect` library (v0.3.15); also `staminaCurveCapable: False` on this device regardless |

### Can we approximate any of the ❌ ones ourselves?

Some, as **our own home-grown proxy** — clearly labeled as such in the UI, not
presented as "Garmin's X", since it won't match Garmin's proprietary formula.
Others genuinely can't be approximated because the raw sensor input doesn't
exist for this device at all.

**Feasible from data we already have:**
- **Tolérance de course (running tolerance)** — an Acute:Chronic Workload
  Ratio (ACWR): 7-day rolling distance/duration ÷ 28-day rolling average.
  Well-established sports-science formula, needs only the per-activity
  distance/duration already in `data.json["activities"]`.
- **Préparation à l'entraînement (training readiness)** — a composite score
  from resting HR (vs personal baseline), sleep duration, average stress, and
  recent training load (days since / intensity of last hard session). This
  is stress idea #4 from earlier — same idea, just framed as a "readiness"
  angle instead of "recovery".
- **Coach de sommeil / sleep score** — a simple heuristic from the sleep
  phases we already pull (`deep_s`/`light_s`/`rem_s`/`awake_s` in
  `sleep_bulk`, or the fuller `dailySleepDTO` from daily sync): e.g. % of
  time in deep+REM, total duration vs a target window (7–9h).

**Not realistically approximable:**
- **HRV status** — the device doesn't measure HRV at all (no raw RR-interval
  data available anywhere in the API responses for this account), so there's
  no input to compute from. **Confirmed closed 2026-09-14**: re-verified
  `get_hrv_data` empty across 5 different past dates (not just "today"), and
  Garmin's own site told the user directly that HRV needs a proper heart
  rate sensor this watch doesn't have. Not a data-fetching problem, don't
  revisit unless the watch changes.
- **Stamina** — Garmin computes this in real time from a high-resolution HR
  stream during the activity itself using a proprietary model; replicating
  it would need per-second HR/power analysis with no public spec to match
  against. Not worth attempting.
- **Endurance score / Hill score** — technically has inputs we partially have
  (VO2max, elevation gain, long-effort history), but Garmin's exact formula
  is undocumented/proprietary; a homemade version would be a rough guess at
  best. Low priority.

## TODO / open questions

- **Map `trainingStatus` numeric codes to labels.** Got `7` for 2026-09-14.
  Community-documented Garmin codes (unverified against this exact API
  version): `0` NO_STATUS, `1` DETRAINING, `2` RECOVERY, `3` MAINTAINING,
  `4` PRODUCTIVE, `5` PEAKING, `6` OVERREACHING, `7` UNPRODUCTIVE, `8` STRAINED.
  Before shipping a label in the UI, cross-check against what the Garmin
  Connect app itself shows for the same day.
- `mostRecentTrainingLoadBalance` is `null` for this account
  (`trainingLoadBalanceCapable: False`) — no aerobic/anaerobic load-split
  beyond what's already in each activity's own `aerobicTrainingEffect` /
  `anaerobicTrainingEffect`.

## Bonus data found while probing (not yet used anywhere)

- **Intraday/continuous heart rate** — `client.get_heart_rates(day)` returns
  a full time-series of HR samples across the day (this is the raw signal
  Garmin's own stress engine consumes, per the official doc above: "à l'aide
  d'une combinaison de données sur la fréquence cardiaque et sa variabilité
  ... par le capteur de fréquence cardiaque optique"). The watch does record
  continuously. Not HRV (beat-to-beat variability, genuinely absent — see
  above), but real minute-by-minute HR. Could power an intraday HR/stress
  timeline chart later instead of just the daily avg/max we show today.
- **Stress duration breakdown** — `get_user_summary(day)` has far more detail
  than the `averageStressLevel`/`maxStressLevel` we currently use:
  `restStressDuration`, `activityStressDuration`, `uncategorizedStressDuration`,
  `lowStressDuration`/`mediumStressDuration`/`highStressDuration` (seconds),
  plus `*Percentage` versions of each, and `stressQualifier`. On a sample
  day, `uncategorizedStressDuration` was ~69% of the day — likely reflects
  how much of the day the watch wasn't actually worn/reading reliably, which
  could itself be a useful "data confidence" indicator for a given day.

## How to test a new endpoint

Uses the already-saved session token (`.garmintokens/`), no login needed:

```bash
cd garmin-ai
./.venv/bin/python3 -c "
from garmin_sync import load_client
c = load_client()
print(c.get_XXX(...))
"
```

Full list of available `get_*` methods on this library version:
```bash
./.venv/bin/python3 -c "import garminconnect; print([m for m in dir(garminconnect.Garmin) if m.startswith('get_')])"
```

## Reference: how Garmin's continuous stress tracking actually works

Official Garmin documentation, kept here verbatim (French) so any stress
feature we build (charts, thresholds, the readiness-proxy idea above) stays
faithful to how the underlying metric is actually defined, instead of
guessing at semantics from the raw numbers alone.

> **SUIVI DU STRESS**
>
> Le stress est la réponse naturelle de votre corps aux défis que posent la vie et l'environnement dans lequel vous évoluez. Il s'agit d'un état physiologique élevé qui vous prépare à réagir rapidement aux situations qui vont se produire. Le suivi continu du stress sur votre montre connectée Garmin s'appuie sur une compréhension éprouvée et validée scientifiquement de votre système nerveux autonome (SNA).
>
> Les niveaux de stress (de 0 à 100) sont estimés par le moteur Garmin Human Performance Lab, principalement à l'aide d'une combinaison de données sur la fréquence cardiaque et sa variabilité. Ces données sont enregistrées par le capteur de fréquence cardiaque optique situé à l'arrière de votre appareil.
>
> Divisé en composantes sympathique et parasympathique, votre SNA régule vos systèmes physiologiques pour optimiser la réponse aux attentes de votre situation. La composante sympathique domine lorsqu'il est temps d'agir. Votre pouls s'accélère, les vaisseaux sanguins se dilatent, la digestion est interrompue et l'adrénaline circule. On parle parfois de « réponse combat-fuite ». Dans les moments plus calmes, la composante parasympathique est plus dominante et votre corps entre dans ce que l'on appelle le mode « repos et digestion ». Cet état permet à votre corps de se réparer et de reconstituer les éléments perdus pendant les périodes les plus intenses.
>
> Le sommeil est une période particulièrement importante pour votre corps en matière de récupération. Sans surprise, la composante parasympathique de votre SNA est généralement la plus active pendant le sommeil.
>
> Les niveaux de stress ne sont pas mesurés par votre appareil Garmin pendant une activité physique, car l'effort fourni peut être considéré comme stressant. Il existe d'autres méthodes permettant de mieux mesurer et analyser l'impact de l'activité physique. Parler en public et monter un escalier en courant peuvent tous deux accélérer votre fréquence cardiaque, mais les raisons sous-jacentes sont fondamentalement différentes selon l'activité.
>
> **Portez régulièrement votre appareil pour obtenir des informations plus personnalisées.** Vos paramètres physiologiques et la réponse de votre corps aux facteurs de stress sont uniques. Vous pouvez améliorer la qualité des informations obtenues en portant votre appareil le plus possible, notamment pendant le sommeil, car c'est là que votre niveau d'effort est généralement le plus faible. Même en portant votre appareil par intermittence, vous obtiendrez quelques enseignements sur votre stress, mais les détails et les niveaux précis peuvent être moins personnalisés qu'avec une utilisation plus régulière.
>
> **Décrypter le suivi continu du stress.** Le graphique de stress de votre appareil ou de l'application Garmin Connect affiche des barres **orange lorsque le niveau de stress dépasse 25**, et **bleues sous ce seuil**. Ce contraste est essentiel pour identifier les états de stress et de détente.
>
> Aux alentours du niveau 25, l'activité au sein des composantes sympathique (stress : combat-fuite) et parasympathique (récupération : repos et digestion) est pratiquement égale. À des niveaux plus élevés (25–100), l'activité sympathique domine. Les niveaux inférieurs (0–25) indiquent que le système parasympathique est le plus actif des deux.
>
> Ces données ne donnent pas d'indication sur la *raison* de ces états. Des niveaux de stress élevés peuvent provenir de la pression au travail, d'une anxiété sociale, d'une altercation sur la route — mais aussi de situations heureuses (nouvel emploi, premier rendez-vous, anticipation avant une course). Une activité physique excessive, des stimulants, une mauvaise alimentation ou une maladie peuvent aussi produire des niveaux supérieurs à la normale. La clé reste de compenser ces épisodes par des moments de détente et un sommeil de bonne qualité.

**Implications for our dashboard work:**
- The 0–25 (calme/parasympathique) vs 25–100 (stress/sympathique) split is
  Garmin's own semantic threshold — any stress chart we build should color
  by this same boundary (orange/blue) rather than inventing our own scale.
- Stress is **never measured during a tracked activity** — so when computing
  "post-workout" stress for idea #3 (stress/RHR the day after a hard
  session), use the *following calendar day's* average, not same-day, since
  same-day stress during/right after the activity window is intentionally
  excluded by Garmin itself.
- The metric explicitly can't distinguish "good" stress (excitement, a race)
  from "bad" stress (work pressure) — worth a caveat in the UI copy so the
  numbers aren't over-interpreted.
